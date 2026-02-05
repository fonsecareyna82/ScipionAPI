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
import os
import mimetypes
from pathlib import Path as FsPath
from typing import Union, Dict, Any, Optional

import numpy as np
from fastapi import HTTPException, Response
from PIL import Image

from app.backend.utils.constants import TEXT_FILE_EXTENSIONS, IMAGES_FILE_EXTENSIONS, maxThumbSize
from pwem.emlib.image.image_readers import ImageReadersRegistry

# Color maps for volume thumbnails
import matplotlib
matplotlib.use("Agg")  # headless-safe
from matplotlib import cm as mplCm


class FileHandlers:
    """
    File/preview helpers scoped to a safe 'browser root' derived from the current project.

    Contract:
    - rootAbs is an absolute boundary folder (default: /home if not inferred).
    - All navigation paths received by list/preview endpoints are relative to rootAbs.
    - Absolute paths are accepted only for backward compatibility and must be lexically under rootAbs.
    """

    def __init__(self, currentProject):
        self.currentProject = currentProject
        mimetypes.init()

    # -------------------------
    # Root / path resolution
    # -------------------------
    def getProtocolPath(self, protocolId):
        """
        Return the protocol browser paths.

        Returns:
          - rootAbs: absolute root boundary (project folder inferred)
          - startPath: relative to rootAbs ("" means rootAbs)
          - protocolRoot: relative to rootAbs (defaults to startPath)
          - path: legacy absolute protocol path (backward compatibility)
        """
        protocol = self.currentProject.getProtocol(int(protocolId))
        protocolAbsPath = os.path.abspath(protocol.getPath())

        rootAbsPath = self._inferProjectRootAbs(protocolAbsPath)
        rootAbsPath = os.path.abspath(rootAbsPath) if rootAbsPath else "/home"

        startRelPath = os.path.relpath(protocolAbsPath, rootAbsPath)
        if startRelPath == ".":
            startRelPath = ""

        # Clamp: never allow a startPath that would escape rootAbs
        if startRelPath.startswith(".."):
            rootAbsPath = "/home"
            startRelPath = ""

        return {
            "rootAbs": rootAbsPath.replace("\\", "/"),
            "startPath": startRelPath.replace("\\", "/"),
            "protocolRoot": startRelPath.replace("\\", "/"),
            "path": protocolAbsPath.replace("\\", "/"),
        }

    def _inferProjectRootAbs(self, protocolAbsPath: str) -> str:
        """
        Infer project root from a protocol path like: <project>/Runs/<protId>/...
        Fallback to currentProject.getPath() if available.
        """
        normPath = os.path.abspath(protocolAbsPath or "")
        runsMarker = f"{os.sep}Runs{os.sep}"
        if runsMarker in normPath:
            return normPath.split(runsMarker)[0] or ""

        runsSuffix = f"{os.sep}Runs"
        if normPath.endswith(runsSuffix):
            return normPath[: -len(runsSuffix)] or ""

        projectPath = ""
        if hasattr(self.currentProject, "getPath"):
            try:
                projectPath = self.currentProject.getPath() or ""
            except Exception:
                projectPath = ""
        elif hasattr(self.currentProject, "path"):
            projectPath = getattr(self.currentProject, "path") or ""

        return os.path.abspath(projectPath) if projectPath else ""

    def _browserRootAbs(self, protocolId: Union[int, str]) -> FsPath:
        """
        Resolve the absolute root folder boundary for browsing.
        """
        info = self.getProtocolPath(str(protocolId))
        rootAbs = (info.get("rootAbs") or "/home").strip()

        p = FsPath(rootAbs).resolve()
        if not p.exists() or not p.is_dir():
            raise HTTPException(status_code=404, detail="Browser root not found")
        return p

    @staticmethod
    def _normalizeRelPath(relPath: str) -> str:
        """
        Normalize a root-relative path, clamping to root (never allowing escape).
        """
        raw = (relPath or "").strip().replace("\\", "/").lstrip("/")
        if not raw or raw in (".", "./"):
            return ""

        parts = [p for p in raw.split("/") if p not in ("", ".")]
        out = []

        for part in parts:
            if part == "..":
                if not out:
                    # Attempt to escape root -> clamp by ignoring
                    continue
                out.pop()
                continue
            out.append(part)

        return "/".join(out)

    @staticmethod
    def _safeRelParts(relPath: str) -> list[str]:
        """
        Build a safe list of path parts that cannot escape the root.
        """
        norm = FileHandlers._normalizeRelPath(relPath)
        if not norm:
            return []
        return [p for p in norm.split("/") if p]

    @staticmethod
    def _guardJoin(root: FsPath, relPath: str) -> FsPath:
        """
        Join root + relPath and ensure the resulting lexical path stays inside root.

        Rules:
        - Input is treated as relative to root (absolute paths rejected here).
        - Path traversal with ".." that would escape root is clamped (never escapes).
        - Symlinks under root are allowed even if they point outside root
          (we do not resolve final targets to decide).
        """
        root = root.resolve()

        relNorm = (relPath or "").strip()

        # Trivial values -> root
        if relNorm in ("", "/", ".", "./"):
            return root

        # Absolute paths are not allowed here; handle them via _resolveWithinRoot
        if FsPath(relNorm).is_absolute():
            raise HTTPException(status_code=400, detail="Invalid path")

        safeParts = FileHandlers._safeRelParts(relNorm)
        if not safeParts:
            return root

        candidate = root.joinpath(*safeParts)

        # Final lexical containment check (candidate is built from safe parts)
        try:
            candidate.relative_to(root)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid path")

        return candidate

    def _resolveWithinRoot(self, root: FsPath, path: str) -> FsPath:
        """
        Accept either:
        - root-relative path (preferred)
        - absolute path (legacy) that is lexically under root

        Returns a lexical path under root without resolving symlinks.
        """
        pRaw = (path or "").strip()
        if not pRaw or pRaw in ("/", ".", "./"):
            return root

        candidate = FsPath(pRaw)

        if candidate.is_absolute():
            # Normalize ".." lexically without resolving symlinks
            candidateNorm = FsPath(os.path.normpath(str(candidate))).absolute()

            # Must be lexically under root
            rootResolved = root.resolve()
            try:
                rel = candidateNorm.relative_to(rootResolved)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid path")

            # Reject any traversal leftovers after normpath (should not contain "..")
            relStr = rel.as_posix()
            safeRel = self._normalizeRelPath(relStr)
            return self._guardJoin(rootResolved, safeRel)

        # Relative path: enforce root boundary
        safeRel = self._normalizeRelPath(pRaw)
        return self._guardJoin(root, safeRel)

    def _relFromRoot(self, root: FsPath, target: FsPath) -> str:
        """
        Compute a root-relative path ("" means root).
        """
        rootResolved = root.resolve()
        try:
            rel = target.relative_to(rootResolved)
        except ValueError:
            return ""
        relStr = rel.as_posix()
        return "" if relStr == "." else relStr

    # -------------------------
    # Mime helpers
    # -------------------------
    @staticmethod
    def _guessMime(p: FsPath) -> str:
        mt, _ = mimetypes.guess_type(str(p))
        return mt or "application/octet-stream"

    def listProtocolDir(self, protocolId: str, path: str) -> list[Dict[str, Any]]:
        """
        Return the directory files list.

        Contract (updated):
        - `path` is relative to the resolved browser root (rootAbs).
        - Absolute paths are accepted only for backward compatibility and must be under rootAbs.
        - items[].path is a leaf (basename) so the client can join cwd + leaf.

        Response:
        - A list of items only (no cwd/dirName):
          items[].name: basename
          items[].path: basename (leaf)
          items[].isDir: bool
          items[].size: int | None (files only)
          items[].mime: str (files only)
        """
        fakeProtocolId = 'fake-protocol-id-for-browser-paths-resolution'
        if protocolId != fakeProtocolId:
            root = self._browserRootAbs(protocolId).resolve()
            target = self._resolveWithinRoot(root, path)
        else:
            root = FsPath(os.path.abspath(self.currentProject.getPath())).resolve()
            target = self._resolveWithinRoot(root, path)

        if not target.exists():
            return []

        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory")

        items: list[Dict[str, Any]] = []

        try:
            for child in target.iterdir():
                # Safely determine isDir and ignore broken entries
                try:
                    isDir = child.is_dir()
                except OSError:
                    continue

                item: Dict[str, Any] = {
                    "name": child.name,
                    "path": child.name,  # leaf-only contract
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

        # Sort folders first, then files alphabetically
        items.sort(key=lambda it: (not it["isDir"], it["name"].lower()))

        return items

    def previewProtocolTextFile(self, protocolId: str, path: str) -> Response:
        """
        Return a lightweight preview for a file under the browser root.

        Contract (updated):
        - `path` is relative to rootAbs ("" is root, but preview requires a file).
        - Absolute paths are accepted only for backward compatibility and must be under rootAbs.

        Behaviors:
        - Text-like files -> UTF-8 text/plain (capped size).
        - Otherwise -> 415 (unsupported).
        """
        root = self._browserRootAbs(protocolId).resolve()
        filePath = self._resolveWithinRoot(root, path)

        if not filePath.exists() or not filePath.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        suffix = filePath.suffix.lower()
        mime = self._guessMime(filePath)  # e.g. "text/plain", etc.

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
                size = filePath.stat().st_size
                if size > MAX_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="File too large to preview",
                    )
            except HTTPException:
                raise
            except Exception:
                # best effort, continue to try reading
                pass

            try:
                text = filePath.read_text(encoding="utf-8", errors="ignore")
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
        Return True if this file is an mrc-like image/volume we can render as PNG.
        """
        suf = filePath.suffix.lower()
        return suf in IMAGES_FILE_EXTENSIONS

    # -------------------------
    # Colormap helpers for volumes
    # -------------------------
    def _colormapName(self) -> str:
        """
        Decide which colormap to use for volume thumbnails.
        Env var SCIPION_THUMB_COLORMAP overrides; default 'inferno'.
        Examples:
        inferno (default, perceptually uniform)
        magma, plasma, viridis
        cividis (colorblind-friendly)
        turbo, cubehelix, bone, gist_earth, gray (if you want to return to gray)
        """
        return os.getenv("SCIPION_THUMB_COLORMAP", "viridis")

    def _applyColormap(self, grayTile: np.ndarray, cmapName: str = "inferno") -> np.ndarray:
        """
        Apply a matplotlib colormap to a 2D tile (float/uint8).
        Returns RGB uint8 array (H, W, 3). Robust to NaNs/constant arrays.
        """
        if grayTile is None or grayTile.ndim != 2:
            return grayTile

        arr = grayTile.astype(np.float32, copy=False)

        # Replace NaNs/inf with median (or 0 if all invalid)
        if not np.isfinite(arr).all():
            finite = np.isfinite(arr)
            fill = float(np.nanmedian(arr[finite])) if finite.any() else 0.0
            arr[~finite] = fill

        aMin = float(np.min(arr))
        aMax = float(np.max(arr))
        if not np.isfinite(aMin) or not np.isfinite(aMax) or aMax <= aMin:
            arr = np.zeros_like(arr, dtype=np.float32)
        else:
            arr = (arr - aMin) / (aMax - aMin)

        try:
            cmap = mplCm.get_cmap(cmapName)
        except Exception:
            cmap = mplCm.get_cmap("inferno")

        rgba = cmap(np.clip(arr, 0.0, 1.0), bytes=True)  # uint8 RGBA
        rgb = rgba[..., :3].copy()
        return rgb

    def _renderImageAsPngAndMeta(self, filePath: FsPath):
        """
        Convert .mrc/.map to an RGB PNG thumbnail (middle Z slice if 3D),
        colorized with a microscopy-friendly colormap (default: inferno).
        Returns (pngBytes, metaDict).
        """
        try:
            imageStk = ImageReadersRegistry.open(str(filePath))
            data = imageStk.getImages()

            if isinstance(data, list):
                data = data[0]

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

            # Voxel size
            props = imageStk.getProperties() or {}
            vx = props.get("sr", 1.0)
            vy = vx
            vz = vx

            # Central slice as raw float
            if data.ndim == 3:
                midZ = nz // 2
                img2d = data[midZ, :, :]
                note = f"Central slice (z={midZ}) rendered as color PNG thumbnail"
            else:
                img2d = data
                note = "2D MRC rendered as color PNG thumbnail"

            arr = np.asarray(img2d, dtype=np.float32)
            if arr.ndim != 2 or arr.size == 0:
                raise HTTPException(
                    status_code=500,
                    detail="Invalid image dimensions"
                )

            # Optional highlight/normalize in real space
            try:
                arr = imageStk.highlightSlice(arr)
                arr = imageStk.normalizeSlice(arr)
            except Exception:
                pass

            # Downscale using PIL
            origHeight, origWidth = arr.shape
            scale = min(
                maxThumbSize / float(origWidth),
                maxThumbSize / float(origHeight),
                1.0,
            )
            thumbWidth = max(1, int(round(origWidth * scale)))
            thumbHeight = max(1, int(round(origHeight * scale)))

            # To uint8 for colormap
            amin, amax = float(np.min(arr)), float(np.max(arr))
            if not np.isfinite(amin) or not np.isfinite(amax) or amax <= amin:
                arrNorm = np.zeros_like(arr, dtype=np.uint8)
            else:
                arrNorm = (arr - amin) / (amax - amin + 1e-12)
                arrNorm = (255.0 * arrNorm).astype(np.uint8)

            pilGray = Image.fromarray(arrNorm, mode="L")
            if thumbWidth < origWidth or thumbHeight < origHeight:
                pilGray = pilGray.resize((thumbWidth, thumbHeight), Image.LANCZOS)

            # Colorize
            cmapName = self._colormapName() if data.ndim == 3 else "gray"
            rgb = self._applyColormap(np.array(pilGray, dtype=np.float32), cmapName=cmapName)
            img = Image.fromarray(rgb, mode="RGB")

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
            "thumbWidth": int(thumbWidth),
            "thumbHeight": int(thumbHeight),
            "sizeBytes": filePath.stat().st_size,
            "note": f"{note} (cmap={cmapName})",
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
              * if MRC/volume -> PNG slice + X-Preview-* headers (RGB colorized)
              * if normal image -> raw image + X-Preview-* headers
              * else -> raw bytes + minimal headers

        Contract (updated):
        - `path` is relative to rootAbs.
        - Absolute paths are accepted only for backward compatibility and must be under rootAbs.
        """
        root = self._browserRootAbs(protocolId).resolve()
        filePath = self._resolveWithinRoot(root, path)

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
