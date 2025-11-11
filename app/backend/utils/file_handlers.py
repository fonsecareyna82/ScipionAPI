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

import numpy as np
from fastapi import HTTPException, Response
from PIL import Image

from app.backend.utils.constants import TEXT_FILE_EXTENSIONS, IMAGES_FILE_EXTENSIONS, maxThumbSize
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
    def _guardJoin(root: FsPath, relPath: str) -> FsPath:
        """
        Join root + relPath and ensure the resulting lexical path stays inside root.

        Rules:
        - Input is treated as relative to root (absolute paths are rejected here).
        - Symlinks under root are allowed even if they point outside root.
          (We do not resolve the final target to decide.)
        - Path traversal with ".." that would escape root is rejected.
        - Special cases like /home are handled by the caller and must not reach here.
        """
        root = root.resolve()

        relNorm = (relPath or "").strip()

        # Trivial values → root
        if relNorm in ("", "/", ".", "./"):
            return root

        # Absolute paths are not allowed here; those are handled at a higher level
        if FsPath(relNorm).is_absolute():
            raise HTTPException(status_code=400, detail="Invalid path")

        # Normalize leading slashes
        relNorm = relNorm.lstrip("/\\")
        if not relNorm:
            return root

        candidate = root / relNorm

        # Lexical containment check:
        # - This does NOT resolve symlinks.
        # - It only ensures that the composed path starts with root and
        #   does not escape via "..".
        try:
            candidate.relative_to(root)
        except ValueError:
            # Any attempt to escape root (e.g. "../..") is rejected
            raise HTTPException(status_code=400, detail="Invalid path")

        # At this point:
        # - candidate is inside root from a path-structure perspective.
        # - If candidate is a symlink pointing outside, it is still allowed,
        #   and will be resolved later when accessed.
        return candidate

    # -------------------------
    # Mime helpers
    # -------------------------
    @staticmethod
    def _guessMime(p: FsPath) -> str:
        mt, _ = mimetypes.guess_type(str(p))
        return mt or "application/octet-stream"

    def listProtocolDir(self, protocolId: str, path: str) -> Dict[str, Any]:
        """
        Return the directory files list.

        Supports:
        - Relative paths inside the protocol root (default mode).
        - Absolute paths under /home (absoluteMode).
        Handles symbolic links safely:
        - In protocol mode: entries are returned relative to the protocol root
          without resolving symlinks; escaping attempts are skipped.
        - In /home mode: entries are returned as absolute paths under /home;
          symlinks that resolve outside /home will be rejected on next request.
        """
        root = self._protocolRoot(protocolId).resolve()
        pRaw = (path or "").strip()

        # Normalize trivial root-like inputs
        if pRaw in ("/", ".", "./"):
            pRaw = ""

        absoluteMode = False

        if not pRaw:
            # Protocol root
            target = root
        else:
            candidate = FsPath(pRaw)

            if candidate.is_absolute():
                # Absolute path: only allow /home and /home/*
                candidate = candidate.resolve()
                try:
                    # If inside protocol root, treat as protocol-relative
                    rel = candidate.relative_to(root)
                    target = (root / rel).resolve()
                except ValueError:
                    candStr = str(candidate)
                    if candStr == "/home" or candStr.startswith("/home/"):
                        absoluteMode = True
                        target = candidate
                    else:
                        # Any other absolute path is not allowed
                        raise HTTPException(status_code=400, detail="Invalid path")
            else:
                # Relative path: must stay inside protocol root
                target = self._guardJoin(root, pRaw)

        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory")

        items: list[Dict[str, Any]] = []

        try:
            for child in target.iterdir():
                # Safely determine if entry is a directory; ignore broken entries
                try:
                    isDir = child.is_dir()
                except OSError:
                    # Skip entries that cannot be stat'ed
                    continue

                if absoluteMode:
                    # In /home mode: build lexical child path without resolving symlinks
                    childPath = (target / child.name).as_posix()

                    # Enforce that listed paths stay under /home prefix
                    if not (childPath == "/home" or childPath.startswith("/home/")):
                        # Skip anything that visually escapes /home
                        continue
                else:
                    # Protocol mode: return path relative to protocol root
                    # Do not resolve symlinks here; only use lexical position.
                    try:
                        rel = child.relative_to(root)
                    except ValueError:
                        # If for any reason this entry is outside root (symlink or mount),
                        # skip it to avoid leaking or escaping.
                        continue
                    childPath = rel.as_posix()

                item: Dict[str, Any] = {
                    "name": child.name,
                    "path": childPath.replace("\\", "/"),
                    "isDir": isDir,
                }

                if not isDir:
                    try:
                        item["size"] = child.stat().st_size
                    except OSError:
                        item["size"] = None
                    item["mime"] = self._guessMime(child)

                items.append(item)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")

        # Sort: folders first, then files; alphabetical by name
        items.sort(key=lambda it: (not it["isDir"], it["name"].lower()))

        # Compute cwd value for the client
        if absoluteMode:
            cwdValue = target.resolve().as_posix()
        else:
            try:
                relCwd = target.resolve().relative_to(root).as_posix()
            except ValueError:
                # If something goes wrong, fall back to protocol root
                relCwd = ""
            cwdValue = "" if relCwd in ("", ".") else relCwd

        return {"cwd": cwdValue, "items": items}

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
        Convert .mrc/.map to an 8-bit grayscale PNG (middle Z slice if 3D),
        using imageStk.thumbnailSlice to generate a thumbnail that fits within
        a 250x250 canvas while preserving aspect ratio.
        Returns (pngBytes, metaDict).
        """
        try:
            imageStk = ImageReadersRegistry.open(str(filePath))
            data = imageStk.getImages()

            # Some readers may return a list-like structure
            if isinstance(data, list):
                data = data[0]

            # Assume:
            # - 3D: (Z, Y, X)
            # - 2D: (Y, X)
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

            # Build base 2D slice and determine original slice dimensions
            if data.ndim == 3:
                midZ = nz // 2
                img2d = imageStk.getCentralImage()
                if hasattr(img2d, "shape") and len(img2d.shape) == 2:
                    origHeight, origWidth = img2d.shape
                else:
                    # Fallback to volume XY dimensions
                    origHeight, origWidth = ny, nx
            else:
                img2d = data
                origHeight, origWidth = ny, nx

            if origWidth <= 0 or origHeight <= 0:
                raise HTTPException(
                    status_code=500,
                    detail="Invalid image dimensions"
                )

            # Compute scale factor so that thumbnail fits within maxThumbSize
            scale = min(
                maxThumbSize / float(origWidth),
                maxThumbSize / float(origHeight),
                1.0,  # do not upscale
            )

            thumbWidth = max(1, int(round(origWidth * scale)))
            thumbHeight = max(1, int(round(origHeight * scale)))

            # Generate thumbnail using imageStk.thumbnailSlice with scaled dimensions
            if data.ndim == 3:
                # Central slice thumbnail
                arr2d = imageStk.asPilImage(img2d, normalize=True)
                arr2d.thumbnail((thumbWidth, thumbHeight))
                note = f"Central slice (z={midZ}) rendered as 8-bit PNG thumbnail"
            else:
                # Normalize first for 2D, then thumbnail
                arr2d = imageStk.asPilImage(img2d, normalize=True)
                arr2d.thumbnail((thumbWidth, thumbHeight))
                note = "2D MRC rendered as 8-bit PNG thumbnail"

            # Apply highlight/normalize helpers
            arr2d = imageStk.highlightSlice(np.array(arr2d))
            arr2d = imageStk.normalizeSlice(arr2d)

            # Encode as PNG
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
            # Original volume/slice dimensions
            "width": int(nx),
            "height": int(ny),
            "depth": int(nz),
            "thumbWidth": int(thumbWidth),
            "thumbHeight": int(thumbHeight),
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
        Load a normal 2D image and generate a thumbnail that fits within
        a 250x250 canvas while preserving aspect ratio.
        Returns (thumbBytes, thumbMediaType, metaDict).

        meta:
          - mime: original image mime type
          - width, height: original image dimensions (if readable)
          - thumbWidth, thumbHeight: thumbnail dimensions actually returned
          - sizeBytes: original file size in bytes
        """
        mediaType = self._guessMime(filePath)

        # Read original bytes once (used as fallback or if no scaling is needed)
        rawBytes = filePath.read_bytes()

        width = None
        height = None
        thumbWidth = None
        thumbHeight = None
        thumbBytes = rawBytes
        thumbMediaType = mediaType

        try:
            with Image.open(io.BytesIO(rawBytes)) as im:
                # Normalize mode to something safe for saving
                if im.mode not in ("RGB", "L"):
                    # Convert palette/alpha/etc to RGB to avoid issues
                    im = im.convert("RGB")

                width, height = im.size

                if width and height and width > 0 and height > 0:
                    # Compute scale factor so that thumbnail fits within maxThumbSize
                    scale = min(
                        maxThumbSize / float(width),
                        maxThumbSize / float(height),
                        1.0,  # do not upscale
                    )

                    thumbWidth = max(1, int(round(width * scale)))
                    thumbHeight = max(1, int(round(height * scale)))

                    if scale < 1.0:
                        # Build resized thumbnail
                        thumbImg = im.resize((thumbWidth, thumbHeight), Image.LANCZOS)
                        buf = io.BytesIO()
                        # Use PNG for preview to keep it consistent and safe
                        thumbImg.save(buf, format="PNG")
                        thumbBytes = buf.getvalue()
                        thumbMediaType = "image/png"
                    else:
                        # No scaling needed; use original bytes and dimensions
                        thumbWidth = width
                        thumbHeight = height
                else:
                    # Invalid dimensions, keep original bytes without extra meta
                    thumbWidth = width
                    thumbHeight = height

        except Exception:
            # If something fails (corrupt image, unknown format), fall back to raw bytes
            thumbBytes = rawBytes
            thumbMediaType = mediaType

        meta = {
            # Original image mime (semantic type)
            "mime": mediaType,
            # Original dimensions (if available)
            "width": width,
            "height": height,
            # Thumbnail output dimensions (what we actually returned)
            "thumbWidth": thumbWidth,
            "thumbHeight": thumbHeight,
            # Original file size
            "sizeBytes": filePath.stat().st_size,
        }

        return thumbBytes, thumbMediaType, meta

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
