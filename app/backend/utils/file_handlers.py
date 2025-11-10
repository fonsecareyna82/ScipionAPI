# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************

from __future__ import annotations
import io
import mimetypes
from pathlib import Path as FsPath
from typing import Union, Dict, Any
from fastapi import HTTPException, Response
from PIL import Image

from app.backend.utils.constants import TEXT_FILE_EXTENSIONS, IMAGES_FILE_EXTENSIONS
from pwem.emlib.image.image_readers import ImageReadersRegistry


class FileHandlers:
    """
    File/preview helpers scoped to a 'protocol root' inside the current project.
    Expects an object with .getProtocol(int).getPath() (Scipion-like).
    """

    def __init__(self, currentProject):
        self.currentProject = currentProject
        mimetypes.init()

    def getProtocolPath(self, protocolId):
        """Return  the protocol paths"""
        protocol = self.currentProject.getProtocol(int(protocolId))
        return protocol.getPath()

    def _protocolRoot(self, protocol_id: Union[int, str]) -> FsPath:
        """
        Resolve the absolute root folder for a protocol, using your service.
        """
        root = self.getProtocolPath(str(protocol_id))
        if not root:
            raise HTTPException(status_code=404, detail="Protocol path not found")

        p = FsPath(root).resolve()
        if not p.exists() or not p.is_dir():
            raise HTTPException(status_code=404, detail="Protocol root not found")
        return p

    @staticmethod
    def _guardJoin(root: FsPath, rel_path: str) -> FsPath:
        """
        Join root + rel_path, resolve, and ensure it stays inside root.
        Strictly forbids escaping outside 'root' (even if the target exists).
        """
        rel = (rel_path or "").strip().lstrip("/\\")
        target = (root / rel).resolve()
        try:
            # Will raise ValueError if target is outside root
            target.relative_to(root)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid path")
        return target

    # -------------------------
    # Mime helpers
    # -------------------------
    @staticmethod
    def _guessMime(p: FsPath) -> str:
        mt, _ = mimetypes.guess_type(str(p))
        return mt or "application/octet-stream"

    def listProtocolDir(self, protocolId: str, path: str) -> Dict[str, Any]:
        """Return the directory files list"""
        root = self._protocolRoot(protocolId)
        target = self._guardJoin(root, path)

        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory")

        items = []
        try:
            for child in target.iterdir():
                is_dir = child.is_dir()
                item = {
                    "name": child.name,
                    "path": str(child.relative_to(root)).replace("\\", "/"),
                    "isDir": is_dir,
                }
                if not is_dir:
                    try:
                        item["size"] = child.stat().st_size
                    except Exception:
                        item["size"] = None
                    item["mime"] = self._guessMime(child)
                items.append(item)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")

        # Directories first, then files; alpha by name
        items.sort(key=lambda it: (not it["isDir"], it["name"].lower()))

        cwd_rel = str(target.relative_to(root)).replace("\\", "/")
        return {"cwd": cwd_rel, "items": items}

    def previewProtocolTextFile(self, protocolId: str, path: str) -> Response:
        """
        Return a lightweight preview for a file inside a protocol workspace.

        Behaviors:
        - Text-like files -> UTF-8 text/plain (capped size).
        - Otherwise -> 415 (unsupported).
        """
        root = self._protocolRoot(protocolId)
        file_path: FsPath = self._guardJoin(root, path)

        if not file_path.exists() or not file_path.is_file():
            file_path = FsPath(path)
            if (not file_path.exists()) or (not file_path.is_file()):
                raise HTTPException(status_code=404, detail="File not found")

        suffix = file_path.suffix.lower()
        mime = self._guessMime(file_path)  # e.g. "text/plain", etc.

        textual = (
            (mime.startswith("text/"))
            or mime in (
                "application/json",
                "application/xml",
                "application/x-yaml",
                "text/x-log",
            )
            or suffix in TEXT_FILE_EXTENSIONS
        )

        if textual:
            MAX_BYTES = 1 * 1024 * 1024  # 1 MiB cap for preview
            try:
                size = file_path.stat().st_size
                if size > MAX_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="File too large to preview",
                    )
            except Exception:
                # best effort, continue to try reading
                pass

            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                raise HTTPException(
                    status_code=500,
                    detail="Could not read file as text",
                )

            return Response(
                content=text,
                media_type="text/plain; charset=utf-8",
            )

        raise HTTPException(
            status_code=415,
            detail="Preview not available for this file type",
        )

    def _isPreviewableMrc(self, filePath: FsPath) -> bool:
        """
        Return True if this file is an .mrc-like volume we can render as PNG.
        """
        suf = filePath.suffix.lower()
        return suf in IMAGES_FILE_EXTENSIONS

    def _renderImageAsPngAndMeta(self, filePath: FsPath):
        """
        Convert .mrc/.map to an 8-bit grayscale PNG (middle Z slice if 3D)
        and build metadata (true volume dims, voxel size, etc.).
        Returns (pngBytes, metaDict).
        """
        try:
            imageStk = ImageReadersRegistry.open(str(filePath))
            data = imageStk.getImages()

            # Assume data is (Z, Y, X) for 3D; (Y, X) for 2D
            if data.ndim == 3:
                nz, ny, nx = data.shape
            elif data.ndim == 2:
                ny, nx = data.shape
                nz = 1
            else:
                raise HTTPException(
                    status_code=415,
                    detail="Unsupported MRC dimensionality (only 2D or 3D supported)"
                )

            # Try to read voxel size (fallback 1.0)
            vx = imageStk.getProperties().get("sr", 1.0)
            vy = vx
            vz = vx

            if data.ndim == 3:
                midZ = nz // 2
                img = imageStk.getCentralImage()  # API from your registry
                arr2d = imageStk.thumbnailSlice(img, nx, ny)
                note = f"central slice (z={midZ}) rendered as 8-bit PNG"
            else:
                arr2d = imageStk.normalizeSlice(data)
                note = "2D MRC rendered as 8-bit PNG"

            if arr2d.dtype.kind != "u" or arr2d.dtype.itemsize != 1:
                # Ensure 8-bit grayscale if your helpers didn’t already
                # (optional safety net)
                from numpy import clip, uint8
                arr2d = uint8(clip(arr2d, 0, 255))

            arr2d = imageStk.highlightSlice(arr2d)
            arr2d = imageStk.normalizeSlice(arr2d)
            img = Image.fromarray(arr2d, mode="L")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            pngBytes = buf.getvalue()

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Could not read/convert MRC file: {str(e)}"
            )

        meta = {
            "mime": "volume/mrc",
            "width": int(nx),
            "height": int(ny),
            "depth": int(nz),
            "sizeBytes": filePath.stat().st_size,
            "note": note,
        }

        if vx is not None and vy is not None and vz is not None:
            try:
                meta["voxelSize"] = [float(vx), float(vy), float(vz)]
            except Exception:
                pass

        return pngBytes, meta

    def _renderImageAndMeta(self, filePath: FsPath):
        """
        Load a normal 2D image, gather width/height, return bytes + meta.
        """
        mediaType = self._guessMime(filePath)
        rawBytes = filePath.read_bytes()

        width = None
        height = None
        try:
            with Image.open(io.BytesIO(rawBytes)) as im:
                width, height = im.size
        except Exception:
            pass

        meta = {
            "mime": mediaType,
            "width": width,
            "height": height,
            "sizeBytes": filePath.stat().st_size,
        }
        return rawBytes, mediaType, meta

    def _buildPreviewHeaders(self, meta: dict) -> Dict[str, str]:
        """
        Convert meta dict into custom headers so frontend can read them.
        Also build Access-Control-Expose-Headers so browser will allow JS
        to read these headers in a cross-origin fetch.
        """
        previewHeaders: Dict[str, str] = {}
        if "mime" in meta and meta["mime"] is not None:
            previewHeaders["X-Preview-Mime"] = str(meta["mime"])
        if "width" in meta and meta["width"] is not None:
            previewHeaders["X-Preview-Width"] = str(meta["width"])
        if "height" in meta and meta["height"] is not None:
            previewHeaders["X-Preview-Height"] = str(meta["height"])
        if "depth" in meta and meta["depth"] is not None:
            previewHeaders["X-Preview-Depth"] = str(meta["depth"])
        if "sizeBytes" in meta and meta["sizeBytes"] is not None:
            previewHeaders["X-Preview-SizeBytes"] = str(meta["sizeBytes"])
        if "voxelSize" in meta and meta["voxelSize"] is not None:
            try:
                vx, vy, vz = meta["voxelSize"]
                previewHeaders["X-Preview-VoxelSize"] = f"{vx},{vy},{vz}"
            except Exception:
                pass
        if "note" in meta and meta["note"]:
            previewHeaders["X-Preview-Note"] = meta["note"]

        exposeList = [
            "Content-Disposition",
            "X-Preview-Mime",
            "X-Preview-Width",
            "X-Preview-Height",
            "X-Preview-Depth",
            "X-Preview-SizeBytes",
            "X-Preview-VoxelSize",
            "X-Preview-Note",
        ]
        previewHeaders["Access-Control-Expose-Headers"] = ", ".join(exposeList)

        return previewHeaders

    def previewProtocolImageFile(self, protocolId, path, inline: bool) -> Response:
        """
        inline == False:
            - attachment download (binary as-is)
        inline == True:
            - preview mode:
              * if MRC/volume -> PNG slice + X-Preview-* headers
              * if normal image -> raw image + X-Preview-* headers
              * else -> raw bytes + minimal headers
        """
        root = self._protocolRoot(protocolId)
        filePath = self._guardJoin(root, path)

        if (not filePath.exists()) or (not filePath.is_file()):
            filePath = FsPath(path)
            if (not filePath.exists()) or (not filePath.is_file()):
                raise HTTPException(status_code=404, detail="File not found")

        if inline:
            # MRC-like volume preview
            if self._isPreviewableMrc(filePath):
                pngBytes, meta = self._renderImageAsPngAndMeta(filePath)
                baseHeaders = {
                    "Content-Disposition": f'inline; filename="{filePath.stem}.png"'
                }
                previewHeaders = self._buildPreviewHeaders(meta)
                return Response(
                    content=pngBytes,
                    media_type="image/png",
                    headers={**baseHeaders, **previewHeaders},
                )

            # Regular image preview
            mediaType = self._guessMime(filePath)
            if mediaType.startswith("image/"):
                imgBytes, realMediaType, meta = self._renderImageAndMeta(filePath)
                baseHeaders = {
                    "Content-Disposition": f'inline; filename="{filePath.name}"'
                }
                previewHeaders = self._buildPreviewHeaders(meta)
                return Response(
                    content=imgBytes,
                    media_type=realMediaType,
                    headers={**baseHeaders, **previewHeaders},
                )

            # Fallback: other file types inline
            rawBytes = filePath.read_bytes()
            meta = {
                "mime": mediaType,
                "sizeBytes": filePath.stat().st_size,
            }
            baseHeaders = {
                "Content-Disposition": f'inline; filename="{filePath.name}"'
            }
            previewHeaders = self._buildPreviewHeaders(meta)
            return Response(
                content=rawBytes,
                media_type=mediaType,
                headers={**baseHeaders, **previewHeaders},
            )

        # attachment / download (inline == False)
        mediaType = self._guessMime(filePath)
        return Response(
            content=filePath.read_bytes(),
            media_type=mediaType,
            headers={
                "Content-Disposition": f'attachment; filename="{filePath.name}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )
