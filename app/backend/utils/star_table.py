"""Tables of metadata files for the file browser: STAR (RELION), XMD (Xmipp), CSV, TSV.

STAR and XMD share their syntax: ``data_<name>`` blocks holding either a
``loop_`` (one ``_label`` per column, then one row per line) or ``_label value``
pairs. The file is read line by line: every block keeps its first rows, and
the rest of a loop is only counted, so a file of millions of particles is
previewed without loading it.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

# STAR values are separated by blanks; quoted values may hold blanks.
_TOKEN = re.compile(r"'[^']*'|\"[^\"]*\"|\S+")

DEFAULT_ROW_LIMIT = 200
# Beyond this many bytes the rest of the file is not read (rows are no longer counted).
DEFAULT_READ_LIMIT = 256 * 1024 * 1024
MAX_BLOCKS = 50


@dataclass
class TableBlock:
    name: str
    kind: str  # "loop" or "pairs"
    columns: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    totalRows: Optional[int] = 0
    truncated: bool = False

    def toDict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "columns": self.columns, "rows": self.rows,
                "totalRows": self.totalRows, "truncated": self.truncated}


@dataclass
class MetadataTable:
    format: str
    blocks: List[TableBlock] = field(default_factory=list)
    # The file was not read to its end: later rows (or blocks) are not counted.
    incomplete: bool = False

    def toDict(self) -> dict:
        main = self.mainBlock()
        return {
            "format": self.format,
            "blocks": [block.toDict() for block in self.blocks],
            "incomplete": self.incomplete,
            # The main block, for clients that show one table.
            "columns": main.columns if main else [],
            "rows": main.rows if main else [],
        }

    def mainBlock(self) -> Optional[TableBlock]:
        loops = [block for block in self.blocks if block.kind == "loop"]
        if loops:
            return max(loops, key=lambda block: block.totalRows or len(block.rows))
        return self.blocks[0] if self.blocks else None


def _tokens(line: str) -> List[str]:
    return [token[1:-1] if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"" else token
            for token in _TOKEN.findall(line)]


def readStarTable(lines: Iterable[str], fmt: str = "star", rowLimit: int = DEFAULT_ROW_LIMIT,
                  readLimit: int = DEFAULT_READ_LIMIT) -> MetadataTable:
    """The blocks of a STAR/XMD file, given its lines."""
    table = MetadataTable(format=fmt)
    block: Optional[TableBlock] = None
    inLoopHeader = False
    readBytes = 0

    for raw in lines:
        readBytes += len(raw)
        if readBytes > readLimit:
            table.incomplete = True
            if block is not None and block.kind == "loop":
                block.totalRows = None
            break
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            # Comments (# XMIPP_STAR_1 *); a blank line ends a loop header too.
            if not line:
                inLoopHeader = False
            continue
        lowered = line.lower()
        if lowered.startswith("data_"):
            if len(table.blocks) >= MAX_BLOCKS:
                table.incomplete = True
                break
            block = TableBlock(name=line[5:] or "data", kind="pairs", columns=["Label", "Value"])
            table.blocks.append(block)
            inLoopHeader = False
            continue
        if block is None:
            continue
        if lowered == "loop_":
            if block.kind == "loop" or block.rows:
                # A second loop in the same block: shown as its own table.
                block = TableBlock(name=block.name, kind="loop")
                table.blocks.append(block)
            block.kind = "loop"
            block.columns = []
            block.rows = []
            block.totalRows = 0
            inLoopHeader = True
            continue
        if line.startswith("_"):
            tokens = _tokens(line)
            label = tokens[0][1:]
            if block.kind == "loop" and (inLoopHeader or not block.totalRows):
                block.columns.append(label)
                inLoopHeader = True
            else:
                block.kind = "pairs"
                if len(block.rows) < rowLimit:
                    block.rows.append([label, " ".join(tokens[1:])])
                else:
                    block.truncated = True
                block.totalRows = (block.totalRows or 0) + 1
            continue
        if block.kind == "loop":
            inLoopHeader = False
            block.totalRows = (block.totalRows or 0) + 1
            if len(block.rows) < rowLimit:
                values = _tokens(line)
                width = len(block.columns)
                if width and len(values) < width:
                    values += [""] * (width - len(values))
                block.rows.append(values[:width] if width else values)
            else:
                block.truncated = True

    # Blocks without content (e.g. a data_ line alone) are not worth a tab.
    table.blocks = [b for b in table.blocks if b.rows or b.columns and b.kind == "loop"]
    return table


def readDelimitedTable(lines: Iterable[str], delimiter: str, fmt: str,
                       rowLimit: int = DEFAULT_ROW_LIMIT, readLimit: int = DEFAULT_READ_LIMIT) -> MetadataTable:
    """A CSV/TSV file as one block: its header row, its first rows and how many there are."""
    table = MetadataTable(format=fmt)
    block = TableBlock(name=fmt.upper(), kind="loop")
    readBytes = 0

    def limited():
        nonlocal readBytes
        for raw in lines:
            readBytes += len(raw)
            if readBytes > readLimit:
                table.incomplete = True
                return
            yield raw

    reader = csv.reader(limited(), delimiter=delimiter)
    for index, row in enumerate(reader):
        if index == 0:
            block.columns = [str(value) for value in row]
            continue
        if not any(str(value).strip() for value in row):
            continue
        block.totalRows += 1
        if len(block.rows) < rowLimit:
            block.rows.append([str(value) for value in row])
        else:
            block.truncated = True
    if table.incomplete:
        block.totalRows = None
    if block.columns:
        table.blocks.append(block)
    return table


TABLE_FORMATS = {".star": "star", ".xmd": "xmd", ".csv": "csv", ".tsv": "tsv"}


def readMetadataTableFile(path: str, rowLimit: int = DEFAULT_ROW_LIMIT,
                          readLimit: int = DEFAULT_READ_LIMIT) -> MetadataTable:
    """The table of a .star, .xmd, .csv or .tsv file."""
    lowered = str(path).lower()
    fmt = next((value for suffix, value in TABLE_FORMATS.items() if lowered.endswith(suffix)), "star")
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        if fmt in ("csv", "tsv"):
            return readDelimitedTable(handle, "\t" if fmt == "tsv" else ",", fmt, rowLimit, readLimit)
        return readStarTable(handle, fmt, rowLimit, readLimit)
