from __future__ import annotations

import csv
import io
import math
import os
import re
import shlex
import tarfile
import zipfile
from pathlib import Path as FsPath, Path
from typing import Union, List, Dict, Any, Optional, Tuple

from threading import RLock
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
    maxThumbSize,
)
from app.backend.utils.file_handlers import FileHandlers  # uses _buildPreviewHeaders
from app.backend.utils.volume_utils import readVolumeArray3d
from pwem.emlib.image.image_readers import ImageReadersRegistry
from pwem.objects import (
    SetOfClasses2D,
    SetOfParticles,
    SetOfClasses3D,
    SetOfVolumes,
    SetOfFSCs,
    SetOfMicrographs,
    EMSet,
)
from pwem.viewers import RENDER
from pwem.viewers.viewers_data import RegistryViewerConfig

# ------------------------------------------------------------------------------
# Stable cache for volume file paths (per protocol root + output signature)
# ------------------------------------------------------------------------------
_VOLUME_PATHS_CACHE: Dict[Tuple[str, str], List[Path]] = {}
_VOLUME_PATHS_LOCK = RLock()


def _outputSignature(out: Any) -> str:
    """Identify output instance across requests in-process."""
    try:
        oid = getattr(out, "getObjId", None)
        if callable(oid):
            return f"{type(out).__name__}:{oid()}"
    except Exception:
        pass
    return f"{type(out).__name__}:{id(out)}"


