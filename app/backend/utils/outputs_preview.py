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
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from fastapi import HTTPException
from fastapi.responses import Response, JSONResponse
from tomo.objects import SetOfTiltSeries

from app.backend.utils.constants import (TEXT_FILE_EXTENSIONS, SQLITE_EXTENSIONS, PDF_EXTENSIONS, TABLE_EXTENSIONS,
                                         ARCHIVE_EXTENSIONS)
from app.backend.utils.file_handlers import FileHandlers
from pwem.emlib.image.image_readers import ImageReadersRegistry
from pwem.objects import SetOfClasses2D, SetOfParticles, SetOfClasses3D, SetOfVolumes, SetOfFSCs, SetOfMicrographs
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
        """
        Entry point: choose the right preview strategy based on output type.
        """
        config = RegistryViewerConfig.getConfig(type(self.output)) or {}

        if isinstance(self.output, (SetOfParticles, SetOfClasses2D)):
            tiles, labels, cols, tileSize, summary = self._collectParticlesOrClasses2D(config, objectManager)
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

        # Fallback for unsupported types: return a simple "No Image Available" image
        return self._makeNoPreviewImageResponse()

    def _collectSetOfMicrographs(self, objectManager) -> Tuple[List[np.ndarray], List[str], int, int, str]:
        """
        Collect tiles for SetOfMicrographs:
          - Each row points to a single 2D image file (MRC/TIF/PNG/...).
          - Build up to 12 normalized tiles.
          - Labels: base filename without extension.
          - Layout: 3 columns, tile size ~100px (scaled later by makeGalleryFromTiles).

        Returns:
          tiles, labels, cols, tileSize, summaryText
        """
        mainTable = "objects"
        table = objectManager.getTable(mainTable)
        rowCount = objectManager.getTableRowCount(mainTable) or 0
        if not rowCount:
            raise HTTPException(status_code=404, detail="No rows available for preview")

        # Resolve the render column (path to the image). Try config first, then safe fallbacks.
        columns = table.getColumns()
        cfg = RegistryViewerConfig.getConfig(type(self.output)) or {}
        renderCandidates: List[str] = []

        # Registry may provide a RENDER string (space-separated). Add common fallbacks.
        try:
            cfgRender = cfg.get(RENDER, "")
            if isinstance(cfgRender, str) and cfgRender.strip():
                renderCandidates.extend(cfgRender.split())
        except Exception:
            pass

        # Pragmatic fallbacks for micrographs
        renderCandidates.extend(["_filename", "micrograph", "micName", "file", "path", "stack"])

        try:
            renderIdx = self.getRenderColumnIndex(renderCandidates, columns)
        except HTTPException:
            # Final fallback: scan first column that contains filename/path.
            renderIdx = -1
            for i, col in enumerate(columns):
                name = (col.getName() or "").lower()
                if any(k in name for k in ("filename", "file", "path", "micrograph", "micname")):
                    renderIdx = i
                    break
            if renderIdx < 0:
                raise HTTPException(
                    status_code=400,
                    detail="Could not resolve a render/filename column for micrographs",
                )

        # Fetch a small page of rows and collect up to maxTiles
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
            if not filePath.exists():
                continue

            # Open with ImageReadersRegistry to reuse normalization/highlight helpers.
            try:
                imgStk = ImageReadersRegistry.open(str(filePath))
            except Exception:
                continue

            # Micrographs are 2D; if a slice index appears, honor it; else try first/central image.
            pilImg = None
            try:
                if sliceIndex is not None:
                    idx0 = max(0, int(sliceIndex) - 1)
                    pilImg = imgStk.getImage(index=idx0, pilImage=True)
                else:
                    # For 2D files, index=0 is enough; fall back to central just in case.
                    try:
                        pilImg = imgStk.getImage(index=0, pilImage=True)
                    except Exception:
                        pilImg = imgStk.getCentralImage(pilImage=True)
            except Exception:
                pilImg = None

            if pilImg is None:
                continue

            # Ensure grayscale 2D array
            try:
                arr = np.array(pilImg)
                if arr.ndim == 3 and arr.shape[-1] in (3, 4):
                    # Convert RGB/RGBA to L
                    pilImg = pilImg.convert("L")
                    arr = np.array(pilImg)
                elif arr.ndim > 2:
                    # Squeeze exotic shapes to 2D when possible
                    arr = np.squeeze(arr)
                    if arr.ndim != 2:
                        continue
            except Exception:
                continue

            try:
                arr = imgStk.highlightSlice(arr)
                arr = imgStk.normalizeSlice(arr)
            except Exception:
                # If helpers fail, still try to use the raw grayscale
                if arr.ndim != 2:
                    continue

            if arr.ndim != 2 or arr.size == 0:
                continue

            tiles.append(arr)

        if not tiles:
            raise HTTPException(
                status_code=404,
                detail="Could not extract any micrograph images for preview",
            )

        # Pad labels length to tiles length if needed
        if labels and len(labels) < len(tiles):
            labels.extend([""] * (len(tiles) - len(labels)))

        total = rowCount or len(tiles)
        summary = f"{total} micrographs" if total != 1 else "1 micrograph"

        return tiles, labels, cols, tileSize, summary

    def _makeNoPreviewImageResponse(self) -> Response:
        """
        Build a simple 'No Image Available' PNG for unsupported preview types.
        """

        # Canvas size chosen to fit nicely in the UI preview panel
        width, height = 140, 140
        bg_color = 245  # light gray background
        border_color = 200
        text_color = 80

        # Create grayscale image
        img = Image.new("L", (width, height), color=bg_color)
        draw = ImageDraw.Draw(img)

        # Optional border
        margin = 10
        draw.rectangle([(margin, margin), (width - margin, height - margin)], outline=border_color, width=1)

        # Main message
        msg = "No Image Available"

        # Try a decent font size; fallback to default if TTF not available
        try:
            font_size = 52
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

        # Measure text size
        bbox = draw.textbbox((0, 0), msg, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        # Center the text
        x = (width - text_w) // 2
        y = (height - text_h) // 2

        draw.text((x, y), msg, font=font, fill=text_color)

        # Encode as PNG
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # Meta for frontend preview
        meta = {
            "mime": "image/png",
            "kind": "image",
            "width": width,
            "height": height,
            "note": f"No preview available for {type(self.output).__name__}",
        }

        # Use your existing header builder if available
        if hasattr(self, "_buildPreviewHeaders"):
            preview_headers = self._buildPreviewHeaders(meta)
        else:
            preview_headers = self.buildPreviewHeadersFallback(meta)

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={
                "Content-Disposition": 'inline; filename="no_preview.png"',
                **preview_headers,
            },
        )

    # --------------------------------------------------------------------
    # Common helper to build Response from tiles
    # --------------------------------------------------------------------
    def _makeFSCResponse(self, filename: str = "fsc_preview.png") -> Response:
        """
        Render one or more FSC curves into a PNG and return as HTTP Response.

        Expected self.output:
          - Iterable of FSC-like objects with:
            - getData() -> (x, y) or Nx2 array/list
            - getObjLabel() -> str (optional)
            - calculateResolution(threshold) -> float in Å (optional)
        """
        matplotlib.use("Agg")  # Non-interactive backend for server side
        # Collect FSC objects + labels
        fsc_items = []
        for i, fsc in enumerate(self.output):
            if fsc is None:
                continue
            clone = getattr(fsc, "clone", lambda: fsc)()
            label = getattr(clone, "getObjLabel", lambda: None)() or f"FSC {i + 1}"
            fsc_items.append((clone, label))

        if not fsc_items:
            raise HTTPException(status_code=404, detail="No FSC data available for preview")

        def get_xy(fsc):
            """Return (x, y) as float numpy arrays from FSC.getData()."""
            data = fsc.getData()
            # Accept both (x, y) tuple or Nx2-like array
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
            x = x[mask]
            y = y[mask]
            return x, y

        def format_res_from_freq(value, pos):
            """
            Formatter for top axis:
            given spatial frequency (1/Å), show resolution in Å.
            """
            if value <= 0:
                return ""
            inv = 1.0 / value
            # Avoid silly large numbers
            if inv > 999:
                return ""
            return f"{inv:.1f}"

        # --- Plot setup ---
        fig, ax = plt.subplots(figsize=(4, 3), dpi=120)

        threshold = 0.143
        max_x = 0.0

        for fsc, base_label in fsc_items:
            try:
                x, y = get_xy(fsc)
            except Exception:
                continue

            if x.size == 0:
                continue

            max_x = max(max_x, float(x.max()))

            # Resolution at threshold (if available)
            res = None
            if hasattr(fsc, "calculateResolution"):
                try:
                    res = fsc.calculateResolution(threshold)
                except Exception:
                    res = None

            # Label with resolution if valid
            res = float(res)
            if res and res > 0:
                label = f"{base_label} ({res:.2f} Å)"
            else:
                label = base_label

            ax.plot(x, y, linewidth=1.2, label=label)

            # Vertical line at the resolution frequency (if inside x-range)
            if res and res > 0:
                freq = 1.0 / float(res)
                if 0 < freq <= max_x * 1.01:
                    ax.axvline(freq, linestyle="--", linewidth=0.6, alpha=0.6)

        # Horizontal threshold line
        ax.axhline(threshold, linestyle="--", linewidth=0.6, alpha=0.6)

        if max_x <= 0:
            max_x = 1.0

        ax.set_xlim(0, max_x)
        ax.set_ylim(0.0, 1.05)

        ax.set_xlabel("Spatial frequency (1/Å)", fontsize=8)
        ax.set_ylabel("FSC", fontsize=8)
        ax.grid(True, linestyle="--", linewidth=0.3, alpha=0.3)

        if len(fsc_items) > 1:
            ax.legend(fontsize=6, loc="best")

        # Top axis: show resolution in Å instead of frequency
        ax_top = ax.twiny()
        ax_top.set_xlim(ax.get_xlim())
        ax_top.set_xlabel("Resolution (Å)", fontsize=8)
        ax_top.xaxis.set_major_formatter(FuncFormatter(format_res_from_freq))

        fig.tight_layout()

        # Encode to PNG
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        png_bytes = buf.getvalue()

        # Meta for your preview pipeline
        meta = {
            "mime": "image/png",
            "kind": "image",
            "note": "FSC curve",
        }
        preview_headers = self._buildPreviewHeaders(meta)

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                **preview_headers,
            },
        )

    # --------------------------------------------------------------------
    # Common helper to build Response from tiles
    # --------------------------------------------------------------------
    def _makeGalleryResponse(
            self,
            tiles: List[np.ndarray],
            labels: List[str],
            cols: int,
            tileSize: int,
            filename: str,
            summary: Optional[str] = None,
    ) -> Response:
        """
        Build final PNG + HTTP response from collected tiles and labels.
        Optionally adds a global summary text at the bottom of the gallery image.
        """
        if not tiles:
            raise HTTPException(
                status_code=404,
                detail="Could not extract any images for preview",
            )

        # Only pass labels if there is at least one non-empty label
        useLabels: Optional[List[str]] = labels if any(l for l in labels) else None

        pngBytes, meta = self.makeGalleryFromTiles(
            tiles,
            cols=cols,
            tileSize=tileSize,
            labels=useLabels,
            summary=summary,
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

    # --------------------------------------------------------------------
    # SetOfParticles / SetOfClasses2D
    # --------------------------------------------------------------------
    def _collectParticlesOrClasses2D(
            self,
            config,
            objectManager,
    ) -> Tuple[List[np.ndarray], List[str], int, int, str]:
        """
        Collect tiles for:
          - SetOfParticles: take particles from a common stack.
          - SetOfClasses2D: 2 cols, labels with class size when available.

        Returns:
          tiles, labels, cols, tileSize, summaryText
        """
        mainTable = "objects"
        table = objectManager.getTable(mainTable)
        rowCount = objectManager.getTableRowCount(mainTable) or 0
        rows = objectManager.getRows(mainTable, 0, 32)
        if not rows:
            raise HTTPException(status_code=404, detail="No particle rows available for preview")

        render = config.get(RENDER, "").split(' ')
        render.extend(['stack', '_filename'])
        columns = table.getColumns()
        renderIdx = self.getRenderColumnIndex(render, columns)

        maxTiles = 12
        cols = 3
        tileSize = 50
        labels: List[str] = []

        isClasses2D = isinstance(self.output, SetOfClasses2D)
        renderSizeIdx: Optional[int] = None

        # Layout override for SetOfClasses2D
        if isClasses2D:
            cols = 2
            tileSize = 70
            renderSizeIdx = self.getRenderColumnIndex("_size", columns)

        # Assume one shared stack for all rows
        relPath, sliceIndex = self.extractPathFromRow(rows[0], renderIdx)
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

            arr = np.array(pilImg)
            arr = imgStk.highlightSlice(arr)
            arr = imgStk.normalizeSlice(arr)
            if arr.ndim != 2:
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

        # Ensure labels length matches tiles length
        if labels and len(labels) < len(tiles):
            labels.extend([""] * (len(tiles) - len(labels)))

        total = rowCount or len(tiles)
        if isClasses2D:
            summary = f"{total} classes"
        else:
            summary = f"{total} particles"

        return tiles, labels, cols, tileSize, summary

    # --------------------------------------------------------------------
    # SetOfClasses3D / SetOfVolumes
    # --------------------------------------------------------------------
    def _collectClasses3DOrVolumes(
            self,
            objectManager,
    ) -> Tuple[List[np.ndarray], List[str], int, int, str]:
        """
        Collect tiles for:
          - SetOfClasses3D: central slice of each volume/stack + size label.
          - SetOfVolumes: central slice of each volume.

        Returns:
          tiles, labels, cols, tileSize, summaryText
        """
        mainTable = "objects"
        table = objectManager.getTable(mainTable)
        rowCount = objectManager.getTableRowCount(mainTable) or 0
        rows = objectManager.getRows(mainTable, 0, 32)
        if not rows:
            raise HTTPException(status_code=404, detail="No rows available for preview")

        columns = table.getColumns()
        renderIdx = self.getRenderColumnIndex("stack", columns)

        tiles: List[np.ndarray] = []
        labels: List[str] = []
        maxTiles = 12
        cols = 2
        tileSize = 70

        isClasses3D = isinstance(self.output, SetOfClasses3D)
        renderSizeIdx: Optional[int] = None
        if isClasses3D:
            renderSizeIdx = self.getRenderColumnIndex("_size", columns)

        for row in rows:
            if len(tiles) >= maxTiles:
                break

            relPath, sliceIndex = self.extractPathFromRow(row, renderIdx)
            filePath = self.resolveFilePath(relPath)
            if not filePath.exists():
                continue

            try:
                imgStk = ImageReadersRegistry.open(str(filePath))
            except Exception:
                continue

            # Central slice if possible, fallback to first slice
            try:
                pilImg = imgStk.getCentralImage(pilImage=True)
            except Exception:
                try:
                    pilImg = imgStk.getImage(index=0, pilImage=True)
                except Exception:
                    pilImg = None

            if pilImg is None:
                continue

            arr = np.array(pilImg)
            arr = imgStk.highlightSlice(arr)
            arr = imgStk.normalizeSlice(arr)
            if arr.ndim != 2:
                continue

            tiles.append(arr)

            if isClasses3D and renderSizeIdx is not None:
                try:
                    sizeVal = row.getValues()[renderSizeIdx]
                    labels.append(f"{sizeVal} particles")
                except Exception:
                    labels.append("")
            else:
                # For SetOfVolumes we keep labels optional/blank for now
                labels.append("")

        if not tiles:
            raise HTTPException(
                status_code=404,
                detail="Could not extract any class/volume images for preview",
            )

        if labels and len(labels) < len(tiles):
            labels.extend([""] * (len(tiles) - len(labels)))

        total = rowCount or len(tiles)
        if isClasses3D:
            summary = f"{total} classes"
        else:
            summary = f"{total} items"

        return tiles, labels, cols, tileSize, summary

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def getRenderColumnIndex(self, renderField: str, columns) -> int:
        """
        Resolve which column index to use as render source.
        Fallbacks to '_filename' if needed.
        """
        for index, column in enumerate(columns):
            if column.getName() in renderField:
                return index
        raise HTTPException(
            status_code=400,
            detail=f"Render field '{renderField}' not found in config",
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
            summary: Optional[str] = None,  # Optional global summary line
            scale: int = 2,  # HiDPI factor for sharper labels
    ) -> Tuple[bytes, Dict[str, Any]]:
        """
        Build a gallery image from a list of 2D tiles.

        - Logical tile size: tileSize x tileSize.
        - Rendered at: (tileSize * scale) to keep text sharp.
        - Each tile is fully used for the particle content.
        - A dark overlay bar is drawn at the bottom for per-tile labels.
        - An optional summary text is rendered below the grid, scaled to remain clearly readable.
        - Tiles are assumed to be already normalized/8-bit.
        """
        if not tiles:
            raise HTTPException(status_code=404, detail="No tiles to build gallery")

        maxTiles = min(len(tiles), cols * math.ceil(len(tiles) / cols))
        cols = max(1, cols)
        rows = math.ceil(maxTiles / cols)

        hasLabels = bool(labels)
        hasSummary = bool(summary)

        # Layout units in real pixels (HiDPI)
        pad = 2
        padPx = pad * scale
        cellPx = tileSize * scale  # tile side in real pixels

        # ---------- Per-tile label font ----------
        try:
            # Reasonable fraction of tile: readable but not huge
            labelFontSize = max(12 * scale, int(cellPx * 0.22))
            labelFont = ImageFont.truetype("arial.ttf", labelFontSize)
        except Exception:
            labelFont = ImageFont.load_default()
            labelFontSize = getattr(labelFont, "size", 12 * scale)

        # ---------- Per-tile label bar ----------
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

        # ---------- Base canvas (grid only) ----------
        canvasW = cols * cellPx + (cols + 1) * padPx
        baseCanvasH = rows * cellPx + (rows + 1) * padPx

        # ---------- Summary band (global text at bottom) ----------
        summaryFont = None
        summaryHeight = 0

        if hasSummary:
            try:
                # Make summary clearly visible, especially for many columns.
                # We scale with total width and cell size.
                # For 4+ columns (typical SetOfParticles), we make it bigger.
                if cols >= 4:
                    # Aggressive scaling for large galleries
                    baseFromWidth = canvasW * 0.07  # ~7% of width
                    baseFromCell = cellPx * 0.55  # big, but still below tile height
                else:
                    # Softer scaling for 1–2 columns
                    baseFromWidth = canvasW * 0.05
                    baseFromCell = cellPx * 0.35

                summaryFontSize = int(max(
                    baseFromWidth,
                    baseFromCell,
                    18 * scale  # absolute minimum size
                ) / 1.0)

                # Clamp to avoid insane sizes on very large images
                summaryFontSize = int(min(summaryFontSize, cellPx * 0.9))

                summaryFont = ImageFont.truetype("arial.ttf", summaryFontSize)
            except Exception:
                summaryFont = labelFont
                summaryFontSize = labelFontSize

            sbbox = summaryFont.getbbox(summary)
            sH = sbbox[3] - sbbox[1] if sbbox else summaryFontSize

            # Vertical padding inside the summary band
            summaryPadY = max(4 * scale, int(sH * 0.2))
            summaryHeight = sH + 2 * summaryPadY

        # Final canvas includes optional summary band
        canvasH = baseCanvasH + summaryHeight
        canvas = Image.new("L", (canvasW, canvasH), color=255)

        # ---------- Paste tiles ----------
        for i, arr in enumerate(tiles[:maxTiles]):
            if arr is None or arr.ndim != 2:
                continue

            h, w = arr.shape
            if h <= 0 or w <= 0:
                continue

            if arr.dtype != np.uint8:
                arr = arr.astype(np.uint8, copy=False)

            # Scale to fit full square
            imgScale = min(cellPx / float(w), cellPx / float(h))
            if imgScale <= 0:
                continue

            newW = max(1, int(w * imgScale))
            newH = max(1, int(h * imgScale))

            tileImg = Image.fromarray(arr, mode="L").resize(
                (newW, newH),
                resample=Image.Resampling.BILINEAR,
            )

            tileCanvas = Image.new("L", (cellPx, cellPx), color=255)

            # Center tile content
            x0 = (cellPx - newW) // 2
            y0 = (cellPx - newH) // 2
            tileCanvas.paste(tileImg, (x0, y0))

            # Bottom label (per tile)
            if hasLabels and i < len(labels) and labels[i]:
                text = str(labels[i])
                draw = ImageDraw.Draw(tileCanvas)

                bbox = draw.textbbox((0, 0), text, font=labelFont)
                textW = bbox[2] - bbox[0]
                textH = bbox[3] - bbox[1]

                # Truncate if too wide
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
                    fill=30,
                )

                xText = max(3 * scale, (cellPx - textW) // 2)
                yText = barTop + max(1 * scale, (labelBarHeight - textH) // 2)

                draw.text((xText, yText), text, font=labelFont, fill=255)

            # Paste tile into main canvas
            r = i // cols
            c = i % cols
            gx = padPx + c * (cellPx + padPx)
            gy = padPx + r * (cellPx + padPx)
            canvas.paste(tileCanvas, (gx, gy))

        # ---------- Draw summary band ----------
        if hasSummary and summaryFont is not None:
            draw = ImageDraw.Draw(canvas)
            sbbox = summaryFont.getbbox(summary)
            sW = sbbox[2] - sbbox[0]
            sH = sbbox[3] - sbbox[1]

            bandTop = canvasH - summaryHeight
            bandBottom = canvasH - 1

            # Light band for contrast
            draw.rectangle(
                [(0, bandTop), (canvasW - 1, bandBottom)],
                fill=230,
            )

            xSummary = max(padPx, (canvasW - sW) // 2)
            ySummary = bandTop + max(2 * scale, (summaryHeight - sH) // 2)

            draw.text((xSummary, ySummary), summary, font=summaryFont, fill=0)

        # ---------- Encode ----------
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
            "note": "SetOfParticles gallery with per-tile labels"
            if hasLabels else "SetOfParticles gallery",
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

    # --------------------------------------------------------------------
    # SetOfTiltSeries
    # --------------------------------------------------------------------
    def _collectSetOfTiltSeries(
            self,
            objectManager,
    ) -> Tuple[List[np.ndarray], List[str], int, int, str]:
        """
        Collect tiles for:
          - SetOfClasses3D: central slice of each volume/stack + size label.
          - SetOfVolumes: central slice of each volume.

        Returns:
          tiles, labels, cols, tileSize, summaryText
        """
        mainTable = "objects"
        tables = objectManager.getTables()
        rowCount = objectManager.getTableRowCount(mainTable) or 0
        summary = ''

        if not rowCount:
            raise HTTPException(status_code=404, detail="No rows available for preview")

        tiles: List[np.ndarray] = []
        labels: List[str] = []
        maxTiles = 12
        cols = 2
        tileSize = 70
        renderIdx = None

        for name in tables.keys():
            if '_Object' in name:
                table = objectManager.getTable(name)
                if len(tiles) >= maxTiles:
                    break
                if not renderIdx:
                    columns = table.getColumns()
                    renderIdx = self.getRenderColumnIndex("stack", columns)
                row = objectManager.getRows(name, 0, 1)[0]
                relPath, sliceIndex = self.extractPathFromRow(row, renderIdx)
                filePath = self.resolveFilePath(relPath)
                if not filePath.exists():
                    continue
                try:
                    imgStk = ImageReadersRegistry.open(str(filePath))
                except Exception as e:
                    continue
                try:
                    pilImg = imgStk.getCentralImage(pilImage=True)  # Central slice if possible, fallback to first slice
                except Exception as e:
                    try:
                        pilImg = imgStk.getImage(index=0, pilImage=True)
                    except Exception as e:
                        pilImg = None

                if pilImg is None:
                    continue

                arr = np.array(pilImg)
                arr = imgStk.highlightSlice(arr)
                arr = imgStk.normalizeSlice(arr)
                if arr.ndim != 2:
                    continue
                tiles.append(arr)
        if not tiles:
            raise HTTPException(
                status_code=404,
                detail="Could not extract any class/volume images for preview",
            )
        summary = '%s items' % rowCount if rowCount > 1 else '1 item'
        return tiles, labels, cols, tileSize, summary
