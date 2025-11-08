# file: outputs_preview.py
from __future__ import annotations

import csv
import io
import math
import os.path
import tarfile
import zipfile
import re
import shlex
from pathlib import Path as FsPath, Path
from typing import Union, List, Dict, Any, Optional, Tuple
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from fastapi import HTTPException
from fastapi.responses import Response, JSONResponse
from fontTools.ttLib.tables.D__e_b_g import table_D__e_b_g
from metadataviewer.dao.numpy_dao import NumpyDao
from metadataviewer.model import ObjectManager

# Reuse your base helpers & constants
from app.backend.utils.constants import TEXT_FILE_EXTENSIONS, SQLITE_EXTENSIONS, PDF_EXTENSIONS, TABLE_EXTENSIONS, \
    ARCHIVE_EXTENSIONS
from app.backend.utils.file_handlers import FileHandlers
from pwem.emlib.image.image_readers import ImageReadersRegistry
from pwem.objects import SetOfClasses2D, SetOfParticles, SetOfClasses3D, SetOfVolumes
from pwem.viewers import RENDER
from pwem.viewers.mdviewer.readers import ScipionImageReader
from pwem.viewers.mdviewer.sqlite_dao import ScipionSetsDAO
from pwem.viewers.mdviewer.star_dao import StarFile
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

    def preview(
        self,
        protocolId: Union[int, str],
        path: str,
        objectManager,
        inline: bool = True,
        table: Optional[str] = None,
        limit: int = 200,
    ):
        """
        Smart preview router:
        - Images / volumes -> delegates to previewProtocolImageFile (parent)
        - Text / logs -> delegates to previewProtocolTextFile (parent)
        - Tables (CSV/TSV/STAR) -> JSON table
        - PDF -> inline view / download
        - Archives (ZIP/TAR) -> list entries (JSON) or download
        - SQLite -> list tables or show top rows for a given table (JSON)
        - Fallback -> raw bytes + meta headers
        """
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

        # Inline -> JSON index of entries
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
        """
        Minimal STAR parser (best-effort):
        - Finds first 'loop_' block
        - Reads _col lines as headers
        - Splits rows with shlex.split to honor quoted tokens
        """
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

        norm_rows: List[Dict[str, Any]] = []
        for r in rows:
            if len(r) != len(columns):
                r = (r + [""] * len(columns))[: len(columns)]
            norm_rows.append({columns[j]: r[j] for j in range(len(columns))})

        headers = {
            "X-Preview-Type": "table",
            "X-Preview-Format": "star",
            "X-Preview-Columns": ",".join(columns),
            "X-Preview-RowCount": str(len(norm_rows)),
            "Access-Control-Expose-Headers": "X-Preview-Type, X-Preview-Format, X-Preview-Columns, X-Preview-RowCount",
        }
        return JSONResponse({"columns": columns, "rows": norm_rows}, headers=headers)

    # -------------------------
    # Fallback bytes (reuses parent's headers helper)
    # -------------------------
    def _fallbackBinary(self, filePath: FsPath, inline: bool) -> Response:
        mediaType = self._guessMime(filePath)
        meta = {"mime": mediaType, "sizeBytes": filePath.stat().st_size}
        headers = {
            "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{filePath.name}"',
            **self._buildPreviewHeaders(meta),
        }
        return Response(content=filePath.read_bytes(), media_type=mediaType, headers=headers)

    def getPreviewOutput(self, objectManager) -> Response:
        config = RegistryViewerConfig.getConfig(type(self.output)) or {}

        if isinstance(self.output, SetOfParticles) or isinstance(self.output, SetOfClasses2D):  # SetOfParticles, SetOfClasses2D
            return self.getOutputPreviewParticles(config, objectManager)
        elif isinstance(self.output, SetOfClasses3D) or isinstance(self.output, SetOfVolumes):  # SetOfClasses3D, SetOfVolumes
            return self.getOutputPreviewSetOfClasses3D(config, objectManager)

        # Later: SetOfClasses2D, etc.
        raise HTTPException(
            status_code=415,
            detail=f"Preview not implemented for output type {type(self.output).__name__}",
        )

    # --------------- SetOfClasses3D, SetOfVolumes --------------------------
    def getOutputPreviewSetOfClasses3D(self, config, objectManager):
        """Return q gallery image preview to SetOfClasses3D"""
        mainTable = "objects"
        table = objectManager.getTable(mainTable)
        render = 'stack'
        rows = objectManager.getRows(mainTable, 0, 32)  # take more, we filter later
        if not rows:
            raise HTTPException(status_code=404, detail="No particle rows available for preview")

        renderIdx = self.getRenderColumnIndex(render, table.getColumns())

        tiles: List[np.ndarray] = []
        maxTiles = 12

        labels = []
        maxTiles = 12
        cols = 2
        tileSize = 70
        isStack = False
        if isinstance(self.output, SetOfClasses3D):
            isStack = True
            renderSize = self.getRenderColumnIndex('_size', table.getColumns())

        for row in rows:
            if len(tiles) >= maxTiles:
                break
            relPath, sliceIndex = self.extractPathFromRow(row, renderIdx)
            filePath = self.resolveFilePath(relPath)
            if not filePath.exists():
                continue
            imgStk = ImageReadersRegistry().open(str(filePath))
            pilImg = imgStk.getCentralImage(pilImage=True)
            npImg = np.array(pilImg)
            tiles.append(npImg)
            if isStack:
                labels.append("%s particles" % row.getValues()[renderSize])

        if not tiles:
            raise HTTPException(
                status_code=404,
                detail="Could not extract any particle images for preview",
            )

        pngBytes, meta = self.makeGalleryFromTiles(tiles, cols=cols, tileSize=tileSize, labels=labels)

        metaWithMime = {"mime": "image/png", **meta}
        previewHeaders = self._buildPreviewHeaders(metaWithMime)

        return Response(
            content=pngBytes,
            media_type="image/png",
            headers={
                "Content-Disposition": 'inline; filename="particles_gallery.png"',
                **previewHeaders,
            },
        )

    # --------------- SetOfParticles, SetOfClasses2D --------------------------
    def getOutputPreviewParticles(self, config, objectManager):
        """Return q gallery image preview to SetOfParticles"""
        mainTable = "objects"
        table = objectManager.getTable(mainTable)
        render = config.get(RENDER, "")
        rows = objectManager.getRows(mainTable, 0, 32)  # take more, we filter later
        if not rows:
            raise HTTPException(status_code=404, detail="No particle rows available for preview")

        if not render:
            raise HTTPException(
                status_code=400,
                detail="Missing 'order' or 'render' in viewer config for SetOfParticles",
            )

        renderIdx = self.getRenderColumnIndex(render, table.getColumns())

        tiles: List[np.ndarray] = []
        labels = []
        maxTiles = 12
        cols = 4
        tileSize = 96
        isStack = False
        if isinstance(self.output, SetOfClasses2D):
            cols = 2
            tileSize = 70
            isStack = True
            renderSize = self.getRenderColumnIndex('_size', table.getColumns())

        relPath, sliceIndex = self.extractPathFromRow(rows[0], renderIdx)
        filePath = self.resolveFilePath(relPath)
        imgStk = ImageReadersRegistry().open(str(filePath))

        for row in rows:
            if len(tiles) >= maxTiles:
                break
            pilImg = imgStk.getImage(index=row._id-1, pilImage=True)
            npImg = np.array(pilImg)
            tiles.append(npImg)
            if isStack:
                labels.append("%s particles" % row.getValues()[renderSize])

        if not tiles:
            raise HTTPException(
                status_code=404,
                detail="Could not extract any particle images for preview",
            )

        pngBytes, meta = self.makeGalleryFromTiles(tiles, cols=cols, tileSize=tileSize, labels=labels)

        metaWithMime = {"mime": "image/png", **meta}
        previewHeaders = self._buildPreviewHeaders(metaWithMime)

        return Response(
            content=pngBytes,
            media_type="image/png",
            headers={
                "Content-Disposition": 'inline; filename="particles_gallery.png"',
                **previewHeaders,
            },
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def getRenderColumnIndex(self, renderField: str, columns) -> int:
        """
        Resolve which column index to use as render source.
        Fallbacks to '_filename' if needed.
        """
        for index, column in enumerate(columns):
            if column.getName() == renderField:
                return index
        raise HTTPException(
            status_code=400,
            detail=f"Render field '{renderField}' not found in config['order']",
        )

    def extractPathFromRow(self, row: Any, renderIdx: int) -> Tuple[Optional[str], Optional[int]]:
        """
        From Row._values, extract (path, sliceIndex) for the render column.

        Supports:
          - "Runs/.../file.stk"
          - "1@Runs/.../file.stk"  -> sliceIndex = 1 (1-based)
        """
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
        """
        Resolve a path; adjust to your project/protocol layout.
        If paths in the table are already absolute, they are returned as-is.
        Otherwise, they are joined against basePath.
        """
        p = Path(maybeRelative)
        if p.is_absolute():
            return p
        return Path(os.path.abspath(str(p)))

    def makeGalleryFromTiles(
            self,
            tiles: List[np.ndarray],
            cols: int = 4,
            tileSize: int = 76,
            labels: Optional[List[str]] = None,  # Optional per-tile label
            scale: int = 2,  # HiDPI factor for sharper labels
    ) -> Tuple[bytes, Dict[str, Any]]:
        """
        Build a gallery image from a list of 2D tiles.

        - Logical tile size: tileSize x tileSize.
        - Rendered at: (tileSize * scale) to keep label text sharp.
        - Each tile is fully used for the particle.
        - A dark overlay bar is drawn at the bottom for the per-tile label.
        - Tiles are assumed to be already normalized/8-bit.
        """
        if not tiles:
            raise HTTPException(status_code=404, detail="No tiles to build gallery")

        maxTiles = min(len(tiles), cols * math.ceil(len(tiles) / cols))
        cols = max(1, cols)
        rows = math.ceil(maxTiles / cols)

        hasLabels = bool(labels)

        # Layout units in real pixels (HiDPI)
        pad = 2
        padPx = pad * scale
        cellPx = tileSize * scale  # tile side in real pixels

        # Font size as a good fraction of tile height so labels are clearly visible
        try:
            # Around 22–26% of tile height => large and readable
            fontSize = max(12 * scale, int(cellPx * 0.24))
            font = ImageFont.truetype("arial.ttf", fontSize)
        except Exception:
            font = ImageFont.load_default()

        # Compute label bar height only if labels exist
        if hasLabels:
            sample = "0000"
            bbox = font.getbbox(sample)
            textH = bbox[3] - bbox[1] if bbox else fontSize

            # Bar slightly taller than text
            labelBarHeight = textH + 4 * scale

            # Clamp: at least text height, at most ~40% of tile
            minBar = textH + 2 * scale
            maxBar = int(cellPx * 0.4)
            labelBarHeight = max(minBar, min(labelBarHeight, maxBar))
        else:
            labelBarHeight = 0

        canvasW = cols * cellPx + (cols + 1) * padPx
        canvasH = rows * cellPx + (rows + 1) * padPx
        canvas = Image.new("L", (canvasW, canvasH), color=255)

        for i, arr in enumerate(tiles[:maxTiles]):
            if arr is None or arr.ndim != 2:
                continue

            h, w = arr.shape
            if h <= 0 or w <= 0:
                continue

            if arr.dtype != np.uint8:
                arr = arr.astype(np.uint8, copy=False)

            # Scale particle to fit inside the full tile
            imgScale = min(cellPx / float(w), cellPx / float(h))
            if imgScale <= 0:
                continue

            newW = max(1, int(w * imgScale))
            newH = max(1, int(h * imgScale))

            tileImg = Image.fromarray(arr, mode="L").resize(
                (newW, newH),
                resample=Image.Resampling.BILINEAR,
            )

            # Per-tile canvas
            tileCanvas = Image.new("L", (cellPx, cellPx), color=255)

            # Center particle
            x0 = (cellPx - newW) // 2
            y0 = (cellPx - newH) // 2
            tileCanvas.paste(tileImg, (x0, y0))

            # Label overlay at the bottom
            if hasLabels and i < len(labels) and labels[i]:
                text = str(labels[i])
                draw = ImageDraw.Draw(tileCanvas)

                bbox = draw.textbbox((0, 0), text, font=font)
                textW = bbox[2] - bbox[0]
                textH = bbox[3] - bbox[1]

                # Truncate if too wide
                maxWidth = cellPx - 6 * scale
                if textW > maxWidth and textW > 0:
                    ratio = maxWidth / float(textW)
                    maxChars = max(3, int(len(text) * ratio))
                    text = text[:maxChars]
                    bbox = draw.textbbox((0, 0), text, font=font)
                    textW = bbox[2] - bbox[0]
                    textH = bbox[3] - bbox[1]

                # Dark bar at the bottom (overlay)
                barTop = cellPx - labelBarHeight
                barTop = max(0, barTop)
                barBottom = cellPx - 1
                draw.rectangle(
                    [(0, barTop), (cellPx - 1, barBottom)],
                    fill=30,
                )

                # Center text in the bar
                xText = max(3 * scale, (cellPx - textW) // 2)
                yText = barTop + max(1 * scale, (labelBarHeight - textH) // 2)

                draw.text((xText, yText), text, font=font, fill=255)

            # Paste tile into the main canvas
            r = i // cols
            c = i % cols
            gx = padPx + c * (cellPx + padPx)
            gy = padPx + r * (cellPx + padPx)
            canvas.paste(tileCanvas, (gx, gy))

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
            "note": "SetOfParticles gallery with per-tile labels" if hasLabels else "SetOfParticles gallery",
        }
        return pngBytes, meta

    def buildPreviewHeadersFallback(self, meta: Dict[str, Any]) -> Dict[str, str]:
        """
        Simple header builder if you don't inject FileHandlers.
        """
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