class OutputsPreview(FileHandlers):
    """
    High-level preview router for Scipion protocol outputs.
    Extends FileHandlers with table/STAR, PDF, archives, and SQLite previews,
    delegating images/MRC and text previews to the parent to avoid duplication.
    """

    def __init__(
        self,
        currentProject,
        protocol,
        output,
        requestHeaders: Optional[Dict[str, str]] = None,
        colormapOverride: Optional[str] = None,
    ):
        super().__init__(currentProject)
        self.currentProject = currentProject
        self.protocol = protocol
        self.output = output

        # Keep a lowercased copy of incoming request headers (if any)
        self.requestHeaders: Dict[str, str] = {
            k.lower(): v for k, v in (requestHeaders or {}).items()
        }

        # Programmatic colormap override (has highest priority)
        self.colormapOverride = colormapOverride

        # Optional note to echo back if a header was invalid
        self._cmapNote: Optional[str] = None

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
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        Main entry point for file previews outside the typed-output flow.
        If 'headers' are provided here, they are merged and may carry UI hints
        such as the preferred colormap (e.g., X-Scipion-Colormap: turbo).
        """
        if headers:
            self._mergeHeaders(headers)

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

        # 3) Archives
        if self._isArchiveSuffix(suffix):
            return self._previewArchive(filePath, inline=inline)

        # 4) SQLite
        if suffix in SQLITE_EXTENSIONS:
            return self._previewSqlite(filePath, objectManager)

        # 5) Tables (CSV/TSV/STAR)
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
                raise HTTPException(
                    status_code=415, detail="Unsupported archive format"
                )

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

    def _previewCsvTsv(
        self, filePath: FsPath, limit: int, delimiter: str
    ) -> JSONResponse:
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
            if (
                not ln
                or ln.lower() == "loop_"
                or ln.startswith("_")
                or ln.lower().startswith("data_")
            ):
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
        return Response(
            content=filePath.read_bytes(), media_type=mediaType, headers=headers
        )

    # ------------------------------------------------------------------ #
    # Output-type dispatcher
    # ------------------------------------------------------------------ #
    def getPreviewOutput(self, objectManager) -> Response:
        config = RegistryViewerConfig.getConfig(type(self.output)) or {}

        if isinstance(self.output, (SetOfParticles, SetOfClasses2D)):
            tiles, labels, cols, tileSize, summary = self._collectParticlesOrClasses2D(
                config, objectManager
            )
            return self._makeGalleryResponse(
                tiles, labels, cols, tileSize, "particles_gallery.png", summary
            )

        if isinstance(self.output, (SetOfClasses3D, SetOfVolumes)):
            tiles, labels, cols, tileSize, summary = (
                self._collectClasses3DOrVolumes(objectManager)
            )
            return self._makeGalleryResponse(
                tiles, labels, cols, tileSize, "volumes_gallery.png", summary
            )

        if isinstance(self.output, SetOfTiltSeries):
            tiles, labels, cols, tileSize, summary = self._collectSetOfTiltSeries(
                objectManager
            )
            return self._makeGalleryResponse(
                tiles, labels, cols, tileSize, "volumes_gallery.png", summary
            )

        if isinstance(self.output, SetOfFSCs):
            return self._makeFSCResponse("fsc.png")

        if isinstance(self.output, SetOfMicrographs):
            tiles, labels, cols, tileSize, summary = self._collectSetOfMicrographs(
                objectManager
            )
            return self._makeGalleryResponse(
                tiles, labels, cols, tileSize, "micrographs_gallery.png", summary
            )

        return self._makeNoPreviewImageResponse()

    # ------------------------------------------------------------------ #
    # Micrographs (2D, grayscale)
    # ------------------------------------------------------------------ #
    def _collectSetOfMicrographs(
        self, objectManager
    ) -> Tuple[List[np.ndarray], List[str], int, int, str]:
        """
        Collect a representative set of micrographs:
        - Deterministic sampling across the full table span.
        - Read each 2D image (slice if needed), normalize, and build small tiles.
        - Labels: basename without extension (truncated).
        """
        mainTable = "objects"
        table = objectManager.getTable(mainTable)
        rowCount = objectManager.getTableRowCount(mainTable) or 0
        if not rowCount:
            raise HTTPException(
                status_code=404, detail="No rows available for preview"
            )

        columns = table.getColumns()
        cfg = RegistryViewerConfig.getConfig(type(self.output)) or {}
        cfgRenderRaw = cfg.get(RENDER, "")
        cfgTokens = (
            [t for t in re.split(r"[,\s]+", cfgRenderRaw) if t]
            if isinstance(cfgRenderRaw, str)
            else []
        )
        candidates = cfgTokens + [
            "_filename",
            "micrograph",
            "micName",
            "file",
            "path",
            "stack",
        ]

        renderIdx = self.getRenderColumnIndex(candidates, columns)
        rows = self._pickSampleRows(objectManager, mainTable, want=32)
        if not rows:
            raise HTTPException(
                status_code=404, detail="No micrograph rows available for preview"
            )

        tiles: List[np.ndarray] = []
        labels: List[str] = []
        maxTiles, cols, tileSize = 12, 3, 54

        for row in rows:
            if len(tiles) >= maxTiles:
                break

            relPath, sliceIndex = self.extractPathFromRow(row, renderIdx)
            if not relPath:
                continue

            filePath = self.resolveFilePath(relPath)
            if not filePath or not filePath.exists():
                continue

            arr = self._read2dTile(
                filePath, sliceIndex=sliceIndex, preferCentral=False
            )
            if arr is None:
                continue

            tiles.append(arr)
            base = Path(filePath).stem or ""
            labels.append(base[:28] + ("..." if len(base) > 28 else ""))

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
        """
        Particles:
          - One common stack; we pull individual particle images by rowId.
        Classes2D:
          - Same, but we show 2 columns and label with class size when available.
        Deterministic sampling is used for representativeness.
        """
        mainTable = "objects"
        table = objectManager.getTable(mainTable)
        rowCount = objectManager.getTableRowCount(mainTable) or 0
        rows = self._pickSampleRows(objectManager, mainTable, want=32)
        if not rows:
            raise HTTPException(
                status_code=404, detail="No particle rows available for preview"
            )

        renderRaw = config.get(RENDER, "")
        renderTokens = (
            [t for t in re.split(r"[,\s]+", renderRaw) if t]
            if isinstance(renderRaw, str)
            else []
        )
        renderTokens += ["stack", "_filename"]

        columns = table.getColumns()
        renderIdx = self.getRenderColumnIndex(renderTokens, columns)

        maxTiles, cols, tileSize = 12, 3, 50
        labels: List[str] = []

        isClasses2D = isinstance(self.output, SetOfClasses2D)
        renderSizeIdx: Optional[int] = None
        if isClasses2D:
            cols, tileSize = 2, 70
            renderSizeIdx = self.getRenderColumnIndex(["_size"], columns)

        relPath, _ = self.extractPathFromRow(rows[0], renderIdx)
        filePath = self.resolveFilePath(relPath)
        if not filePath.exists():
            raise HTTPException(
                status_code=404, detail="Stack file not found for particles preview"
            )

        try:
            imgStk = ImageReadersRegistry.open(str(filePath))
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Could not open image stack for preview: {e}"
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
        self, objectManager
    ) -> Tuple[List[np.ndarray], List[str], int, int, str]:
        """
        Collect tiles for:
          - SetOfClasses3D: central slice of each volume + size label.
          - SetOfVolumes: central slice of each volume.

        For both, tiles are colorized using a colormap (default 'viridis').
        Deterministic sampling is used for representativeness.
        """
        mainTable = "objects"
        table = objectManager.getTable(mainTable)
        rowCount = objectManager.getTableRowCount(mainTable) or 0
        rows = self._pickSampleRows(objectManager, mainTable, want=24)
        if not rows:
            raise HTTPException(
                status_code=404, detail="No rows available for preview"
            )

        columns = table.getColumns()
        renderIdx = self.getRenderColumnIndex(["stack"], columns)

        tiles: List[np.ndarray] = []
        labels: List[str] = []
        maxTiles, cols, tileSize = 12, 2, 70

        isClasses3D = isinstance(self.output, SetOfClasses3D)
        renderSizeIdx: Optional[int] = None
        if isClasses3D:
            renderSizeIdx = self.getRenderColumnIndex(["_size"], columns)

        cmapName = self._resolveColormapForOutputType(defaultCmap="viridis")

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

            color = self._applyColormap(gray, cmapName or "viridis")
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

    def renderImageFromFilePath(
            self,
            filePath: Union[str, Path],
            size: Optional[int] = None,
            fmt: str = "png",
            index: int = 0,
            inline: bool = True,
            quality: int = 75,
            applyTransform: bool = True,
            rot=None,
            shifts=None
    ) -> Response:
        """
        Render a single 2D image (or first slice of a stack) from an absolute file path.

        - Uses the same normalization pipeline as gallery thumbnails.
        - Optionally resizes to a square thumbnail with max side = size.
        - If applyTransform is True and rot/shifts are provided, apply alignment
          transforms scaled to the thumbnail size.
        """
        p = Path(str(filePath)).expanduser().resolve()
        if not p.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"Image file not found: {p}",
            )

        try:
            reader = ImageReadersRegistry.open(str(p))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Could not open image file: {e}",
            )

        # Try first image, fallback to central if needed
        try:
            pilImg = reader.getImage(index=index, pilImage=True)
        except Exception:
            try:
                pilImg = reader.getCentralImage(pilImage=True)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Could not read image from file: {e}",
                )

        # Keep original dimensions to be able to rescale shifts
        try:
            origWidth, origHeight = pilImg.size
        except Exception:
            # Fallback in case PIL image is not standard
            arr = np.asarray(pilImg)
            if arr.ndim >= 2:
                origHeight, origWidth = arr.shape[0], arr.shape[1]
            else:
                origWidth, origHeight = 1, 1

        # Build thumbnail/tile
        tile = self._pilTo2dTile(reader, pilImg, thumbSize=size)

        # Apply alignment transforms in thumbnail space if requested
        if (
                applyTransform
                and rot is not None
                and shifts is not None
                and tile is not None
                and origWidth > 0
                and origHeight > 0
        ):
            # tile is a 2D array: (h, w) or (h, w, 1)
            tileArr = np.asarray(tile)
            if tileArr.ndim == 2:
                tileHeight, tileWidth = tileArr.shape
            else:
                tileHeight, tileWidth = tileArr.shape[0], tileArr.shape[1]

            # Scale shifts from original size to thumbnail size
            scaleX = tileWidth / float(origWidth)
            scaleY = tileHeight / float(origHeight)

            scaledShifts = (shifts[0] * scaleX, shifts[1] * scaleY)

            # Apply transform on the thumbnail
            tile = reader.transformSlice(tileArr, scaledShifts, rot)

        # Apply flip at the end to match viewer orientation
        tile = reader.flipSlice(tile)

        if tile is None:
            raise HTTPException(
                status_code=500,
                detail="Empty or invalid image tile",
            )

        fmtLower = (fmt or "png").lower()
        if fmtLower in ("jpg", "jpeg"):
            pilFormat = "JPEG"
            mediaType = "image/jpeg"
            saveKw = {"quality": int(quality or 75)}
        elif fmtLower == "webp":
            pilFormat = "WEBP"
            mediaType = "image/webp"
            saveKw = {"quality": int(quality or 75)}
        else:
            pilFormat = "PNG"
            mediaType = "image/png"
            saveKw = {}

        img = Image.fromarray(tile.astype(np.uint8), mode="L")
        buf = io.BytesIO()
        img.save(buf, format=pilFormat, **saveKw)

        meta = {
            "mime": mediaType,
            "width": img.width,
            "height": img.height,
            "note": f"Static image preview for {p.name}",
        }
        previewHeaders = self._buildPreviewHeaders(meta)

        disp = "inline" if inline else "attachment"
        filename = (
            f"{p.name}.{fmtLower}"
            if not p.name.lower().endswith(fmtLower)
            else p.name
        )

        headers = {
            "Content-Disposition": f'{disp}; filename="{filename}"',
            "X-Preview-Mime": mediaType,
            "X-Preview-Width": str(img.width),
            "X-Preview-Height": str(img.height),
            "X-Preview-Note": f"file={p.name}",
            "Access-Control-Expose-Headers": ", ".join(
                [
                    "Content-Disposition",
                    "X-Preview-Mime",
                    "X-Preview-Width",
                    "X-Preview-Height",
                    "X-Preview-Note",
                ]
            ),
            **previewHeaders,
        }

        return Response(
            content=buf.getvalue(),
            media_type=mediaType,
            headers=headers,
        )

    # ------------------------------------------------------------------ #
    # TiltSeries (grayscale)
    # ------------------------------------------------------------------ #
    def _collectSetOfTiltSeries(
        self, objectManager
    ) -> Tuple[List[np.ndarray], List[str], int, int, str]:
        """
        Collect a single representative slice per tilt-series object table.
        """
        mainTable = "objects"
        tables = objectManager.getTables()
        rowCount = objectManager.getTableRowCount(mainTable) or 0

        if not rowCount:
            raise HTTPException(
                status_code=404, detail="No rows available for preview"
            )

        tiles: List[np.ndarray] = []
        labels: List[str] = []
        maxTiles, cols, tileSize = 12, 2, 70
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

            arr = self._read2dTile(
                filePath, sliceIndex=None, preferCentral=True
            )
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
    def _pickSampleRows(
        self, objectManager, tableName: str, want: int
    ) -> list:
        """
        Deterministically sample up to `want` rows from a table, spreading them
        across the full rowCount range. This avoids biased previews toward the
        first page while keeping the output stable across calls.
        """
        rowCount = objectManager.getTableRowCount(tableName) or 0
        if rowCount <= 0:
            return []

        n = max(1, min(want, rowCount))
        if rowCount <= n:
            return objectManager.getRows(tableName, 0, n) or []

        rows = []
        for k in range(n):
            idx = k
            chunk = objectManager.getRows(tableName, idx, 1) or []
            if chunk:
                rows.append(chunk[0])
        return rows

    def getRenderColumnIndex(
        self, renderField: Union[str, List[str]], columns
    ) -> int:
        """
        Resolve which column index to use as render source.
        - Accepts str or list[str] of candidate names.
        - Case-insensitive; allows substring match.
        - Falls back through common names if needed.
        """
        if isinstance(renderField, str):
            tokens = [
                t.strip() for t in re.split(r"[,\s]+", renderField) if t.strip()
            ]
        else:
            tokens = [
                str(t).strip()
                for t in (renderField or [])
                if str(t).strip()
            ]

        for fb in [
            "stack",
            "_filename",
            "micrograph",
            "micName",
            "file",
            "path",
        ]:
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

    def extractPathFromRow(
        self, row: Any, renderIdx: int
    ) -> Tuple[Optional[str], Optional[int]]:
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

        candidates: List[Path] = []

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
    # Gallery (supports L and RGB; can forceRgb)
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
            raise HTTPException(
                status_code=404, detail="No tiles to build gallery"
            )

        if forceRgb:
            isRgb = True
        else:
            first = tiles[0]
            isRgb = (
                isinstance(first, np.ndarray)
                and first.ndim == 3
                and first.shape[-1] == 3
            )

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

                summaryFontSize = int(
                    min(
                        max(baseFromWidth, baseFromCell, 18 * scale),
                        cellPx * 0.9,
                    )
                )
                summaryFont = ImageFont.truetype("arial.ttf", summaryFontSize)
            except Exception:
                summaryFont = labelFont
                summaryFontSize = labelFontSize

            sbbox = summaryFont.getbbox(summary)
            sH = sbbox[3] - sbbox[1] if sbbox else summaryFontSize
            summaryPadY = max(4 * scale, int(sH * 0.2))
            summaryHeight = sH + 2 * summaryPadY

        canvasMode = "RGB" if isRgb else "L"
        bgColor = (255, 255, 255) if isRgb else 255
        barColor = (30, 30, 30) if isRgb else 30
        textLight = (255, 255, 255) if isRgb else 255
        summaryBand = (230, 230, 230) if isRgb else 230
        textDark = (0, 0, 0) if isRgb else 0

        canvasH = baseCanvasH + summaryHeight
        canvas = Image.new(canvasMode, (canvasW, canvasH), color=bgColor)

        for i, arr in enumerate(tiles[:maxTiles]):
            if arr is None:
                continue

            if isRgb:
                if isinstance(arr, np.ndarray) and arr.ndim == 2:
                    arr = np.stack([arr, arr, arr], axis=-1)
                if not (
                    isinstance(arr, np.ndarray)
                    and arr.ndim == 3
                    and arr.shape[-1] == 3
                ):
                    continue
            else:
                if (
                    isinstance(arr, np.ndarray)
                    and arr.ndim == 3
                    and arr.shape[-1] == 3
                ):
                    arr = (
                        np.mean(arr.astype(np.float32), axis=-1)
                        .clip(0, 255)
                        .astype(np.uint8)
                    )
                if not (isinstance(arr, np.ndarray) and arr.ndim == 2):
                    continue

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

            tileImg = Image.fromarray(
                arr, mode=("RGB" if isRgb else "L")
            ).resize((newW, newH), resample=Image.Resampling.BILINEAR)

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

                draw.rectangle(
                    [(0, barTop), (cellPx - 1, barBottom)],
                    fill=barColor,
                )
                xText = max(3 * scale, (cellPx - textW) // 2)
                yText = barTop + max(
                    1 * scale, (labelBarHeight - textH) // 2
                )
                draw.text(
                    (xText, yText),
                    text,
                    font=labelFont,
                    fill=textLight,
                )

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

            draw.rectangle(
                [(0, bandTop), (canvasW - 1, bandBottom)],
                fill=summaryBand,
            )
            xSummary = max(padPx, (canvasW - sW) // 2)
            ySummary = bandTop + max(
                2 * scale, (summaryHeight - sH) // 2
            )
            draw.text(
                (xSummary, ySummary),
                summary,
                font=summaryFont,
                fill=textDark,
            )

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

    def buildPreviewHeadersFallback(
        self, meta: Dict[str, Any]
    ) -> Dict[str, str]:
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
        headers["Access-Control-Expose-Headers"] = ", ".join(
            [
                "Content-Disposition",
                "X-Preview-Mime",
                "X-Preview-Width",
                "X-Preview-Height",
                "X-Preview-Tiles",
                "X-Preview-Note",
            ]
        )
        return headers

    # ------------------------------------------------------------------ #
    # Fallback "No Image" PNG
    # ------------------------------------------------------------------ #
    def _makeNoPreviewImageResponse(self) -> Response:
        width, height = 140, 140
        bgColor, borderColor, textColor = 245, 200, 80

        img = Image.new("L", (width, height), color=bgColor)
        draw = ImageDraw.Draw(img)

        margin = 10
        draw.rectangle(
            [(margin, margin), (width - margin, height - margin)],
            outline=borderColor,
            width=1,
        )

        msg = "No Image Available"
        try:
            font = ImageFont.truetype("arial.ttf", 52)
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), msg, font=font)
        x = (width - (bbox[2] - bbox[0])) // 2
        y = (height - (bbox[3] - bbox[1])) // 2
        draw.text((x, y), msg, font=font, fill=textColor)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        pngBytes = buf.getvalue()

        meta = {
            "mime": "image/png",
            "kind": "image",
            "width": width,
            "height": height,
            "note": f"No preview available for {type(self.output).__name__}",
        }
        previewHeaders = (
            self._buildPreviewHeaders(meta)
            if hasattr(self, "_buildPreviewHeaders")
            else self.buildPreviewHeadersFallback(meta)
        )

        return Response(
            content=pngBytes,
            media_type="image/png",
            headers={
                "Content-Disposition": 'inline; filename="no_preview.png"',
                **previewHeaders,
            },
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
        """
        Open an image/stack and extract a single 2D slice as uint8 tile.
        - Honors sliceIndex (1-based in tables) if provided.
        - Otherwise takes first or central slice depending on preferCentral.
        - Applies highlight/normalize defensively.
        """
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

    def _pilTo2dTile(self, imgStk, pilImg, thumbSize=maxThumbSize) -> Optional[np.ndarray]:
        """
        Convert a PIL image from a stack into a 2D uint8 tile.

        - Downsamples to <= size.
        - Converts to grayscale.
        - Runs highlightSlice/normalizeSlice at most once.
        - Final output is uint8 [0, 255] so we can avoid re-normalizing later.
        """
        try:
            width, height = pilImg.size
            scale = min(
                thumbSize / float(width),
                thumbSize / float(height),
                1.0,
            )
            thumbWidth = max(1, int(round(width * scale)))
            thumbHeight = max(1, int(round(height * scale)))

            if pilImg.mode not in ("L", "I;16", "F"):
                pilGray = pilImg.convert("L")
            else:
                pilGray = pilImg

            if thumbWidth < width or thumbHeight < height:
                pilGray = pilGray.copy()
                pilGray.thumbnail((thumbWidth, thumbHeight))

            arr = np.asarray(pilGray, dtype=np.float32)
            arr = np.squeeze(arr)
            if arr.ndim != 2 or arr.size == 0:
                return None

            try:
                arr = imgStk.highlightSlice(arr)
                arr = imgStk.normalizeSlice(arr)
            except Exception:
                pass

            amin, amax = float(np.min(arr)), float(np.max(arr))
            if (
                not np.isfinite(amin)
                or not np.isfinite(amax)
                or amax <= amin
            ):
                return np.zeros_like(arr, dtype=np.uint8)

            arr = (arr - amin) / (amax - amin + 1e-12)
            return (255.0 * arr).astype(np.uint8)
        except Exception:
            return None

    def _applyColormap(
        self, grayTile: np.ndarray, cmapName: str = "inferno"
    ) -> np.ndarray:
        """
        Apply a matplotlib colormap to a 2D tile (uint8 or float).
        Returns RGB uint8 array (H, W, 3).
        """
        if grayTile is None or grayTile.ndim != 2:
            return grayTile

        arr = grayTile.astype(np.float32)

        if not np.isfinite(arr).all():
            if np.any(np.isfinite(arr)):
                arr[~np.isfinite(arr)] = np.nanmedian(arr[np.isfinite(arr)])
            else:
                arr = np.zeros_like(arr, dtype=np.float32)

        aMin = float(np.nanmin(arr))
        aMax = float(np.nanmax(arr))
        if (
            not np.isfinite(aMin)
            or not np.isfinite(aMax)
            or aMax <= aMin
        ):
            arr = np.zeros_like(arr, dtype=np.float32)
        else:
            arr = (arr - aMin) / (aMax - aMin)

        try:
            from matplotlib import cm as mpl_cm

            cmap = mpl_cm.get_cmap(cmapName)
        except Exception:
            from matplotlib import cm as mpl_cm

            cmap = mpl_cm.get_cmap("inferno")

        rgba = cmap(np.clip(arr, 0.0, 1.0), bytes=True)
        return rgba[..., :3].copy()

    # ------------------------------------------------------------------ #
    # Colormap resolution (unified and de-duplicated)
    # ------------------------------------------------------------------ #
    def _mergeHeaders(self, newHeaders: Dict[str, str]) -> None:
        """Merge/normalize headers into self.requestHeaders (keys lowercased)."""
        for k, v in (newHeaders or {}).items():
            if isinstance(k, str):
                self.requestHeaders[k.lower()] = v

    def _getHeader(self, *names: str) -> Optional[str]:
        """Return first present header value (case-insensitive)."""
        for name in names:
            v = self.requestHeaders.get(name.lower())
            if v:
                return str(v).strip()
        return None

    def _resolveColormapForOutputType(
        self, defaultCmap: str = "viridis"
    ) -> Optional[str]:
        """
        Decide which colormap to use for volume thumbnails.
        Priority:
          1) self.colormapOverride
          2) Request headers (X-Scipion-Colormap, X-Preview-Colormap, X-Colormap, Scipion-Colormap, Colormap)
          3) RegistryViewerConfig (optional 'colormap'/'cmap')
          4) Environment var SCIPION_GALLERY_COLORMAP
          5) defaultCmap
        Only applies to SetOfClasses3D / SetOfVolumes.
        """
        if not isinstance(self.output, (SetOfClasses3D, SetOfVolumes)):
            return None

        if self.colormapOverride:
            return self.colormapOverride

        raw = self._getHeader(
            "X-Scipion-Colormap",
            "X-Preview-Colormap",
            "X-Colormap",
            "Scipion-Colormap",
            "Colormap",
        )
        if raw:
            try:
                from matplotlib import cm as mpl_cm

                _ = mpl_cm.get_cmap(raw)
                return raw
            except Exception:
                self._cmapNote = (
                    f"Invalid colormap '{raw}', falling back to default."
                )

        cfg = RegistryViewerConfig.getConfig(type(self.output)) or {}
        cmName = cfg.get("colormap") or cfg.get("cmap")
        if cmName:
            return cmName

        envCm = os.getenv("SCIPION_GALLERY_COLORMAP")
        if envCm:
            return envCm

        return defaultCmap

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

        extraHeaders: Dict[str, str] = {}
        if forceRgb:
            usedCmap = self._resolveColormapForOutputType(defaultCmap="viridis")
            if usedCmap:
                extraHeaders["X-Preview-Colormap"] = usedCmap
            if self._cmapNote:
                extraHeaders["X-Preview-Colormap-Note"] = self._cmapNote
            expose = previewHeaders.get("Access-Control-Expose-Headers", "")
            exposeList = [h.strip() for h in expose.split(",") if h.strip()]
            for k in ("X-Preview-Colormap", "X-Preview-Colormap-Note"):
                if k not in exposeList:
                    exposeList.append(k)
            previewHeaders["Access-Control-Expose-Headers"] = ", ".join(
                exposeList
            )

        return Response(
            content=pngBytes,
            media_type="image/png",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                **previewHeaders,
                **extraHeaders,
            },
        )

    # ======================================================================
    # Volumes API (list / info / slice)
    # ======================================================================

    def listOutputVolumes(self) -> List[Dict[str, Any]]:
        """
        Return a list of volume entries for the current output.
        Each entry: { id: int, name: str, relPath: str }
        - id is 0-based index to be used by getVolumeInfo/renderVolumeSlice
        """
        protRoot = Path(self.protocol.getPath()).resolve()
        paths = self._collectVolumePaths()
        items: List[Dict[str, Any]] = []
        for i, p in enumerate(paths):
            items.append(
                {
                    "id": i,
                    "name": p.name,
                    "relPath": self._relPathInside(protRoot, p),
                }
            )
        return items

    def getVolumeInfo(self, volumeId: Union[int, str]) -> Dict[str, Any]:
        """
        Return metadata for a specific volume: dims (x,y,z), voxel size, sizeBytes, etc.
        Uses reader.getImages() as fast path. Dims returned as (X, Y, Z).
        """
        protRoot = Path(self.protocol.getPath()).resolve()
        paths = self._collectVolumePaths()
        if not paths:
            raise HTTPException(
                status_code=404, detail="No volume files found in this output"
            )

        try:
            idx = int(volumeId)
        except Exception:
            idx = 0
        if idx < 0 or idx >= len(paths):
            raise HTTPException(
                status_code=404, detail="Volume index out of range"
            )

        absPath = paths[idx]
        relPath = self._relPathInside(protRoot, absPath)

        dims = None
        voxel = (None, None, None)
        try:
            reader = ImageReadersRegistry.open(str(absPath))
            images = reader.getImages()
            if images.ndim == 3:
                dims = (
                    int(images.shape[0]),
                    int(images.shape[1]),
                    int(images.shape[2]),
                )
            elif images.ndim == 2:
                dims = (int(images.shape[1]), int(images.shape[0]), 1)
            else:
                dims = (0, 0, 0)

            try:
                props = reader.getProperties() or {}
                voxel = self._extractVoxelFromProps(props)
            except Exception:
                pass
        except Exception:
            dims = (0, 0, 0)

        try:
            sizeBytes = absPath.stat().st_size
        except Exception:
            sizeBytes = None

        return {
            "id": idx,
            "name": absPath.name,
            "relPath": relPath,
            "type": "Volume",
            "dims": dims,
            "voxelSize": voxel,
            "sizeBytes": sizeBytes,
        }

    def renderVolumeSlice(
        self,
        volumeId: Union[int, str],
        sliceIndex: int,
        axis: str = "z",
        colormap: Optional[str] = None,
        normalize: str = "minmax",
        scale: float = 1.0,
        inline: bool = True,
        fmt: str = "png",
        thumb: Optional[int] = None,
        fast: bool = True,
        quality: int = 75,
        **_unused,
    ) -> Response:
        axis = (axis or "z").lower()
        if axis not in ("z", "y", "x"):
            axis = "z"

        protRoot = Path(self.protocol.getPath()).resolve()
        paths = self._collectVolumePaths()
        if not paths:
            raise HTTPException(
                status_code=404, detail="No volume files found in this output"
            )

        try:
            idx = int(volumeId)
        except Exception:
            idx = 0
        if idx < 0 or idx >= len(paths):
            raise HTTPException(
                status_code=404, detail="Volume index out of range"
            )

        absPath = paths[idx]
        relPath = self._relPathInside(protRoot, absPath)

        usedCmap = (
            colormap
            or self._resolveColormapForOutputType(defaultCmap="viridis")
            or "viridis"
        )

        fmtLower = (fmt or "png").lower()
        if fmtLower in ("jpg", "jpeg"):
            pilFormat = "JPEG"
            mediaType = "image/jpeg"
            saveKw = {"quality": int(quality or 75)}
        elif fmtLower == "webp":
            pilFormat = "WEBP"
            mediaType = "image/webp"
            saveKw = {"quality": int(quality or 75)}
        else:
            pilFormat = "PNG"
            mediaType = "image/png"
            saveKw = {}

        gray = None
        props = None
        zdim = ydim = xdim = 0
        k = max(0, int(sliceIndex))

        # Fast path: z axis + fast
        if axis == "z" and fast:
            try:
                reader = ImageReadersRegistry.open(str(absPath))

                try:
                    imgs = reader.getImages()
                    if hasattr(imgs, "ndim") and imgs.ndim == 3:
                        zdim, ydim, xdim = (
                            int(imgs.shape[0]),
                            int(imgs.shape[1]),
                            int(imgs.shape[2]),
                        )
                    elif hasattr(imgs, "ndim") and imgs.ndim == 2:
                        zdim, ydim, xdim = 1, int(imgs.shape[0]), int(
                            imgs.shape[1]
                        )
                    else:
                        zdim, ydim, xdim = 1, 0, 0
                except Exception:
                    zdim, ydim, xdim = 1, 0, 0

                if zdim > 0:
                    k = min(k, zdim - 1)
                else:
                    k = 0

                try:
                    pilImg = reader.getImage(index=k, pilImage=True)
                except Exception:
                    try:
                        pilImg = reader.getCentralImage(pilImage=True)
                        k = max(
                            0,
                            min(int(zdim // 2), max(zdim - 1, 0)),
                        )
                    except Exception:
                        pilImg = reader.getImage(index=0, pilImage=True)
                        k = 0

                gray = self._pilTo2dTile(reader, pilImg)
                if gray is None:
                    raise RuntimeError("Empty/invalid image slice")

                gray = self._normMode2D(gray, mode=normalize or "minmax")
            except Exception:
                gray = None

        # Slow path
        if gray is None:
            try:
                vol3d, props = readVolumeArray3d(str(absPath))  # Z, Y, X
                if vol3d.ndim != 3:
                    raise ValueError(
                        f"Unsupported volume shape {vol3d.shape}, expected 3D"
                    )

                zdim, ydim, xdim = (
                    int(vol3d.shape[0]),
                    int(vol3d.shape[1]),
                    int(vol3d.shape[2]),
                )

                if axis == "z":
                    dim = zdim
                elif axis == "y":
                    dim = ydim
                else:
                    dim = xdim

                if dim <= 0:
                    raise ValueError("Empty volume")

                k = max(0, min(int(sliceIndex), dim - 1))

                if axis == "z":
                    slice2d = vol3d[k, :, :]
                elif axis == "y":
                    slice2d = vol3d[:, k, :]
                else:
                    slice2d = vol3d[:, :, k]

                gray = self._normMode2D(slice2d, mode=normalize or "minmax")
            except Exception as e:
                try:
                    return self.previewProtocolImageFile(
                        self.protocol.getObjId(), relPath, inline=True
                    )
                except Exception:
                    raise HTTPException(
                        status_code=500, detail=f"Slice render failed: {e}"
                    )

        # Thumbnail
        if thumb is not None and thumb > 0:
            pilTmp = Image.fromarray(gray.astype(np.uint8), mode="L")
            pilTmp.thumbnail((thumb, thumb))
            gray = np.array(pilTmp, copy=False)

        # Colormap + scale
        rgb = self._applyColormap(gray, usedCmap)
        rgb = self._resizeIfNeeded(rgb, scale or 1.0)

        img = Image.fromarray(rgb.astype(np.uint8), mode="RGB")

        buf = io.BytesIO()
        img.save(buf, format=pilFormat, **saveKw)

        voxel = (None, None, None)
        if props is not None:
            voxel = self._extractVoxelFromProps(props)

        headers = {
            "X-Preview-Mime": mediaType,
            "X-Preview-Width": str(img.width),
            "X-Preview-Height": str(img.height),
            "X-Preview-Depth": str(zdim or 0),
            "X-Preview-Colormap": usedCmap,
            "X-Preview-Note": f"slice axis={axis} index={k}",
            "Access-Control-Expose-Headers": ", ".join(
                [
                    "Content-Disposition",
                    "X-Preview-Mime",
                    "X-Preview-Width",
                    "X-Preview-Height",
                    "X-Preview-Depth",
                    "X-Preview-Colormap",
                    "X-Preview-Note",
                    "X-Preview-VoxelSize",
                ]
            ),
        }
        if all(v is not None for v in voxel):
            headers["X-Preview-VoxelSize"] = (
                f"{voxel[0]},{voxel[1]},{voxel[2]}"
            )

        disp = "inline" if inline else "attachment"
        filename = f"{absPath.name}_axis-{axis}_slice-{k}.{fmtLower}"
        headers["Content-Disposition"] = (
            f'{disp}; filename="{filename}"'
        )

        return Response(
            content=buf.getvalue(), media_type=mediaType, headers=headers
        )

    # -------------------------
    # Private helpers (volumes)
    # -------------------------

    def _collectVolumePaths(self) -> List[Path]:
        """
        Resolve absolute file paths for the current output in a stable and thread-safe way.
        We cache the list per (protocol root, output signature) to avoid concurrent iterator issues.
        """
        out = self.output
        protRoot = Path(self.protocol.getPath()).resolve()
        key = (str(protRoot), _outputSignature(out))

        with _VOLUME_PATHS_LOCK:
            cached = _VOLUME_PATHS_CACHE.get(key)
            if cached is not None:
                existing = [p for p in cached if p.exists()]
                if existing:
                    return existing

            paths: List[Path] = []

            def pushItem(item: Any):
                try:
                    fp = item.getFileName()
                    if fp:
                        p = Path(fp).resolve()
                        if p.exists():
                            paths.append(p)
                except Exception:
                    pass

            isSet = isinstance(out, EMSet)
            if isSet:
                ok = False
                try:
                    it = getattr(out, "iterItems", None)
                    if callable(it):
                        for itx in it():
                            pushItem(itx)
                        ok = True
                except Exception:
                    ok = False
                if not ok:
                    try:
                        for itx in out:
                            pushItem(itx)
                    except Exception:
                        pass
            else:
                try:
                    fp = out.getFileName()
                    if fp:
                        p = Path(fp).resolve()
                        if p.exists():
                            paths.append(p)
                except Exception:
                    pass
                try:
                    for itx in out:
                        pushItem(itx)
                except Exception:
                    pass

            seen = set()
            dedup: List[Path] = []
            for p in paths:
                s = str(p)
                if s not in seen:
                    seen.add(s)
                    dedup.append(p)

            _VOLUME_PATHS_CACHE[key] = dedup
            return dedup

    def _extractVoxelFromProps(
        self, props: Dict[str, Any]
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Try common keys used by EM stack readers to encode sampling/voxel size.
        Returns (vx, vy, vz) or (None, None, None).
        """
        if not isinstance(props, dict):
            return (None, None, None)

        for key in ("voxelSize", "voxel", "samplingRate", "pixelSize", "sr"):
            if key in props:
                val = props[key]
                try:
                    if isinstance(val, (list, tuple)) and len(val) >= 3:
                        return (float(val[0]), float(val[1]), float(val[2]))
                    f = float(val)
                    return (f, f, f)
                except Exception:
                    continue
        return (None, None, None)

    def _normMode2D(self, a: np.ndarray, mode: str = "minmax") -> np.ndarray:
        """
        Normalize a 2D slice into uint8: 'minmax' | 'zscore' | 'none'.

        If input is already uint8 and mode in ('minmax', 'none'),
        it is returned as is.
        """
        if a.ndim != 2:
            raise ValueError("Expected 2D slice")
        arr = np.asarray(a)

        if arr.dtype == np.uint8 and (mode or "minmax").lower() in (
            "minmax",
            "none",
        ):
            return arr.copy()

        arr = arr.astype(np.float32, copy=False)
        mode = (mode or "minmax").lower()

        finiteMask = np.isfinite(arr)
        if not finiteMask.all():
            if finiteMask.any():
                fillVal = float(np.nanmedian(arr[finiteMask]))
            else:
                fillVal = 0.0
            arr = np.where(finiteMask, arr, fillVal)

        if mode == "zscore":
            mu = float(np.mean(arr))
            sd = float(np.std(arr))
            if sd == 0.0 or not np.isfinite(sd):
                return np.zeros_like(arr, dtype=np.uint8)
            arr = (arr - mu) / sd
            arr = np.clip(arr, -3.0, 3.0)
            amin, amax = float(arr.min()), float(arr.max())
            if amax <= amin:
                return np.zeros_like(arr, dtype=np.uint8)
            arr = (arr - amin) / (amax - amin + 1e-12)
            return (255.0 * arr).astype(np.uint8)

        amin, amax = float(arr.min()), float(arr.max())
        if (
            not np.isfinite(amin)
            or not np.isfinite(amax)
            or amax <= amin
        ):
            return np.zeros_like(arr, dtype=np.uint8)

        arr = (arr - amin) / (amax - amin + 1e-12)
        return (255.0 * arr).astype(np.uint8)

    def _resizeIfNeeded(self, imgArr: np.ndarray, scale: float) -> np.ndarray:
        if abs(scale - 1.0) < 1e-6:
            return imgArr
        pil = Image.fromarray(imgArr)
        newW = max(1, int(round(pil.width * scale)))
        newH = max(1, int(round(pil.height * scale)))
        pil = pil.resize((newW, newH), Image.BILINEAR)
        return np.array(pil, copy=False)

    def _relPathInside(self, root: Path, absPath: Path) -> str:
        try:
            rel = absPath.resolve().relative_to(root.resolve())
            return rel.as_posix()
        except Exception:
            return absPath.name

    def getVolumeHistogram(self, volumePath, bins: int = 128):
        """
        Return a simple intensity histogram for the selected volume.

        Output:
        {
          "binEdges": [float, ...],
          "counts":   [int,   ...]
        }
        """
        imgStk = ImageReadersRegistry.open(volumePath)
        data = np.asarray(imgStk.getImages())

        if data is None:
            return {"binEdges": [], "counts": []}

        arr = np.asarray(data, dtype=np.float32).ravel()
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return {"binEdges": [], "counts": []}

        counts, binEdges = np.histogram(arr, bins=bins)

        return {
            "binEdges": binEdges.tolist(),
            "counts": counts.tolist(),
        }

    # ------------------------------------------------------------------ #
    # FSC plot
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
            raise HTTPException(
                status_code=404, detail="No FSC data available for preview"
            )

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
            label = (
                f"{baseLabel} ({res:.2f} Å)"
                if res and res > 0
                else baseLabel
            )

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
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                **previewHeaders,
            },
        )

    def listTiltSeriesFrames(
            self,
            tiltSeriesName: str,
    ) -> Dict[str, Any]:
        """
        Return metadata for a single tilt series:
        - nFrames
        - dims [width, height]
        - stackRelPath
        - optional tiltAngles
        """
        if not isinstance(self.output, SetOfTiltSeries):
            raise HTTPException(
                status_code=400,
                detail="Output is not a SetOfTiltSeries",
            )

        # locate tilt series object by name/id/label
        targetTs = None
        for ts in self.output:
            # try match by tsId
            getTsId = getattr(ts, "getTsId", None)
            if callable(getTsId) and getTsId() == tiltSeriesName:
                targetTs = ts
                break

            # fallback: match by label
            getLabel = getattr(ts, "getObjLabel", None)
            if callable(getLabel) and getLabel() == tiltSeriesName:
                targetTs = ts
                break

        if targetTs is None:
            raise HTTPException(
                status_code=404,
                detail=f"TiltSeries '{tiltSeriesName}' not found",
            )

        try:
            stackPath = Path(targetTs.getFileName()).resolve()
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Tilt series does not provide a valid stack file",
            )

        try:
            reader = ImageReadersRegistry.open(str(stackPath))
            data = np.asarray(reader.getImages())
        except Exception:
            data = None

        if data is None or data.ndim != 3:
            raise HTTPException(
                status_code=500,
                detail="Tilt series stack is not a 3D array",
            )

        zdim, ydim, xdim = map(int, data.shape)

        tiltAngles = None
        getTiltAngles = getattr(targetTs, "getTiltAngles", None)
        if callable(getTiltAngles):
            try:
                tiltAngles = list(getTiltAngles())
            except Exception:
                tiltAngles = None

        protRoot = Path(self.protocol.getPath()).resolve()

        return {
            "name": tiltSeriesName,
            "nFrames": zdim,
            "dims": [xdim, ydim],
            "stackRelPath": self._relPathInside(protRoot, stackPath),
            "tiltAngles": tiltAngles,
        }

    def renderTiltSeriesFrame(
        self,
        tiltSeriesName: str,
        index: int,
        size: int = 1024,
        fmt: str = "png",
        inline: bool = True,
        applyTransform: bool = True,
    ) -> Response:
        """
        Render a single frame from a tilt series stack.
        - index is 0-based
        - size sets the max side in pixels (square thumbnail)
        """
        if not isinstance(self.output, SetOfTiltSeries):
            raise HTTPException(
                status_code=400,
                detail="Output is not a SetOfTiltSeries",
            )

        # reuse listTiltSeriesFrames to locate the stack
        meta = self.listTiltSeriesFrames(tiltSeriesName)
        protRoot = Path(self.protocol.getPath()).resolve()
        stackPath = (protRoot / Path(meta["stackRelPath"])).resolve()

        if not stackPath.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Stack file not found for tilt series '{tiltSeriesName}'",
            )

        try:
            reader = ImageReadersRegistry.open(str(stackPath))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Could not open tilt series stack: {e}",
            )

        # get frame index safely
        nFrames = int(meta["nFrames"])
        k = max(0, min(int(index), max(nFrames - 1, 0)))

        try:
            pilImg = reader.getImage(index=k, pilImage=True)
        except Exception:
            # fallback: central image
            try:
                pilImg = reader.getCentralImage(pilImage=True)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Could not get tilt frame: {e}",
                )

        # reuse the same 2D tile pipeline as other previews
        tile = self._pilTo2dTile(reader, pilImg)
        if tile is None:
            raise HTTPException(
                status_code=500,
                detail="Empty or invalid tilt frame image",
            )

        # optional resize to requested size
        if size and size > 0:
            pilTile = Image.fromarray(tile, mode="L")
            pilTile.thumbnail((size, size))
            tile = np.array(pilTile, copy=False)

        # build PNG/JPEG/WEBP, similar to renderVolumeSlice
        fmtLower = (fmt or "png").lower()
        if fmtLower in ("jpg", "jpeg"):
            pilFormat = "JPEG"
            mediaType = "image/jpeg"
            saveKw = {"quality": 75}
        elif fmtLower == "webp":
            pilFormat = "WEBP"
            mediaType = "image/webp"
            saveKw = {"quality": 75}
        else:
            pilFormat = "PNG"
            mediaType = "image/png"
            saveKw = {}

        img = Image.fromarray(tile.astype(np.uint8), mode="L")
        buf = io.BytesIO()
        img.save(buf, format=pilFormat, **saveKw)

        headers = {
            "X-Preview-Mime": mediaType,
            "X-Preview-Width": str(img.width),
            "X-Preview-Height": str(img.height),
            "X-Preview-Note": f"tiltSeries={tiltSeriesName} index={k}",
            "Access-Control-Expose-Headers": ", ".join(
                [
                    "Content-Disposition",
                    "X-Preview-Mime",
                    "X-Preview-Width",
                    "X-Preview-Height",
                    "X-Preview-Note",
                ]
            ),
        }

        disp = "inline" if inline else "attachment"
        filename = f"{tiltSeriesName}_tilt-{k}.{fmtLower}"
        headers["Content-Disposition"] = f'{disp}; filename="{filename}"'

        return Response(
            content=buf.getvalue(),
            media_type=mediaType,
            headers=headers,
        )

