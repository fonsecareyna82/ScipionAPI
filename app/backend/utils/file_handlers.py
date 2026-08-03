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
import json
import sqlite3
import mimetypes
from urllib.parse import quote
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

        protocolId must be a Scipion runtime protocol id. PostgreSQL protocol
        ids must be resolved by ProjectService before calling FileHandlers.

        Returns:
          - rootAbs: absolute root boundary (project folder inferred)
          - startPath: relative to rootAbs ("" means rootAbs)
          - protocolRoot: relative to rootAbs (defaults to startPath)
          - path: legacy absolute protocol path (backward compatibility)
        """
        fakeProtocolId = 'fake-protocol-id-for-browser-paths-resolution'
        if str(protocolId).strip() != fakeProtocolId:
            protocol = self.currentProject.getProtocol(int(protocolId))
            protocolAbsPath = os.path.abspath(protocol.getPath())
        else:
            protocolAbsPath = os.path.abspath(self.currentProject.getPath())

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

    def _coerceExistingRoot(self, root: Union[str, FsPath]) -> FsPath:
        """
        Normalize an arbitrary browser root and ensure it exists as a directory.
        """
        p = FsPath(root).expanduser().resolve()
        if not p.exists() or not p.is_dir():
            raise HTTPException(status_code=404, detail="Browser root not found")
        return p

    def listRemoteDirectoryUnderRoot(self, root: Union[str, FsPath], path: str) -> list[Dict[str, Any]]:
        """
        List a directory under an arbitrary safe root.

        Response contract:
          - name: basename of the entry
          - path: path relative to root
          - absPath: absolute lexical path of the entry
          - isDir: whether the entry is a directory
          - size/mime: only for files
        """
        rootPath = self._coerceExistingRoot(root)
        target = self._resolveWithinRoot(rootPath, path)

        if not target.exists():
            return []

        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory")

        items: list[Dict[str, Any]] = []

        try:
            for child in target.iterdir():
                try:
                    isDir = child.is_dir()
                except OSError:
                    continue

                relPath = self._relFromRoot(rootPath, child)
                absPath = str(child.absolute()).replace("\\", "/")

                item: Dict[str, Any] = {
                    "name": child.name,
                    "path": relPath,
                    "absPath": absPath,
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

        items.sort(key=lambda it: (not it["isDir"], it["name"].lower()))
        return items

    def previewTextFileUnderRoot(self, root: Union[str, FsPath], path: str) -> Response:
        """
        Return a text preview for a file under an arbitrary safe root.
        """
        rootPath = self._coerceExistingRoot(root)
        filePath = self._resolveWithinRoot(rootPath, path)

        if not filePath.exists() or not filePath.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        suffix = filePath.suffix.lower()
        mime = self._guessMime(filePath)

        textual = (
                mime.startswith("text/")
                or mime in (
                    "application/json",
                    "application/xml",
                    "application/x-yaml",
                    "text/x-log",
                )
                or suffix in TEXT_FILE_EXTENSIONS
        )

        if not textual:
            raise HTTPException(
                status_code=415,
                detail="Preview not available for this file type",
            )

        maxBytes = 1 * 1024 * 1024
        try:
            size = filePath.stat().st_size
            if size > maxBytes:
                raise HTTPException(
                    status_code=413,
                    detail="File too large to preview",
                )
        except HTTPException:
            raise
        except Exception:
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

    def previewImageFileUnderRoot(self, root: Union[str, FsPath], path: str, inline: bool) -> Response:
        """
        Preview or download a file under an arbitrary safe root.

        - inline=False: attachment download
        - inline=True:
          * MRC-like files -> PNG thumbnail with preview headers
          * regular images -> image preview with preview headers
          * other files -> raw inline bytes with minimal metadata
        """
        rootPath = self._coerceExistingRoot(root)
        filePath = self._resolveWithinRoot(rootPath, path)

        if not filePath.exists() or not filePath.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        if inline:
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

            rawBytes = filePath.read_bytes()
            meta = {
                "name": filePath.name,
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

        mediaType = self._guessMime(filePath)
        return Response(
            content=filePath.read_bytes(),
            media_type=mediaType,
            headers={
                "Content-Disposition": f'attachment; filename="{filePath.name}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )

    def previewRemoteEntryUnderRoot(
            self,
            root: Union[str, FsPath],
            path: str,
            databaseInspector=None,
    ) -> Response:
        """
        Return a unified lightweight preview for a file under an arbitrary safe root.
        """
        rootPath = self._coerceExistingRoot(root)

        rawPath = (path or "").strip()
        if not rawPath or rawPath in ("/", ".", "./"):
            raise HTTPException(status_code=400, detail="A file path is required")

        stackIndex: Optional[int] = None
        resolvedPath = rawPath

        if "@" in rawPath:
            prefix, rest = rawPath.split("@", 1)
            prefixStr = prefix.strip()
            if prefixStr.isdigit():
                stackIndex = int(prefixStr)
                resolvedPath = rest.strip()

        filePath = self._resolveWithinRoot(rootPath, resolvedPath)

        if not filePath.exists():
            raise HTTPException(status_code=404, detail="Entry not found")
        if filePath.is_dir():
            raise HTTPException(status_code=400, detail="Not a file")

        suffix = filePath.suffix.lower()
        mime = self._guessMime(filePath)

        try:
            sizeBytes = filePath.stat().st_size
        except Exception:
            sizeBytes = None

        textual = (
                mime.startswith("text/")
                or mime in ("application/json", "application/xml", "application/x-yaml", "text/x-log")
                or suffix in TEXT_FILE_EXTENSIONS
        )

        if textual:
            resp = self.previewTextFileUnderRoot(rootPath, resolvedPath)
            meta = {
                "name": filePath.name,
                "mime": mime,
                "sizeBytes": sizeBytes,
            }
            return self._attachPreviewContract(
                resp,
                kind="text",
                name=filePath.name,
                meta=meta,
            )

        isMrcLike = suffix in IMAGES_FILE_EXTENSIONS
        isRegularImage = mime.startswith("image/")

        if isMrcLike or isRegularImage:
            if stackIndex is not None and isMrcLike:
                imageSpec = f"{stackIndex}@{str(filePath)}"
                pngBytes, meta = self._renderImageSpecAsPngAndMeta(imageSpec, filePath)

                depth = meta.get("depth")
                kind = "volume" if (isinstance(depth, int) and depth > 1) else "image"

                resp = Response(
                    content=pngBytes,
                    media_type="image/png",
                    headers={
                        "Content-Disposition": f'inline; filename="{filePath.stem}.png"',
                    },
                )
                return self._attachPreviewContract(
                    resp,
                    kind=kind,
                    name=filePath.name,
                    meta=meta,
                    responseMime="image/png",
                )

            resp = self.previewImageFileUnderRoot(rootPath, resolvedPath, inline=True)

            previewMime = resp.headers.get("X-Preview-Mime", "") or ""
            previewDepth = resp.headers.get("X-Preview-Depth")

            kind = "image"
            if previewMime.startswith("volume/"):
                kind = "volume"
            elif previewDepth:
                try:
                    if int(previewDepth) > 1:
                        kind = "volume"
                except Exception:
                    pass

            meta = {
                "name": filePath.name,
                "mime": previewMime or mime,
                "sizeBytes": sizeBytes,
            }

            return self._attachPreviewContract(
                resp,
                kind=kind,
                name=filePath.name,
                meta=meta,
            )

        if self._isSqliteLike(filePath):
            return self._previewSqliteDatabase(
                filePath=filePath,
                mime=mime,
                sizeBytes=sizeBytes,
                databaseInspector=databaseInspector,
            )

        maxBytes = 256 * 1024
        try:
            with open(filePath, "rb") as f:
                chunk = f.read(maxBytes)
        except Exception:
            raise HTTPException(status_code=500, detail="Could not read file")

        meta = {
            "name": filePath.name,
            "mime": mime,
            "sizeBytes": sizeBytes,
            "note": f"binaryPreviewFirstBytes={len(chunk)}",
        }

        resp = Response(
            content=chunk,
            media_type=mime,
            headers={
                "Content-Disposition": f'inline; filename="{filePath.name}"',
            },
        )

        return self._attachPreviewContract(
            resp,
            kind="binary",
            name=filePath.name,
            meta=meta,
        )

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
        root = self._browserRootAbs(protocolId).resolve()
        return self.listRemoteDirectoryUnderRoot(root, path)

    def previewProtocolRemoteEntry(
            self,
            protocolId: str,
            path: str,
            databaseInspector=None,
    ) -> Response:
        root = self._browserRootAbs(protocolId).resolve()
        return self.previewRemoteEntryUnderRoot(
            root,
            path,
            databaseInspector=databaseInspector,
        )

    def _renderImageSpecAsPngAndMeta(self, imageSpec: str, backingPath: FsPath):
        """
        Render a preview PNG from an ImageReadersRegistry spec like '3@/abs/file.mrcs'.
        """
        try:
            imageStk = ImageReadersRegistry.open(imageSpec)
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
                    detail="Unsupported image dimensionality (only 2D or 3D supported)",
                )

            props = imageStk.getProperties() or {}
            vx = props.get("sr", 1.0)
            vy = vx
            vz = vx

            if data.ndim == 3:
                midZ = nz // 2
                img2d = data[midZ, :, :]
                note = f"Central slice (z={midZ}) rendered as color PNG thumbnail"
            else:
                img2d = data
                note = "2D image rendered as PNG thumbnail"

            arr = np.asarray(img2d, dtype=np.float32)
            if arr.ndim != 2 or arr.size == 0:
                raise HTTPException(status_code=500, detail="Invalid image dimensions")

            try:
                arr = imageStk.highlightSlice(arr)
                arr = imageStk.normalizeSlice(arr)
            except Exception:
                pass

            origHeight, origWidth = arr.shape
            scale = min(
                maxThumbSize / float(origWidth),
                maxThumbSize / float(origHeight),
                1.0,
            )
            thumbWidth = max(1, int(round(origWidth * scale)))
            thumbHeight = max(1, int(round(origHeight * scale)))

            amin, amax = float(np.min(arr)), float(np.max(arr))
            if not np.isfinite(amin) or not np.isfinite(amax) or amax <= amin:
                arrNorm = np.zeros_like(arr, dtype=np.uint8)
            else:
                arrNorm = (arr - amin) / (amax - amin + 1e-12)
                arrNorm = (255.0 * arrNorm).astype(np.uint8)

            pilGray = Image.fromarray(arrNorm, mode="L")
            if thumbWidth < origWidth or thumbHeight < origHeight:
                pilGray = pilGray.resize((thumbWidth, thumbHeight), Image.LANCZOS)

            cmapName = self._colormapName() if data.ndim == 3 else "gray"
            rgb = self._applyColormap(np.array(pilGray, dtype=np.float32), cmapName=cmapName)
            img = Image.fromarray(rgb, mode="RGB")

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            pngBytes = buf.getvalue()

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not read/convert image: {str(e)}")

        meta = {
            "mime": "volume/mrc" if backingPath.suffix.lower() in IMAGES_FILE_EXTENSIONS else self._guessMime(
                backingPath),
            "width": int(nx),
            "height": int(ny),
            "depth": int(nz),
            "thumbWidth": int(thumbWidth),
            "thumbHeight": int(thumbHeight),
            "sizeBytes": backingPath.stat().st_size,
            "note": f"{note} (cmap={cmapName})",
        }

        try:
            meta["voxelSize"] = [float(vx), float(vy), float(vz)]
        except Exception:
            pass

        return pngBytes, meta

    def previewProtocolTextFile(self, protocolId: str, path: str) -> Response:
        root = self._browserRootAbs(protocolId).resolve()
        return self.previewTextFileUnderRoot(root, path)

    def _isPreviewableMrc(self, filePath: FsPath) -> bool:
        """
        Return True if this file is an mrc-like image/volume we can render as PNG.
        """
        suf = filePath.suffix.lower()
        return suf in IMAGES_FILE_EXTENSIONS

    def _isSqliteLike(self, filePath: FsPath) -> bool:
        """
        Return True if this file should be inspected as a SQLite database.
        """
        suffix = filePath.suffix.lower()
        if suffix in {".sqlite", ".sqlite3", ".db"}:
            return True

        try:
            with open(filePath, "rb") as handle:
                return handle.read(16) == b"SQLite format 3\x00"
        except Exception:
            return False

    def _connectReadonlySqlite(self, filePath: FsPath) -> sqlite3.Connection:
        """
        Open a SQLite database in read-only mode.
        """
        resolvedPath = str(filePath.resolve()).replace("\\", "/")
        sqliteUri = f"file:{quote(resolvedPath, safe='/:')}?mode=ro"

        conn = sqlite3.connect(sqliteUri, uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _quoteSqliteIdentifier(identifier: str) -> str:
        """
        Quote a SQLite identifier safely.
        """
        return '"' + str(identifier).replace('"', '""') + '"'

    @staticmethod
    def _normalizeSqliteCell(value: Any) -> Any:
        """
        Convert SQLite values into JSON-safe preview values.
        """
        if value is None:
            return None

        if isinstance(value, (int, float, str)):
            if isinstance(value, str) and len(value) > 240:
                return value[:240] + "..."
            return value

        if isinstance(value, bytes):
            return f"<bytes {len(value)}>"

        return str(value)

    def _fetchSqlitePragmaValue(
            self,
            conn: sqlite3.Connection,
            pragmaName: str,
            defaultValue: Any = None,
    ) -> Any:
        """
        Fetch a single-value PRAGMA safely.
        """
        try:
            row = conn.execute(f"PRAGMA {pragmaName}").fetchone()
            if row is None:
                return defaultValue
            if len(row.keys()) <= 0:
                return defaultValue
            return row[0]
        except Exception:
            return defaultValue

    def _fetchSqliteQuickCheck(self, conn: sqlite3.Connection) -> str:
        """
        Run a lightweight integrity check.
        """
        try:
            row = conn.execute("PRAGMA quick_check(1)").fetchone()
            if row is None:
                return "unknown"
            return str(row[0])
        except Exception:
            return "unknown"

    def _inspectGenericSqliteDatabase(
            self,
            filePath: FsPath,
            sizeBytes: Optional[int],
    ) -> Dict[str, Any]:
        """
        Inspect a SQLite database without depending on Scipion object readers.
        """
        warnings: list[str] = []
        tables: list[Dict[str, Any]] = []
        sample: Optional[Dict[str, Any]] = None

        try:
            conn = self._connectReadonlySqlite(filePath)
        except Exception as exc:
            return {
                "engine": "sqlite",
                "readable": False,
                "isScipion": False,
                "summary": [
                    {"key": "Status", "value": "Could not open database"},
                    {"key": "Error", "value": str(exc)},
                ],
                "tables": [],
                "sample": None,
                "warnings": [str(exc)],
            }

        try:
            pageSize = self._fetchSqlitePragmaValue(conn, "page_size")
            pageCount = self._fetchSqlitePragmaValue(conn, "page_count")
            encoding = self._fetchSqlitePragmaValue(conn, "encoding")
            userVersion = self._fetchSqlitePragmaValue(conn, "user_version")
            applicationId = self._fetchSqlitePragmaValue(conn, "application_id")
            quickCheck = self._fetchSqliteQuickCheck(conn)

            schemaRows = conn.execute(
                """
                SELECT name, type
                FROM sqlite_master
                WHERE type IN ('table', 'view')
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY type, name
                """
            ).fetchall()

            indexCountRow = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM sqlite_master
                WHERE type = 'index'
                  AND name NOT LIKE 'sqlite_%'
                """
            ).fetchone()
            indexCount = int(indexCountRow["count"]) if indexCountRow is not None else 0

            maxTables = 60
            if len(schemaRows) > maxTables:
                warnings.append(f"Only the first {maxTables} tables/views are described.")

            for schemaRow in schemaRows[:maxTables]:
                tableName = str(schemaRow["name"])
                tableType = str(schemaRow["type"])
                quotedName = self._quoteSqliteIdentifier(tableName)

                columnsInfo = []
                try:
                    pragmaRows = conn.execute(f"PRAGMA table_info({quotedName})").fetchall()
                    for pragmaRow in pragmaRows:
                        columnsInfo.append({
                            "name": str(pragmaRow["name"]),
                            "type": str(pragmaRow["type"] or ""),
                            "notNull": bool(pragmaRow["notnull"]),
                            "primaryKey": bool(pragmaRow["pk"]),
                        })
                except Exception as exc:
                    warnings.append(f"Could not inspect columns for {tableName}: {exc}")

                rowCount: Optional[int] = None
                if tableType == "table":
                    try:
                        countRow = conn.execute(f"SELECT COUNT(*) AS count FROM {quotedName}").fetchone()
                        rowCount = int(countRow["count"]) if countRow is not None else None
                    except Exception as exc:
                        warnings.append(f"Could not count rows for {tableName}: {exc}")

                tables.append({
                    "name": tableName,
                    "type": tableType,
                    "rows": rowCount,
                    "columns": len(columnsInfo),
                    "columnPreview": columnsInfo[:12],
                })

            sampleTable = self._chooseSqliteSampleTable(tables)
            if sampleTable:
                sample = self._buildSqliteSample(conn, sampleTable)

            isScipionLike = self._looksLikeScipionSqlite(tables)

            summary = [
                {"key": "Status", "value": "Readable"},
                {"key": "Type", "value": "Scipion SQLite database" if isScipionLike else "SQLite database"},
                {"key": "Tables", "value": len([t for t in tables if t.get("type") == "table"])},
                {"key": "Views", "value": len([t for t in tables if t.get("type") == "view"])},
                {"key": "Indexes", "value": indexCount},
            ]

            if sizeBytes is not None:
                summary.append({"key": "Size", "value": sizeBytes})
            if encoding:
                summary.append({"key": "Encoding", "value": encoding})
            if pageSize:
                summary.append({"key": "Page size", "value": pageSize})
            if pageCount:
                summary.append({"key": "Page count", "value": pageCount})
            if userVersion is not None:
                summary.append({"key": "User version", "value": userVersion})
            if applicationId is not None:
                summary.append({"key": "Application id", "value": applicationId})
            if quickCheck:
                summary.append({"key": "Quick check", "value": quickCheck})

            return {
                "engine": "sqlite",
                "readable": True,
                "isScipion": isScipionLike,
                "objectClass": None,
                "summary": summary,
                "tables": tables,
                "sample": sample,
                "warnings": warnings,
            }

        except Exception as exc:
            return {
                "engine": "sqlite",
                "readable": False,
                "isScipion": False,
                "objectClass": None,
                "objectCount": None,
                "summary": [
                    {"key": "Status", "value": "Could not inspect database"},
                    {"key": "Error", "value": str(exc)},
                ],
                "tables": [],
                "sample": None,
                "warnings": [str(exc)],
            }

        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _looksLikeScipionSqlite(self, tables: list[Dict[str, Any]]) -> bool:
        """
        Best-effort schema heuristic for Scipion object databases.
        """
        tableNames = {str(t.get("name") or "").lower() for t in tables}

        scipionHints = {
            "objects",
            "relations",
            "properties",
            "classes",
        }

        return bool(tableNames.intersection(scipionHints))

    def _chooseSqliteSampleTable(self, tables: list[Dict[str, Any]]) -> Optional[str]:
        """
        Pick the most useful table for a compact row preview.
        """
        if not tables:
            return None

        preferredNames = ["Objects", "objects", "Properties", "properties"]

        for preferredName in preferredNames:
            for table in tables:
                if table.get("type") == "table" and table.get("name") == preferredName:
                    return str(table["name"])

        regularTables = [t for t in tables if t.get("type") == "table"]
        if not regularTables:
            return None

        regularTables.sort(
            key=lambda t: (
                int(t.get("rows") or 0),
                str(t.get("name") or "").lower(),
            ),
            reverse=True,
        )

        return str(regularTables[0].get("name") or "") or None

    def _buildSqliteSample(
            self,
            conn: sqlite3.Connection,
            tableName: str,
            maxRows: int = 25,
            maxColumns: int = 12,
    ) -> Optional[Dict[str, Any]]:
        """
        Build a compact preview of rows from one SQLite table.
        """
        if not tableName:
            return None

        quotedName = self._quoteSqliteIdentifier(tableName)

        try:
            pragmaRows = conn.execute(f"PRAGMA table_info({quotedName})").fetchall()
            columns = [str(row["name"]) for row in pragmaRows][:maxColumns]
        except Exception:
            columns = []

        if not columns:
            return None

        quotedColumns = ", ".join(self._quoteSqliteIdentifier(c) for c in columns)

        try:
            rows = conn.execute(
                f"SELECT {quotedColumns} FROM {quotedName} LIMIT ?",
                (maxRows,),
            ).fetchall()
        except Exception:
            return None

        outRows = []
        for row in rows:
            outRows.append([
                self._normalizeSqliteCell(row[col])
                for col in columns
            ])

        return {
            "table": tableName,
            "columns": columns,
            "rows": outRows,
            "truncated": len(outRows) >= maxRows,
        }

    def _tryInspectScipionSqliteDatabase(self, filePath: FsPath) -> Optional[Dict[str, Any]]:
        """
        Hook for Scipion-specific object inspection.

        This is intentionally isolated so the generic SQLite preview remains
        stable even if Scipion readers fail for a particular file.
        """
        try:
            # Scipion reader integration will be added here.
            return None
        except Exception:
            return None

    def _previewSqliteDatabase(
            self,
            filePath: FsPath,
            mime: str,
            sizeBytes: Optional[int],
            databaseInspector=None,
    ) -> Response:
        """
        Return a structured preview for SQLite databases.
        """
        effectiveMime = mime
        if not effectiveMime or effectiveMime == "application/octet-stream":
            effectiveMime = "application/vnd.sqlite3"

        databaseInfo = self._inspectGenericSqliteDatabase(
            filePath=filePath,
            sizeBytes=sizeBytes,
        )

        scipionInfo = None

        if databaseInspector is not None:
            try:
                scipionInfo = databaseInspector(filePath)
            except Exception as exc:
                warnings = databaseInfo.setdefault("warnings", [])
                warnings.append(f"Scipion reader failed: {exc}")

        if scipionInfo:
            databaseInfo["isScipion"] = True
            databaseInfo["scipion"] = scipionInfo

            objectClass = scipionInfo.get("objectClass")
            if objectClass:
                databaseInfo["objectClass"] = objectClass

            objectCount = scipionInfo.get("objectCount")
            if objectCount is not None:
                databaseInfo["objectCount"] = objectCount

        databaseType = "scipion" if databaseInfo.get("isScipion") else "sqlite"

        meta = {
            "name": filePath.name,
            "mime": effectiveMime,
            "sizeBytes": sizeBytes,
            "databaseType": databaseType,
            "readable": bool(databaseInfo.get("readable")),
            "tableCount": len(databaseInfo.get("tables") or []),
            "objectClass": databaseInfo.get("objectClass"),
        }

        payload = {
            "kind": "database",
            "mime": effectiveMime,
            "meta": meta,
            "database": databaseInfo,
        }

        response = Response(
            content=json.dumps(payload, ensure_ascii=False),
            media_type="application/json",
            headers={
                "Content-Disposition": f'inline; filename="{filePath.name}"',
            },
        )

        return self._attachPreviewContract(
            response=response,
            kind="database",
            name=filePath.name,
            meta=meta,
            responseMime="application/json",
        )

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
            "name": filePath.name,
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
            "name": filePath.name,
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

        if "kind" in meta and meta["kind"] is not None:
            previewHeaders["X-Preview-Kind"] = str(meta["kind"])
        if "name" in meta and meta["name"] is not None:
            previewHeaders["X-Preview-Name"] = str(meta["name"])
        if "mime" in meta and meta["mime"] is not None:
            previewHeaders["X-Preview-Mime"] = str(meta["mime"])
        if "responseMime" in meta and meta["responseMime"] is not None:
            previewHeaders["X-Preview-ResponseMime"] = str(meta["responseMime"])

        if "width" in meta and meta["width"] is not None:
            previewHeaders["X-Preview-Width"] = str(meta["width"])
        if "height" in meta and meta["height"] is not None:
            previewHeaders["X-Preview-Height"] = str(meta["height"])
        if "depth" in meta and meta["depth"] is not None:
            previewHeaders["X-Preview-Depth"] = str(meta["depth"])

        if "thumbWidth" in meta and meta["thumbWidth"] is not None:
            previewHeaders["X-Preview-ThumbWidth"] = str(meta["thumbWidth"])
        if "thumbHeight" in meta and meta["thumbHeight"] is not None:
            previewHeaders["X-Preview-ThumbHeight"] = str(meta["thumbHeight"])

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

        previewHeaders['X-Preview-Schema'] = 'scipion'

        exposeList = [
            "Content-Disposition",
            "X-Preview-Kind",
            "X-Preview-Name",
            "X-Preview-Mime",
            "X-Preview-ResponseMime",
            "X-Preview-Width",
            "X-Preview-Height",
            "X-Preview-Depth",
            "X-Preview-ThumbWidth",
            "X-Preview-ThumbHeight",
            "X-Preview-SizeBytes",
            "X-Preview-VoxelSize",
            "X-Preview-Note",
            "X-Preview-Columns",
            "X-Preview-RowCount",
            "X-Preview-Type",
            "X-Preview-Mode",
            "X-Preview-Truncated",
            'X-Preview-Schema'
        ]
        previewHeaders["Access-Control-Expose-Headers"] = ", ".join(exposeList)

        return previewHeaders

    def _attachPreviewContract(
            self,
            response: Response,
            kind: str,
            name: str,
            meta: Optional[Dict[str, Any]] = None,
            responseMime: Optional[str] = None,
    ) -> Response:
        # ensureResponseMime
        resolvedResponseMime = responseMime
        if not resolvedResponseMime:
            resolvedResponseMime = getattr(response, "media_type", None) or response.headers.get("content-type")
        if not resolvedResponseMime:
            resolvedResponseMime = "application/octet-stream"

        mergedMeta: Dict[str, Any] = dict(meta or {})
        mergedMeta["kind"] = kind
        mergedMeta["name"] = name
        mergedMeta["responseMime"] = resolvedResponseMime

        # ensureContentDisposition
        if "Content-Disposition" not in response.headers:
            response.headers["Content-Disposition"] = f'inline; filename="{name}"'

        previewHeaders = self._buildPreviewHeaders(mergedMeta)
        response.headers.update(previewHeaders)
        return response

    def previewProtocolImageFile(self, protocolId, path, inline: bool) -> Response:
        root = self._browserRootAbs(protocolId).resolve()
        return self.previewImageFileUnderRoot(root, path, inline)