# file: outputs_preview.py
from __future__ import annotations

import csv
import io
import math
import os
import os.path
import tarfile
import zipfile
import re
import shlex
from pathlib import Path as FsPath, Path
from typing import Union, List, Dict, Any, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from fastapi import HTTPException
from fastapi.responses import Response, JSONResponse
from tomo.objects import SetOfTiltSeries

from app.backend.utils.constants import (
    TEXT_FILE_EXTENSIONS,
    SQLITE_EXTENSIONS,
    PDF_EXTENSIONS,
    TABLE_EXTENSIONS,
    ARCHIVE_EXTENSIONS,
)
from app.backend.utils.file_handlers import FileHandlers
from pwem.emlib.image.image_readers import ImageReadersRegistry
from pwem.objects import (
    SetOfClasses2D,
    SetOfParticles,
    SetOfClasses3D,
    SetOfVolumes,
    SetOfFSCs,
    SetOfMicrographs,
)
from pwem.viewers import RENDER
from pwem.viewers.viewers_data import RegistryViewerConfig


class OutputsPreview(FileHandlers):
    """
    High-level preview router for Scipion protocol outputs.
    Extends FileHandlers with table/STAR, PDF, archives, and SQLite previews,
    delegating images/MRC and text previews to the parent to avoid duplication.
    """

    def __init__(self, currentProject, protocol, output):
        super().__init__(currentProject)
        self.currentProject = currentProject
        self.protocol = protocol
        self.output = output

    # ------------------------------------------------------------------ #
    # Entry router
    # ------------------------------------------------------------------ #
    def preview(
        self,
        protocolId: Union[int, str],
        path: str,
        objectManager,
        inline: bool = True,
        table: Optional[str] = None,
        limit: int = 200,
    ):
        filePath = FsPath(path)

        if (not filePath.exists()) or (not filePath.is_file()):
            raise HTTPException(status_code=404, detail="File not found")

        suffix = filePath.suffix.lower()
        mime = self._guessMime(filePath)

        # 1) Volumes & normal images (delegate to parent)
        if self._isPreviewableMrc(filePath):
            return self.previewProtocolImageFile(protocolId, path, inline=True)
        if mime.startswith("image/"):
            return self.previewProtocolImageFile(protocolId, path, inline=inline)

        # 2) PDFs
        if suffix in PDF_EXTENSIONS or mime == "application/pdf":
            return self._previewPdf(filePath, inline=inline)

        # 3) Archives (index as JSON when inline=True)
        if self._isArchiveSuffix(suffix):
            return self._previewArchive(filePath, inline=inline)

        # 4) SQLite
        if suffix in SQLITE_EXTENSIONS:
            return self._previewSqlite(filePath, objectManager)

        # 5) Tables (CSV/TSV/STAR) -> JSON table
        if suffix in TABLE_EXTENSIONS:
            return self._previewTableFile(filePath, limit=limit)

        # 6) Plain text-ish (delegate to parent)
        if mime.startswith("text/") or suffix in TEXT_FILE_EXTENSIONS:
            return self.previewProtocolTextFile(protocolId, path)

        # 7) Fallback: raw bytes + meta headers
        return self._fallbackBinary(filePath, inline=inline)

    # -------------------------
    # PDF
    # -------------------------
    def _previewPdf(self, filePath: FsPath, inline: bool) -> Response:
        mediaType = "application/pdf"
        disp = "inline" if inline else "attachment"
        return Response(
            content=filePath.read_bytes(),
            media_type=mediaType,
            headers={
                "Content-Disposition": f'{disp}; filename="{filePath.name}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )

    # -------------------------
    # Archives (ZIP/TAR)
    # -------------------------
    def _isArchiveSuffix(self, suffix: str) -> bool:
        return suffix in ARCHIVE_EXTENSIONS or any(
            str(suffix).endswith(ext) for ext in ARCHIVE_EXTENSIONS
        )

    def _previewArchive(self, filePath: FsPath, inline: bool):
        if not inline:
            mediaType = self._guessMime(filePath) or "application/octet-stream"
            return Response(
                content=filePath.read_bytes(),
                media_type=mediaType,
                headers={
                    "Content-Disposition": f'attachment; filename="{filePath.name}"',
                    "Access-Control-Expose-Headers": "Content-Disposition",
                },
            )

        entries: List[Dict[str, Any]] = []
        if zipfile.is_zipfile(filePath):
            with zipfile.ZipFile(filePath, "r") as zf:
                for i in zf.infolist():
                    entries.append(
                        {
                            "name": i.filename,
                            "isDir": i.is_dir(),
                            "size": None if i.is_dir() else i.file_size,
                            "compressedSize": None if i.is_dir() else i.compress_size,
                        }
                    )
            kind = "zip"
        else:
            try:
                with tarfile.open(filePath, "r:*") as tf:
                    for m in tf.getmembers():
                        entries.append(
                            {
                                "name": m.name,
                                "isDir": m.isdir(),
                                "size": None if m.isdir() else m.size,
                            }
                        )
                kind = "tar"
            except tarfile.ReadError:
                raise HTTPException(status_code=415, detail="Unsupported archive format")

        headers = {
            "X-Preview-Type": "archive",
            "X-Archive-Kind": kind,
            "X-Preview-SizeBytes": str(filePath.stat().st_size),
            "Access-Control-Expose-Headers": "X-Preview-Type, X-Archive-Kind, X-Preview-SizeBytes",
        }
        return JSONResponse({"entries": entries}, headers=headers)

    # -------------------------
    # SQLite (read-only)
    # -------------------------
    _SAFE_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def _previewSqlite(self, filePath: FsPath, objectManager) -> Any:
        objectManager._fileName = filePath
        objectManager._dao = None
        objectManager._tables = {}
        objectManager.selectDAO()
        objectManager.getTables()
        return self.getPreviewOutput(objectManager)

    # -------------------------
    # Tables (CSV/TSV/STAR)
    # -------------------------
    def _previewTableFile(self, filePath: FsPath, limit: int = 200) -> JSONResponse:
        suffix = filePath.suffix.lower()
        if suffix == ".csv" or suffix == ".tsv":
            return self._previewCsvTsv(
                filePath, limit=limit, delimiter=("\t" if suffix == ".tsv" else ",")
            )
        if suffix == ".star":
            return self._previewStar(filePath, limit=limit)

        raise HTTPException(status_code=415, detail="Unsupported table format")

    def _previewCsvTsv(self, filePath: FsPath, limit: int, delimiter: str) -> JSONResponse:
        rows: List[Dict[str, Any]] = []
        with filePath.open("r", encoding="utf-8", errors="ignore") as fh:
            reader = csv.DictReader(fh, delimiter=delimiter)
            columns = reader.fieldnames or []
            for i, row in enumerate(reader):
                if i >= limit:
                    break
                rows.append({k: row.get(k) for k in columns})

        headers = {
            "X-Preview-Type": "table",
            "X-Preview-Format": "csv" if delimiter == "," else "tsv",
            "X-Preview-Columns": ",".join(columns),
            "X-Preview-RowCount": str(len(rows)),
            "Access-Control-Expose-Headers": "X-Preview-Type, X-Preview-Format, X-Preview-Columns, X-Preview-RowCount",
        }
        return JSONResponse({"columns": columns, "rows": rows}, headers=headers)

    def _previewStar(self, filePath: FsPath, limit: int) -> JSONResponse:
        text = filePath.read_text(encoding="utf-8", errors="ignore")
        lines = [ln.strip() for ln in text.splitlines()]

        i = 0
        n = len(lines)
        while i < n and lines[i].lower() != "loop_":
            i += 1
        if i >= n:
            preview = "\n".join(lines[:200])
            headers = {
                "X-Preview-Type": "text",
                "X-Preview-Note": "STAR without loop_ block; returning head",
                "Access-Control-Expose-Headers": "X-Preview-Type, X-Preview-Note",
            }
            return JSONResponse({"text": preview}, headers=headers)

        i += 1
        columns: List[str] = []
        while i < n and lines[i].startswith("_"):
            tok = lines[i].split()[0]
            columns.append(tok.lstrip("_"))
            i += 1

        rows: List[List[str]] = []
        while i < n and len(rows) < limit:
            ln = lines[i]
            if not ln or ln.lower() == "loop_" or ln.startswith("_") or ln.lower().startswith("data_"):
                break
            try:
                tokens = shlex.split(ln, posix=True)
            except Exception:
                tokens = ln.split()
            if tokens:
                rows.append(tokens)
            i += 1

        normRows: List[Dict[str, Any]] = []
        for r in rows:
            if len(r) != len(columns):
                r = (r + [""] * len(columns))[: len(columns)]
            normRows.append({columns[j]: r[j] for j in range(len(columns))})

        headers = {
            "X-Preview-Type": "table",
            "X-Preview-Format": "star",
            "X-Preview-Columns": ",".join(columns),
            "X-Preview-RowCount": str(len(normRows)),
            "Access-Control-Expose-Headers": "X-Preview-Type, X-Preview-Format, X-Preview-Columns, X-Preview-RowCount",
        }
        return JSONResponse({"columns": columns, "rows": normRows}, headers=headers)

    # -------------------------
    # Fallback bytes
    # -------------------------
    def _fallbackBinary(self, filePath: FsPath, inline: bool) -> Response:
        mediaType = self._guessMime(filePath)
        meta = {"mime": mediaType, "sizeBytes": filePath.stat().st_size}
        headers = {
            "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{filePath.name}"',
            **self._buildPreviewHeaders(meta),
        }
        return Response(content=filePath.read_bytes(), media_type=mediaType, headers=headers)

    # ------------------------------------------------------------------ #
    # Output-type dispatcher
    # ------------------------------------------------------------------ #
    def getPreviewOutput(self, objectManager) -> Response:
        config = RegistryViewerConfig.getConfig(type(self.output)) or {}

        if isinstance(self.output, (SetOfParticles, SetOfClasses2D)):
            tiles, labels, cols, tileSize, summary = self._collectParticlesOrClasses2D(
                config, objectManager
            )
            filename = "particles_gallery.png"
            return self._makeGalleryResponse(tiles, labels, cols, tileSize, filename, summary)

        if isinstance(self.output, (SetOfClasses3D, SetOfVolumes)):
            tiles, labels, cols, tileSize, summary = self._collectClasses3DOrVolumes(objectManager)
            filename = "volumes_gallery.png"
            return self._makeGalleryResponse(tiles, labels, cols, tileSize, filename, summary)

        if isinstance(self.output, SetOfTiltSeries):
            tiles, labels, cols, tileSize, summary = self._collectSetOfTiltSeries(objectManager)
            filename = "volumes_gallery.png"
            return self._makeGalleryResponse(tiles, labels, cols, tileSize, filename, summary)

        if isinstance(self.output, SetOfFSCs):
            filename = "fsc.png"
            return self._makeFSCResponse(filename)

        if isinstance(self.output, SetOfMicrographs):
            tiles, labels, cols, tileSize, summary = self._collectSetOfMicrographs(objectManager)
            filename = "micrographs_gallery.png"
            return self._makeGalleryResponse(tiles, labels, cols, tileSize, filename, summary)

        return self._makeNoPreviewImageResponse()

    # ------------------------------------------------------------------ #
    # Micrographs (2D, grayscale)
    # ------------------------------------------------------------------ #
    def _collectSetOfMicrographs(
        self, objectManager
    ) -> Tuple[List[np.ndarray], List[str], int, int, str]:
        mainTable = "objects"
        table = objectManager.getTable(mainTable)
        rowCount = objectManager.getTableRowCount(mainTable) or 0
        if not rowCount:
            raise HTTPException(status_code=404, detail="No rows available for preview")

        columns = table.getColumns()
        cfg = RegistryViewerConfig.getConfig(type(self.output)) or {}
        cfgRenderRaw = cfg.get(RENDER, "")
        cfgTokens = []
        if isinstance(cfgRenderRaw, str) and cfgRenderRaw.strip():
            cfgTokens = [t for t in re.split(r"[,\s]+", cfgRenderRaw) if t]
        candidates = cfgTokens + ["_filename", "micrograph", "micName", "file", "path", "stack"]

        renderIdx = self.getRenderColumnIndex(candidates, columns)

        rows = objectManager.getRows(mainTable, 0, 32) or []
        if not rows:
            raise HTTPException(status_code=404, detail="No micrograph rows available for preview")

        tiles: List[np.ndarray] = []
        labels: List[str] = []
        maxTiles = 12
        cols = 3
        tileSize = 54

        for row in rows:
            if len(tiles) >= maxTiles:
                break

            relPath, sliceIndex = self.extractPathFromRow(row, renderIdx)
            if not relPath:
                continue

            filePath = self.resolveFilePath(relPath)
            if not filePath or not filePath.exists():
                continue

            arr = self._read2dTile(filePath, sliceIndex=sliceIndex, preferCentral=False)
            if arr is None:
                continue

            tiles.append(arr)
            labels.append(Path(filePath).stem or "")

        if not tiles:
            raise HTTPException(
                status_code=404,
                detail="Could not extract any micrograph images for preview",
            )

        if labels and len(labels) < len(tiles):
            labels.extend([""] * (len(tiles) - len(labels)))

        total = rowCount or len(tiles)
        summary = f"{total} micrographs" if total != 1 else "1 micrograph"
        return tiles, labels, cols, tileSize, summary

    # ------------------------------------------------------------------ #
    # Particles / Classes2D (grayscale)
    # ------------------------------------------------------------------ #
    def _collectParticlesOrClasses2D(
        self,
        config,
        objectManager,
    ) -> Tuple[List[np.ndarray], List[str], int, int, str]:
        mainTable = "objects"
        table = objectManager.getTable(mainTable)
        rowCount = objectManager.getTableRowCount(mainTable) or 0
        rows = objectManager.getRows(mainTable, 0, 32)
        if not rows:
            raise HTTPException(status_code=404, detail="No particle rows available for preview")

        renderRaw = config.get(RENDER, "")
        renderTokens = []
        if isinstance(renderRaw, str) and renderRaw.strip():
            renderTokens = [t for t in re.split(r"[,\s]+", renderRaw) if t]
        renderTokens += ["stack", "_filename"]

        columns = table.getColumns()
        renderIdx = self.getRenderColumnIndex(renderTokens, columns)

        maxTiles = 12
        cols = 3
        tileSize = 50
        labels: List[str] = []

        isClasses2D = isinstance(self.output, SetOfClasses2D)
        renderSizeIdx: Optional[int] = None

        if isClasses2D:
            cols = 2
            tileSize = 70
            renderSizeIdx = self.getRenderColumnIndex(["_size"], columns)

        relPath, _ = self.extractPathFromRow(rows[0], renderIdx)
        filePath = self.resolveFilePath(relPath)
        if not filePath.exists():
            raise HTTPException(
                status_code=404,
                detail="Stack file not found for particles preview",
            )

        try:
            imgStk = ImageReadersRegistry.open(str(filePath))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Could not open image stack for preview: {e}",
            )

        tiles: List[np.ndarray] = []

        for row in rows:
            if len(tiles) >= maxTiles:
                break

            rowId = getattr(row, "_id", None)
            if rowId is None:
                try:
                    rowId = row.getId()
                except Exception:
                    continue
            if rowId is None:
                continue

            try:
                pilImg = imgStk.getImage(index=rowId - 1, pilImage=True)
            except Exception:
                continue

            arr = self._pilTo2dTile(imgStk, pilImg)
            if arr is None:
                continue

            tiles.append(arr)

            if isClasses2D and renderSizeIdx is not None:
                try:
                    sizeVal = row.getValues()[renderSizeIdx]
                    labels.append(f"{sizeVal} particles")
                except Exception:
                    labels.append("")

        if not tiles:
            raise HTTPException(
                status_code=404,
                detail="Could not extract any particle images for preview",
            )

        if labels and len(labels) < len(tiles):
            labels.extend([""] * (len(tiles) - len(labels)))

        total = rowCount or len(tiles)
        summary = f"{total} classes" if isClasses2D else f"{total} particles"
        return tiles, labels, cols, tileSize, summary

    # ------------------------------------------------------------------ #
    # Classes3D / Volumes (colorized with colormap)
    # ------------------------------------------------------------------ #
    def _collectClasses3DOrVolumes(
        self,
        objectManager,
    ) -> Tuple[List[np.ndarray], List[str], int, int, str]:
        """
        Collect tiles for:
          - SetOfClasses3D: central slice of each volume + size label.
          - SetOfVolumes: central slice of each volume.

        For both, tiles are colorized using a colormap (default 'inferno').
        """
        mainTable = "objects"
        table = objectManager.getTable(mainTable)
        rowCount = objectManager.getTableRowCount(mainTable) or 0
        rows = objectManager.getRows(mainTable, 0, 32)
        if not rows:
            raise HTTPException(status_code=404, detail="No rows available for preview")

        columns = table.getColumns()
        renderIdx = self.getRenderColumnIndex(["stack"], columns)

        tiles: List[np.ndarray] = []
        labels: List[str] = []
        maxTiles = 12
        cols = 2
        tileSize = 70

        isClasses3D = isinstance(self.output, SetOfClasses3D)
        renderSizeIdx: Optional[int] = None
        if isClasses3D:
            renderSizeIdx = self.getRenderColumnIndex(["_size"], columns)

        cmapName = self._resolveColormapForOutputType(defaultCmap="inferno")

        for row in rows:
            if len(tiles) >= maxTiles:
                break

            relPath, _ = self.extractPathFromRow(row, renderIdx)
            filePath = self.resolveFilePath(relPath)
            if not filePath.exists():
                continue

            gray = self._read2dTile(filePath, sliceIndex=None, preferCentral=True)
            if gray is None:
                continue

            # Always colorize for these output types
            color = self._applyColormap(gray, cmapName or "inferno")
            tiles.append(color)

            if isClasses3D and renderSizeIdx is not None:
                try:
                    sizeVal = row.getValues()[renderSizeIdx]
                    labels.append(f"{sizeVal} particles")
                except Exception:
                    labels.append("")
            else:
                labels.append("")

        if not tiles:
            raise HTTPException(
                status_code=404,
                detail="Could not extract any class/volume images for preview",
            )

        if labels and len(labels) < len(tiles):
            labels.extend([""] * (len(tiles) - len(labels)))

        total = rowCount or len(tiles)
        summary = f"{total} classes" if isClasses3D else f"{total} items"
        return tiles, labels, cols, tileSize, summary

    # ------------------------------------------------------------------ #
    # TiltSeries (grayscale)
    # ------------------------------------------------------------------ #
    def _collectSetOfTiltSeries(
        self,
        objectManager,
    ) -> Tuple[List[np.ndarray], List[str], int, int, str]:
        mainTable = "objects"
        tables = objectManager.getTables()
        rowCount = objectManager.getTableRowCount(mainTable) or 0

        if not rowCount:
            raise HTTPException(status_code=404, detail="No rows available for preview")

        tiles: List[np.ndarray] = []
        labels: List[str] = []
        maxTiles = 12
        cols = 2
        tileSize = 70
        renderIdx = None

        for name in tables.keys():
            if "_Object" not in name:
                continue
            if len(tiles) >= maxTiles:
                break

            table = objectManager.getTable(name)
            if renderIdx is None:
                columns = table.getColumns()
                renderIdx = self.getRenderColumnIndex(["stack"], columns)

            rows = objectManager.getRows(name, 0, 1)
            if not rows:
                continue

            relPath, _ = self.extractPathFromRow(rows[0], renderIdx)
            filePath = self.resolveFilePath(relPath)
            if not filePath.exists():
                continue

            arr = self._read2dTile(filePath, sliceIndex=None, preferCentral=True)
            if arr is None:
                continue

            tiles.append(arr)

        if not tiles:
            raise HTTPException(
                status_code=404,
                detail="Could not extract any class/volume images for preview",
            )

        summary = f"{rowCount} items" if rowCount > 1 else "1 item"
        return tiles, labels, cols, tileSize, summary

    # ------------------------------------------------------------------ #
    # Helpers (robust)
    # ------------------------------------------------------------------ #
    def getRenderColumnIndex(self, renderField: Union[str, List[str]], columns) -> int:
        if isinstance(renderField, str):
            tokens = [t.strip() for t in re.split(r"[,\s]+", renderField) if t.strip()]
        else:
            tokens = [str(t).strip() for t in (renderField or []) if str(t).strip()]

        for fb in ["stack", "_filename", "micrograph", "micName", "file", "path"]:
            if fb not in tokens:
                tokens.append(fb)

        colNames = [(c.getName() or "") for c in columns]
        colLower = [n.lower() for n in colNames]

        for cand in tokens:
            if cand in colNames:
                return colNames.index(cand)

        for cand in tokens:
            cl = cand.lower()
            if cl in colLower:
                return colLower.index(cl)

        for cand in tokens:
            cl = cand.lower()
            for i, name in enumerate(colLower):
                if cl in name and colNames[i]:
                    return i

        raise HTTPException(
            status_code=400,
            detail=f"Render field not found. Tried: {', '.join(tokens)}",
        )

    def extractPathFromRow(self, row: Any, renderIdx: int) -> Tuple[Optional[str], Optional[int]]:
        values = getattr(row, "_values", None)
        if values is None or renderIdx >= len(values):
            return None, None

        raw = values[renderIdx]
        if raw is None:
            return None, None

        s = str(raw).strip()
        if not s:
            return None, None

        if "@" in s:
            idxStr, relPath = s.split("@", 1)
            try:
                sliceIndex = int(idxStr)
            except ValueError:
                sliceIndex = None
            return relPath, sliceIndex

        return s, None

    def resolveFilePath(self, maybeRelative: str) -> Path:
        p = Path(str(maybeRelative or "")).expanduser()
        if p.is_absolute():
            return p

        candidates = []

        for attr in ("getWorkingDir", "getTmpPath", "getPath"):
            if hasattr(self.protocol, attr):
                try:
                    root = getattr(self.protocol, attr)()
                    if root:
                        candidates.append(Path(root))
                except Exception:
                    pass

        for attr in ("getPath", "path", "projPath", "projDir", "projectPath"):
            if hasattr(self.currentProject, attr):
                try:
                    val = getattr(self.currentProject, attr)
                    root = Path(val() if callable(val) else val)
                    if root:
                        candidates.append(root)
                except Exception:
                    pass

        candidates.append(Path.cwd())

        for root in candidates:
            try:
                cand = (root / p).resolve()
                if cand.exists():
                    return cand
            except Exception:
                continue

        return (Path.cwd() / p).resolve()

    # ------------------------------------------------------------------ #
    # Gallery (supports L and RGB; can force RGB)
    # ------------------------------------------------------------------ #
    def makeGalleryFromTiles(
        self,
        tiles: List[np.ndarray],
        cols: int = 4,
        tileSize: int = 76,
        labels: Optional[List[str]] = None,
        summary: Optional[str] = None,
        scale: int = 2,
        forceRgb: bool = False,
    ) -> Tuple[bytes, Dict[str, Any]]:
        if not tiles:
            raise HTTPException(status_code=404, detail="No tiles to build gallery")

        # If we know we're showing volumes/classes3D, force RGB canvas (color colormap)
        if forceRgb:
            isRgb = True
        else:
            first = tiles[0]
            isRgb = isinstance(first, np.ndarray) and first.ndim == 3 and first.shape[-1] == 3

        maxTiles = min(len(tiles), cols * math.ceil(len(tiles) / cols))
        cols = max(1, cols)
        rows = math.ceil(maxTiles / cols)

        hasLabels = bool(labels)
        hasSummary = bool(summary)

        pad = 2
        padPx = pad * scale
        cellPx = tileSize * scale

        try:
            labelFontSize = max(12 * scale, int(cellPx * 0.22))
            labelFont = ImageFont.truetype("arial.ttf", labelFontSize)
        except Exception:
            labelFont = ImageFont.load_default()
            labelFontSize = getattr(labelFont, "size", 12 * scale)

        if hasLabels:
            sample = "0000"
            bbox = labelFont.getbbox(sample)
            textH = bbox[3] - bbox[1] if bbox else labelFontSize
            minBar = textH + 2 * scale
            defaultBar = textH + 4 * scale
            maxBar = int(cellPx * 0.40)
            labelBarHeight = max(minBar, min(defaultBar, maxBar))
        else:
            labelBarHeight = 0

        canvasW = cols * cellPx + (cols + 1) * padPx
        baseCanvasH = rows * cellPx + (rows + 1) * padPx

        summaryFont = None
        summaryHeight = 0
        if hasSummary:
            try:
                if cols >= 4:
                    baseFromWidth = canvasW * 0.07
                    baseFromCell = cellPx * 0.55
                else:
                    baseFromWidth = canvasW * 0.05
                    baseFromCell = cellPx * 0.35

                summaryFontSize = int(max(baseFromWidth, baseFromCell, 18 * scale))
                summaryFontSize = int(min(summaryFontSize, cellPx * 0.9))
                summaryFont = ImageFont.truetype("arial.ttf", summaryFontSize)
            except Exception:
                summaryFont = labelFont
                summaryFontSize = labelFontSize

            sbbox = summaryFont.getbbox(summary)
            sH = sbbox[3] - sbbox[1] if sbbox else summaryFontSize
            summaryPadY = max(4 * scale, int(sH * 0.2))
            summaryHeight = sH + 2 * summaryPadY

        # Canvas mode & colors
        canvasMode = "RGB" if isRgb else "L"
        bgColor = (255, 255, 255) if isRgb else 255
        barColor = (30, 30, 30) if isRgb else 30
        textLight = (255, 255, 255) if isRgb else 255
        summaryBand = (230, 230, 230) if isRgb else 230
        textDark = (0, 0, 0) if isRgb else 0

        canvasH = baseCanvasH + summaryHeight
        canvas = Image.new(canvasMode, (canvasW, canvasH), color=bgColor)

        # Paste tiles
        for i, arr in enumerate(tiles[:maxTiles]):
            if arr is None:
                continue

            # Normalize dtype/shape for mode
            if isRgb:
                if isinstance(arr, np.ndarray) and arr.ndim == 2:
                    arr = np.stack([arr, arr, arr], axis=-1)
                if not (isinstance(arr, np.ndarray) and arr.ndim == 3 and arr.shape[-1] == 3):
                    continue
            else:
                if isinstance(arr, np.ndarray) and arr.ndim == 3 and arr.shape[-1] == 3:
                    arr = np.mean(arr.astype(np.float32), axis=-1).astype(np.uint8)
                if not (isinstance(arr, np.ndarray) and arr.ndim == 2):
                    continue

            # dimensions
            if arr.ndim == 2:
                h, w = arr.shape
            else:
                h, w, _ = arr.shape
            if h <= 0 or w <= 0:
                continue

            if arr.dtype != np.uint8:
                arr = arr.astype(np.uint8, copy=False)

            imgScale = min(cellPx / float(w), cellPx / float(h))
            if imgScale <= 0:
                continue

            newW = max(1, int(w * imgScale))
            newH = max(1, int(h * imgScale))

            tileImg = Image.fromarray(arr, mode=("RGB" if isRgb else "L")).resize(
                (newW, newH), resample=Image.Resampling.BILINEAR
            )

            tileCanvas = Image.new(canvasMode, (cellPx, cellPx), color=bgColor)

            x0 = (cellPx - newW) // 2
            y0 = (cellPx - newH) // 2
            tileCanvas.paste(tileImg, (x0, y0))

            if hasLabels and i < len(labels) and labels[i]:
                text = str(labels[i])
                draw = ImageDraw.Draw(tileCanvas)

                bbox = draw.textbbox((0, 0), text, font=labelFont)
                textW = bbox[2] - bbox[0]
                textH = bbox[3] - bbox[1]

                maxWidth = cellPx - 6 * scale
                if textW > maxWidth and textW > 0:
                    ratio = maxWidth / float(textW)
                    maxChars = max(3, int(len(text) * ratio))
                    text = text[:maxChars]
                    bbox = draw.textbbox((0, 0), text, font=labelFont)
                    textW = bbox[2] - bbox[0]
                    textH = bbox[3] - bbox[1]

                barTop = max(0, cellPx - labelBarHeight)
                barBottom = cellPx - 1

                draw.rectangle([(0, barTop), (cellPx - 1, barBottom)], fill=barColor)
                xText = max(3 * scale, (cellPx - textW) // 2)
                yText = barTop + max(1 * scale, (labelBarHeight - textH) // 2)
                draw.text((xText, yText), text, font=labelFont, fill=textLight)

            r = i // cols
            c = i % cols
            gx = padPx + c * (cellPx + padPx)
            gy = padPx + r * (cellPx + padPx)
            canvas.paste(tileCanvas, (gx, gy))

        if hasSummary and summaryFont is not None:
            draw = ImageDraw.Draw(canvas)
            sbbox = summaryFont.getbbox(summary)
            sW = sbbox[2] - sbbox[0]
            sH = sbbox[3] - sbbox[1]

            bandTop = canvasH - summaryHeight
            bandBottom = canvasH - 1

            draw.rectangle([(0, bandTop), (canvasW - 1, bandBottom)], fill=summaryBand)

            xSummary = max(padPx, (canvasW - sW) // 2)
            ySummary = bandTop + max(2 * scale, (summaryHeight - sH) // 2)

            draw.text((xSummary, ySummary), summary, font=summaryFont, fill=textDark)

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        pngBytes = buf.getvalue()

        meta = {
            "width": canvasW,
            "height": canvasH,
            "tiles": maxTiles,
            "grid": [rows, cols],
            "tileSize": tileSize,
            "scale": scale,
            "labelBarHeight": int(labelBarHeight),
            "hasSummary": bool(hasSummary),
            "note": "Gallery (RGB)" if isRgb else "Gallery (L)",
        }
        return pngBytes, meta

    def buildPreviewHeadersFallback(self, meta: Dict[str, Any]) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if meta.get("mime"):
            headers["X-Preview-Mime"] = str(meta["mime"])
        if meta.get("width") is not None:
            headers["X-Preview-Width"] = str(meta["width"])
        if meta.get("height") is not None:
            headers["X-Preview-Height"] = str(meta["height"])
        if meta.get("tiles") is not None:
            headers["X-Preview-Tiles"] = str(meta["tiles"])
        if meta.get("note"):
            headers["X-Preview-Note"] = str(meta["note"])

        expose = [
            "Content-Disposition",
            "X-Preview-Mime",
            "X-Preview-Width",
            "X-Preview-Height",
            "X-Preview-Tiles",
            "X-Preview-Note",
        ]
        headers["Access-Control-Expose-Headers"] = ", ".join(expose)
        return headers

    # ------------------------------------------------------------------ #
    # Fallback "No Image" PNG
    # ------------------------------------------------------------------ #
    def _makeNoPreviewImageResponse(self) -> Response:
        width, height = 140, 140
        bgColor = 245
        borderColor = 200
        textColor = 80

        img = Image.new("L", (width, height), color=bgColor)
        draw = ImageDraw.Draw(img)

        margin = 10
        draw.rectangle([(margin, margin), (width - margin, height - margin)], outline=borderColor, width=1)

        msg = "No Image Available"
        try:
            fontSize = 52
            font = ImageFont.truetype("arial.ttf", fontSize)
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), msg, font=font)
        textW = bbox[2] - bbox[0]
        textH = bbox[3] - bbox[1]
        x = (width - textW) // 2
        y = (height - textH) // 2
        draw.text((x, y), msg, font=font, fill=textColor)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        pngBytes = buf.getvalue()

        meta = {"mime": "image/png", "kind": "image", "width": width, "height": height, "note": f"No preview available for {type(self.output).__name__}"}
        previewHeaders = self._buildPreviewHeaders(meta) if hasattr(self, "_buildPreviewHeaders") else self.buildPreviewHeadersFallback(meta)

        return Response(
            content=pngBytes,
            media_type="image/png",
            headers={"Content-Disposition": 'inline; filename="no_preview.png"', **previewHeaders},
        )

    # ------------------------------------------------------------------ #
    # Tile readers & colormap
    # ------------------------------------------------------------------ #
    def _read2dTile(
        self,
        filePath: Path,
        sliceIndex: Optional[int] = None,
        preferCentral: bool = False,
    ) -> Optional[np.ndarray]:
        try:
            if not filePath or not Path(filePath).exists():
                return None
            imgStk = ImageReadersRegistry.open(str(filePath))
        except Exception:
            return None

        pilImg = None
        try:
            if sliceIndex is not None:
                idx0 = max(0, int(sliceIndex) - 1)
                pilImg = imgStk.getImage(index=idx0, pilImage=True)
            else:
                if preferCentral:
                    try:
                        pilImg = imgStk.getCentralImage(pilImage=True)
                    except Exception:
                        pilImg = imgStk.getImage(index=0, pilImage=True)
                else:
                    try:
                        pilImg = imgStk.getImage(index=0, pilImage=True)
                    except Exception:
                        pilImg = imgStk.getCentralImage(pilImage=True)
        except Exception:
            pilImg = None

        if pilImg is None:
            return None

        return self._pilTo2dTile(imgStk, pilImg)

    def _pilTo2dTile(self, imgStk, pilImg) -> Optional[np.ndarray]:
        try:
            arr = np.array(pilImg)

            if arr.ndim == 3 and arr.shape[-1] in (3, 4):
                arr = np.array(pilImg.convert("L"))

            arr = np.squeeze(arr)
            if arr.ndim != 2 or arr.size == 0:
                return None

            try:
                arr = imgStk.highlightSlice(arr)
                arr = imgStk.normalizeSlice(arr)
            except Exception:
                pass

            # safe stretch to uint8
            aMin = float(np.nanmin(arr)) if arr.size else 0.0
            aMax = float(np.nanmax(arr)) if arr.size else 1.0
            if (not np.isfinite(aMin)) or (not np.isfinite(aMax)) or (aMax <= aMin):
                arr = np.clip(arr, 0, 255).astype(np.uint8, copy=False)
            else:
                if arr.dtype != np.uint8 or aMax > 255.0 or aMin < 0.0:
                    arr = ((arr - aMin) / (aMax - aMin) * 255.0).astype(np.uint8, copy=False)

            return arr
        except Exception:
            return None

    def _applyColormap(self, grayTile: np.ndarray, cmapName: str = "inferno") -> np.ndarray:
        """
        Apply a matplotlib colormap to a 2D uint8 (or float) tile.
        Returns RGB uint8 array (H, W, 3).
        """
        if grayTile is None or grayTile.ndim != 2:
            return grayTile

        arr = grayTile.astype(np.float32)

        # handle NaNs / constants robustly
        if not np.isfinite(arr).all():
            nanMask = ~np.isfinite(arr)
            arr[nanMask] = np.nanmedian(arr[np.isfinite(arr)]) if np.any(np.isfinite(arr)) else 0.0

        aMin = float(np.nanmin(arr))
        aMax = float(np.nanmax(arr))
        if not np.isfinite(aMin) or not np.isfinite(aMax) or aMax <= aMin:
            arr = np.zeros_like(arr, dtype=np.float32)  # avoid division by zero
        else:
            arr = (arr - aMin) / (aMax - aMin)

        try:
            from matplotlib import cm as mpl_cm
            cmap = mpl_cm.get_cmap(cmapName)
        except Exception:
            from matplotlib import cm as mpl_cm
            cmap = mpl_cm.get_cmap("inferno")

        rgba = cmap(np.clip(arr, 0.0, 1.0), bytes=True)  # uint8 RGBA
        rgb = rgba[..., :3].copy()
        return rgb

    def _resolveColormapForOutputType(self, defaultCmap: str = "inferno") -> Optional[str]:
        """
        Decide which colormap to use for volume thumbnails.
        Env var SCIPION_THUMB_COLORMAP overrides; default 'inferno'.
        Examples:
        inferno (default, perceptually uniform)
        magma, plasma, viridis
        cividis (colorblind-friendly)
        turbo, cubehelix, bone, gist_earth, gray (if you want to return to gray)
        """
        if not isinstance(self.output, (SetOfClasses3D, SetOfVolumes)):
            return None
        cfg = RegistryViewerConfig.getConfig(type(self.output)) or {}
        cm = cfg.get("colormap") or cfg.get("cmap") or os.getenv("SCIPION_GALLERY_COLORMAP")
        return (cm or defaultCmap)

    # ------------------------------------------------------------------ #
    # Final HTTP response builder for galleries
    # ------------------------------------------------------------------ #
    def _makeGalleryResponse(
        self,
        tiles: List[np.ndarray],
        labels: List[str],
        cols: int,
        tileSize: int,
        filename: str,
        summary: Optional[str] = None,
    ) -> Response:
        if not tiles:
            raise HTTPException(
                status_code=404,
                detail="Could not extract any images for preview",
            )

        # Decide if we must force RGB canvas (for colorized volumes/classes3D)
        forceRgb = isinstance(self.output, (SetOfClasses3D, SetOfVolumes))

        useLabels: Optional[List[str]] = labels if any(l for l in labels) else None

        pngBytes, meta = self.makeGalleryFromTiles(
            tiles,
            cols=cols,
            tileSize=tileSize,
            labels=useLabels,
            summary=summary,
            forceRgb=forceRgb,
        )

        metaWithMime = {"mime": "image/png", **meta}
        previewHeaders = self._buildPreviewHeaders(metaWithMime)

        return Response(
            content=pngBytes,
            media_type="image/png",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                **previewHeaders,
            },
        )

    # ------------------------------------------------------------------ #
    # FSC plot (unchanged except backend)
    # ------------------------------------------------------------------ #
    def _makeFSCResponse(self, filename: str = "fsc_preview.png") -> Response:
        matplotlib.use("Agg")
        fscItems = []
        for i, fsc in enumerate(self.output):
            if fsc is None:
                continue
            clone = getattr(fsc, "clone", lambda: fsc)()
            label = getattr(clone, "getObjLabel", lambda: None)() or f"FSC {i + 1}"
            fscItems.append((clone, label))

        if not fscItems:
            raise HTTPException(status_code=404, detail="No FSC data available for preview")

        def getXY(fsc):
            data = fsc.getData()
            if isinstance(data, (list, tuple)) and len(data) == 2:
                x, y = data
                x = np.asarray(x, dtype=float)
                y = np.asarray(y, dtype=float)
            else:
                arr = np.asarray(data, dtype=float)
                if arr.ndim != 2 or arr.shape[1] < 2:
                    raise ValueError("Invalid FSC data shape")
                x, y = arr[:, 0], arr[:, 1]
            mask = np.isfinite(x) & np.isfinite(y)
            return x[mask], y[mask]

        def formatResFromFreq(value, pos):
            if value <= 0:
                return ""
            inv = 1.0 / value
            if inv > 999:
                return ""
            return f"{inv:.1f}"

        fig, ax = plt.subplots(figsize=(4, 3), dpi=120)
        threshold = 0.143
        maxX = 0.0

        for fsc, baseLabel in fscItems:
            try:
                x, y = getXY(fsc)
            except Exception:
                continue
            if x.size == 0:
                continue
            maxX = max(maxX, float(x.max()))

            res = None
            if hasattr(fsc, "calculateResolution"):
                try:
                    res = fsc.calculateResolution(threshold)
                except Exception:
                    res = None

            res = float(res) if res is not None else None
            label = f"{baseLabel} ({res:.2f} Å)" if res and res > 0 else baseLabel

            ax.plot(x, y, linewidth=1.2, label=label)
            if res and res > 0:
                freq = 1.0 / float(res)
                if 0 < freq <= maxX * 1.01:
                    ax.axvline(freq, linestyle="--", linewidth=0.6, alpha=0.6)

        ax.axhline(threshold, linestyle="--", linewidth=0.6, alpha=0.6)

        if maxX <= 0:
            maxX = 1.0
        ax.set_xlim(0, maxX)
        ax.set_ylim(0.0, 1.05)

        ax.set_xlabel("Spatial frequency (1/Å)", fontsize=8)
        ax.set_ylabel("FSC", fontsize=8)
        ax.grid(True, linestyle="--", linewidth=0.3, alpha=0.3)
        if len(fscItems) > 1:
            ax.legend(fontsize=6, loc="best")

        axTop = ax.twiny()
        axTop.set_xlim(ax.get_xlim())
        axTop.set_xlabel("Resolution (Å)", fontsize=8)
        axTop.xaxis.set_major_formatter(FuncFormatter(formatResFromFreq))

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        pngBytes = buf.getvalue()

        meta = {"mime": "image/png", "kind": "image", "note": "FSC curve"}
        previewHeaders = self._buildPreviewHeaders(meta)

        return Response(
            content=pngBytes,
            media_type="image/png",
            headers={"Content-Disposition": f'inline; filename="{filename}"', **previewHeaders},
        )
