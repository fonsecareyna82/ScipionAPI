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
# app/backend/utils/thumbnail_service.py

import base64
import io
import logging
import os
import re
import json
import hashlib
from urllib.parse import quote
from pathlib import Path
import threading
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageFont

from metadataviewer.dao.numpy_dao import NumpyDao
from metadataviewer.model import ObjectManager

from tomo.constants import BOTTOM_LEFT_CORNER
from tomo.objects import (SetOfTiltSeries, SetOfTiltSeriesM, SetOfTomoMasks,
                          SetOfMeshes, SetOfTiltSeriesCoordinates, SetOfLandmarkModels)

from app.backend.utils.constants import maxThumbSize
from app.backend.utils.volume_utils import readVolumeArray3d

from pwem.emlib.image.image_readers import ImageReadersRegistry
from pwem.objects import (
    EMSet,
    SetOfClasses2D,
    SetOfClasses3D,
    SetOfFSCs,
    SetOfMicrographs,
    SetOfCoordinates,
    SetOfParticles,
    SetOfVolumes,
    SetOfMovies,
    SetOfCTF,
    SetOfDefocusGroup,
    VolumeMask, Mask, AtomStruct,
    PdbFile,
    SetOfAtomStructs,
    SetOfPDBs,
    SetOfSequences,
    NormalMode,
    SetOfNormalModes,
    SetOfPrincipalComponents,
)
from pwem.viewers import RENDER
from pwem.viewers.mdviewer.readers import ScipionImageReader
from pwem.viewers.mdviewer.sqlite_dao import ScipionSetsDAO
from pwem.viewers.mdviewer.star_dao import StarFile
from pwem.viewers.viewers_data import RegistryViewerConfig

from pyworkflow.object import (
    Object as ScipionObject,
    Set as ScipionSet,
)

logger = logging.getLogger(__name__)
_thumbnailBuildLocksGuard = threading.Lock()
_thumbnailBuildLocks: Dict[str, threading.Lock] = {}


class ThumbnailService:
    CACHE_VERSION = "v1"
    PROTOCOL_ASPECT_RATIO = 0.68

    def __init__(self, currentProject):
        self.currentProject = currentProject

        # Detached PostgreSQL outputs indexed by:
        # protocolId -> outputName -> runtime object.
        self._postgresqlOutputsByProtocolId = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def _getPostgresqlRuntimeMapper(
            self,
    ):
        mapper = getattr(
            self.currentProject,
            "mapper",
            None,
        )

        if mapper is None:
            return None

        marker = getattr(
            mapper,
            "isPostgresqlRuntimeMapper",
            False,
        )

        if callable(marker):
            try:
                marker = marker()
            except Exception:
                return None

        if not marker:
            return None

        return mapper

    @staticmethod
    def _getRuntimeOutputParentId(
            output,
    ) -> Optional[int]:
        parentId = None

        getter = getattr(
            output,
            "getObjParentId",
            None,
        )

        if callable(getter):
            try:
                parentId = getter()
            except Exception:
                parentId = None

        if parentId is None:
            parentId = getattr(
                output,
                "_objParentId",
                None,
            )

        try:
            return int(parentId)
        except (
                TypeError,
                ValueError,
        ):
            return None

    @staticmethod
    def _getRuntimeOutputName(
            output,
            parentProtocolId: int,
    ) -> str:
        outputName = None

        getter = getattr(
            output,
            "getObjName",
            None,
        )

        if callable(getter):
            try:
                outputName = getter()
            except Exception:
                outputName = None

        if not outputName:
            outputName = getattr(
                output,
                "_objName",
                None,
            )

        outputName = str(
            outputName or ""
        ).strip()

        protocolPrefix = (
            "%s."
            % int(parentProtocolId)
        )

        if outputName.startswith(
                protocolPrefix
        ):
            outputName = outputName[
                len(protocolPrefix):
            ]

        return outputName

    def _loadPostgresqlOutputsByProtocolId(
            self,
    ) -> Dict[str, Dict[str, Any]]:
        if (
                self._postgresqlOutputsByProtocolId
                is not None
        ):
            return (
                self
                ._postgresqlOutputsByProtocolId
            )

        result: Dict[
            str,
            Dict[str, Any],
        ] = {}

        # Set the cache before loading objects. Pointer resolution can
        # recursively reconstruct other PostgreSQL runtime objects.
        self._postgresqlOutputsByProtocolId = (
            result
        )

        runtimeMapper = (
            self._getPostgresqlRuntimeMapper()
        )

        if runtimeMapper is None:
            return result

        for objectClass in (
                ScipionSet,
                ScipionObject,
        ):
            try:
                runtimeObjects = (
                    runtimeMapper.selectByClass(
                        objectClass,
                        includeSubclasses=True,
                        iterate=False,
                    )
                    or []
                )

            except Exception:
                logger.debug(
                    "Could not load PostgreSQL "
                    "thumbnail output objects. "
                    "className=%s",
                    objectClass.__name__,
                    exc_info=True,
                )

                continue

            for runtimeObject in (
                    runtimeObjects
            ):
                parentProtocolId = (
                    self
                    ._getRuntimeOutputParentId(
                        runtimeObject
                    )
                )

                if parentProtocolId is None:
                    continue

                outputName = (
                    self
                    ._getRuntimeOutputName(
                        output=runtimeObject,
                        parentProtocolId=(
                            parentProtocolId
                        ),
                    )
                )

                if not outputName:
                    continue

                result.setdefault(
                    str(parentProtocolId),
                    {},
                ).setdefault(
                    outputName,
                    runtimeObject,
                )

        return result

    def _iterPostgresqlOutputAttributes(
            self,
            protocol,
    ) -> Iterable[Tuple[str, Any]]:
        try:
            protocolId = int(
                protocol.getObjId()
            )
        except Exception:
            return

        outputsByName = (
            self
            ._loadPostgresqlOutputsByProtocolId()
            .get(
                str(protocolId),
                {},
            )
        )

        for outputName, output in (
                outputsByName.items()
        ):
            if output is not None:
                yield outputName, output

    def _findProtocolOutput(
            self,
            protocol,
            outputName: str,
    ):
        expectedName = str(
            outputName or ""
        )

        for candidateName, output in (
                self._iterOutputAttributes(
                    protocol
                )
        ):
            if str(candidateName) == expectedName:
                return output

        return None

    def _getThumbnailBuildLock(self, cachePath: Path):
        key = str(cachePath)
        with _thumbnailBuildLocksGuard:
            lock = _thumbnailBuildLocks.get(key)
            if lock is None:
                lock = threading.Lock()
                _thumbnailBuildLocks[key] = lock
            return lock

    def _isValidCachedImage(self, cachePath: Path) -> bool:
        try:
            if not cachePath.exists():
                return False
            if cachePath.stat().st_size <= 0:
                return False
            with Image.open(cachePath) as img:
                img.verify()
            return True
        except Exception:
            try:
                cachePath.unlink(missing_ok=True)
            except Exception:
                pass
            return False

    def listUsefulProtocols(self, maxProtocols: int = 12) -> List[Dict[str, Any]]:
        protocols = self._iterProtocols()
        candidates: List[Dict[str, Any]] = []

        for protocol in protocols:
            try:
                bestOutput = self._selectBestOutput(protocol)
                if bestOutput is None:
                    continue

                output = bestOutput["output"]
                itemsCount = self._safeOutputSize(output)
                totalScore = (
                    int(bestOutput["score"])
                    + self._scoreProtocolStatus(protocol)
                    + min(itemsCount or 0, 12)
                )

                if totalScore < 60:
                    continue

                candidates.append(
                    {
                        "protocolId": int(protocol.getObjId()),
                        "protocolLabel": self._getProtocolLabel(protocol),
                        "status": self._getProtocolStatus(protocol),
                        "outputName": bestOutput["outputName"],
                        "outputClassName": bestOutput["outputClassName"],
                        "itemsCount": itemsCount or 0,
                        "score": totalScore,
                    }
                )
            except Exception:
                logger.debug(
                    "Skipping protocol while listing useful thumbnails",
                    exc_info=True,
                )

        candidates.sort(
            key=lambda item: (
                int(item.get("score", 0)),
                int(item.get("itemsCount", 0)),
                int(item.get("protocolId", 0)),
            ),
            reverse=True,
        )
        return candidates[: max(1, int(maxProtocols))]

    def buildProtocolThumbnail(
            self,
            protocolId: int,
            force: bool = False,
            size: int = 360,
            outputName: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
                Build a thumbnail for a Scipion runtime protocol id.

                PostgreSQL protocol ids must be resolved by ProjectService before
                calling ThumbnailService.
                """
        try:
            protocol = self.currentProject.getProtocol(int(protocolId))
        except Exception:
            protocol = None

        if protocol is None:
            return {
                "protocolId": int(protocolId),
                "protocolLabel": f"Protocol {int(protocolId)}",
                "status": "unknown",
                "outputName": outputName,
                "outputClassName": None,
                "absolutePath": None,
                "cached": False,
                "exists": False,
            }

        cachePath = self._getProtocolCachePath(
            protocolId,
            size=size,
            outputName=outputName,
        )

        selectedCandidate: Optional[Dict[str, Any]] = None
        if outputName:
            for candidate in self._collectSortedOutputCandidates(protocol):
                if str(candidate.get("outputName")) == str(outputName):
                    selectedCandidate = candidate
                    break

            if selectedCandidate is None:
                return {
                    "protocolId": int(protocolId),
                    "protocolLabel": self._getProtocolLabel(protocol),
                    "status": self._getProtocolStatus(protocol),
                    "outputName": outputName,
                    "outputClassName": None,
                    "absolutePath": None,
                    "cached": False,
                    "exists": False,
                }

        buildLock = self._getThumbnailBuildLock(cachePath)
        with buildLock:
            if not force and self._isValidCachedImage(cachePath):
                return {
                    "protocolId": int(protocolId),
                    "protocolLabel": self._getProtocolLabel(protocol),
                    "status": self._getProtocolStatus(protocol),
                    "outputName": selectedCandidate["outputName"] if selectedCandidate else outputName,
                    "outputClassName": selectedCandidate["outputClassName"] if selectedCandidate else None,
                    "absolutePath": str(cachePath),
                    "cached": True,
                    "exists": True,
                }

            previewImage: Optional[Image.Image] = None
            candidates = (
                [selectedCandidate]
                if selectedCandidate is not None
                else self._collectSortedOutputCandidates(protocol)
            )

            for candidate in candidates:
                if candidate is None:
                    continue

                try:
                    image = self._renderProtocolPreviewImage(
                        protocol=protocol,
                        output=candidate["output"],
                        outputName=candidate["outputName"],
                        outputClassName=candidate["outputClassName"],
                        size=size,
                    )
                    if image is not None:
                        selectedCandidate = candidate
                        previewImage = image
                        break
                except Exception:
                    logger.debug(
                        "Candidate thumbnail render failed. protocolId=%s output=%s class=%s",
                        protocolId,
                        candidate.get("outputName"),
                        candidate.get("outputClassName"),
                        exc_info=True,
                    )

            if previewImage is None and outputName is None:
                try:
                    previewImage = self._renderProtocolFilesystemFallback(protocol, size=size)
                except Exception:
                    logger.debug(
                        "Filesystem thumbnail fallback failed. protocolId=%s",
                        protocolId,
                        exc_info=True,
                    )
                    previewImage = None

            if previewImage is None:
                return {
                    "protocolId": int(protocolId),
                    "protocolLabel": self._getProtocolLabel(protocol),
                    "status": self._getProtocolStatus(protocol),
                    "outputName": selectedCandidate["outputName"] if selectedCandidate else outputName,
                    "outputClassName": selectedCandidate["outputClassName"] if selectedCandidate else None,
                    "absolutePath": None,
                    "cached": False,
                    "exists": False,
                }

            thumbnail = self._finalizeProtocolThumbnail(
                previewImage=previewImage,
                size=size,
                protocolId=int(protocolId),
            )
            self._saveImage(thumbnail, cachePath)

            return {
                "protocolId": int(protocolId),
                "protocolLabel": self._getProtocolLabel(protocol),
                "status": self._getProtocolStatus(protocol),
                "outputName": selectedCandidate["outputName"] if selectedCandidate else outputName,
                "outputClassName": selectedCandidate["outputClassName"] if selectedCandidate else None,
                "absolutePath": str(cachePath),
                "cached": False,
                "exists": True,
            }

    def buildProjectThumbnail(
            self,
            force: bool = False,
            size: int = 720,
            maxProtocols: int = 6,
    ) -> Dict[str, Any]:
        cachePath = self._getProjectCachePath(size=size, maxProtocols=maxProtocols)

        buildLock = self._getThumbnailBuildLock(cachePath)
        with buildLock:
            if not force and self._isValidCachedImage(cachePath):
                return {
                    "absolutePath": str(cachePath),
                    "cached": True,
                    "items": None,
                }

            useful = self.listUsefulProtocols(
                maxProtocols=max(3, int(maxProtocols) * 3),
            )
            renderedItems: List[Dict[str, Any]] = []
            protocolThumbWidth = self._projectProtocolSize(
                size=int(size),
                maxProtocols=int(maxProtocols),
            )

            for candidate in useful:
                try:
                    built = self.buildProtocolThumbnail(
                        protocolId=int(candidate["protocolId"]),
                        force=force,
                        size=protocolThumbWidth,
                    )

                    if not built.get("exists") or not built.get("absolutePath"):
                        continue

                    renderedItems.append(
                        {
                            "protocolId": int(candidate["protocolId"]),
                            "protocolLabel": candidate.get("protocolLabel"),
                            "status": candidate.get("status"),
                            "outputName": candidate.get("outputName"),
                            "outputClassName": candidate.get("outputClassName"),
                            "itemsCount": candidate.get("itemsCount", 0),
                            "absolutePath": built["absolutePath"],
                        }
                    )

                    if len(renderedItems) >= int(maxProtocols):
                        break

                except Exception:
                    logger.debug(
                        "Skipping failed protocol thumbnail while building project strip. protocolId=%s",
                        candidate.get("protocolId"),
                        exc_info=True,
                    )

            if not renderedItems:
                return {
                    "absolutePath": None,
                    "cached": False,
                    "items": 0,
                }

            strip = self._composeProjectStrip(
                items=renderedItems,
                size=int(size),
            )
            self._saveImage(strip, cachePath)

            return {
                "absolutePath": str(cachePath),
                "cached": False,
                "items": len(renderedItems),
            }

    def _getBadgeFont(self, badgeH: int):
        fontSize = max(12, int(round(badgeH * 0.48)))
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]

        for path in candidates:
            try:
                if Path(path).exists():
                    return ImageFont.truetype(path, fontSize)
            except Exception:
                continue

        return ImageFont.load_default()

    def _drawProtocolBadge(self, image: Image.Image, text: str):
        if not text:
            return

        draw = ImageDraw.Draw(image)
        width, height = image.size

        marginX = max(8, int(round(width * 0.03)))
        marginY = max(8, int(round(height * 0.05)))
        badgeH = max(24, int(round(height * 0.17)))
        textPadX = max(10, int(round(badgeH * 0.42)))
        font = self._getBadgeFont(badgeH)

        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            textW = bbox[2] - bbox[0]
            textH = bbox[3] - bbox[1]
        except Exception:
            textW = max(24, len(text) * 8)
            textH = 12

        badgeW = textW + textPadX * 2
        x0 = marginX
        y0 = marginY
        x1 = x0 + badgeW
        y1 = y0 + badgeH

        draw.rounded_rectangle(
            (x0, y0, x1, y1),
            radius=max(9, int(round(badgeH * 0.46))),
            fill=(15, 23, 42),
            outline=(129, 140, 248),
            width=1,
        )

        tx = x0 + (badgeW - textW) // 2
        ty = y0 + (badgeH - textH) // 2 - 1

        draw.text((tx + 1, ty + 1), text, fill=(0, 0, 0), font=font)
        draw.text((tx, ty), text, fill=(255, 255, 255), font=font)

    def _cacheSafeToken(self, value: str) -> str:
        raw = str(value or "").strip()
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._")
        if not safe:
            safe = "output"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
        return f"{safe}_{digest}"

    def _getProtocolOutputCachePath(self, protocolId: int, outputName: str, size: int) -> Path:
        token = self._cacheSafeToken(outputName)
        return self._getCacheDir() / (
            f"protocol_{int(protocolId)}_{token}_{int(size)}_{self.CACHE_VERSION}.png"
        )

    def _getProtocolOutputNegativeCachePath(self, protocolId: int, outputName: str, size: int) -> Path:
        return self._getProtocolOutputCachePath(protocolId=protocolId, outputName=outputName, size=size).with_suffix(".missing.json")

    def _readNegativeThumbnailCache(self, cachePath: Path) -> Optional[dict]:
        if not cachePath.is_file():
            return None

        try:
            payload = json.loads(cachePath.read_text(encoding="utf-8"))
        except Exception:
            cachePath.unlink(missing_ok=True)
            return None

        if not isinstance(payload, dict):
            cachePath.unlink(missing_ok=True)
            return None

        return payload

    def _writeNegativeThumbnailCache(self, cachePath: Path, outputClassName: Optional[str] = None, error: Optional[str] = None) -> None:
        try:
            cachePath.parent.mkdir(parents=True, exist_ok=True)
            payload = {"outputClassName": outputClassName, "error": str(error) if error else None}
            cachePath.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            logger.debug("Could not write negative thumbnail cache. cachePath=%s", cachePath, exc_info=True)

    def _clearNegativeThumbnailCache(self, cachePath: Path) -> None:
        try:
            cachePath.unlink(missing_ok=True)
        except Exception:
            logger.debug("Could not clear negative thumbnail cache. cachePath=%s", cachePath, exc_info=True)

    def buildProtocolOutputThumbnail(
            self,
            protocolId: int,
            outputName: str,
            force: bool = False,
            size: int = 320,
    ) -> Dict[str, Any]:
        try:
            protocol = self.currentProject.getProtocol(int(protocolId))
        except Exception:
            protocol = None

        if protocol is None:
            return {
                "protocolId": int(protocolId),
                "protocolLabel": f"Protocol {int(protocolId)}",
                "status": "unknown",
                "outputName": outputName,
                "outputClassName": None,
                "absolutePath": None,
                "cached": False,
                "exists": False,
            }

        cachePath = self._getProtocolOutputCachePath(protocolId=int(protocolId), outputName=outputName, size=int(size))
        negativeCachePath = self._getProtocolOutputNegativeCachePath(protocolId=int(protocolId), outputName=outputName,
                                                                     size=int(size))

        if not force and self._isValidCachedImage(cachePath):
            self._clearNegativeThumbnailCache(negativeCachePath)
            return {
                "protocolId": int(protocolId),
                "protocolLabel": self._getProtocolLabel(protocol),
                "status": self._getProtocolStatus(protocol),
                "outputName": outputName,
                "outputClassName": None,
                "absolutePath": str(cachePath),
                "cached": True,
                "exists": True,
            }

        if not force:
            negativeCache = self._readNegativeThumbnailCache(negativeCachePath)
            if negativeCache is not None:
                return {
                    "protocolId": int(protocolId),
                    "protocolLabel": self._getProtocolLabel(protocol),
                    "status": self._getProtocolStatus(protocol),
                    "outputName": outputName,
                    "outputClassName": negativeCache.get("outputClassName"),
                    "absolutePath": None,
                    "cached": True,
                    "exists": False,
                    "error": negativeCache.get("error"),
                }

        output = self._findProtocolOutput(protocol=protocol, outputName=outputName)

        if output is None:
            self._writeNegativeThumbnailCache(negativeCachePath, outputClassName=None, error="Output not found")
            return {
                "protocolId": int(
                    protocolId
                ),
                "protocolLabel": (
                    self._getProtocolLabel(
                        protocol
                    )
                ),
                "status": (
                    self._getProtocolStatus(
                        protocol
                    )
                ),
                "outputName": outputName,
                "outputClassName": None,
                "absolutePath": None,
                "cached": False,
                "exists": False,
            }

        outputClassName = self._getOutputClassName(output)
        score = self._scoreOutput(outputName, output)

        if score <= 0 and not self._looksRenderableOutput(output):
            self._writeNegativeThumbnailCache(negativeCachePath, outputClassName=outputClassName,
                                              error="Output is not renderable")
            return {
                "protocolId": int(protocolId),
                "protocolLabel": self._getProtocolLabel(protocol),
                "status": self._getProtocolStatus(protocol),
                "outputName": outputName,
                "outputClassName": outputClassName,
                "absolutePath": None,
                "cached": False,
                "exists": False,
            }

        cachePath = self._getProtocolOutputCachePath(
            protocolId=int(protocolId),
            outputName=outputName,
            size=size,
        )

        buildLock = self._getThumbnailBuildLock(cachePath)
        with buildLock:
            if not force and self._isValidCachedImage(cachePath):
                self._clearNegativeThumbnailCache(negativeCachePath)
                return {
                    "protocolId": int(protocolId),
                    "protocolLabel": self._getProtocolLabel(protocol),
                    "status": self._getProtocolStatus(protocol),
                    "outputName": outputName,
                    "outputClassName": outputClassName,
                    "absolutePath": str(cachePath),
                    "cached": True,
                    "exists": True,
                }

            previewImage: Optional[Image.Image] = None

            try:
                previewImage = self._renderProtocolPreviewImage(
                    protocol=protocol,
                    output=output,
                    outputName=outputName,
                    outputClassName=outputClassName,
                    size=size,
                )
            except Exception:
                logger.debug(
                    "Output thumbnail render failed. protocolId=%s output=%s class=%s",
                    protocolId,
                    outputName,
                    outputClassName,
                    exc_info=True,
                )

            if previewImage is None:
                try:
                    previewImage = self._renderGenericPreview(protocol, output, size=size)
                except Exception:
                    logger.debug(
                        "Generic output thumbnail render failed. protocolId=%s output=%s",
                        protocolId,
                        outputName,
                        exc_info=True,
                    )

            if previewImage is None:
                self._writeNegativeThumbnailCache(negativeCachePath, outputClassName=outputClassName,
                                                  error="Thumbnail not available")
                return {
                    "protocolId": int(protocolId),
                    "protocolLabel": self._getProtocolLabel(protocol),
                    "status": self._getProtocolStatus(protocol),
                    "outputName": outputName,
                    "outputClassName": outputClassName,
                    "absolutePath": None,
                    "cached": False,
                    "exists": False,
                }

            thumbnail = self._finalizeProtocolThumbnail(
                previewImage=previewImage,
                size=size,
                protocolId=int(protocolId),
            )
            self._saveImage(thumbnail, cachePath)
            self._clearNegativeThumbnailCache(negativeCachePath)

            return {
                "protocolId": int(protocolId),
                "protocolLabel": self._getProtocolLabel(protocol),
                "status": self._getProtocolStatus(protocol),
                "outputName": outputName,
                "outputClassName": outputClassName,
                "absolutePath": str(cachePath),
                "cached": False,
                "exists": True,
            }

    # ------------------------------------------------------------------
    # Candidate selection
    # ------------------------------------------------------------------
    def _iterProtocols(self) -> List[Any]:
        graph = self.currentProject.getRunsGraph(refresh=False, checkPids=False)
        nodesDict = getattr(graph, "_nodesDict", {}) or {}

        protocols: List[Any] = []
        seen = set()

        for nodeId, nodeObj in nodesDict.items():
            if str(nodeId) == "PROJECT":
                continue

            protocol = getattr(nodeObj, "run", None)
            if protocol is None:
                try:
                    protocol = self.currentProject.getProtocol(int(nodeId))
                except Exception:
                    protocol = None

            if protocol is None or not hasattr(protocol, "getObjId"):
                continue

            protocolDbId = int(protocol.getObjId())
            if protocolDbId in seen:
                continue

            seen.add(protocolDbId)
            protocols.append(protocol)

        protocols.sort(
            key=lambda protocol: (
                self._scoreProtocolStatus(protocol),
                int(protocol.getObjId()),
            ),
            reverse=True,
        )
        return protocols

    def _selectBestOutput(self, protocol) -> Optional[Dict[str, Any]]:
        best = None

        for outputName, output in self._iterOutputAttributes(protocol):
            score = self._scoreOutput(outputName, output)
            if score <= 0:
                continue

            candidate = {
                "outputName": outputName,
                "output": output,
                "outputClassName": self._getOutputClassName(output),
                "score": score,
            }
            if best is None or candidate["score"] > best["score"]:
                best = candidate

        return best

    def _collectSortedOutputCandidates(self, protocol) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []

        for outputName, output in self._iterOutputAttributes(protocol):
            try:
                score = self._scoreOutput(outputName, output)
                if score <= 0:
                    continue

                candidates.append(
                    {
                        "outputName": outputName,
                        "output": output,
                        "outputClassName": self._getOutputClassName(output),
                        "score": int(score),
                        "itemsCount": self._safeOutputSize(output) or 0,
                    }
                )
            except Exception:
                logger.debug(
                    "Skipping output candidate while collecting thumbnails. protocolId=%s output=%s",
                    getattr(protocol, "getObjId", lambda: "unknown")(),
                    outputName,
                    exc_info=True,
                )

        candidates.sort(
            key=lambda item: (
                int(item.get("score", 0)),
                int(item.get("itemsCount", 0)),
            ),
            reverse=True,
        )
        return candidates

    def _iterOutputAttributes(
            self,
            protocol,
    ) -> Iterable[Tuple[str, Any]]:
        seenOutputNames = set()

        try:
            for outputName, output in (
                    protocol
                            .iterOutputAttributes()
            ):
                if output is None:
                    continue

                outputName = str(
                    outputName
                )

                seenOutputNames.add(
                    outputName
                )

                yield outputName, output

        except Exception:
            logger.debug(
                "Could not iterate native protocol "
                "outputs while building thumbnail. "
                "protocolId=%s",
                getattr(
                    protocol,
                    "getObjId",
                    lambda: None,
                )(),
                exc_info=True,
            )

        for outputName, output in (
                self
                        ._iterPostgresqlOutputAttributes(
                    protocol
                )
        ):
            outputName = str(
                outputName
            )

            if outputName in (
                    seenOutputNames
            ):
                continue

            seenOutputNames.add(
                outputName
            )

            yield outputName, output

    def _scoreProtocolStatus(self, protocol) -> int:
        status = self._getProtocolStatus(protocol).lower()
        if any(token in status for token in ("finished", "done", "complete", "success")):
            return 120
        if any(token in status for token in ("running", "launched", "active", "progress")):
            return 70
        if any(token in status for token in ("scheduled", "waiting", "queued")):
            return 40
        if any(token in status for token in ("saved", "new")):
            return 20
        if any(token in status for token in ("failed", "error", "aborted", "stopped")):
            return -200
        return 10

    def _scoreOutput(self, outputName: str, output: Any) -> int:
        name = (outputName or "").strip().lower()
        className = self._getOutputClassName(output).lower()

        if any(token in name for token in ("discard", "tmp", "temp", "aux", "debug")):
            return 0

        sizeHint = self._safeOutputSize(output)
        if sizeHint is not None and sizeHint <= 0:
            return 0

        if "setofmicrograph" in className or "micrograph" in className:
            score = 175
        elif "setofmovies" in className or ("movie" in className and "particle" not in className):
            score = 174
        elif "classessubtomogram" in className or "classsubtomogram" in className:
            score = 176
        elif "averagesubtomogram" in className or "subtomogram" in className:
            score = 170
        elif "class2d" in className or "average" in className:
            score = 182
        elif (
                "setofclassesstructflex" in className
                or "classstructflex" in className
                or "setofatomstructflex" in className
                or "atomstructflex" in className
        ):
            score = 119
        elif (
                "setofclassesflex" in className
                or className == "classflex"
                or "setofvolumesflex" in className
                or "volumeflex" in className
        ):
            score = 166
        elif "setofparticlesflex" in className or "particleflex" in className:
            score = 168
        elif "class3d" in className:
            score = 176
        elif (
                "volumemask" in className
                or className == "mask"
                or "setofmask" in className
        ):
            score = 145
        elif "setofparticle" in className or "particle" in className:
            score = 168
        elif "ctftomo" in className or "setofctftomo" in className:
            score = 156
        elif (
                "setofctf" in className
                or "ctfmodel" in className
                or (className == "ctf")
        ):
            score = 154
        elif "setofdefocusgroup" in className or "defocusgroup" in className:
            score = 146
        elif "setoftomomask" in className or "tomomask" in className:
            score = 162
        elif "setofvolume" in className or "volume" in className:
            score = 164
        elif "tomogram" in className:
            score = 164
        elif "landmark" in className:
            score = 124
        elif "setoftiltseriescoordinate" in className or "tiltseriescoordinate" in className:
            score = 129
        elif "setoftiltseriesm" in className or "tiltseriesm" in className:
            score = 148
        elif "setoftiltseries" in className or "tiltseries" in className:
            score = 150
        elif "setofmeshes" in className or "mesh" in className:
            score = 127
        elif "coordinate3d" in className or "coordinates3d" in className or "setofcoordinates3d" in className:
            score = 128
        elif "setofcoordinate" in className or "coordinate" in className:
            score = 126
        elif (
                "setofatomstruct" in className
                or "atomstruct" in className
                or "setofpdb" in className
                or className == "pdbfile"
                or className == "pdb"
        ):
            score = 118
        elif (
                "setofsequence" in className
                or className == "sequence"
                or "sequence" in className
        ):
            score = 116

        elif (
                "setofnormalmode" in className
                or "normalmode" in className
                or "setofprincipalcomponent" in className
                or "principalcomponent" in className
        ):
            score = 114

        elif "fsc" in className:
            score = 112
        elif self._looksRenderableOutput(output):
            score = 70
        else:
            score = 0

        if (
                "mask" in className
                and "tomomask" not in className
                and "volumemask" not in className
                and className != "mask"
                and "setofmask" not in className
        ):
            score -= 35

        if name.startswith("output"):
            score += 10

        if sizeHint is not None:
            score += min(int(sizeHint), 8)

        return max(score, 0)

    def listProtocolThumbnailItems(
            self,
            projectId: int,
            force: bool = False,
            size: int = 320,
            maxProtocols: int = 12,
            maxOutputsPerProtocol: int = 4,
            inlineImages: bool = False,
    ) -> List[Dict[str, Any]]:
        groups: List[Dict[str, Any]] = []

        for protocol in self._iterProtocols():
            if len(groups) >= max(1, int(maxProtocols)):
                break

            try:
                protocolId = int(protocol.getObjId())
            except Exception:
                continue

            candidates = self._collectSortedOutputCandidates(protocol)
            if not candidates:
                continue

            outputs: List[Dict[str, Any]] = []

            for candidate in candidates:
                if len(outputs) >= max(1, int(maxOutputsPerProtocol)):
                    break

                outputName = candidate.get("outputName")
                outputClassName = candidate.get("outputClassName")

                if not outputName:
                    continue

                try:
                    built = self.buildProtocolOutputThumbnail(
                        protocolId=protocolId,
                        outputName=outputName,
                        force=force,
                        size=size,
                    )
                except Exception:
                    logger.debug(
                        "Failed building protocol output thumbnail. protocolId=%s outputName=%s",
                        protocolId,
                        outputName,
                        exc_info=True,
                    )
                    continue

                if not built.get("exists") or not built.get("absolutePath"):
                    continue

                thumbnailDataUrl = None

                if inlineImages:
                    try:
                        thumbPath = Path(str(built["absolutePath"]))
                        if thumbPath.exists() and thumbPath.stat().st_size > 0:
                            with thumbPath.open("rb") as fh:
                                encoded = base64.b64encode(fh.read()).decode("ascii")
                            thumbnailDataUrl = f"data:image/png;base64,{encoded}"
                    except Exception:
                        logger.debug(
                            "Could not inline thumbnail image. protocolId=%s outputName=%s",
                            protocolId,
                            outputName,
                            exc_info=True,
                        )

                outputs.append(
                    {
                        "outputName": outputName,
                        "outputClassName": outputClassName,
                        "exists": True,
                        "thumbnailUrl": (
                            f"/projects/{int(projectId)}/protocols/{protocolId}/outputs/{quote(str(outputName), safe='')}/thumbnail"
                        ),
                        "thumbnailDataUrl": thumbnailDataUrl,
                        "thumbnailRebuildUrl": None,
                    }
                )

            if not outputs:
                continue

            groups.append(
                {
                    "protocolId": protocolId,
                    "label": self._getProtocolLabel(protocol),
                    "status": self._getProtocolStatus(protocol),
                    "outputs": outputs,
                }
            )

        return groups

    # ------------------------------------------------------------------
    # Typed renderers
    # ------------------------------------------------------------------
    def _renderProtocolPreviewImage(
        self,
        protocol,
        output,
        outputName: str,
        outputClassName: str,
        size: int,
    ) -> Optional[Image.Image]:
        try:
            if isinstance(output, SetOfMicrographs):
                return self._renderMicrographsPreview(protocol, output, size=size)
            if isinstance(output, SetOfMovies):
                return self._renderMoviesPreview(protocol, output, size=size)
            if isinstance(output, SetOfCTF):
                return self._renderCtfPreview(protocol, output, size=size)
            if isinstance(output, SetOfDefocusGroup):
                return self._renderDefocusGroupPreview(output, size=size)
            if isinstance(output, (Mask, VolumeMask)):
                return self._renderMaskPreview(protocol, output, size=size)
            if isinstance(output, (SetOfParticles, SetOfClasses2D)):
                return self._renderParticlesOrClasses2dPreview(protocol, output, size=size)
            if isinstance(output, SetOfCoordinates):
                return self._renderCoordinates2dPreview(protocol, output, size=size)
            if isinstance(output, SetOfTomoMasks):
                return self._renderTomoMasksPreview(protocol, output, size=size)
            if isinstance(output, (SetOfClasses3D, SetOfVolumes)):
                return self._renderClasses3dOrVolumesPreview(protocol, output, size=size)
            if isinstance(output, SetOfTiltSeriesM):
                return self._renderTiltSeriesMPreview(protocol, output, size=size)
            if isinstance(output, SetOfTiltSeries):
                return self._renderTiltSeriesPreview(protocol, output, size=size)
            if isinstance(output, SetOfMeshes):
                return self._renderMeshesPreview(protocol, output, size=size)
            if isinstance(output, SetOfTiltSeriesCoordinates):
                return self._renderTiltSeriesCoordinatesPreview(protocol, output, size=size)
            if isinstance(output, SetOfLandmarkModels):
                return self._renderLandmarkModelsPreview(protocol, output, size=size)
            if isinstance(output, (SetOfAtomStructs, SetOfPDBs, AtomStruct, PdbFile)):
                return self._renderAtomStructPreview(protocol, output, size=size)
            if isinstance(output, SetOfSequences):
                return self._renderSequencesPreview(protocol, output, size=size)
            if isinstance(output, (SetOfNormalModes, SetOfPrincipalComponents, NormalMode)):
                return self._renderNormalModesPreview(protocol, output, size=size)
            if isinstance(output, SetOfFSCs):
                return self._renderFscPreview(output, size=size)
        except Exception:
            logger.debug(
                "Typed isinstance renderer failed. protocolId=%s output=%s class=%s",
                getattr(protocol, "getObjId", lambda: "unknown")(),
                outputName,
                outputClassName,
                exc_info=True,
            )

        className = (outputClassName or "").lower()
        try:
            if "landmark" in className:
                image = self._renderLandmarkModelsPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "setoftiltseriescoordinate" in className or "tiltseriescoordinate" in className:
                image = self._renderTiltSeriesCoordinatesPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "setofmeshes" in className or "mesh" in className:
                image = self._renderMeshesPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "flex" in className:
                image = self._renderFlexPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "coordinate3d" in className or "coordinates3d" in className or "setofcoordinates3d" in className:
                image = self._renderCoordinates3dPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if (
                    ("setofcoordinate" in className or "coordinate" in className)
                    and "coordinate3d" not in className
                    and "coordinates3d" not in className
                    and "setofcoordinates3d" not in className
            ):
                image = self._renderCoordinates2dPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "setofctftomo" in className or "ctftomo" in className:
                image = self._renderCtftomoPreview(protocol, output, size=size)
                if image is not None:
                    return image
            if (
                    "setofctf" in className
                    or "ctfmodel" in className
                    or className == "ctf"
            ):
                image = self._renderCtfPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "setofdefocusgroup" in className or "defocusgroup" in className:
                image = self._renderDefocusGroupPreview(output, size=size)
                if image is not None:
                    return image

            if "subtomogram" in className:
                image = self._renderSubTomogramsPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "setoftomomask" in className or "tomomask" in className:
                image = self._renderTomoMasksPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if (
                    "volumemask" in className
                    or className == "mask"
                    or "setofmask" in className
            ):
                image = self._renderMaskPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "tomogram" in className or "volume" in className or "class3d" in className:
                image = self._renderVolumeLikePreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "setoftiltseriesm" in className or "tiltseriesm" in className:
                image = self._renderTiltSeriesMPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "tiltseries" in className:
                image = self._renderTiltSeriesPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "setofmovies" in className or ("movie" in className and "particle" not in className):
                image = self._renderMoviesPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "micrograph" in className:
                image = self._renderMicrographsPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "particle" in className or "class2d" in className or "average" in className:
                image = self._renderParticlesOrClasses2dPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if (
                    "setofatomstruct" in className
                    or "atomstruct" in className
                    or "setofpdb" in className
                    or className == "pdbfile"
                    or className == "pdb"
            ):
                image = self._renderAtomStructPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if (
                    "setofsequence" in className
                    or className == "sequence"
                    or "sequence" in className
            ):
                image = self._renderSequencesPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if (
                    "setofnormalmode" in className
                    or "normalmode" in className
                    or "setofprincipalcomponent" in className
                    or "principalcomponent" in className
            ):
                image = self._renderNormalModesPreview(protocol, output, size=size)
                if image is not None:
                    return image

            if "fsc" in className:
                image = self._renderFscPreview(output, size=size)
                if image is not None:
                    return image

        except Exception:
            logger.debug(
                "Typed string renderer failed. protocolId=%s output=%s class=%s",
                getattr(protocol, "getObjId", lambda: "unknown")(),
                outputName,
                outputClassName,
                exc_info=True,
            )

        try:
            image = self._renderGenericPreview(protocol, output, size=size)
            if image is not None:
                return image
        except Exception:
            logger.debug(
                "Generic thumbnail renderer failed. protocolId=%s output=%s class=%s",
                getattr(protocol, "getObjId", lambda: "unknown")(),
                outputName,
                outputClassName,
                exc_info=True,
            )

        return None

    def _renderMoviesPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []
        maxItems = 4

        if isinstance(output, SetOfMovies):
            movieIterator = self._iterItemsDirect(output)
        else:
            movieIterator = iter([output])

        for movie in movieIterator:
            try:
                tile = self._renderMovieItemPreview(protocol, movie)
                if tile is not None:
                    tiles.append(tile)

                if len(tiles) >= maxItems:
                    break
            except Exception:
                logger.debug("Movie preview failed", exc_info=True)

        if not tiles:
            return None

        return self._composeCleanGrid(
            tiles=tiles[:maxItems],
            maxCols=2,
            targetWidth=size,
            background=(246, 249, 252),
        )

    def _renderMovieItemPreview(self, protocol, movie) -> Optional[Image.Image]:
        sources: List[Tuple[str, Optional[int]]] = []
        seen = set()

        for getterName in ("getFileName", "getLocation", "getOdd", "getEven"):
            getter = getattr(movie, getterName, None)
            if not callable(getter):
                continue

            try:
                sourcePath, sourceIndex = self._splitIndexedImagePath(getter())
                if sourcePath:
                    key = (sourcePath, sourceIndex)
                    if key not in seen:
                        seen.add(key)
                        sources.append((sourcePath, sourceIndex))
            except Exception:
                continue

        try:
            sourcePath, sourceIndex = self._resolveImageSourceFromItem(movie)
            if sourcePath:
                key = (sourcePath, sourceIndex)
                if key not in seen:
                    seen.add(key)
                    sources.append((sourcePath, sourceIndex))
        except Exception:
            pass

        for sourcePath, sourceIndex in sources:
            try:
                image = self._readMoviePreviewFromPath(
                    protocol=protocol,
                    filePath=sourcePath,
                    index=sourceIndex,
                    movie=movie,
                )
                if image is not None:
                    return image
            except Exception:
                continue

        for sourcePath, sourceIndex in sources:
            try:
                image = self._readImagePreview(protocol, sourcePath, sourceIndex)
                if image is not None:
                    return image
            except Exception:
                continue

        return None

    def _renderMicrographsPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []
        objectManager = self._createPreviewObjectManager(protocol, output)

        sampleCount = 3

        if objectManager is not None:
            try:
                table = objectManager.getTable("objects")
                if table is not None:
                    columns = table.getColumns()
                    cfg = RegistryViewerConfig.getConfig(type(output)) or {}
                    renderRaw = cfg.get(RENDER, "")
                    renderTokens = (
                        [token for token in re.split(r"[,\s]+", renderRaw) if token]
                        if isinstance(renderRaw, str)
                        else []
                    )
                    renderTokens += ["_filename", "micrograph", "micName", "file", "path", "stack"]
                    renderIdx = self._getRenderColumnIndex(renderTokens, columns)
                    rows = self._pickSampleRows(objectManager, "objects", want=sampleCount)

                    for row in rows:
                        relPath, sliceIndex = self._extractPathFromRow(row, renderIdx)
                        if not relPath:
                            continue

                        filePath = self._resolveFilePath(protocol, relPath)
                        if filePath is None or not filePath.exists():
                            continue

                        gray = self._read2dTile(
                            filePath=filePath,
                            sliceIndex=sliceIndex,
                            preferCentral=False,
                            thumbSize=maxThumbSize,
                        )
                        if gray is None:
                            continue

                        tile = self._grayTileToImage(gray)
                        if tile is not None:
                            tiles.append(tile)
            except Exception:
                logger.debug("Metadata micrograph preview failed", exc_info=True)

        if not tiles:
            for item in self._iterPreviewItems(output, maxItems=sampleCount):
                sourcePath, sourceIndex = self._resolveImageSourceFromItem(item)
                if not sourcePath:
                    continue
                tile = self._readImagePreview(protocol, sourcePath, sourceIndex)
                if tile is not None:
                    tiles.append(tile)

        if not tiles:
            return None

        return self._composeMicrographStrip(tiles[:3], targetWidth=size)

    def _renderParticlesOrClasses2dPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []
        objectManager = self._createPreviewObjectManager(protocol, output)

        sampleCount = 4 if isinstance(output, SetOfClasses2D) else 6
        maxCols = 2 if isinstance(output, SetOfClasses2D) else 3

        if objectManager is not None:
            try:
                table = objectManager.getTable("objects")
                if table is not None:
                    columns = table.getColumns()
                    cfg = RegistryViewerConfig.getConfig(type(output)) or {}
                    renderRaw = cfg.get(RENDER, "")
                    renderTokens = (
                        [token for token in re.split(r"[,\s]+", renderRaw) if token]
                        if isinstance(renderRaw, str)
                        else []
                    )
                    renderTokens += ["stack", "_filename", "file", "path"]
                    renderIdx = self._getRenderColumnIndex(renderTokens, columns)
                    rows = self._pickSampleRows(objectManager, "objects", want=sampleCount)

                    for row in rows:
                        relPath, sliceIndex = self._extractPathFromRow(row, renderIdx)
                        if not relPath:
                            continue

                        stackPath = self._resolveFilePath(protocol, relPath)
                        if stackPath is None or not stackPath.exists():
                            continue

                        gray = self._read2dTile(
                            filePath=stackPath,
                            sliceIndex=sliceIndex,
                            preferCentral=False,
                            thumbSize=maxThumbSize,
                        )
                        if gray is None:
                            continue

                        tile = self._grayTileToImage(gray)
                        if tile is not None:
                            tiles.append(tile)
            except Exception:
                logger.debug("Metadata particle/class2d preview failed", exc_info=True)

        if not tiles:
            for item in self._iterPreviewItems(output, maxItems=sampleCount):
                sourcePath, sourceIndex = self._resolveImageSourceFromItem(item)
                if not sourcePath:
                    continue

                tile = self._readImagePreview(protocol, sourcePath, sourceIndex)
                if tile is not None:
                    tiles.append(tile)

        if not tiles:
            return None

        return self._composeParticleMosaic(tiles, targetWidth=size, maxCols=maxCols)

    def _renderClasses3dOrVolumesPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []
        cmapName = self._volumeColormapName()
        objectManager = self._createPreviewObjectManager(protocol, output)

        if objectManager is not None:
            try:
                table = objectManager.getTable("objects")
                if table is not None:
                    columns = table.getColumns()
                    renderIdx = self._getRenderColumnIndex(["stack", "_filename", "file", "path"], columns)
                    rows = self._pickSampleRows(objectManager, "objects", want=3)

                    for row in rows:
                        relPath, sliceIndex = self._extractPathFromRow(row, renderIdx)
                        if not relPath:
                            continue

                        filePath = self._resolveFilePath(protocol, relPath)
                        if filePath is None or not filePath.exists():
                            continue

                        gray = self._read2dTile(
                            filePath=filePath,
                            sliceIndex=sliceIndex,
                            preferCentral=True,
                            thumbSize=maxThumbSize,
                        )
                        if gray is None:
                            continue

                        tile = self._rgbTileToImage(self._applyColormap(gray, cmapName=cmapName))
                        if tile is not None:
                            tiles.append(tile)
            except Exception:
                logger.debug("Metadata class3d/volume preview failed", exc_info=True)

        if not tiles:
            volumePaths = self._collectDirectVolumePaths(protocol, output, maxItems=2)
            for volumePath in volumePaths:
                tile = self._renderVolumeFromPath(volumePath, size=size)
                if tile is not None:
                    tiles.append(tile)

        if not tiles:
            return None

        return self._composeCleanStrip(tiles, targetHeight=max(190, int(round(size * 0.40))))

    def _renderTiltSeriesMPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []

        if isinstance(output, SetOfTiltSeriesM):
            seriesIterator = self._iterItemsDirect(output)
        else:
            seriesIterator = iter([output])

        for tiltSeries in seriesIterator:
            try:
                tile = self._renderTiltSeriesMMoviePreview(protocol, tiltSeries)
                if tile is not None:
                    tiles.append(tile)
            except Exception:
                logger.debug("TiltSeriesM movie preview failed", exc_info=True)

            if len(tiles) >= 4:
                break

        if not tiles:
            return None

        return self._composeTiltSeriesStrip(tiles[:4], targetWidth=size)

    def _renderTiltSeriesMMoviePreview(self, protocol, tiltSeries) -> Optional[Image.Image]:
        checkedMovies = 0

        for tiltMovie in self._iterItemsDirect(tiltSeries):
            checkedMovies += 1

            try:
                if not self._isEnabled(tiltMovie):
                    if checkedMovies >= 12:
                        break
                    continue
            except Exception:
                pass

            tile = self._renderTiltMovieImagePreview(protocol, tiltMovie)
            if tile is not None:
                return tile

            if checkedMovies >= 12:
                break

        return None

    def _renderTiltMovieImagePreview(self, protocol, tiltMovie) -> Optional[Image.Image]:
        sources: List[Tuple[str, Optional[int]]] = []

        for getterName in ("getOdd", "getEven", "getFileName", "getLocation"):
            getter = getattr(tiltMovie, getterName, None)
            if not callable(getter):
                continue

            try:
                sourcePath, sourceIndex = self._splitIndexedImagePath(getter())
                if sourcePath:
                    sources.append((sourcePath, sourceIndex))
            except Exception:
                continue

        seen = set()

        for sourcePath, sourceIndex in sources:
            key = (sourcePath, sourceIndex)
            if key in seen:
                continue
            seen.add(key)

            image = self._readMoviePreviewFromPath(
                protocol=protocol,
                filePath=sourcePath,
                index=sourceIndex,
                movie=tiltMovie,
            )
            if image is not None:
                return image

        return None

    def _renderTiltSeriesPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []
        seriesList: List[Any]

        if isinstance(output, (SetOfTiltSeries, SetOfTiltSeriesM)):
            seriesList = list(self._iterPreviewItems(output, maxItems=4))
        else:
            seriesList = [output]

        for tiltSeries in seriesList:
            try:
                getFileNameFn = getattr(tiltSeries, "getFileName", None)
                if callable(getFileNameFn):
                    stackPath = self._resolveFilePath(protocol, getFileNameFn())
                    if stackPath is not None and stackPath.exists():
                        gray = self._read2dTile(
                            filePath=stackPath,
                            sliceIndex=None,
                            preferCentral=True,
                            thumbSize=maxThumbSize,
                        )
                        if gray is not None:
                            tile = self._grayTileToImage(gray)
                            if tile is not None:
                                tiles.append(tile)
                                continue
            except Exception:
                logger.debug("Direct tilt-series stack preview failed", exc_info=True)

            try:
                checkedFrames = 0

                for frame in self._iterItemsDirect(tiltSeries):
                    checkedFrames += 1

                    sourcePath, sourceIndex = self._resolveImageSourceFromItem(frame)
                    if not sourcePath:
                        if checkedFrames >= 8:
                            break
                        continue

                    resolvedPath = self._resolveFilePath(protocol, sourcePath)
                    if resolvedPath is None or not resolvedPath.exists():
                        if checkedFrames >= 8:
                            break
                        continue

                    gray = self._read2dTile(
                        filePath=resolvedPath,
                        sliceIndex=None,
                        preferCentral=True,
                        thumbSize=maxThumbSize,
                    )

                    if gray is None:
                        tile = self._readImagePreview(protocol, sourcePath, sourceIndex)
                    else:
                        tile = self._grayTileToImage(gray)

                    if tile is not None:
                        tiles.append(tile)
                        break

                    if checkedFrames >= 8:
                        break

            except Exception:
                logger.debug("Tilt-series frame preview failed", exc_info=True)

        if not tiles:
            objectManager = self._createPreviewObjectManager(protocol, output)
            if objectManager is not None:
                try:
                    tables = objectManager.getTables() or {}
                    for name in tables.keys():
                        if "_Object" not in name or len(tiles) >= 4:
                            continue

                        table = objectManager.getTable(name)
                        if table is None:
                            continue

                        columns = table.getColumns()
                        renderIdx = self._getRenderColumnIndex(["stack", "_filename", "file", "path"], columns)
                        rows = objectManager.getRows(name, 0, 1) or []
                        if not rows:
                            continue

                        relPath, sliceIndex = self._extractPathFromRow(rows[0], renderIdx)
                        if not relPath:
                            continue

                        filePath = self._resolveFilePath(protocol, relPath)
                        if filePath is None or not filePath.exists():
                            continue

                        gray = self._read2dTile(
                            filePath=filePath,
                            sliceIndex=sliceIndex,
                            preferCentral=True,
                            thumbSize=maxThumbSize,
                        )
                        if gray is None:
                            continue

                        tile = self._grayTileToImage(gray)
                        if tile is not None:
                            tiles.append(tile)
                except Exception:
                    logger.debug("Metadata tilt-series preview failed", exc_info=True)

        if not tiles:
            return None

        return self._composeTiltSeriesStrip(tiles[:4], targetWidth=size)

    def _safeScalarValue(self, value: Any) -> Any:
        if hasattr(value, "get"):
            try:
                return value.get()
            except Exception:
                pass
        return value

    def _renderDefocusGroupPreview(self, output, size: int) -> Optional[Image.Image]:
        groups: List[Any] = []

        for group in self._iterItemsDirect(output):
            try:
                if not self._isEnabled(group):
                    continue

                groups.append(group)

                if len(groups) >= 80:
                    break
            except Exception:
                continue

        if not groups:
            return None

        return self._buildDefocusGroupPreviewImage(
            groups=groups,
            size=size,
        )

    def _buildDefocusGroupPreviewImage(
            self,
            groups: Sequence[Any],
            size: int,
    ) -> Optional[Image.Image]:
        fig = None

        try:
            data: List[Tuple[int, float, float, float, int]] = []

            for index, group in enumerate(groups):
                try:
                    defocusMin = self._safeScalarValue(
                        getattr(group, "getDefocusMin", lambda: None)()
                    )
                    defocusMax = self._safeScalarValue(
                        getattr(group, "getDefocusMax", lambda: None)()
                    )
                    defocusAvg = self._safeScalarValue(
                        getattr(group, "getDefocusAvg", lambda: None)()
                    )
                    groupSize = self._safeScalarValue(
                        getattr(group, "getSize", lambda: 0)()
                    )

                    if defocusMin is None or defocusMax is None:
                        continue

                    minValue = float(defocusMin)
                    maxValue = float(defocusMax)

                    if defocusAvg is None:
                        avgValue = (minValue + maxValue) * 0.5
                    else:
                        avgValue = float(defocusAvg)

                    sizeValue = int(groupSize or 0)

                    if not (
                            np.isfinite(minValue)
                            and np.isfinite(maxValue)
                            and np.isfinite(avgValue)
                    ):
                        continue

                    if maxValue < minValue:
                        minValue, maxValue = maxValue, minValue

                    data.append(
                        (
                            index + 1,
                            minValue,
                            maxValue,
                            avgValue,
                            sizeValue,
                        )
                    )
                except Exception:
                    continue

            if not data:
                return None

            data.sort(key=lambda item: item[3])

            yValues = list(range(1, len(data) + 1))
            minValues = [item[1] for item in data]
            maxValues = [item[2] for item in data]
            avgValues = [item[3] for item in data]
            sizeValues = [item[4] for item in data]

            fig = plt.figure(figsize=(5.4, 3.35), dpi=130)
            ax = fig.add_subplot(111)

            ax.set_facecolor("white")
            ax.grid(True, axis="x", linestyle="-", linewidth=0.55, alpha=0.35)
            ax.set_title("Defocus groups", fontsize=11, pad=6)
            ax.set_xlabel("Defocus (Å)", fontsize=9)
            ax.set_ylabel("Group", fontsize=9)
            ax.tick_params(axis="both", labelsize=8)

            for yValue, minValue, maxValue, avgValue, sizeValue in zip(
                    yValues,
                    minValues,
                    maxValues,
                    avgValues,
                    sizeValues,
            ):
                ax.plot(
                    [minValue, maxValue],
                    [yValue, yValue],
                    linewidth=4.0,
                    solid_capstyle="round",
                    color="tab:blue",
                    alpha=0.78,
                )
                ax.scatter(
                    [avgValue],
                    [yValue],
                    marker="o",
                    s=38,
                    color="tab:red",
                    zorder=4,
                )

                if sizeValue > 0:
                    ax.text(
                        maxValue,
                        yValue,
                        f"  n={sizeValue}",
                        va="center",
                        ha="left",
                        fontsize=7.5,
                        color="#334155",
                    )

            ax.set_yticks(yValues)
            ax.set_yticklabels([str(i) for i in yValues])

            xMin = min(minValues)
            xMax = max(maxValues)
            if xMax > xMin:
                xPad = max(1.0, (xMax - xMin) * 0.12)
                ax.set_xlim(xMin - xPad, xMax + xPad)

            ax.set_ylim(0.4, len(data) + 0.6)

            subtitle = f"{len(data)} groups"
            ax.text(
                0.99,
                0.02,
                subtitle,
                transform=ax.transAxes,
                ha="right",
                va="bottom",
                fontsize=8,
                color="#334155",
                bbox={
                    "boxstyle": "round,pad=0.25",
                    "facecolor": "white",
                    "edgecolor": "#cbd5e1",
                    "alpha": 0.85,
                },
            )

            fig.subplots_adjust(
                left=0.12,
                right=0.86,
                top=0.86,
                bottom=0.18,
            )

            buffer = io.BytesIO()
            fig.savefig(
                buffer,
                format="png",
                facecolor="white",
                edgecolor="white",
                dpi=130,
            )
            buffer.seek(0)

            return Image.open(buffer).convert("RGB")

        except Exception:
            logger.debug("Defocus group thumbnail failed", exc_info=True)
            return None
        finally:
            if fig is not None:
                plt.close(fig)

    def _renderCtfPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []
        ctfItems: List[Any] = []
        maxItems = 4

        if isinstance(output, SetOfCTF):
            ctfIterator = self._iterItemsDirect(output, orderBy="id")
        else:
            ctfIterator = iter([output])

        for ctfModel in ctfIterator:
            try:
                ctfItems.append(ctfModel)

                tile = self._renderCtfPsdPreviewFromItem(
                    protocol=protocol,
                    ctfModel=ctfModel,
                )
                if tile is not None:
                    tiles.append(tile)

                if len(tiles) >= maxItems:
                    break

                if len(ctfItems) >= 80 and tiles:
                    break

            except Exception:
                logger.debug("CTF item preview failed", exc_info=True)

        if tiles:
            return self._composeCleanGrid(
                tiles=tiles[:maxItems],
                maxCols=2,
                targetWidth=size,
                background=(246, 249, 252),
            )

        if ctfItems:
            image = self._buildCtfDefocusPreviewImage(
                ctfItems=ctfItems,
                size=size,
            )
            if image is not None:
                return image

        return None

    def _renderCtfPsdPreviewFromItem(
            self,
            protocol,
            ctfModel,
    ) -> Optional[Image.Image]:
        getPsdFileFn = getattr(ctfModel, "getPsdFile", None)
        if not callable(getPsdFileFn):
            return None

        try:
            psdFile = getPsdFileFn()
        except Exception:
            return None

        sourcePath, sourceIndex = self._splitIndexedImagePath(psdFile)
        if not sourcePath:
            return None

        psdPath = self._resolveFilePath(protocol, sourcePath)
        if psdPath is None or not psdPath.exists():
            return None

        try:
            gray = self._read2dTile(
                filePath=psdPath,
                sliceIndex=sourceIndex,
                preferCentral=False,
                thumbSize=maxThumbSize,
            )
            if gray is not None:
                image = self._grayTileToImage(gray)
                if image is not None:
                    return self._drawSimplePreviewLabel(
                        image=image,
                        label="PSD",
                    )
        except Exception:
            pass

        try:
            image = self._readImagePreview(protocol, sourcePath, sourceIndex)
            if image is not None:
                return self._drawSimplePreviewLabel(
                    image=image,
                    label="PSD",
                )
        except Exception:
            pass

        return None

    def _buildCtfDefocusPreviewImage(
            self,
            ctfItems: Sequence[Any],
            size: int,
    ) -> Optional[Image.Image]:
        fig = None

        try:
            data: List[Tuple[float, float, float, float, float]] = []

            for index, ctfModel in enumerate(ctfItems):
                try:
                    defocusU = self._safeScalarValue(
                        getattr(ctfModel, "getDefocusU", lambda: None)()
                    )
                    defocusV = self._safeScalarValue(
                        getattr(ctfModel, "getDefocusV", lambda: None)()
                    )
                    resolution = self._safeScalarValue(
                        getattr(ctfModel, "getResolution", lambda: 0)()
                    )
                    fitQuality = self._safeScalarValue(
                        getattr(ctfModel, "getFitQuality", lambda: 0)()
                    )

                    if defocusU is None or defocusV is None:
                        continue

                    xValue = float(index + 1)
                    defocusUValue = float(defocusU)
                    defocusVValue = float(defocusV)
                    resolutionValue = float(resolution or 0)
                    fitQualityValue = float(fitQuality or 0)

                    if not (
                            np.isfinite(defocusUValue)
                            and np.isfinite(defocusVValue)
                    ):
                        continue

                    data.append(
                        (
                            xValue,
                            defocusUValue,
                            defocusVValue,
                            resolutionValue,
                            fitQualityValue,
                        )
                    )

                except Exception:
                    continue

            if not data:
                return None

            xValues = [item[0] for item in data]
            defocusUValues = [item[1] for item in data]
            defocusVValues = [item[2] for item in data]
            resolutionValues = [item[3] for item in data]
            fitQualityValues = [item[4] for item in data]

            fig = plt.figure(figsize=(5.4, 3.35), dpi=130)
            defocusPlot = fig.add_subplot(111)

            defocusPlot.set_facecolor("white")
            defocusPlot.grid(True, linestyle="-", linewidth=0.55, alpha=0.35)

            defocusPlot.set_title("CTF", fontsize=11, pad=6)
            defocusPlot.set_xlabel("Micrograph / CTF index", fontsize=9)
            defocusPlot.set_ylabel("Defocus (Å)", fontsize=9)
            defocusPlot.tick_params(axis="both", labelsize=8)

            lineU, = defocusPlot.plot(
                xValues,
                defocusUValues,
                marker="o",
                markersize=5.2,
                linewidth=2.8,
                color="tab:red",
                label="DefocusU (Å)",
                zorder=4,
            )
            lineV, = defocusPlot.plot(
                xValues,
                defocusVValues,
                marker="o",
                markersize=5.2,
                linewidth=2.8,
                color="tab:blue",
                label="DefocusV (Å)",
                zorder=5,
            )

            yValues = defocusUValues + defocusVValues
            yMin = min(yValues)
            yMax = max(yValues)
            yPad = max(1.0, (yMax - yMin) * 0.12)
            defocusPlot.set_ylim(yMin - yPad, yMax + yPad)

            xMin = min(xValues)
            xMax = max(xValues)
            if xMax > xMin:
                xPad = max(0.5, (xMax - xMin) * 0.04)
                defocusPlot.set_xlim(xMin - xPad, xMax + xPad)

            legendHandles = [lineU, lineV]

            hasResolution = any(value > 0 for value in resolutionValues)
            hasFitQuality = any(value > 0 for value in fitQualityValues)

            if hasResolution or hasFitQuality:
                secondPlot = defocusPlot.twinx()

                if hasResolution:
                    secondPlot.set_ylim(0, max(30.0, max(resolutionValues) * 1.15))
                    secondPlot.set_ylabel("Resolution (Å)", color="tab:green", fontsize=9)
                    lineExtra, = secondPlot.plot(
                        xValues,
                        resolutionValues,
                        marker="o",
                        markersize=4.5,
                        linewidth=2.3,
                        color="tab:green",
                        label="Resolution (Å)",
                        zorder=3,
                    )
                else:
                    secondPlot.set_ylim(0, max(1.0, max(fitQualityValues) * 1.15))
                    secondPlot.set_ylabel("Fit quality", color="tab:green", fontsize=9)
                    lineExtra, = secondPlot.plot(
                        xValues,
                        fitQualityValues,
                        marker="o",
                        markersize=4.5,
                        linewidth=2.3,
                        color="tab:green",
                        label="Fit quality",
                        zorder=3,
                    )

                secondPlot.tick_params(axis="y", labelsize=8, colors="tab:green")
                legendHandles.append(lineExtra)

            defocusPlot.legend(
                handles=legendHandles,
                loc="upper left",
                fontsize=8,
                frameon=False,
                handlelength=2.2,
                borderaxespad=0.2,
            )

            subtitle = f"{len(data)} CTFs"
            defocusPlot.text(
                0.99,
                0.02,
                subtitle,
                transform=defocusPlot.transAxes,
                ha="right",
                va="bottom",
                fontsize=8,
                color="#334155",
                bbox={
                    "boxstyle": "round,pad=0.25",
                    "facecolor": "white",
                    "edgecolor": "#cbd5e1",
                    "alpha": 0.85,
                },
            )

            fig.subplots_adjust(
                left=0.14,
                right=0.86,
                top=0.86,
                bottom=0.20,
            )

            buffer = io.BytesIO()
            fig.savefig(
                buffer,
                format="png",
                facecolor="white",
                edgecolor="white",
                dpi=130,
            )
            buffer.seek(0)

            return Image.open(buffer).convert("RGB")

        except Exception:
            logger.debug("CTF defocus thumbnail failed", exc_info=True)
            return None
        finally:
            if fig is not None:
                plt.close(fig)

    def _renderCtftomoPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        ctfSerie = None

        iterSeriesFn = getattr(output, "iterItems", None)
        if callable(iterSeriesFn):
            try:
                seriesIterator = iterSeriesFn(iterate=False)
            except TypeError:
                try:
                    seriesIterator = iterSeriesFn()
                except Exception:
                    seriesIterator = None
            except Exception:
                seriesIterator = None

            if seriesIterator is not None:
                try:
                    for serie in seriesIterator:
                        ctfSerie = serie
                        break
                except Exception:
                    ctfSerie = None

        if ctfSerie is None:
            return None

        itemSelected = self._safeScalarValue(
            getattr(ctfSerie, "getTsId", lambda: None)()
        )

        if itemSelected is None:
            return None

        angDict: Dict[Any, float] = {}

        tiltSeriesSet = None
        getSetOfTiltSeriesFn = getattr(output, "getSetOfTiltSeries", None)
        if callable(getSetOfTiltSeriesFn):
            try:
                tiltSeriesSet = getSetOfTiltSeriesFn()
            except Exception:
                tiltSeriesSet = None

        if tiltSeriesSet is not None:
            try:
                iterTiltSeriesFn = getattr(tiltSeriesSet, "iterItems", None)
                if callable(iterTiltSeriesFn):
                    try:
                        tiltSeriesIterator = iterTiltSeriesFn(iterate=False)
                    except TypeError:
                        tiltSeriesIterator = iterTiltSeriesFn()
                else:
                    tiltSeriesIterator = iter(tiltSeriesSet)

                for ts in tiltSeriesIterator:
                    tsId = self._safeScalarValue(
                        getattr(ts, "getTsId", lambda: None)()
                    )

                    if str(tsId) != str(itemSelected):
                        continue

                    try:
                        iterViewsFn = getattr(ts, "iterItems", None)
                        if callable(iterViewsFn):
                            try:
                                viewIterator = iterViewsFn(iterate=False)
                            except TypeError:
                                viewIterator = iterViewsFn()
                        else:
                            viewIterator = iter(ts)

                        for tiltItem in viewIterator:
                            acqOrder = self._safeScalarValue(
                                getattr(tiltItem, "getAcquisitionOrder", lambda: None)()
                            )
                            tiltAngle = self._safeScalarValue(
                                getattr(tiltItem, "getTiltAngle", lambda: None)()
                            )

                            if acqOrder is None or tiltAngle is None:
                                continue

                            angDict[acqOrder] = float(tiltAngle)

                    except Exception:
                        logger.debug("Failed building CTFTomo angle dictionary", exc_info=True)

                    break

            except Exception:
                logger.debug("Failed iterating associated tilt-series set", exc_info=True)

        if not angDict:
            return None

        angList: List[float] = []
        defocusUList: List[float] = []
        defocusVList: List[float] = []
        phShList: List[float] = []
        resList: List[float] = []
        hasPhaseShift = False
        lastItemHasPhaseShift = False

        iterItemsFn = getattr(ctfSerie, "iterItems", None)
        if not callable(iterItemsFn):
            return None

        try:
            ctfIterator = iterItemsFn(orderBy="id")
        except TypeError:
            try:
                ctfIterator = iterItemsFn()
            except Exception:
                return None
        except Exception:
            return None

        try:
            for item in ctfIterator:
                acqOrder = self._safeScalarValue(
                    getattr(item, "getAcquisitionOrder", lambda: None)()
                )

                if acqOrder not in angDict:
                    continue

                defocusU = self._safeScalarValue(
                    getattr(item, "getDefocusU", lambda: None)()
                )
                defocusV = self._safeScalarValue(
                    getattr(item, "getDefocusV", lambda: None)()
                )

                if defocusU is None or defocusV is None:
                    continue

                try:
                    defocusU = float(defocusU)
                    defocusV = float(defocusV)
                except Exception:
                    continue

                if defocusU <= -900 or defocusV <= -0.5:
                    continue

                angList.append(float(angDict[acqOrder]))
                defocusUList.append(defocusU)
                defocusVList.append(defocusV)

                itemHasPhaseShift = False
                hasPhaseShiftFn = getattr(item, "hasPhaseShift", None)
                if callable(hasPhaseShiftFn):
                    try:
                        itemHasPhaseShift = bool(hasPhaseShiftFn())
                    except Exception:
                        itemHasPhaseShift = False

                lastItemHasPhaseShift = itemHasPhaseShift

                if itemHasPhaseShift:
                    hasPhaseShift = True
                    phaseShift = self._safeScalarValue(
                        getattr(item, "getPhaseShift", lambda: 0)()
                    )
                    phShList.append(float(phaseShift or 0))
                else:
                    phShList.append(0.0)

                resolution = self._safeScalarValue(
                    getattr(item, "getResolution", lambda: 0)()
                )
                resList.append(float(resolution or 0))

        except Exception:
            logger.debug("Failed iterating CTFTomo measurements", exc_info=True)

        if not angList:
            return None

        return self._buildCtftomoPlotImage(
            seriesLabel=self._getCtftomoSeriesLabel(ctfSerie),
            angList=angList,
            defocusUList=defocusUList,
            defocusVList=defocusVList,
            phShList=phShList,
            resList=resList,
            hasPhaseShift=hasPhaseShift and lastItemHasPhaseShift,
            size=size,
        )

    def _buildCtftomoPlotImage(
            self,
            seriesLabel: str,
            angList: List[float],
            defocusUList: List[float],
            defocusVList: List[float],
            phShList: List[float],
            resList: List[float],
            hasPhaseShift: bool,
            size: int,
    ) -> Optional[Image.Image]:
        fig = None
        try:
            data = []
            for x, defocusU, defocusV, phaseShift, resolution in zip(
                    angList,
                    defocusUList,
                    defocusVList,
                    phShList,
                    resList,
            ):
                try:
                    xValue = float(x)
                    defocusUValue = float(defocusU)
                    defocusVValue = float(defocusV)
                    phaseShiftValue = float(phaseShift or 0)
                    resolutionValue = float(resolution or 0)

                    if not (
                            np.isfinite(xValue)
                            and np.isfinite(defocusUValue)
                            and np.isfinite(defocusVValue)
                    ):
                        continue

                    data.append(
                        (
                            xValue,
                            defocusUValue,
                            defocusVValue,
                            phaseShiftValue,
                            resolutionValue,
                        )
                    )
                except Exception:
                    continue

            if not data:
                return None

            data.sort(key=lambda item: item[0])

            xValues = [item[0] for item in data]
            defocusUValues = [item[1] for item in data]
            defocusVValues = [item[2] for item in data]
            phaseShiftValues = [item[3] for item in data]
            resolutionValues = [item[4] for item in data]

            fig = plt.figure(figsize=(5.4, 3.35), dpi=130)
            defocusPlot = fig.add_subplot(111)

            defocusPlot.set_facecolor("white")
            defocusPlot.grid(True, linestyle="-", linewidth=0.55, alpha=0.35)

            defocusPlot.set_title(str(seriesLabel or "CTF Tomo"), fontsize=11, pad=6)
            defocusPlot.set_xlabel("Tilt angle (deg)", fontsize=9)
            defocusPlot.set_ylabel("Defocus (Å)", fontsize=9)

            defocusPlot.tick_params(axis="both", labelsize=8)

            lineU, = defocusPlot.plot(
                xValues,
                defocusUValues,
                marker="o",
                markersize=5.5,
                linewidth=3.2,
                color="tab:red",
                label="DefocusU (Å)",
                zorder=4,
            )
            lineV, = defocusPlot.plot(
                xValues,
                defocusVValues,
                marker="o",
                markersize=5.5,
                linewidth=3.2,
                color="tab:blue",
                label="DefocusV (Å)",
                zorder=5,
            )

            yValues = defocusUValues + defocusVValues
            yMin = min(yValues)
            yMax = max(yValues)
            yPad = max(1.0, (yMax - yMin) * 0.12)
            defocusPlot.set_ylim(yMin - yPad, yMax + yPad)

            xMin = min(xValues)
            xMax = max(xValues)
            if xMax > xMin:
                xPad = max(0.5, (xMax - xMin) * 0.04)
                defocusPlot.set_xlim(xMin - xPad, xMax + xPad)

            legendHandles = [lineU, lineV]

            if hasPhaseShift:
                secondPlot = defocusPlot.twinx()
                secondPlot.set_ylim(0, 180)
                secondPlot.set_ylabel("Phase shift", color="tab:green", fontsize=9)
                secondPlot.tick_params(axis="y", labelsize=8, colors="tab:green")

                lineExtra, = secondPlot.plot(
                    xValues,
                    phaseShiftValues,
                    marker="o",
                    markersize=4.8,
                    linewidth=2.6,
                    color="tab:green",
                    label="Phase shift (deg)",
                    zorder=3,
                )
            else:
                secondPlot = defocusPlot.twinx()
                secondPlot.set_ylim(0, 30)
                secondPlot.set_ylabel("Resolution (Å)", color="tab:green", fontsize=9)
                secondPlot.tick_params(axis="y", labelsize=8, colors="tab:green")

                lineExtra, = secondPlot.plot(
                    xValues,
                    resolutionValues,
                    marker="o",
                    markersize=4.8,
                    linewidth=2.6,
                    color="tab:green",
                    label="Resolution (Å)",
                    zorder=3,
                )

            legendHandles.append(lineExtra)

            defocusPlot.legend(
                handles=legendHandles,
                loc="upper left",
                fontsize=8,
                frameon=False,
                handlelength=2.2,
                borderaxespad=0.2,
            )

            fig.subplots_adjust(
                left=0.14,
                right=0.86,
                top=0.86,
                bottom=0.20,
            )

            buffer = io.BytesIO()
            fig.savefig(
                buffer,
                format="png",
                facecolor="white",
                edgecolor="white",
                dpi=130,
            )
            buffer.seek(0)

            return Image.open(buffer).convert("RGB")
        except Exception:
            logger.debug("CTFTomo plot thumbnail failed", exc_info=True)
            return None
        finally:
            if fig is not None:
                plt.close(fig)

    def _getCtftomoSeriesLabel(self, ctfSerie) -> str:
        getLabelFn = getattr(ctfSerie, "getObjLabel", None)
        if callable(getLabelFn):
            try:
                label = getLabelFn()
                if label:
                    return str(label)
            except Exception:
                pass

        getTsIdFn = getattr(ctfSerie, "getTsId", None)
        if callable(getTsIdFn):
            try:
                tsId = getTsIdFn()
                if tsId is not None:
                    return str(tsId)
            except Exception:
                pass

        return "CTF Tomo"

    def _composeParticleMosaic(
            self,
            tiles: Sequence[Image.Image],
            targetWidth: int,
            maxCols: int = 3,
    ) -> Image.Image:
        count = len(tiles)
        if count == 0:
            return Image.new("RGB", (320, 200), (246, 249, 252))

        cols = min(max(1, int(maxCols)), count)
        rows = int(np.ceil(count / float(cols)))

        baseWidth = max(240, int(targetWidth))
        gap = max(3, int(round(baseWidth * 0.012)))
        tileW = max(92, int((baseWidth - gap * max(0, cols - 1)) / cols))
        tileH = tileW

        width = cols * tileW + max(0, cols - 1) * gap
        height = rows * tileH + max(0, rows - 1) * gap
        canvas = Image.new("RGB", (width, height), (246, 249, 252))

        index = 0
        for row in range(rows):
            for col in range(cols):
                if index >= count:
                    break

                x0 = col * (tileW + gap)
                y0 = row * (tileH + gap)
                x1 = x0 + tileW - 1
                y1 = y0 + tileH - 1

                self._pasteContainedPreview(
                    canvas=canvas,
                    previewImage=tiles[index],
                    box=(x0, y0, x1, y1),
                    padding=2,
                    radius=max(8, int(round(tileH * 0.08))),
                    background=(246, 249, 252),
                    contain=True,
                )
                index += 1

        return canvas

    def _composeTiltSeriesStrip(
            self,
            tiles: Sequence[Image.Image],
            targetWidth: int,
    ) -> Image.Image:
        if not tiles:
            return Image.new("RGB", (420, 220), (246, 249, 252))

        return self._composeCleanGrid(
            tiles=tiles,
            maxCols=2,
            targetWidth=targetWidth,
            background=(246, 249, 252),
        )

    def _composeMicrographStrip(
            self,
            tiles: Sequence[Image.Image],
            targetWidth: int,
    ) -> Image.Image:
        if not tiles:
            return Image.new("RGB", (420, 200), (246, 249, 252))

        count = min(3, len(tiles))
        baseWidth = max(260, int(targetWidth))
        gap = max(4, int(round(baseWidth * 0.012)))
        tileW = max(120, int((baseWidth - gap * max(0, count - 1)) / count))
        tileH = max(118, int(round(tileW * 0.82)))

        width = count * tileW + max(0, count - 1) * gap
        height = tileH
        canvas = Image.new("RGB", (width, height), (246, 249, 252))

        for index, tile in enumerate(tiles[:count]):
            x0 = index * (tileW + gap)
            x1 = x0 + tileW - 1
            self._pasteContainedPreview(
                canvas=canvas,
                previewImage=tile,
                box=(x0, 0, x1, tileH - 1),
                padding=2,
                radius=max(8, int(round(tileH * 0.07))),
                background=(246, 249, 252),
                contain=True,
            )

        return canvas

    def _looksRenderableOutput(self, output: Any) -> bool:
        if output is None:
            return False

        if isinstance(output, EMSet):
            return True

        getFileNameFn = getattr(output, "getFileName", None)
        if callable(getFileNameFn):
            try:
                value = getFileNameFn()
                if value:
                    return True
            except Exception:
                pass

        iterItemsFn = getattr(output, "iterItems", None)
        if callable(iterItemsFn):
            return True

        iterTomogramsFn = getattr(output, "iterTomograms", None)
        if callable(iterTomogramsFn):
            return True

        getTomogramsFn = getattr(output, "getTomograms", None)
        if callable(getTomogramsFn):
            return True

        return False

    def _iterItemsDirect(self, output, orderBy: Optional[str] = None) -> Iterable[Any]:
        iterItemsFn = getattr(output, "iterItems", None)

        if callable(iterItemsFn):
            iterator = None

            try:
                if orderBy is not None:
                    iterator = iterItemsFn(orderBy=orderBy)
                else:
                    iterator = iterItemsFn(iterate=False)
            except TypeError:
                try:
                    iterator = iterItemsFn()
                except Exception:
                    iterator = None
            except Exception:
                iterator = None

            if iterator is not None:
                try:
                    for item in iterator:
                        yield item
                except Exception:
                    return
                return

        try:
            for item in output:
                yield item
        except Exception:
            return

    def _readCoordinateScalar(self, item, getterName: str) -> Optional[float]:
        getter = getattr(item, getterName, None)
        if not callable(getter):
            return None

        for args in ((), (0,)):
            try:
                value = self._safeScalarValue(getter(*args))
                if value is None:
                    continue
                return float(value)
            except TypeError:
                continue
            except Exception:
                continue

        return None

    def _readCoordinate3dScalar(self, item, getterName: str) -> Optional[float]:
        getter = getattr(item, getterName, None)
        if not callable(getter):
            return None

        for args in ((BOTTOM_LEFT_CORNER,), ()):
            try:
                value = self._safeScalarValue(getter(*args))
                if value is None:
                    continue
                return float(value)
            except TypeError:
                continue
            except Exception:
                continue

        return None

    def _renderLandmarkModelsPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []
        maxItems = 4

        for landmarkModel in self._iterItemsDirect(output):
            try:
                tile = self._renderLandmarkModelPreviewFromItem(
                    protocol=protocol,
                    landmarkModel=landmarkModel,
                    size=size,
                )
                if tile is not None:
                    tiles.append(tile)

                if len(tiles) >= maxItems:
                    break
            except Exception:
                logger.debug("LandmarkModel preview failed", exc_info=True)

        if not tiles:
            return None

        return self._composeCleanGrid(
            tiles=tiles[:maxItems],
            maxCols=2,
            targetWidth=size,
            background=(246, 249, 252),
        )

    def _renderLandmarkModelPreviewFromItem(
            self,
            protocol,
            landmarkModel,
            size: int,
    ) -> Optional[Image.Image]:
        points = self._collectLandmarkModelPoints(
            protocol=protocol,
            landmarkModel=landmarkModel,
            maxPoints=1500,
        )

        tiltSeries = self._resolveLandmarkModelTiltSeries(landmarkModel)

        if tiltSeries is not None and points:
            image = self._renderTiltSeriesCoordinatesOverlayPreview(
                protocol=protocol,
                tiltSeries=tiltSeries,
                points=points,
                size=size,
            )
            if image is not None:
                return image

        if tiltSeries is not None:
            baseImage, _xDim, _yDim = self._readTiltSeriesRepresentativeImage(
                protocol=protocol,
                tiltSeries=tiltSeries,
            )
            if baseImage is not None:
                return self._drawSimplePreviewLabel(
                    image=baseImage,
                    label="Landmarks",
                )

        if points:
            return self._buildCoordinatesScatterImage(
                title="Landmarks",
                points=points,
                zValues=None,
                is3d=False,
                size=size,
            )

        return None

    def _resolveLandmarkModelTiltSeries(self, landmarkModel) -> Optional[Any]:
        for getterName in (
                "getTiltSeries",
                "getTiltSeriesPointer",
                "getTiltSeriesObj",
                "getTs",
        ):
            getter = getattr(landmarkModel, getterName, None)
            if not callable(getter):
                continue

            try:
                tiltSeries = self._safeScalarValue(getter())
                if tiltSeries is not None:
                    return tiltSeries
            except Exception:
                continue

        return None

    def _collectLandmarkModelPoints(
            self,
            protocol,
            landmarkModel,
            maxPoints: int,
    ) -> List[Tuple[float, float]]:
        points: List[Tuple[float, float]] = []

        retrieveInfoTableFn = getattr(landmarkModel, "retrieveInfoTable", None)
        if callable(retrieveInfoTableFn):
            try:
                infoTable = retrieveInfoTableFn()
                for row in self._iterLandmarkInfoRows(infoTable):
                    point = self._extractLandmarkPointFromRow(row)
                    if point is None:
                        continue

                    points.append(point)

                    if len(points) >= maxPoints:
                        return points
            except Exception:
                logger.debug("LandmarkModel info table parsing failed", exc_info=True)

        if points:
            return points

        getFileNameFn = getattr(landmarkModel, "getFileName", None)
        if callable(getFileNameFn):
            try:
                filePath = self._resolveFilePath(protocol, getFileNameFn())
                if filePath is not None and filePath.exists():
                    points.extend(
                        self._collectLandmarkPointsFromFile(
                            filePath=filePath,
                            maxPoints=maxPoints,
                        )
                    )
            except Exception:
                logger.debug("LandmarkModel file parsing failed", exc_info=True)

        return points[:maxPoints]

    def _iterLandmarkInfoRows(self, infoTable) -> Iterable[Any]:
        if infoTable is None:
            return

        if hasattr(infoTable, "to_dict"):
            try:
                records = infoTable.to_dict("records")
                for record in records:
                    yield record
                return
            except Exception:
                pass

        if hasattr(infoTable, "iterrows"):
            try:
                for _index, row in infoTable.iterrows():
                    yield row
                return
            except Exception:
                pass

        if isinstance(infoTable, dict):
            rows = None
            for key in ("rows", "data", "values", "records"):
                value = infoTable.get(key)
                if value is not None:
                    rows = value
                    break

            if rows is not None:
                try:
                    for row in rows:
                        yield row
                    return
                except Exception:
                    pass

            yield infoTable
            return

        for attrName in ("rows", "_rows", "data", "_data"):
            rows = getattr(infoTable, attrName, None)
            if rows is None:
                continue

            try:
                rows = rows() if callable(rows) else rows
                for row in rows:
                    yield row
                return
            except Exception:
                continue

        try:
            for row in infoTable:
                yield row
        except Exception:
            return

    def _extractLandmarkPointFromRow(self, row) -> Optional[Tuple[float, float]]:
        xValue = self._readValueFromRow(
            row=row,
            names=(
                "x",
                "X",
                "_x",
                "xcoor",
                "xcoord",
                "xCoord",
                "xCoordinate",
                "coordX",
                "positionX",
            ),
        )
        yValue = self._readValueFromRow(
            row=row,
            names=(
                "y",
                "Y",
                "_y",
                "ycoor",
                "ycoord",
                "yCoord",
                "yCoordinate",
                "coordY",
                "positionY",
            ),
        )

        if xValue is None or yValue is None:
            numericValues = self._numericValuesFromRow(row)
            if len(numericValues) >= 2:
                xValue = numericValues[0]
                yValue = numericValues[1]

        if xValue is None or yValue is None:
            return None

        try:
            xValue = float(xValue)
            yValue = float(yValue)

            if not np.isfinite(xValue) or not np.isfinite(yValue):
                return None

            return xValue, yValue
        except Exception:
            return None

    def _readValueFromRow(self, row, names: Sequence[str]) -> Optional[float]:
        if row is None:
            return None

        if isinstance(row, dict):
            lowerMap = {str(key).lower(): value for key, value in row.items()}

            for name in names:
                if name in row:
                    return self._safeScalarValue(row[name])

                value = lowerMap.get(str(name).lower())
                if value is not None:
                    return self._safeScalarValue(value)

            return None

        for name in names:
            getterName = "get%s" % str(name)[0].upper() + str(name)[1:]
            getter = getattr(row, getterName, None)
            if callable(getter):
                try:
                    return self._safeScalarValue(getter())
                except Exception:
                    pass

            if hasattr(row, name):
                try:
                    value = getattr(row, name)
                    return self._safeScalarValue(value() if callable(value) else value)
                except Exception:
                    pass

        try:
            if hasattr(row, "get"):
                for name in names:
                    try:
                        value = row.get(name)
                        if value is not None:
                            return self._safeScalarValue(value)
                    except Exception:
                        continue
        except Exception:
            pass

        return None

    def _numericValuesFromRow(self, row) -> List[float]:
        values: List[Any] = []

        if isinstance(row, dict):
            values = list(row.values())
        elif isinstance(row, (list, tuple)):
            values = list(row)
        else:
            rawValues = getattr(row, "_values", None)
            if rawValues is not None:
                values = list(rawValues)

        numericValues: List[float] = []
        for value in values:
            try:
                value = self._safeScalarValue(value)
                number = float(value)

                if np.isfinite(number):
                    numericValues.append(number)
            except Exception:
                continue

        return numericValues

    def _collectLandmarkPointsFromFile(
            self,
            filePath: Path,
            maxPoints: int,
    ) -> List[Tuple[float, float]]:
        points: List[Tuple[float, float]] = []

        try:
            with filePath.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    text = line.strip()
                    if not text or text.startswith("#"):
                        continue

                    tokens = re.split(r"[\s,;]+", text)
                    numericValues: List[float] = []

                    for token in tokens:
                        try:
                            value = float(token)
                            if np.isfinite(value):
                                numericValues.append(value)
                        except Exception:
                            continue

                    if len(numericValues) < 2:
                        continue

                    points.append((numericValues[0], numericValues[1]))

                    if len(points) >= maxPoints:
                        break
        except Exception:
            return points

        return points

    def _drawSimplePreviewLabel(
            self,
            image: Image.Image,
            label: str,
    ) -> Image.Image:
        canvas = image.copy().convert("RGB")
        draw = ImageDraw.Draw(canvas)

        label = str(label or "").strip()
        if not label:
            return canvas

        textWidth = max(76, min(180, 16 + len(label) * 7))

        draw.rounded_rectangle(
            (8, 8, textWidth, 30),
            radius=8,
            fill=(255, 255, 255),
            outline=(203, 213, 225),
            width=1,
        )
        draw.text((14, 13), label, fill=(51, 65, 85))

        return canvas

    def _renderTiltSeriesCoordinatesPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        points: List[Tuple[float, float]] = []
        bestTiltSeries = None
        bestPoints: List[Tuple[float, float]] = []
        maxPoints = 1500

        tiltSeriesSet = self._resolveTiltSeriesCoordinatesSet(output)

        if tiltSeriesSet is not None:
            checkedTiltSeries = 0

            for tiltSeries in self._iterItemsDirect(tiltSeriesSet):
                checkedTiltSeries += 1

                localPoints = self._collectTiltSeriesCoordinatePoints(
                    output=output,
                    tiltSeries=tiltSeries,
                    maxPoints=maxPoints,
                )

                if len(localPoints) > len(bestPoints):
                    bestTiltSeries = tiltSeries
                    bestPoints = localPoints

                if bestTiltSeries is not None and bestPoints:
                    image = self._renderTiltSeriesCoordinatesOverlayPreview(
                        protocol=protocol,
                        tiltSeries=bestTiltSeries,
                        points=bestPoints,
                        size=size,
                    )
                    if image is not None:
                        return image

                if len(bestPoints) >= maxPoints:
                    break

                if checkedTiltSeries >= 8 and bestPoints:
                    break

        if bestPoints:
            points.extend(bestPoints[:maxPoints])

        if not points:
            points = self._collectTiltSeriesCoordinatePoints(
                output=output,
                tiltSeries=None,
                maxPoints=maxPoints,
            )

            if tiltSeriesSet is not None and points:
                for tiltSeries in self._iterItemsDirect(tiltSeriesSet):
                    image = self._renderTiltSeriesCoordinatesOverlayPreview(
                        protocol=protocol,
                        tiltSeries=tiltSeries,
                        points=points,
                        size=size,
                    )
                    if image is not None:
                        return image
                    break

        if points:
            return self._buildCoordinatesScatterImage(
                title=self._getOutputClassName(output),
                points=points,
                zValues=None,
                is3d=False,
                size=size,
            )

        return None

    def _resolveTiltSeriesCoordinatesSet(self, output) -> Optional[Any]:
        for getterName in (
                "getSetOfTiltSeries",
                "getTiltSeries",
                "getTiltSeriesSet",
                "getInputTiltSeries",
        ):
            getter = getattr(output, getterName, None)
            if not callable(getter):
                continue

            try:
                tiltSeriesSet = self._safeScalarValue(getter())
                if tiltSeriesSet is not None:
                    return tiltSeriesSet
            except Exception:
                continue

        return None

    def _collectTiltSeriesCoordinatePoints(
            self,
            output,
            tiltSeries,
            maxPoints: int,
    ) -> List[Tuple[float, float]]:
        points: List[Tuple[float, float]] = []
        iterCoordinatesFn = getattr(output, "iterCoordinates", None)
        coordinateIterator = None

        if callable(iterCoordinatesFn):
            if tiltSeries is not None:
                candidateArgs: List[Any] = [tiltSeries]

                for getterName in ("getTsId", "getObjId"):
                    getter = getattr(tiltSeries, getterName, None)
                    if not callable(getter):
                        continue

                    try:
                        value = self._safeScalarValue(getter())
                        if value is not None:
                            candidateArgs.append(value)
                    except Exception:
                        continue

                for arg in candidateArgs:
                    try:
                        coordinateIterator = iterCoordinatesFn(arg)
                        break
                    except Exception:
                        coordinateIterator = None

            if coordinateIterator is None:
                try:
                    coordinateIterator = iterCoordinatesFn()
                except Exception:
                    coordinateIterator = None

        if coordinateIterator is None:
            coordinateIterator = self._iterItemsDirect(output)

        for coord in coordinateIterator:
            try:
                if tiltSeries is not None and not self._coordinateMatchesTiltSeries(coord, tiltSeries):
                    continue

                xValue = self._readCoordinateScalar(coord, "getX")
                yValue = self._readCoordinateScalar(coord, "getY")

                if xValue is None or yValue is None:
                    continue

                if not np.isfinite(xValue) or not np.isfinite(yValue):
                    continue

                points.append((float(xValue), float(yValue)))

                if len(points) >= maxPoints:
                    break

            except Exception:
                continue

        return points

    def _coordinateMatchesTiltSeries(self, coord, tiltSeries) -> bool:
        tiltSeriesKeys: List[Any] = []

        for getterName in ("getTsId", "getObjId"):
            getter = getattr(tiltSeries, getterName, None)
            if not callable(getter):
                continue

            try:
                value = self._safeScalarValue(getter())
                if value is not None:
                    tiltSeriesKeys.append(value)
                    tiltSeriesKeys.append(str(value))
            except Exception:
                continue

        coordKeys: List[Any] = []

        for getterName in (
                "getTsId",
                "getTiltSeriesId",
                "getTiltSeriesObjId",
                "getTiltSeriesName",
        ):
            getter = getattr(coord, getterName, None)
            if not callable(getter):
                continue

            try:
                value = self._safeScalarValue(getter())
                if value is not None:
                    coordKeys.append(value)
                    coordKeys.append(str(value))
            except Exception:
                continue

        if not coordKeys or not tiltSeriesKeys:
            return True

        return any(str(coordKey) == str(tsKey) for coordKey in coordKeys for tsKey in tiltSeriesKeys)

    def _renderTiltSeriesCoordinatesOverlayPreview(
            self,
            protocol,
            tiltSeries,
            points: List[Tuple[float, float]],
            size: int,
    ) -> Optional[Image.Image]:
        try:
            baseImage, xDim, yDim = self._readTiltSeriesRepresentativeImage(protocol, tiltSeries)
            if baseImage is None:
                return None

            baseImage = baseImage.copy().convert("RGB")
            draw = ImageDraw.Draw(baseImage)

            try:
                xDim = float(xDim) if xDim is not None else float(baseImage.width)
            except Exception:
                xDim = float(baseImage.width)

            try:
                yDim = float(yDim) if yDim is not None else float(baseImage.height)
            except Exception:
                yDim = float(baseImage.height)

            if xDim <= 0:
                xDim = float(baseImage.width)
            if yDim <= 0:
                yDim = float(baseImage.height)

            scaleX = float(baseImage.width) / xDim
            scaleY = float(baseImage.height) / yDim

            radius = max(2, int(round(min(baseImage.size) * 0.012)))
            outlineWidth = max(1, int(round(radius * 0.55)))

            for xValue, yValue in points[:1500]:
                try:
                    px = int(round(float(xValue) * scaleX))
                    py = int(round(float(yValue) * scaleY))

                    if px < 0 or py < 0 or px >= baseImage.width or py >= baseImage.height:
                        continue

                    draw.ellipse(
                        (
                            px - radius,
                            py - radius,
                            px + radius,
                            py + radius,
                        ),
                        outline=(255, 64, 64),
                        width=outlineWidth,
                    )
                except Exception:
                    continue

            label = f"{min(len(points), 1500)} coords"
            draw.rounded_rectangle(
                (8, 8, 118, 30),
                radius=8,
                fill=(255, 255, 255),
                outline=(203, 213, 225),
                width=1,
            )
            draw.text((14, 13), label, fill=(51, 65, 85))

            return baseImage

        except Exception:
            logger.debug("TiltSeriesCoordinates overlay thumbnail failed", exc_info=True)
            return None

    def _readTiltSeriesRepresentativeImage(
            self,
            protocol,
            tiltSeries,
    ) -> Tuple[Optional[Image.Image], Optional[float], Optional[float]]:
        try:
            getFileNameFn = getattr(tiltSeries, "getFileName", None)
            if callable(getFileNameFn):
                stackPath = self._resolveFilePath(protocol, getFileNameFn())
                if stackPath is not None and stackPath.exists():
                    gray = self._read2dTile(
                        filePath=stackPath,
                        sliceIndex=None,
                        preferCentral=True,
                        thumbSize=maxThumbSize,
                    )

                    if gray is not None:
                        image = self._grayTileToImage(gray)
                        xDim, yDim = self._getImageItemDimensions(tiltSeries, image)
                        return image, xDim, yDim
        except Exception:
            logger.debug("Direct tilt-series coordinate image failed", exc_info=True)

        checkedFrames = 0

        for frame in self._iterItemsDirect(tiltSeries):
            checkedFrames += 1

            try:
                sourcePath, sourceIndex = self._resolveImageSourceFromItem(frame)
                if not sourcePath:
                    if checkedFrames >= 12:
                        break
                    continue

                resolvedPath = self._resolveFilePath(protocol, sourcePath)
                if resolvedPath is None or not resolvedPath.exists():
                    if checkedFrames >= 12:
                        break
                    continue

                gray = self._read2dTile(
                    filePath=resolvedPath,
                    sliceIndex=sourceIndex,
                    preferCentral=False,
                    thumbSize=maxThumbSize,
                )

                if gray is not None:
                    image = self._grayTileToImage(gray)
                else:
                    image = self._readImagePreview(protocol, sourcePath, sourceIndex)

                if image is not None:
                    xDim, yDim = self._getImageItemDimensions(frame, image)
                    return image, xDim, yDim

            except Exception:
                continue

            if checkedFrames >= 12:
                break

        return None, None, None

    def _getImageItemDimensions(
            self,
            item,
            image: Optional[Image.Image] = None,
    ) -> Tuple[Optional[float], Optional[float]]:
        xDim = None
        yDim = None

        getDimFn = getattr(item, "getDim", None)
        if callable(getDimFn):
            try:
                dims = getDimFn()
                if isinstance(dims, (list, tuple)) and len(dims) >= 2:
                    xDim = self._safeScalarValue(dims[0])
                    yDim = self._safeScalarValue(dims[1])
            except Exception:
                pass

        if xDim is None:
            getXDimFn = getattr(item, "getXDim", None)
            if callable(getXDimFn):
                try:
                    xDim = self._safeScalarValue(getXDimFn())
                except Exception:
                    xDim = None

        if yDim is None:
            getYDimFn = getattr(item, "getYDim", None)
            if callable(getYDimFn):
                try:
                    yDim = self._safeScalarValue(getYDimFn())
                except Exception:
                    yDim = None

        if image is not None:
            if xDim is None:
                xDim = image.width
            if yDim is None:
                yDim = image.height

        try:
            xDim = float(xDim) if xDim is not None else None
        except Exception:
            xDim = None

        try:
            yDim = float(yDim) if yDim is not None else None
        except Exception:
            yDim = None

        return xDim, yDim

    def _renderCoordinates2dPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        points: List[Tuple[float, float]] = []
        maxPoints = 1500

        iterCoordinatesFn = getattr(output, "iterCoordinates", None)
        micrographs = self._resolveCoordinatesMicrographs(output)
        micrographsById = self._buildMicrographsLookup(micrographs)

        if callable(iterCoordinatesFn) and micrographs is not None:
            bestMicrograph = None
            bestPoints: List[Tuple[float, float]] = []

            try:
                checkedMicrographs = 0

                for micrograph in self._iterItemsDirect(micrographs):
                    checkedMicrographs += 1
                    localPoints: List[Tuple[float, float]] = []

                    coordinateIterator = None

                    for arg in self._micrographIterationArgs(micrograph):
                        try:
                            coordinateIterator = iterCoordinatesFn(arg)
                            break
                        except Exception:
                            coordinateIterator = None

                    if coordinateIterator is None:
                        continue

                    for coord in coordinateIterator:
                        try:
                            xValue = self._readCoordinateScalar(coord, "getX")
                            yValue = self._readCoordinateScalar(coord, "getY")

                            if xValue is None or yValue is None:
                                continue

                            if not np.isfinite(xValue) or not np.isfinite(yValue):
                                continue

                            localPoints.append((float(xValue), float(yValue)))

                            if len(localPoints) >= maxPoints:
                                break

                        except Exception:
                            continue

                    if len(localPoints) > len(bestPoints):
                        bestMicrograph = micrograph
                        bestPoints = localPoints

                    if len(bestPoints) >= maxPoints:
                        break

                    if checkedMicrographs >= 8 and bestPoints:
                        break

            except Exception:
                logger.debug("Coordinates2D micrograph iteration failed", exc_info=True)

            if bestMicrograph is not None and bestPoints:
                image = self._renderCoordinates2dMicrographOverlayPreview(
                    protocol=protocol,
                    micrograph=bestMicrograph,
                    points=bestPoints,
                    size=size,
                )
                if image is not None:
                    return image

                points.extend(bestPoints[:maxPoints])

        if not points:
            if callable(iterCoordinatesFn):
                try:
                    coordIterator = iterCoordinatesFn()
                except Exception:
                    coordIterator = None
            else:
                coordIterator = self._iterItemsDirect(output)

            if coordIterator is not None:
                groupedPoints: Dict[int, Dict[str, Any]] = {}

                for coord in coordIterator:
                    try:
                        xValue = self._readCoordinateScalar(coord, "getX")
                        yValue = self._readCoordinateScalar(coord, "getY")

                        if xValue is None or yValue is None:
                            continue

                        if not np.isfinite(xValue) or not np.isfinite(yValue):
                            continue

                        point = (float(xValue), float(yValue))
                        points.append(point)

                        micrograph = self._resolveCoordinateMicrograph(
                            coord=coord,
                            micrographs=micrographs,
                            micrographsById=micrographsById,
                        )

                        if micrograph is not None:
                            key = id(micrograph)
                            entry = groupedPoints.get(key)
                            if entry is None:
                                entry = {
                                    "micrograph": micrograph,
                                    "points": [],
                                }
                                groupedPoints[key] = entry

                            entry["points"].append(point)

                        if len(points) >= maxPoints:
                            break

                    except Exception:
                        continue

                if groupedPoints:
                    groups = sorted(
                        groupedPoints.values(),
                        key=lambda entry: len(entry["points"]),
                        reverse=True,
                    )

                    for group in groups[:4]:
                        image = self._renderCoordinates2dMicrographOverlayPreview(
                            protocol=protocol,
                            micrograph=group["micrograph"],
                            points=group["points"],
                            size=size,
                        )
                        if image is not None:
                            return image

        if points:
            return self._buildCoordinatesScatterImage(
                title=self._getOutputClassName(output),
                points=points,
                zValues=None,
                is3d=False,
                size=size,
            )

        return None

    def _resolveCoordinatesMicrographs(self, output) -> Optional[Any]:
        for getterName in ("getMicrographs", "getMicrographsPointer", "getInputMicrographs"):
            getter = getattr(output, getterName, None)
            if not callable(getter):
                continue

            try:
                micrographs = self._safeScalarValue(getter())
                if micrographs is not None:
                    return micrographs
            except Exception:
                continue

        return None

    def _buildMicrographsLookup(self, micrographs) -> Dict[Any, Any]:
        micrographsById: Dict[Any, Any] = {}

        if micrographs is None:
            return micrographsById

        for micrograph in self._iterItemsDirect(micrographs):
            try:
                keys: List[Any] = []

                for getterName in (
                        "getObjId",
                        "getMicId",
                        "getMicName",
                        "getName",
                        "getFileName",
                ):
                    getter = getattr(micrograph, getterName, None)
                    if not callable(getter):
                        continue

                    try:
                        value = self._safeScalarValue(getter())
                        if value is not None:
                            keys.extend(self._micrographLookupKeys(value))
                    except Exception:
                        continue

                for key in keys:
                    micrographsById[key] = micrograph
                    micrographsById[str(key)] = micrograph

            except Exception:
                continue

        return micrographsById

    def _micrographIterationArgs(self, micrograph) -> List[Any]:
        args: List[Any] = [micrograph]

        for getterName in ("getObjId", "getMicId"):
            getter = getattr(micrograph, getterName, None)
            if not callable(getter):
                continue

            try:
                value = self._safeScalarValue(getter())
                if value is not None:
                    args.append(value)
            except Exception:
                continue

        result: List[Any] = []
        seen = set()

        for arg in args:
            marker = str(arg)
            if marker in seen:
                continue
            seen.add(marker)
            result.append(arg)

        return result

    def _resolveCoordinateMicrograph(
            self,
            coord,
            micrographs,
            micrographsById: Dict[Any, Any],
    ) -> Optional[Any]:
        getMicrographFn = getattr(coord, "getMicrograph", None)
        if callable(getMicrographFn):
            try:
                micrograph = getMicrographFn()
                if micrograph is not None:
                    return micrograph
            except Exception:
                pass

        for getterName in (
                "getMicId",
                "getMicrographId",
                "getMicName",
                "getMicrographName",
                "getFileName",
        ):
            getter = getattr(coord, getterName, None)
            if not callable(getter):
                continue

            try:
                value = self._safeScalarValue(getter())
                micrograph = self._lookupMicrographByKey(
                    micrographs=micrographs,
                    micrographsById=micrographsById,
                    key=value,
                )
                if micrograph is not None:
                    return micrograph
            except Exception:
                continue

        return None

    def _micrographLookupKeys(self, value: Any) -> List[Any]:
        keys: List[Any] = []

        value = self._safeScalarValue(value)
        if value is None:
            return keys

        keys.append(value)

        text = str(value).strip()
        if text:
            keys.append(text)

            try:
                keys.append(int(float(text)))
            except Exception:
                pass

            try:
                path = Path(text)
                if path.name:
                    keys.append(path.name)
                if path.stem:
                    keys.append(path.stem)
            except Exception:
                pass

        result: List[Any] = []
        seen = set()

        for key in keys:
            marker = str(key)
            if marker in seen:
                continue
            seen.add(marker)
            result.append(key)

        return result

    def _lookupMicrographByKey(
            self,
            micrographs,
            micrographsById: Dict[Any, Any],
            key: Any,
    ) -> Optional[Any]:
        if key is None:
            return None

        for lookupKey in self._micrographLookupKeys(key):
            micrograph = micrographsById.get(lookupKey)
            if micrograph is not None:
                return micrograph

            micrograph = micrographsById.get(str(lookupKey))
            if micrograph is not None:
                return micrograph

        if micrographs is None:
            return None

        getItemFn = getattr(micrographs, "getItem", None)
        if callable(getItemFn):
            for lookupKey in self._micrographLookupKeys(key):
                for fieldName in ("id", "_objId", "_micId", "micId", "_micName", "micName"):
                    try:
                        micrograph = getItemFn(fieldName, lookupKey)
                        if micrograph is not None:
                            return micrograph
                    except Exception:
                        continue

                try:
                    micrograph = getItemFn(lookupKey)
                    if micrograph is not None:
                        return micrograph
                except Exception:
                    pass

        return None

    def _getFirstRenderableMicrograph(self, protocol, micrographs) -> Optional[Any]:
        if micrographs is None:
            return None

        for micrograph in self._iterItemsDirect(micrographs):
            try:
                sourcePath, sourceIndex = self._resolveImageSourceFromItem(micrograph)
                if not sourcePath:
                    continue

                image = self._readImagePreview(protocol, sourcePath, sourceIndex)
                if image is not None:
                    return micrograph

            except Exception:
                continue

        return None

    def _renderCoordinates2dMicrographOverlayPreview(
            self,
            protocol,
            micrograph,
            points: List[Tuple[float, float]],
            size: int,
    ) -> Optional[Image.Image]:
        try:
            sourcePath, sourceIndex = self._resolveImageSourceFromItem(micrograph)
            if not sourcePath:
                return None

            micrographPath = self._resolveFilePath(protocol, sourcePath)
            if micrographPath is None or not micrographPath.exists():
                return None

            gray = self._read2dTile(
                filePath=micrographPath,
                sliceIndex=sourceIndex,
                preferCentral=False,
                thumbSize=maxThumbSize,
            )

            if gray is not None:
                baseImage = self._grayTileToImage(gray)
            else:
                baseImage = self._readImagePreview(protocol, sourcePath, sourceIndex)

            if baseImage is None:
                return None

            baseImage = baseImage.copy().convert("RGB")
            draw = ImageDraw.Draw(baseImage)

            xDim = None
            yDim = None

            getDimFn = getattr(micrograph, "getDim", None)
            if callable(getDimFn):
                try:
                    dims = getDimFn()
                    if isinstance(dims, (list, tuple)) and len(dims) >= 2:
                        xDim = self._safeScalarValue(dims[0])
                        yDim = self._safeScalarValue(dims[1])
                except Exception:
                    pass

            if xDim is None:
                getXDimFn = getattr(micrograph, "getXDim", None)
                if callable(getXDimFn):
                    try:
                        xDim = self._safeScalarValue(getXDimFn())
                    except Exception:
                        xDim = None

            if yDim is None:
                getYDimFn = getattr(micrograph, "getYDim", None)
                if callable(getYDimFn):
                    try:
                        yDim = self._safeScalarValue(getYDimFn())
                    except Exception:
                        yDim = None

            try:
                xDim = float(xDim) if xDim is not None else float(baseImage.width)
            except Exception:
                xDim = float(baseImage.width)

            try:
                yDim = float(yDim) if yDim is not None else float(baseImage.height)
            except Exception:
                yDim = float(baseImage.height)

            if xDim <= 0:
                xDim = float(baseImage.width)
            if yDim <= 0:
                yDim = float(baseImage.height)

            scaleX = float(baseImage.width) / xDim
            scaleY = float(baseImage.height) / yDim

            radius = max(2, int(round(min(baseImage.size) * 0.012)))
            outlineWidth = max(1, int(round(radius * 0.55)))

            for xValue, yValue in points[:1500]:
                try:
                    px = int(round(float(xValue) * scaleX))
                    py = int(round(float(yValue) * scaleY))

                    if px < 0 or py < 0 or px >= baseImage.width or py >= baseImage.height:
                        continue

                    draw.ellipse(
                        (
                            px - radius,
                            py - radius,
                            px + radius,
                            py + radius,
                        ),
                        outline=(255, 64, 64),
                        width=outlineWidth,
                    )
                except Exception:
                    continue

            label = f"{min(len(points), 1500)} coords"
            draw.rounded_rectangle(
                (8, 8, 118, 30),
                radius=8,
                fill=(255, 255, 255),
                outline=(203, 213, 225),
                width=1,
            )
            draw.text((14, 13), label, fill=(51, 65, 85))

            return baseImage

        except Exception:
            logger.debug("Coordinates2D micrograph overlay thumbnail failed", exc_info=True)
            return None

    def _renderMeshesPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        image = self._renderCoordinates3dPreview(protocol, output, size=size)
        if image is not None:
            return image

        return self._renderMeshesScatterPreview(protocol, output, size=size)

    def _renderMeshesScatterPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        points: List[Tuple[float, float]] = []
        zValues: List[float] = []
        maxPoints = 1500

        for meshPoint in self._iterItemsDirect(output):
            try:
                xValue = self._readCoordinate3dScalar(meshPoint, "getX")
                yValue = self._readCoordinate3dScalar(meshPoint, "getY")
                zValue = self._readCoordinate3dScalar(meshPoint, "getZ")

                if xValue is None or yValue is None or zValue is None:
                    continue

                if not (
                        np.isfinite(xValue)
                        and np.isfinite(yValue)
                        and np.isfinite(zValue)
                ):
                    continue

                points.append((float(xValue), float(yValue)))
                zValues.append(float(zValue))

                if len(points) >= maxPoints:
                    break

            except Exception:
                continue

        if not points:
            return None

        return self._buildCoordinatesScatterImage(
            title=self._getOutputClassName(output),
            points=points,
            zValues=zValues,
            is3d=True,
            size=size,
        )

    def _renderCoordinates3dPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        points: List[Tuple[float, float]] = []
        zValues: List[float] = []
        maxPoints = 1200

        iterCoordinatesFn = getattr(output, "iterCoordinates", None)

        if callable(iterCoordinatesFn):
            tomogramSources: List[Any] = []

            iterTomogramsFn = getattr(output, "iterVolumes", None)
            if callable(iterTomogramsFn):
                try:
                    for tomogram in iterTomogramsFn():
                        tomogramSources.append(tomogram)
                except Exception:
                    logger.debug("Coords3D iterVolumes failed", exc_info=True)

            if not tomogramSources:
                getTomogramsFn = getattr(output, "getTomograms", None)
                if callable(getTomogramsFn):
                    try:
                        tomograms = getTomogramsFn()
                        for tomogram in self._iterItemsDirect(tomograms):
                            tomogramSources.append(tomogram)
                    except Exception:
                        logger.debug("Coords3D getTomograms failed", exc_info=True)

            for tomogram in tomogramSources:
                localPoints: List[Tuple[float, float]] = []
                localZValues: List[float] = []

                try:
                    coordIterator = iterCoordinatesFn(tomogram)
                except Exception:
                    continue

                for coord in coordIterator:
                    try:
                        xValue = self._readCoordinate3dScalar(coord, "getX")
                        yValue = self._readCoordinate3dScalar(coord, "getY")
                        zValue = self._readCoordinate3dScalar(coord, "getZ")

                        if xValue is None or yValue is None or zValue is None:
                            continue

                        if not (
                                np.isfinite(xValue)
                                and np.isfinite(yValue)
                                and np.isfinite(zValue)
                        ):
                            continue

                        localPoints.append((xValue, yValue))
                        localZValues.append(zValue)

                        if len(localPoints) >= maxPoints:
                            break
                    except Exception:
                        continue

                if localPoints:
                    image = self._renderCoordinates3dTomogramOverlayPreview(
                        protocol=protocol,
                        tomogram=tomogram,
                        points=localPoints,
                        zValues=localZValues,
                        size=size,
                    )
                    if image is not None:
                        return image

                    remaining = maxPoints - len(points)
                    if remaining > 0:
                        points.extend(localPoints[:remaining])
                        zValues.extend(localZValues[:remaining])

                    if len(points) >= maxPoints:
                        break

        if not points:
            for coord in self._iterItemsDirect(output):
                try:
                    xValue = self._readCoordinate3dScalar(coord, "getX")
                    yValue = self._readCoordinate3dScalar(coord, "getY")
                    zValue = self._readCoordinate3dScalar(coord, "getZ")

                    if xValue is None or yValue is None or zValue is None:
                        continue

                    if not (
                            np.isfinite(xValue)
                            and np.isfinite(yValue)
                            and np.isfinite(zValue)
                    ):
                        continue

                    points.append((xValue, yValue))
                    zValues.append(zValue)

                    if len(points) >= maxPoints:
                        break
                except Exception:
                    continue

        if points:
            return self._buildCoordinatesScatterImage(
                title=self._getOutputClassName(output),
                points=points,
                zValues=zValues,
                is3d=True,
                size=size,
            )

        iterTomogramsFn = getattr(output, "iterVolumes", None)
        if callable(iterTomogramsFn):
            try:
                for tomogram in iterTomogramsFn():
                    getFileNameFn = getattr(tomogram, "getFileName", None)
                    if callable(getFileNameFn):
                        tomoPath = self._resolveFilePath(protocol, getFileNameFn())
                        if tomoPath is not None:
                            return self._renderVolumeFromPath(tomoPath, size=size)
                    break
            except Exception:
                logger.debug("Coords3D volume fallback preview failed", exc_info=True)

        getTomogramsFn = getattr(output, "getTomograms", None)
        if callable(getTomogramsFn):
            try:
                tomograms = getTomogramsFn()
                if hasattr(tomograms, "iterItems"):
                    for tomo in tomograms.iterItems():
                        getFileNameFn = getattr(tomo, "getFileName", None)
                        if callable(getFileNameFn):
                            tomoPath = self._resolveFilePath(protocol, getFileNameFn())
                            if tomoPath is not None:
                                return self._renderVolumeFromPath(tomoPath, size=size)
                        break
            except Exception:
                logger.debug("Coords3D getTomograms fallback preview failed", exc_info=True)

        return None

    def _renderCoordinates3dTomogramOverlayPreview(
            self,
            protocol,
            tomogram,
            points: List[Tuple[float, float]],
            zValues: List[float],
            size: int,
    ) -> Optional[Image.Image]:
        try:
            getFileNameFn = getattr(tomogram, "getFileName", None)
            if not callable(getFileNameFn):
                return None

            tomoPath = self._resolveFilePath(protocol, getFileNameFn())
            if tomoPath is None or not tomoPath.exists():
                return None

            volume, _props = readVolumeArray3d(str(tomoPath))
            volume = np.asarray(volume)

            if volume.ndim != 3:
                return None

            zSize, ySize, xSize = volume.shape
            if zSize <= 0 or ySize <= 0 or xSize <= 0:
                return None

            centerZ = zSize // 2
            slice2d = np.asarray(volume[centerZ], dtype=np.float32)

            baseImage = self._arrayToImage(slice2d)
            if baseImage is None:
                return None

            draw = ImageDraw.Draw(baseImage)

            zTolerance = max(3.0, float(zSize) * 0.04)

            selectedPoints: List[Tuple[float, float]] = []
            for point, zValue in zip(points, zValues):
                try:
                    xValue = float(point[0])
                    yValue = float(point[1])
                    zValue = float(zValue)

                    if abs(zValue - float(centerZ)) <= zTolerance:
                        selectedPoints.append((xValue, yValue))
                except Exception:
                    continue

            if not selectedPoints:
                selectedPoints = [(float(x), float(y)) for x, y in points[:1200]]

            radius = max(2, int(round(min(baseImage.size) * 0.010)))
            outlineWidth = max(1, int(round(radius * 0.55)))

            for xValue, yValue in selectedPoints[:1200]:
                try:
                    px = int(round(xValue))
                    py = int(round(yValue))

                    if px < 0 or py < 0 or px >= xSize or py >= ySize:
                        continue

                    draw.ellipse(
                        (
                            px - radius,
                            py - radius,
                            px + radius,
                            py + radius,
                        ),
                        outline=(255, 64, 64),
                        width=outlineWidth,
                    )
                except Exception:
                    continue

            label = f"{len(selectedPoints)} coords"
            draw.rounded_rectangle(
                (8, 8, 118, 30),
                radius=8,
                fill=(255, 255, 255),
                outline=(203, 213, 225),
                width=1,
            )
            draw.text((14, 13), label, fill=(51, 65, 85))

            return baseImage

        except Exception:
            logger.debug("Coordinates3D tomogram overlay thumbnail failed", exc_info=True)
            return None


    def _buildCoordinatesScatterImage(
            self,
            title: str,
            points: List[Tuple[float, float]],
            zValues: Optional[List[float]],
            is3d: bool,
            size: int,
    ) -> Optional[Image.Image]:
        fig = None
        try:
            cleanPoints: List[Tuple[float, float]] = []
            cleanZ: List[float] = []

            for index, point in enumerate(points):
                try:
                    xValue = float(point[0])
                    yValue = float(point[1])

                    if not np.isfinite(xValue) or not np.isfinite(yValue):
                        continue

                    cleanPoints.append((xValue, yValue))

                    if zValues is not None and index < len(zValues):
                        zValue = float(zValues[index])
                        cleanZ.append(zValue if np.isfinite(zValue) else 0.0)
                except Exception:
                    continue

            if not cleanPoints:
                return None

            xValues = [point[0] for point in cleanPoints]
            yValues = [point[1] for point in cleanPoints]

            fig = plt.figure(figsize=(5.2, 3.35), dpi=130)
            ax = fig.add_subplot(111)

            ax.set_facecolor("white")
            ax.grid(True, linestyle="-", linewidth=0.45, alpha=0.25)
            ax.set_title(str(title or "Coordinates"), fontsize=11, pad=6)
            ax.set_xlabel("X", fontsize=9)
            ax.set_ylabel("Y", fontsize=9)
            ax.tick_params(axis="both", labelsize=8)

            pointCount = len(cleanPoints)
            markerSize = 18 if pointCount <= 250 else 10 if pointCount <= 700 else 6

            if is3d and cleanZ and len(cleanZ) == len(cleanPoints):
                ax.scatter(
                    xValues,
                    yValues,
                    c=cleanZ,
                    cmap="viridis",
                    s=markerSize,
                    alpha=0.80,
                    linewidths=0,
                )
            else:
                ax.scatter(
                    xValues,
                    yValues,
                    s=markerSize,
                    alpha=0.80,
                    linewidths=0,
                    color="tab:blue",
                )

            xMin = min(xValues)
            xMax = max(xValues)
            yMin = min(yValues)
            yMax = max(yValues)

            xPad = max(1.0, (xMax - xMin) * 0.06)
            yPad = max(1.0, (yMax - yMin) * 0.06)

            ax.set_xlim(xMin - xPad, xMax + xPad)
            ax.set_ylim(yMax + yPad, yMin - yPad)
            ax.set_aspect("equal", adjustable="box")

            subtitle = f"{pointCount} coordinates"
            ax.text(
                0.99,
                0.02,
                subtitle,
                transform=ax.transAxes,
                ha="right",
                va="bottom",
                fontsize=8,
                color="#334155",
                bbox={
                    "boxstyle": "round,pad=0.25",
                    "facecolor": "white",
                    "edgecolor": "#cbd5e1",
                    "alpha": 0.85,
                },
            )

            fig.subplots_adjust(
                left=0.13,
                right=0.96,
                top=0.86,
                bottom=0.18,
            )

            buffer = io.BytesIO()
            fig.savefig(
                buffer,
                format="png",
                facecolor="white",
                edgecolor="white",
                dpi=130,
            )
            buffer.seek(0)

            return Image.open(buffer).convert("RGB")
        except Exception:
            logger.debug("Coordinates scatter thumbnail failed", exc_info=True)
            return None
        finally:
            if fig is not None:
                plt.close(fig)

    def _renderSubTomogramsPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []
        maxItems = 4

        for item in self._iterItemsDirect(output):
            try:
                for candidate in self._iterSubTomogramPreviewCandidates(item):
                    tile = self._renderVolumePreviewFromItem(protocol, candidate, size=size)
                    if tile is not None:
                        tiles.append(tile)
                        break

                if len(tiles) >= maxItems:
                    break
            except Exception:
                continue

        if not tiles:
            tile = self._renderVolumePreviewFromItem(protocol, output, size=size)
            if tile is not None:
                tiles.append(tile)

        if not tiles:
            return None

        return self._composeParticleMosaic(
            tiles=tiles[:maxItems],
            targetWidth=size,
            maxCols=2,
        )

    def _iterSubTomogramPreviewCandidates(self, item) -> Iterable[Any]:
        seen: Set[int] = set()

        def emit(candidate):
            if candidate is None:
                return
            candidateId = id(candidate)
            if candidateId in seen:
                return
            seen.add(candidateId)
            yield candidate

        for getterName in ("getRepresentative", "getRepresentativeItem", "getRep"):
            getter = getattr(item, getterName, None)
            if callable(getter):
                try:
                    representative = getter()
                    for candidate in emit(representative):
                        yield candidate
                except Exception:
                    pass

        for candidate in emit(item):
            yield candidate

        for iteratorName in ("iterSubtomos", "iterItems"):
            iteratorFn = getattr(item, iteratorName, None)
            if not callable(iteratorFn):
                continue

            try:
                iterator = iteratorFn()
            except TypeError:
                try:
                    iterator = iteratorFn(iterate=False)
                except Exception:
                    iterator = None
            except Exception:
                iterator = None

            if iterator is None:
                continue

            try:
                for subItem in iterator:
                    for candidate in emit(subItem):
                        yield candidate
                    break
            except Exception:
                continue

    def _renderVolumePreviewFromItem(
            self,
            protocol,
            item,
            size: int,
    ) -> Optional[Image.Image]:
        for getterName in ("getFileName", "getVolName"):
            getter = getattr(item, getterName, None)
            if not callable(getter):
                continue

            try:
                rawPath = getter()
            except Exception:
                continue

            if not rawPath:
                continue

            volumePath = self._resolveFilePath(protocol, rawPath)
            if volumePath is None or not volumePath.exists():
                continue

            image = self._renderVolumeFromPath(volumePath, size=size)
            if image is not None:
                return image

        getLocationFn = getattr(item, "getLocation", None)
        if callable(getLocationFn):
            try:
                location = getLocationFn()
                rawPath = None

                if isinstance(location, (list, tuple)) and location:
                    rawPath = location[-1]
                elif location:
                    rawPath = location

                if rawPath:
                    volumePath = self._resolveFilePath(protocol, rawPath)
                    if volumePath is not None and volumePath.exists():
                        image = self._renderVolumeFromPath(volumePath, size=size)
                        if image is not None:
                            return image
            except Exception:
                pass

        return None

    def _renderMaskPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        className = self._getOutputClassName(output).lower()

        if isinstance(output, VolumeMask) or "volumemask" in className:
            return self._renderVolumeMaskPreview(protocol, output, size=size)

        if isinstance(output, Mask) or className == "mask":
            return self._renderImageMaskPreview(protocol, output)

        tiles: List[Image.Image] = []
        maxItems = 4

        for item in self._iterItemsDirect(output):
            try:
                image = self._renderMaskPreview(protocol, item, size=size)
                if image is not None:
                    tiles.append(image)

                if len(tiles) >= maxItems:
                    break
            except Exception:
                continue

        if not tiles:
            image = self._renderVolumeMaskPreview(protocol, output, size=size)
            if image is not None:
                return image

            return self._renderImageMaskPreview(protocol, output)

        return self._composeCleanGrid(
            tiles=tiles[:maxItems],
            maxCols=2,
            targetWidth=size,
            background=(246, 249, 252),
        )

    def _renderVolumeMaskPreview(
            self,
            protocol,
            maskItem,
            size: int,
    ) -> Optional[Image.Image]:
        maskPath = self._resolveVolumePathFromItem(
            protocol=protocol,
            item=maskItem,
            includeVolName=True,
        )

        if maskPath is None or not maskPath.exists():
            return None

        image = self._renderTomoMaskOnlyFromPath(maskPath)
        if image is not None:
            return image

        return self._renderVolumeFromPath(maskPath, size=size)

    def _renderImageMaskPreview(
            self,
            protocol,
            maskItem,
    ) -> Optional[Image.Image]:
        sourcePath, sourceIndex = self._resolveImageSourceFromItem(maskItem)
        if not sourcePath:
            return None

        image = self._readImagePreview(protocol, sourcePath, sourceIndex)
        if image is None:
            return None

        return self._drawSimplePreviewLabel(
            image=image,
            label="Mask",
        )

    def _renderTomoMasksPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []
        maxItems = 4

        if isinstance(output, SetOfTomoMasks):
            maskIterator = self._iterItemsDirect(output)
        else:
            maskIterator = iter([output])

        for maskItem in maskIterator:
            try:
                tile = self._renderTomoMaskPreviewFromItem(
                    protocol=protocol,
                    maskItem=maskItem,
                    size=size,
                )
                if tile is not None:
                    tiles.append(tile)

                if len(tiles) >= maxItems:
                    break
            except Exception:
                logger.debug("TomoMask preview failed", exc_info=True)

        if not tiles:
            return None

        return self._composeCleanGrid(
            tiles=tiles[:maxItems],
            maxCols=2,
            targetWidth=size,
            background=(246, 249, 252),
        )

    def _renderTomoMaskPreviewFromItem(
            self,
            protocol,
            maskItem,
            size: int,
    ) -> Optional[Image.Image]:
        maskPath = self._resolveVolumePathFromItem(
            protocol=protocol,
            item=maskItem,
            includeVolName=False,
        )

        if maskPath is None or not maskPath.exists():
            return None

        tomogramPath = self._resolveTomoMaskReferencePath(
            protocol=protocol,
            maskItem=maskItem,
        )

        if tomogramPath is not None and tomogramPath.exists():
            image = self._renderTomoMaskOverlayFromPaths(
                tomogramPath=tomogramPath,
                maskPath=maskPath,
            )
            if image is not None:
                return image

        return self._renderTomoMaskOnlyFromPath(maskPath)

    def _resolveTomoMaskReferencePath(self, protocol, maskItem) -> Optional[Path]:
        getTomogramFn = getattr(maskItem, "getTomogram", None)
        if callable(getTomogramFn):
            try:
                tomogram = getTomogramFn()
                tomogramPath = self._resolveVolumePathFromItem(
                    protocol=protocol,
                    item=tomogram,
                    includeVolName=True,
                )
                if tomogramPath is not None and tomogramPath.exists():
                    return tomogramPath
            except Exception:
                pass

        getVolNameFn = getattr(maskItem, "getVolName", None)
        if callable(getVolNameFn):
            try:
                rawPath = getVolNameFn()
                if rawPath:
                    tomogramPath = self._resolveFilePath(protocol, rawPath)
                    if tomogramPath is not None and tomogramPath.exists():
                        return tomogramPath
            except Exception:
                pass

        return None

    def _resolveVolumePathFromItem(
            self,
            protocol,
            item,
            includeVolName: bool = True,
    ) -> Optional[Path]:
        getterNames = ["getFileName"]

        if includeVolName:
            getterNames.append("getVolName")

        for getterName in getterNames:
            getter = getattr(item, getterName, None)
            if not callable(getter):
                continue

            try:
                rawPath = getter()
            except Exception:
                continue

            sourcePath, _sourceIndex = self._splitIndexedImagePath(rawPath)
            if not sourcePath:
                continue

            volumePath = self._resolveFilePath(protocol, sourcePath)
            if volumePath is not None and volumePath.exists():
                return volumePath

        getLocationFn = getattr(item, "getLocation", None)
        if callable(getLocationFn):
            try:
                sourcePath, _sourceIndex = self._splitIndexedImagePath(getLocationFn())
                if sourcePath:
                    volumePath = self._resolveFilePath(protocol, sourcePath)
                    if volumePath is not None and volumePath.exists():
                        return volumePath
            except Exception:
                pass

        return None

    def _readVolumeArrayFromPath(self, volumePath: Path) -> Optional[np.ndarray]:
        try:
            volume, _props = readVolumeArray3d(str(volumePath))
            volume = np.asarray(volume)

            if volume.ndim != 3 or volume.size == 0:
                return None

            return volume
        except Exception:
            return None

    def _pickMaskRepresentativeSlice(self, maskVolume: np.ndarray) -> int:
        try:
            mask = np.asarray(maskVolume, dtype=np.float32)
            if mask.ndim != 3 or mask.shape[0] <= 0:
                return 0

            foreground = np.isfinite(mask) & (np.abs(mask) > 1e-6)
            counts = foreground.reshape(mask.shape[0], -1).sum(axis=1)

            if counts.size > 0 and int(counts.max()) > 0:
                return int(np.argmax(counts))

            return int(mask.shape[0] // 2)
        except Exception:
            return 0

    def _renderTomoMaskOverlayFromPaths(
            self,
            tomogramPath: Path,
            maskPath: Path,
    ) -> Optional[Image.Image]:
        try:
            tomogramVolume = self._readVolumeArrayFromPath(tomogramPath)
            maskVolume = self._readVolumeArrayFromPath(maskPath)

            if tomogramVolume is None or maskVolume is None:
                return None

            maskZSize, _maskYSize, _maskXSize = maskVolume.shape
            tomoZSize, _tomoYSize, _tomoXSize = tomogramVolume.shape

            if maskZSize <= 0 or tomoZSize <= 0:
                return None

            maskZ = self._pickMaskRepresentativeSlice(maskVolume)

            if maskZSize > 1 and tomoZSize > 1:
                tomoZ = int(round(maskZ * float(tomoZSize - 1) / float(maskZSize - 1)))
            else:
                tomoZ = tomoZSize // 2

            maskZ = max(0, min(maskZ, maskZSize - 1))
            tomoZ = max(0, min(tomoZ, tomoZSize - 1))

            tomogramSlice = np.asarray(tomogramVolume[tomoZ], dtype=np.float32)
            maskSlice = np.asarray(maskVolume[maskZ], dtype=np.float32)

            baseImage = self._arrayToImage(tomogramSlice)
            if baseImage is None:
                return None

            baseImage = baseImage.convert("RGB")
            alpha = self._buildTomoMaskAlpha(maskSlice, baseImage.size)
            if alpha is None:
                return baseImage

            overlay = Image.new("RGB", baseImage.size, (255, 64, 64))
            baseImage.paste(overlay, (0, 0), alpha)

            draw = ImageDraw.Draw(baseImage)
            label = "Mask overlay"
            draw.rounded_rectangle(
                (8, 8, 128, 30),
                radius=8,
                fill=(255, 255, 255),
                outline=(203, 213, 225),
                width=1,
            )
            draw.text((14, 13), label, fill=(51, 65, 85))

            return baseImage

        except Exception:
            logger.debug("TomoMask overlay thumbnail failed", exc_info=True)
            return None

    def _renderTomoMaskOnlyFromPath(self, maskPath: Path) -> Optional[Image.Image]:
        try:
            maskVolume = self._readVolumeArrayFromPath(maskPath)
            if maskVolume is None:
                return None

            zSize, _ySize, _xSize = maskVolume.shape
            if zSize <= 0:
                return None

            maskZ = self._pickMaskRepresentativeSlice(maskVolume)
            maskZ = max(0, min(maskZ, zSize - 1))

            maskSlice = np.asarray(maskVolume[maskZ], dtype=np.float32)

            baseImage = Image.new("RGB", (maskSlice.shape[1], maskSlice.shape[0]), (15, 23, 42))
            alpha = self._buildTomoMaskAlpha(maskSlice, baseImage.size)

            if alpha is None:
                return self._arrayToImage(maskSlice)

            overlay = Image.new("RGB", baseImage.size, (255, 64, 64))
            baseImage.paste(overlay, (0, 0), alpha)

            draw = ImageDraw.Draw(baseImage)
            label = "Mask"
            draw.rounded_rectangle(
                (8, 8, 78, 30),
                radius=8,
                fill=(255, 255, 255),
                outline=(203, 213, 225),
                width=1,
            )
            draw.text((14, 13), label, fill=(51, 65, 85))

            return baseImage

        except Exception:
            logger.debug("TomoMask standalone thumbnail failed", exc_info=True)
            return None

    def _buildTomoMaskAlpha(
            self,
            maskSlice: np.ndarray,
            targetSize: Tuple[int, int],
    ) -> Optional[Image.Image]:
        try:
            arr = np.asarray(maskSlice, dtype=np.float32)
            if arr.ndim != 2 or arr.size == 0:
                return None

            finiteMask = np.isfinite(arr)
            if not finiteMask.any():
                return None

            foreground = finiteMask & (np.abs(arr) > 1e-6)
            if not foreground.any():
                return None

            alpha = np.zeros(arr.shape, dtype=np.uint8)
            alpha[foreground] = 115

            alphaImage = Image.fromarray(alpha, mode="L")

            if alphaImage.size != targetSize:
                alphaImage = alphaImage.resize(
                    targetSize,
                    resample=Image.Resampling.NEAREST,
                )

            return alphaImage
        except Exception:
            return None

    def _renderVolumeLikePreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        try:
            getFileNameFn = getattr(output, "getFileName", None)
            if callable(getFileNameFn):
                volumePath = self._resolveFilePath(protocol, getFileNameFn())
                if volumePath is not None:
                    image = self._renderVolumeFromPath(volumePath, size=size)
                    if image is not None:
                        return image
        except Exception:
            logger.debug("Direct volume-like preview failed", exc_info=True)

        for item in self._iterPreviewItems(output, maxItems=1):
            try:
                getFileNameFn = getattr(item, "getFileName", None)
                if callable(getFileNameFn):
                    volumePath = self._resolveFilePath(protocol, getFileNameFn())
                    if volumePath is not None:
                        image = self._renderVolumeFromPath(volumePath, size=size)
                        if image is not None:
                            return image
            except Exception:
                continue

        return None

    def _renderNormalModesPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        modes: List[Any] = []

        if isinstance(output, (SetOfNormalModes, SetOfPrincipalComponents)):
            modeIterator = self._iterItemsDirect(output)
        else:
            modeIterator = iter([output])

        for mode in modeIterator:
            try:
                if not self._isEnabled(mode):
                    continue

                modes.append(mode)

                if len(modes) >= 80:
                    break
            except Exception:
                continue

        if not modes:
            return None

        image = self._buildNormalModesPlotImage(
            output=output,
            modes=modes,
            size=size,
        )
        if image is not None:
            return image

        return self._buildNormalModesCardImage(
            output=output,
            modes=modes,
            size=size,
        )

    def _buildNormalModesPlotImage(
            self,
            output,
            modes: Sequence[Any],
            size: int,
    ) -> Optional[Image.Image]:
        fig = None

        try:
            data: List[Tuple[int, Optional[float], Optional[float]]] = []

            for index, mode in enumerate(modes):
                score = self._safeScalarValue(
                    getattr(mode, "getScore", lambda: None)()
                )
                collectivity = self._safeScalarValue(
                    getattr(mode, "getCollectivity", lambda: None)()
                )

                scoreValue = None
                collectivityValue = None

                try:
                    if score is not None:
                        scoreValue = float(score)
                        if not np.isfinite(scoreValue):
                            scoreValue = None
                except Exception:
                    scoreValue = None

                try:
                    if collectivity is not None:
                        collectivityValue = float(collectivity)
                        if not np.isfinite(collectivityValue):
                            collectivityValue = None
                except Exception:
                    collectivityValue = None

                if scoreValue is None and collectivityValue is None:
                    continue

                data.append((index + 1, scoreValue, collectivityValue))

            if not data:
                return None

            xValues = [item[0] for item in data]
            scoreValues = [item[1] for item in data]
            collectivityValues = [item[2] for item in data]

            hasScore = any(value is not None for value in scoreValues)
            hasCollectivity = any(value is not None for value in collectivityValues)

            if not hasScore and not hasCollectivity:
                return None

            title = self._getOutputClassName(output) or "Normal modes"
            title = "Principal components" if "principal" in title.lower() else "Normal modes"

            fig = plt.figure(figsize=(5.4, 3.35), dpi=130)
            ax = fig.add_subplot(111)

            ax.set_facecolor("white")
            ax.grid(True, linestyle="-", linewidth=0.55, alpha=0.35)
            ax.set_title(title, fontsize=11, pad=6)
            ax.set_xlabel("Mode index", fontsize=9)
            ax.tick_params(axis="both", labelsize=8)

            legendHandles = []

            if hasScore:
                scoreX = [x for x, value in zip(xValues, scoreValues) if value is not None]
                scoreY = [value for value in scoreValues if value is not None]

                ax.set_ylabel("Score", fontsize=9)

                lineScore, = ax.plot(
                    scoreX,
                    scoreY,
                    marker="o",
                    markersize=5.0,
                    linewidth=2.5,
                    color="tab:blue",
                    label="Score",
                    zorder=4,
                )
                legendHandles.append(lineScore)

            if hasCollectivity:
                collectivityX = [x for x, value in zip(xValues, collectivityValues) if value is not None]
                collectivityY = [value for value in collectivityValues if value is not None]

                if hasScore:
                    collectivityPlot = ax.twinx()
                    collectivityPlot.set_ylabel("Collectivity", color="tab:green", fontsize=9)
                    collectivityPlot.tick_params(axis="y", labelsize=8, colors="tab:green")
                else:
                    collectivityPlot = ax
                    collectivityPlot.set_ylabel("Collectivity", fontsize=9)

                lineCollectivity, = collectivityPlot.plot(
                    collectivityX,
                    collectivityY,
                    marker="o",
                    markersize=5.0,
                    linewidth=2.5,
                    color="tab:green",
                    label="Collectivity",
                    zorder=3,
                )
                legendHandles.append(lineCollectivity)

            if legendHandles:
                ax.legend(
                    handles=legendHandles,
                    loc="upper left",
                    fontsize=8,
                    frameon=False,
                    handlelength=2.2,
                    borderaxespad=0.2,
                )

            subtitle = f"{len(modes)} modes"
            ax.text(
                0.99,
                0.02,
                subtitle,
                transform=ax.transAxes,
                ha="right",
                va="bottom",
                fontsize=8,
                color="#334155",
                bbox={
                    "boxstyle": "round,pad=0.25",
                    "facecolor": "white",
                    "edgecolor": "#cbd5e1",
                    "alpha": 0.85,
                },
            )

            fig.subplots_adjust(
                left=0.14,
                right=0.86,
                top=0.86,
                bottom=0.18,
            )

            buffer = io.BytesIO()
            fig.savefig(
                buffer,
                format="png",
                facecolor="white",
                edgecolor="white",
                dpi=130,
            )
            buffer.seek(0)

            return Image.open(buffer).convert("RGB")

        except Exception:
            logger.debug("Normal modes plot thumbnail failed", exc_info=True)
            return None
        finally:
            if fig is not None:
                plt.close(fig)

    def _buildNormalModesCardImage(
            self,
            output,
            modes: Sequence[Any],
            size: int,
    ) -> Image.Image:
        width = max(360, int(size))
        height = max(220, int(round(width * 0.58)))

        image = Image.new("RGB", (width, height), (246, 249, 252))
        draw = ImageDraw.Draw(image)

        margin = max(18, int(round(width * 0.05)))
        card = (
            margin,
            margin,
            width - margin,
            height - margin,
        )

        draw.rounded_rectangle(
            card,
            radius=18,
            fill=(255, 255, 255),
            outline=(203, 213, 225),
            width=1,
        )

        className = self._getOutputClassName(output) or "NormalModes"
        badgeText = "PCs" if "principal" in className.lower() else "Modes"

        badgeBox = (
            margin + 16,
            margin + 16,
            margin + 104,
            margin + 46,
        )

        draw.rounded_rectangle(
            badgeBox,
            radius=9,
            fill=(226, 232, 240),
            outline=(203, 213, 225),
            width=1,
        )
        draw.text((badgeBox[0] + 12, badgeBox[1] + 8), badgeText, fill=(15, 23, 42))

        title = "Principal components" if "principal" in className.lower() else "Normal modes"
        draw.text((margin + 16, margin + 58), title, fill=(15, 23, 42))

        draw.text(
            (margin + 16, margin + 88),
            f"{len(modes)} items",
            fill=(51, 65, 85),
        )

        firstFile = None
        for mode in modes:
            getter = getattr(mode, "getModeFile", None)
            if not callable(getter):
                continue

            try:
                value = self._safeScalarValue(getter())
                if value:
                    firstFile = Path(str(value)).name
                    break
            except Exception:
                continue

        if firstFile:
            firstFile = self._ellipsizeText(firstFile, 42)
            draw.text((margin + 16, margin + 124), firstFile, fill=(100, 116, 139))
        else:
            draw.text((margin + 16, margin + 124), "Mode metadata", fill=(100, 116, 139))

        return image

    def _renderSequencesPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []
        maxItems = 4

        if isinstance(output, SetOfSequences):
            sequenceIterator = self._iterItemsDirect(output)
        else:
            sequenceIterator = iter([output])

        for sequence in sequenceIterator:
            try:
                tile = self._renderSequenceItemPreview(
                    protocol=protocol,
                    sequence=sequence,
                    size=size,
                )
                if tile is not None:
                    tiles.append(tile)

                if len(tiles) >= maxItems:
                    break
            except Exception:
                logger.debug("Sequence preview failed", exc_info=True)

        if not tiles:
            return None

        if len(tiles) == 1:
            return tiles[0]

        return self._composeCleanGrid(
            tiles=tiles[:maxItems],
            maxCols=2,
            targetWidth=size,
            background=(246, 249, 252),
        )

    def _renderSequenceItemPreview(
            self,
            protocol,
            sequence,
            size: int,
    ) -> Optional[Image.Image]:
        info = self._extractSequenceInfo(
            protocol=protocol,
            sequence=sequence,
        )

        return self._buildSequenceCardImage(
            name=info.get("name") or "Sequence",
            sequenceId=info.get("id"),
            sequenceType=info.get("type") or "Sequence",
            sequenceLength=info.get("length"),
            fileName=info.get("fileName"),
            preview=info.get("preview"),
            size=size,
        )

    def _extractSequenceInfo(
            self,
            protocol,
            sequence,
    ) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "name": None,
            "id": None,
            "type": None,
            "length": None,
            "fileName": None,
            "preview": None,
        }

        for getterName, key in (
                ("getSeqName", "name"),
                ("getId", "id"),
                ("getDescription", "description"),
        ):
            getter = getattr(sequence, getterName, None)
            if not callable(getter):
                continue

            try:
                value = self._safeScalarValue(getter())
                if value:
                    info[key] = str(value)
            except Exception:
                continue

        getIsAminoacidsFn = getattr(sequence, "getIsAminoacids", None)
        if callable(getIsAminoacidsFn):
            try:
                isAmino = self._safeScalarValue(getIsAminoacidsFn())
                info["type"] = "Protein" if bool(isAmino) else "Nucleotide"
            except Exception:
                info["type"] = "Sequence"

        sequenceText = None
        getSequenceFn = getattr(sequence, "getSequence", None)
        if callable(getSequenceFn):
            try:
                sequenceText = self._safeScalarValue(getSequenceFn())
            except Exception:
                sequenceText = None

        if sequenceText:
            cleanSequence = "".join(str(sequenceText).split())
            info["length"] = len(cleanSequence)
            info["preview"] = cleanSequence[:64]

        getFileNameFn = getattr(sequence, "getFileName", None)
        if callable(getFileNameFn):
            try:
                rawPath = self._safeScalarValue(getFileNameFn())
            except Exception:
                rawPath = None

            if rawPath:
                sourcePath, _sourceIndex = self._splitIndexedImagePath(rawPath)
                if sourcePath:
                    resolvedPath = self._resolveFilePath(protocol, sourcePath)
                    filePath = resolvedPath if resolvedPath is not None else Path(str(sourcePath))
                    info["fileName"] = filePath.name or Path(str(sourcePath)).name

                    if info.get("length") is None or info.get("preview") is None:
                        fileInfo = self._readSequenceFileInfo(filePath)
                        for key, value in fileInfo.items():
                            if info.get(key) is None and value is not None:
                                info[key] = value

        if not info.get("name"):
            info["name"] = info.get("id") or info.get("fileName") or "Sequence"

        if not info.get("type"):
            info["type"] = "Sequence"

        return info

    def _readSequenceFileInfo(self, filePath: Path) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "name": None,
            "id": None,
            "length": None,
            "preview": None,
        }

        if filePath is None or not filePath.exists():
            return info

        try:
            sequenceParts: List[str] = []
            header = None

            with filePath.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue

                    if text.startswith(">"):
                        if header is None:
                            header = text[1:].strip()
                        elif sequenceParts:
                            break
                        continue

                    if text.startswith(";"):
                        continue

                    sequenceParts.append(text)

                    if sum(len(part) for part in sequenceParts) >= 5000:
                        break

            if header:
                info["id"] = header.split()[0] if header.split() else header
                info["name"] = header

            cleanSequence = "".join(sequenceParts)
            cleanSequence = "".join(cleanSequence.split())

            if cleanSequence:
                info["length"] = len(cleanSequence)
                info["preview"] = cleanSequence[:64]

        except Exception:
            return info

        return info

    def _buildSequenceCardImage(
            self,
            name: str,
            sequenceId: Optional[str],
            sequenceType: str,
            sequenceLength: Optional[int],
            fileName: Optional[str],
            preview: Optional[str],
            size: int,
    ) -> Image.Image:
        width = max(360, int(size))
        height = max(220, int(round(width * 0.58)))

        image = Image.new("RGB", (width, height), (246, 249, 252))
        draw = ImageDraw.Draw(image)

        margin = max(18, int(round(width * 0.05)))
        card = (
            margin,
            margin,
            width - margin,
            height - margin,
        )

        draw.rounded_rectangle(
            card,
            radius=18,
            fill=(255, 255, 255),
            outline=(203, 213, 225),
            width=1,
        )

        badgeText = self._ellipsizeText(sequenceType or "Sequence", 12)
        badgeW = max(92, min(160, 28 + len(badgeText) * 7))
        badgeH = 30
        badgeBox = (
            margin + 16,
            margin + 16,
            margin + 16 + badgeW,
            margin + 16 + badgeH,
        )

        draw.rounded_rectangle(
            badgeBox,
            radius=9,
            fill=(226, 232, 240),
            outline=(203, 213, 225),
            width=1,
        )
        draw.text((badgeBox[0] + 12, badgeBox[1] + 8), badgeText, fill=(15, 23, 42))

        title = self._ellipsizeText(name or "Sequence", 34)
        draw.text((margin + 16, margin + 58), title, fill=(15, 23, 42))

        subtitleParts: List[str] = []
        if sequenceId:
            subtitleParts.append(str(sequenceId))
        if fileName:
            subtitleParts.append(str(fileName))

        subtitle = " · ".join(subtitleParts) if subtitleParts else "Sequence data"
        subtitle = self._ellipsizeText(subtitle, 42)
        draw.text((margin + 16, margin + 86), subtitle, fill=(51, 65, 85))

        y = margin + 122

        if sequenceLength is not None:
            stat = f"{sequenceLength} residues"
        else:
            stat = "Unknown length"

        draw.rounded_rectangle(
            (margin + 16, y, margin + 170, y + 28),
            radius=8,
            fill=(248, 250, 252),
            outline=(226, 232, 240),
            width=1,
        )
        draw.text((margin + 28, y + 8), stat, fill=(71, 85, 105))

        if preview:
            previewText = self._ellipsizeText(preview, 46)
            draw.text((margin + 16, y + 42), previewText, fill=(100, 116, 139))

        return image

    def _renderFlexPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        className = self._getOutputClassName(output).lower()

        if "setofclassesstructflex" in className or "classstructflex" in className:
            image = self._renderFlexClassRepresentativesPreview(
                protocol=protocol,
                output=output,
                size=size,
                representativeKind="atom",
            )
            if image is not None:
                return image

        if "setofclassesflex" in className or className == "classflex":
            image = self._renderFlexClassRepresentativesPreview(
                protocol=protocol,
                output=output,
                size=size,
                representativeKind="volume",
            )
            if image is not None:
                return image

        if "setofatomstructflex" in className or "atomstructflex" in className:
            image = self._renderAtomStructPreview(protocol, output, size=size)
            if image is not None:
                return image

            return self._buildFlexCardImage(
                output=output,
                title="AtomStruct Flex",
                size=size,
            )

        if "setofvolumesflex" in className:
            image = self._renderClasses3dOrVolumesPreview(protocol, output, size=size)
            if image is not None:
                return image

            image = self._renderVolumeLikePreview(protocol, output, size=size)
            if image is not None:
                return image

            return self._buildFlexCardImage(
                output=output,
                title="Volumes Flex",
                size=size,
            )

        if "volumeflex" in className:
            image = self._renderVolumeLikePreview(protocol, output, size=size)
            if image is not None:
                return image

            return self._buildFlexCardImage(
                output=output,
                title="Volume Flex",
                size=size,
            )

        if "setofparticlesflex" in className or "particleflex" in className:
            image = self._renderParticlesOrClasses2dPreview(protocol, output, size=size)
            if image is not None:
                return image

            return self._buildFlexCardImage(
                output=output,
                title="Particles Flex",
                size=size,
            )

        return self._buildFlexCardImage(
            output=output,
            title="Flex",
            size=size,
        )

    def _renderFlexClassRepresentativesPreview(
            self,
            protocol,
            output,
            size: int,
            representativeKind: str,
    ) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []

        for representative in self._iterFlexClassRepresentatives(output, maxItems=4):
            try:
                if representativeKind == "atom":
                    tile = self._renderAtomStructPreview(
                        protocol=protocol,
                        output=representative,
                        size=size,
                    )
                else:
                    tile = self._renderVolumeLikePreview(
                        protocol=protocol,
                        output=representative,
                        size=size,
                    )

                if tile is not None:
                    tiles.append(tile)

                if len(tiles) >= 4:
                    break

            except Exception:
                logger.debug("Flex representative preview failed", exc_info=True)

        if tiles:
            return self._composeCleanGrid(
                tiles=tiles[:4],
                maxCols=2,
                targetWidth=size,
                background=(246, 249, 252),
            )

        title = "Classes Struct Flex" if representativeKind == "atom" else "Classes Flex"

        return self._buildFlexCardImage(
            output=output,
            title=title,
            size=size,
        )

    def _iterFlexClassRepresentatives(self, output, maxItems: int) -> Iterable[Any]:
        yielded = 0

        iterRepresentativesFn = getattr(output, "iterRepresentatives", None)
        if callable(iterRepresentativesFn):
            try:
                for representative in iterRepresentativesFn():
                    if representative is None:
                        continue

                    yield representative
                    yielded += 1

                    if yielded >= maxItems:
                        return
            except Exception:
                pass

        for classItem in self._iterItemsDirect(output):
            try:
                representative = None

                hasRepresentativeFn = getattr(classItem, "hasRepresentative", None)
                if callable(hasRepresentativeFn):
                    try:
                        if not hasRepresentativeFn():
                            continue
                    except Exception:
                        pass

                for getterName in ("getRepresentative", "getRep"):
                    getter = getattr(classItem, getterName, None)
                    if not callable(getter):
                        continue

                    try:
                        representative = getter()
                    except Exception:
                        representative = None

                    if representative is not None:
                        break

                if representative is None:
                    continue

                yield representative
                yielded += 1

                if yielded >= maxItems:
                    return

            except Exception:
                continue

    def _buildFlexCardImage(
            self,
            output,
            title: str,
            size: int,
    ) -> Image.Image:
        width = max(360, int(size))
        height = max(220, int(round(width * 0.58)))

        image = Image.new("RGB", (width, height), (246, 249, 252))
        draw = ImageDraw.Draw(image)

        margin = max(18, int(round(width * 0.05)))
        card = (
            margin,
            margin,
            width - margin,
            height - margin,
        )

        draw.rounded_rectangle(
            card,
            radius=18,
            fill=(255, 255, 255),
            outline=(203, 213, 225),
            width=1,
        )

        badgeBox = (
            margin + 16,
            margin + 16,
            margin + 104,
            margin + 46,
        )

        draw.rounded_rectangle(
            badgeBox,
            radius=9,
            fill=(226, 232, 240),
            outline=(203, 213, 225),
            width=1,
        )
        draw.text((badgeBox[0] + 12, badgeBox[1] + 8), "Flex", fill=(15, 23, 42))

        draw.text((margin + 16, margin + 58), title or "Flex", fill=(15, 23, 42))

        className = self._getOutputClassName(output)
        className = self._ellipsizeText(className or "Flex object", 42)

        draw.text((margin + 16, margin + 88), className, fill=(51, 65, 85))

        progName = self._getFlexProgramName(output)
        if progName:
            progName = self._ellipsizeText(progName, 42)
            draw.text((margin + 16, margin + 124), progName, fill=(100, 116, 139))
        else:
            draw.text((margin + 16, margin + 124), "Flex metadata", fill=(100, 116, 139))

        sizeHint = self._safeOutputSize(output)
        if sizeHint is not None:
            draw.rounded_rectangle(
                (margin + 16, margin + 154, margin + 132, margin + 182),
                radius=8,
                fill=(248, 250, 252),
                outline=(226, 232, 240),
                width=1,
            )
            draw.text((margin + 28, margin + 162), f"{sizeHint} items", fill=(71, 85, 105))

        return image

    def _getFlexProgramName(self, output) -> Optional[str]:
        getFlexInfoFn = getattr(output, "getFlexInfo", None)
        if not callable(getFlexInfoFn):
            return None

        try:
            flexInfo = getFlexInfoFn()
        except Exception:
            return None

        if flexInfo is None:
            return None

        getProgNameFn = getattr(flexInfo, "getProgName", None)
        if not callable(getProgNameFn):
            return None

        try:
            progName = self._safeScalarValue(getProgNameFn())
            return str(progName) if progName else None
        except Exception:
            return None

    def _renderAtomStructPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []
        maxItems = 4

        if isinstance(output, (SetOfAtomStructs, SetOfPDBs)):
            atomIterator = self._iterItemsDirect(output)
        else:
            atomIterator = iter([output])

        for atomStruct in atomIterator:
            try:
                tile = self._renderAtomStructItemPreview(
                    protocol=protocol,
                    atomStruct=atomStruct,
                    size=size,
                )
                if tile is not None:
                    tiles.append(tile)

                if len(tiles) >= maxItems:
                    break
            except Exception:
                logger.debug("AtomStruct preview failed", exc_info=True)

        if not tiles:
            return None

        if len(tiles) == 1:
            return tiles[0]

        return self._composeCleanGrid(
            tiles=tiles[:maxItems],
            maxCols=2,
            targetWidth=size,
            background=(246, 249, 252),
        )

    def _renderAtomStructItemPreview(
            self,
            protocol,
            atomStruct,
            size: int,
    ) -> Optional[Image.Image]:
        getFileNameFn = getattr(atomStruct, "getFileName", None)
        if not callable(getFileNameFn):
            return None

        try:
            rawPath = getFileNameFn()
        except Exception:
            rawPath = None

        if not rawPath:
            return None

        sourcePath, _sourceIndex = self._splitIndexedImagePath(rawPath)
        if not sourcePath:
            return None

        filePath = self._resolveFilePath(protocol, sourcePath)
        if filePath is None:
            filePath = Path(str(sourcePath))

        fileName = filePath.name if filePath.name else Path(str(sourcePath)).name
        suffix = filePath.suffix.upper().lstrip(".") or "PDB"

        atomCount = None
        lineCount = None

        if filePath.exists():
            atomCount, lineCount = self._readAtomStructStats(filePath)

        return self._buildAtomStructCardImage(
            fileName=fileName,
            fileType=suffix,
            atomCount=atomCount,
            lineCount=lineCount,
            size=size,
        )

    def _readAtomStructStats(self, filePath: Path) -> Tuple[Optional[int], Optional[int]]:
        atomCount = 0
        lineCount = 0

        try:
            with filePath.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    lineCount += 1

                    if line.startswith("ATOM") or line.startswith("HETATM"):
                        atomCount += 1

                    if lineCount >= 50000:
                        break

            return atomCount if atomCount > 0 else None, lineCount if lineCount > 0 else None

        except Exception:
            return None, None

    def _buildAtomStructCardImage(
            self,
            fileName: str,
            fileType: str,
            atomCount: Optional[int],
            lineCount: Optional[int],
            size: int,
    ) -> Image.Image:
        width = max(360, int(size))
        height = max(220, int(round(width * 0.58)))

        image = Image.new("RGB", (width, height), (246, 249, 252))
        draw = ImageDraw.Draw(image)

        margin = max(18, int(round(width * 0.05)))
        card = (
            margin,
            margin,
            width - margin,
            height - margin,
        )

        draw.rounded_rectangle(
            card,
            radius=18,
            fill=(255, 255, 255),
            outline=(203, 213, 225),
            width=1,
        )

        badgeW = 86
        badgeH = 30
        badgeBox = (
            margin + 16,
            margin + 16,
            margin + 16 + badgeW,
            margin + 16 + badgeH,
        )

        draw.rounded_rectangle(
            badgeBox,
            radius=9,
            fill=(226, 232, 240),
            outline=(203, 213, 225),
            width=1,
        )
        draw.text((badgeBox[0] + 12, badgeBox[1] + 8), str(fileType or "PDB"), fill=(15, 23, 42))

        title = "AtomStruct"
        draw.text((margin + 16, margin + 58), title, fill=(15, 23, 42))

        displayName = self._ellipsizeText(
            text=fileName or "Unknown file",
            maxChars=38,
        )
        draw.text((margin + 16, margin + 86), displayName, fill=(51, 65, 85))

        y = margin + 122

        stats: List[str] = []
        if atomCount is not None:
            stats.append(f"{atomCount} atoms")
        if lineCount is not None:
            stats.append(f"{lineCount} lines")

        if not stats:
            stats.append("Structure file")

        for stat in stats[:2]:
            draw.rounded_rectangle(
                (margin + 16, y, margin + 158, y + 28),
                radius=8,
                fill=(248, 250, 252),
                outline=(226, 232, 240),
                width=1,
            )
            draw.text((margin + 28, y + 8), stat, fill=(71, 85, 105))
            y += 36

        return image

    def _ellipsizeText(self, text: str, maxChars: int) -> str:
        text = str(text or "")
        if len(text) <= maxChars:
            return text

        if maxChars <= 3:
            return text[:maxChars]

        return text[:maxChars - 3] + "..."

    def _renderFscPreview(self, output, size: int) -> Optional[Image.Image]:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except Exception:
            return None

        fscItems = []
        try:
            for index, fsc in enumerate(output):
                if fsc is None:
                    continue
                clone = getattr(fsc, "clone", lambda: fsc)()
                label = getattr(clone, "getObjLabel", lambda: None)() or f"FSC {index + 1}"
                fscItems.append((clone, label))
        except Exception:
            return None

        if not fscItems:
            return None

        def getXY(fscObj):
            data = fscObj.getData()
            if isinstance(data, (list, tuple)) and len(data) == 2:
                xVals = np.asarray(data[0], dtype=float)
                yVals = np.asarray(data[1], dtype=float)
            else:
                arr = np.asarray(data, dtype=float)
                if arr.ndim != 2 or arr.shape[1] < 2:
                    return np.asarray([]), np.asarray([])
                xVals = arr[:, 0]
                yVals = arr[:, 1]
            mask = np.isfinite(xVals) & np.isfinite(yVals)
            return xVals[mask], yVals[mask]

        figW = max(4.8, size / 95.0)
        figH = max(2.7, figW * 0.58)
        fig, ax = plt.subplots(figsize=(figW, figH), dpi=130)
        try:
            threshold = 0.143
            maxX = 0.0
            for fscObj, label in fscItems:
                xVals, yVals = getXY(fscObj)
                if xVals.size == 0:
                    continue
                maxX = max(maxX, float(xVals.max()))
                ax.plot(xVals, yVals, linewidth=1.6, label=label)
            ax.axhline(threshold, linestyle="--", linewidth=0.9, alpha=0.6)
            ax.set_xlim(0, maxX if maxX > 0 else 1.0)
            ax.set_ylim(0.0, 1.05)
            ax.grid(True, linestyle="--", linewidth=0.35, alpha=0.3)
            ax.set_xlabel("Spatial frequency")
            ax.set_ylabel("FSC")
            if len(fscItems) > 1:
                ax.legend(fontsize=6, loc="best")
            fig.tight_layout(pad=0.8)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", facecolor="white")
            data = buf.getvalue()
        finally:
            plt.close(fig)

        try:
            return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            return None

    def _renderGenericPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        try:
            getFileNameFn = getattr(output, "getFileName", None)
            if callable(getFileNameFn):
                filePath = self._resolveFilePath(protocol, getFileNameFn())
                if filePath is not None and filePath.exists():
                    preview = self._renderPathPreview(protocol, filePath, size=size)
                    if preview is not None:
                        return preview
        except Exception:
            logger.debug("Generic direct file preview failed", exc_info=True)

        for item in self._iterPreviewItems(output, maxItems=6):
            try:
                sourcePath, sourceIndex = self._resolveImageSourceFromItem(item)
                if sourcePath:
                    tile = self._readImagePreview(protocol, sourcePath, sourceIndex)
                    if tile is not None:
                        return tile
                getFileNameFn = getattr(item, "getFileName", None)
                if callable(getFileNameFn):
                    filePath = self._resolveFilePath(protocol, getFileNameFn())
                    if filePath is not None and filePath.exists():
                        preview = self._renderPathPreview(protocol, filePath, size=size)
                        if preview is not None:
                            return preview
            except Exception:
                continue

        return None

    def _renderProtocolFilesystemFallback(self, protocol, size: int) -> Optional[Image.Image]:
        protocolPathFn = getattr(protocol, "getPath", None)
        if not callable(protocolPathFn):
            return None
        protocolPath = Path(protocolPathFn())
        if not protocolPath.exists():
            return None

        preferredExts = (
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".tif",
            ".tiff",
            ".mrc",
            ".map",
            ".mrcs",
            ".stk",
            ".vol",
            ".em",
            ".hdf",
            ".h5",
        )
        candidates: List[Path] = []
        maxDepth = 3
        maxScanned = 800
        scanned = 0

        for root, _dirs, files in os.walk(str(protocolPath)):
            try:
                depth = len(Path(root).relative_to(protocolPath).parts)
            except Exception:
                depth = 0
            if depth > maxDepth:
                continue

            for name in files:
                scanned += 1
                if scanned > maxScanned:
                    break
                lowerName = name.lower()
                path = Path(root) / name
                if not self._isLikelyPreviewFile(lowerName):
                    continue
                if path.suffix.lower() in preferredExts:
                    candidates.append(path)
            if scanned > maxScanned:
                break

        if not candidates:
            return None

        candidates.sort(key=self._filesystemPreviewSortKey)
        for path in candidates[:24]:
            try:
                image = self._renderPathPreview(protocol, path, size=size)
                if image is not None:
                    return image
            except Exception:
                logger.debug(
                    "Filesystem candidate failed. protocolId=%s path=%s",
                    getattr(protocol, "getObjId", lambda: "unknown")(),
                    str(path),
                    exc_info=True,
                )
        return None

    def _renderPathPreview(self, protocol, filePath: Path, size: int) -> Optional[Image.Image]:
        suffix = filePath.suffix.lower()
        if suffix in self._volumeLikeExtensions():
            image = self._renderVolumeFromPath(filePath, size=size)
            if image is not None:
                return image

        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
            try:
                image = Image.open(filePath)
                return self._normalizePilImage(image)
            except Exception:
                pass

        try:
            image = self._readImagePreview(protocol, str(filePath), None)
            if image is not None:
                return image
        except Exception:
            pass
        return None

    def _renderVolumeFromPath(self, volumePath: Path, size: int) -> Optional[Image.Image]:
        try:
            volume, _props = readVolumeArray3d(str(volumePath))
        except Exception:
            return None

        volume = np.asarray(volume)
        if volume.ndim != 3:
            return None

        zSize, _ySize, _xSize = volume.shape
        centerZ = zSize // 2

        maxSlices = 5
        halfWindow = maxSlices // 2

        z0 = max(0, centerZ - halfWindow)
        z1 = min(zSize, centerZ + halfWindow + 1)

        slab = volume[z0:z1, :, :]
        if slab.size == 0:
            return None

        meanSliceZ = np.mean(slab.astype(np.float32, copy=False), axis=0)

        cmapName = self._volumeColormapName()
        image = self._arrayToImage(meanSliceZ, cmapName=cmapName)
        if image is None:
            return None

        return image

    # ------------------------------------------------------------------
    # Object manager
    # ------------------------------------------------------------------
    def _createPreviewObjectManager(self, protocol, output) -> Optional[ObjectManager]:
        getFileNameFn = getattr(output, "getFileName", None)
        if not callable(getFileNameFn):
            return None

        try:
            metaPath = getFileNameFn()
        except Exception:
            return None
        if not metaPath:
            return None

        absMetaPath = self._resolveFilePath(protocol, metaPath)
        if absMetaPath is None or not absMetaPath.exists():
            return None

        try:
            objectManager = ObjectManager()
            objectManager.registerDAO(ScipionSetsDAO)
            objectManager.registerDAO(StarFile)
            objectManager.registerReader(ScipionImageReader)
            NumpyDao.addCompatibleFileType("cs")
            objectManager._fileName = Path(absMetaPath)
            objectManager._dao = None
            objectManager._tables = {}
            objectManager.selectDAO()
            objectManager.getTables()
            return objectManager
        except Exception:
            logger.debug("Could not create preview ObjectManager", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _finalizeProtocolThumbnail(
            self,
            previewImage: Image.Image,
            size: int,
            protocolId: Optional[int] = None,
    ) -> Image.Image:
        width = max(248, int(size))
        height = max(164, int(round(width * self.PROTOCOL_ASPECT_RATIO)))

        background = (244, 247, 251)
        canvas = Image.new("RGB", (width, height), background)

        outerRadius = max(16, int(round(height * 0.08)))
        mask = self._buildRoundedMask((width, height), radius=outerRadius)

        innerPad = max(3, int(round(min(width, height) * 0.015)))
        innerW = max(1, width - innerPad * 2)
        innerH = max(1, height - innerPad * 2)

        contained = ImageOps.contain(
            previewImage.convert("RGB"),
            (innerW, innerH),
            method=Image.Resampling.LANCZOS,
        )

        panel = Image.new("RGB", (width, height), background)
        ox = (width - contained.width) // 2
        oy = (height - contained.height) // 2
        panel.paste(contained, (ox, oy))

        canvas.paste(panel, (0, 0), mask)

        # if protocolId is not None:
        #     self._drawProtocolBadge(canvas, f"Protocol {int(protocolId)}")

        return canvas

    def _composeProjectStrip(self, items: List[Dict[str, Any]], size: int) -> Image.Image:
        if not items:
            placeholder = self._makeProtocolPlaceholderPreview(
                status="unknown",
                size=max(300, int(size * 0.46)),
            )
            return self._finalizeProtocolThumbnail(
                placeholder,
                size=max(300, int(size * 0.46)),
            )

        loadedImages: List[Image.Image] = []
        for item in items:
            try:
                absPath = item.get("absolutePath")
                if not absPath:
                    continue
                loadedImages.append(Image.open(absPath).convert("RGB"))
            except Exception:
                logger.debug(
                    "Failed to reopen protocol thumbnail while building project strip",
                    exc_info=True,
                )

        if not loadedImages:
            placeholder = self._makeProtocolPlaceholderPreview(
                status="unknown",
                size=max(300, int(size * 0.46)),
            )
            return self._finalizeProtocolThumbnail(
                placeholder,
                size=max(300, int(size * 0.46)),
            )

        tileH = max(img.height for img in loadedImages)
        gap = max(4, int(round(tileH * 0.018)))
        padX = max(6, int(round(tileH * 0.02)))
        padY = max(6, int(round(tileH * 0.02)))

        width = sum(img.width for img in loadedImages) + gap * max(0, len(loadedImages) - 1) + padX * 2
        height = tileH + padY * 2

        canvas = Image.new("RGB", (width, height), (247, 249, 252))

        x = padX
        for img in loadedImages:
            y = padY + max(0, (tileH - img.height) // 2)
            canvas.paste(img, (x, y))
            x += img.width + gap

        return canvas

    def _composeCleanGrid(
            self,
            tiles: Sequence[Image.Image],
            maxCols: int = 3,
            targetWidth: Optional[int] = None,
            background: Tuple[int, int, int] = (246, 249, 252),
    ) -> Image.Image:
        count = len(tiles)
        if count == 0:
            return Image.new("RGB", (320, 200), background)

        maxCols = max(1, int(maxCols))
        cols = min(maxCols, count)
        rows = int(np.ceil(count / float(cols)))

        baseWidth = max(220, int(targetWidth or 360))
        gap = max(4, int(round(baseWidth * 0.015)))
        tileW = max(96, int((baseWidth - gap * max(0, cols - 1)) / cols))
        tileH = max(88, int(round(tileW * 0.76)))

        width = cols * tileW + max(0, cols - 1) * gap
        height = rows * tileH + max(0, rows - 1) * gap
        canvas = Image.new("RGB", (width, height), background)

        index = 0
        for row in range(rows):
            for col in range(cols):
                if index >= count:
                    break

                x0 = col * (tileW + gap)
                y0 = row * (tileH + gap)
                x1 = x0 + tileW - 1
                y1 = y0 + tileH - 1

                self._pasteContainedPreview(
                    canvas=canvas,
                    previewImage=tiles[index],
                    box=(x0, y0, x1, y1),
                    padding=2,
                    radius=max(10, int(round(tileH * 0.08))),
                    background=background,
                    contain=True,
                )
                index += 1

        return canvas

    def _composeCleanStrip(self, panels: Sequence[Image.Image], targetHeight: int = 190) -> Image.Image:
        if not panels:
            return Image.new("RGB", (480, 190), (246, 249, 252))

        tileH = max(120, int(targetHeight))
        gap = max(8, int(round(tileH * 0.04)))
        prepared: List[Image.Image] = []

        for panel in panels:
            img = panel.convert("RGB")
            contained = ImageOps.contain(
                img,
                (max(140, int(round(tileH * 1.35))), tileH),
                method=Image.Resampling.LANCZOS,
            )

            frameW = max(140, contained.width + 10)
            frame = Image.new("RGB", (frameW, tileH), (246, 249, 252))
            ox = (frameW - contained.width) // 2
            oy = (tileH - contained.height) // 2
            frame.paste(contained, (ox, oy))
            prepared.append(frame)

        width = sum(img.width for img in prepared) + gap * max(0, len(prepared) - 1)
        canvas = Image.new("RGB", (width, tileH), (246, 249, 252))

        x = 0
        for img in prepared:
            canvas.paste(img, (x, 0))
            x += img.width + gap

        return canvas

    def _composeTriptych(self, panels: Sequence[Image.Image], targetHeight: int = 206) -> Image.Image:
        if not panels:
            return Image.new("RGB", (620, 210), (246, 249, 252))

        tileH = max(120, int(targetHeight))
        gap = max(6, int(round(tileH * 0.035)))
        tileW = max(120, int(round(tileH * 1.02)))
        width = len(panels) * tileW + max(0, len(panels) - 1) * gap
        canvas = Image.new("RGB", (width, tileH), (246, 249, 252))

        for index, panel in enumerate(panels):
            x0 = index * (tileW + gap)
            x1 = x0 + tileW - 1
            self._pasteContainedPreview(
                canvas=canvas,
                previewImage=panel,
                box=(x0, 0, x1, tileH - 1),
                padding=4,
                radius=max(10, int(round(tileH * 0.08))),
                background=(246, 249, 252),
                contain=True,
            )

        return canvas

    def _pasteContainedPreview(
            self,
            canvas: Image.Image,
            previewImage: Image.Image,
            box: Tuple[int, int, int, int],
            padding: int = 4,
            radius: int = 16,
            background: Tuple[int, int, int] = (246, 249, 252),
            contain: bool = True,
    ):
        x0, y0, x1, y1 = box
        boxW = max(1, x1 - x0 + 1)
        boxH = max(1, y1 - y0 + 1)

        targetW = max(1, boxW - padding * 2)
        targetH = max(1, boxH - padding * 2)

        panel = Image.new("RGB", (boxW, boxH), background)
        image = previewImage.convert("RGB")

        fitted = ImageOps.contain(
            image,
            (targetW, targetH),
            method=Image.Resampling.LANCZOS,
        )

        ox = (boxW - fitted.width) // 2
        oy = (boxH - fitted.height) // 2
        panel.paste(fitted, (ox, oy))

        mask = self._buildRoundedMask((boxW, boxH), radius=radius)
        canvas.paste(panel, (x0, y0), mask)

    def _buildRoundedMask(self, size: Tuple[int, int], radius: int) -> Image.Image:
        width, height = size
        mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
        return mask

    def _makeProtocolPlaceholderPreview(self, status: str, size: int) -> Image.Image:
        width = max(180, int(size))
        height = max(120, int(round(size * self.PROTOCOL_ASPECT_RATIO)))
        canvas = Image.new("RGB", (width, height), (242, 246, 250))
        draw = ImageDraw.Draw(canvas)

        accent = self._statusAccent(status)
        accentSoftA = self._mixColor(accent, (255, 255, 255), 0.82)
        accentSoftB = self._mixColor(accent, (255, 255, 255), 0.90)
        neutralA = (233, 238, 244)
        neutralB = (238, 242, 247)

        draw.ellipse(
            (
                int(width * 0.06),
                int(height * 0.10),
                int(width * 0.42),
                int(height * 0.86),
            ),
            fill=accentSoftA,
        )
        draw.ellipse(
            (
                int(width * 0.40),
                int(height * 0.04),
                int(width * 0.88),
                int(height * 0.56),
            ),
            fill=accentSoftB,
        )
        draw.rounded_rectangle(
            (
                int(width * 0.12),
                int(height * 0.62),
                int(width * 0.84),
                int(height * 0.73),
            ),
            radius=12,
            fill=neutralA,
        )
        draw.rounded_rectangle(
            (
                int(width * 0.12),
                int(height * 0.79),
                int(width * 0.56),
                int(height * 0.88),
            ),
            radius=12,
            fill=neutralB,
        )
        return canvas

    # ------------------------------------------------------------------
    # Preview source resolution
    # ------------------------------------------------------------------
    def _iterPreviewItems(self, output, maxItems: int) -> Iterable[Any]:
        items: List[Any] = []
        iterItemsFn = getattr(output, "iterItems", None)
        if not callable(iterItemsFn):
            return items

        try:
            for item in iterItemsFn(iterate=False):
                if not self._isEnabled(item):
                    continue
                items.append(item)
                if len(items) >= maxItems:
                    break
        except TypeError:
            try:
                for item in iterItemsFn():
                    if not self._isEnabled(item):
                        continue
                    items.append(item)
                    if len(items) >= maxItems:
                        break
            except Exception:
                return []
        except Exception:
            return []
        return items

    def _splitIndexedImagePath(self, value: Any) -> Tuple[Optional[str], Optional[int]]:
        if value is None:
            return None, None

        value = self._safeScalarValue(value)

        if isinstance(value, (list, tuple)):
            rawValues = [self._safeScalarValue(v) for v in value]

            fileName = None
            index = None

            for raw in reversed(rawValues):
                if raw is None:
                    continue

                text = str(raw).strip()
                if not text:
                    continue

                if "@" in text:
                    return self._splitIndexedImagePath(text)

                try:
                    float(text)
                    isNumeric = True
                except Exception:
                    isNumeric = False

                if not isNumeric:
                    fileName = text
                    break

            for raw in rawValues:
                if raw is None:
                    continue

                text = str(raw).strip()
                if not text or text == fileName:
                    continue

                try:
                    index = int(float(text))
                    break
                except Exception:
                    continue

            return fileName, index

        text = str(value).strip()
        if not text:
            return None, None

        if "@" in text:
            indexText, fileName = text.split("@", 1)
            try:
                index = int(indexText)
            except Exception:
                index = None

            return fileName.strip() or None, index

        return text, None

    def _resolveImageSourceFromItem(self, item) -> Tuple[Optional[str], Optional[int]]:
        candidateObjects = [item]

        for methodName in ("getRepresentative", "getAverage", "getMicrograph", "getParticle", "getImage"):
            getter = getattr(item, methodName, None)
            if callable(getter):
                try:
                    resolved = getter()
                    if resolved is not None:
                        candidateObjects.append(resolved)
                except Exception:
                    continue

        for candidate in candidateObjects:
            locationFn = getattr(candidate, "getLocation", None)
            if callable(locationFn):
                try:
                    sourcePath, sourceIndex = self._splitIndexedImagePath(locationFn())
                    if sourcePath:
                        return sourcePath, sourceIndex
                except Exception:
                    pass

            getFileNameFn = getattr(candidate, "getFileName", None)
            if not callable(getFileNameFn):
                continue

            try:
                fileName = getFileNameFn()
            except Exception:
                fileName = None

            sourcePath, sourceIndex = self._splitIndexedImagePath(fileName)
            if not sourcePath:
                continue

            if sourceIndex is None:
                getIndexFn = getattr(candidate, "getIndex", None)
                if callable(getIndexFn):
                    try:
                        sourceIndex = int(self._safeScalarValue(getIndexFn()))
                    except Exception:
                        sourceIndex = None

            return sourcePath, sourceIndex

        return None, None

    # ------------------------------------------------------------------
    # Low level readers
    # ------------------------------------------------------------------
    def _readImagePreview(self, protocol, filePath: str, index: Optional[int]) -> Optional[Image.Image]:
        sourcePath, parsedIndex = self._splitIndexedImagePath(filePath)

        if parsedIndex is not None and index is None:
            index = parsedIndex

        resolvedPath = self._resolveFilePath(protocol, sourcePath)
        if resolvedPath is None:
            return None

        try:
            reader = ImageReadersRegistry.open(str(resolvedPath))
        except Exception:
            return None

        candidateIndexes: List[int] = []
        if index is not None:
            if index >= 0:
                candidateIndexes.append(index)
            if index > 0:
                candidateIndexes.append(index - 1)
        candidateIndexes.append(0)

        image = None
        for idx in self._uniqueInts(candidateIndexes):
            try:
                image = reader.getImage(index=idx, pilImage=True)
                if image is not None:
                    break
            except Exception:
                continue

        if image is None:
            try:
                image = reader.getCentralImage(pilImage=True)
            except Exception:
                image = None
        if image is None:
            return None
        return self._normalizePilImage(image)

    def _readMoviePreviewFromPath(
            self,
            protocol,
            filePath: str,
            index: Optional[int],
            movie=None,
    ) -> Optional[Image.Image]:
        sourcePath, parsedIndex = self._splitIndexedImagePath(filePath)

        if parsedIndex is not None and index is None:
            index = parsedIndex

        resolvedPath = self._resolveFilePath(protocol, sourcePath)
        if resolvedPath is None or not resolvedPath.exists():
            return None

        candidateIndexes: List[int] = []

        if index is not None:
            try:
                indexValue = int(index)
                candidateIndexes.append(indexValue)
                if indexValue > 0:
                    candidateIndexes.append(indexValue - 1)
            except Exception:
                pass

        try:
            getNumberOfFramesFn = getattr(movie, "getNumberOfFrames", None)
            if callable(getNumberOfFramesFn):
                numberOfFrames = int(getNumberOfFramesFn())
                if numberOfFrames > 1:
                    candidateIndexes.append(numberOfFrames // 2)
                    candidateIndexes.append(max(0, numberOfFrames // 2 - 1))
        except Exception:
            pass

        try:
            getDimFn = getattr(movie, "getDim", None)
            if callable(getDimFn):
                dim = getDimFn()
                if isinstance(dim, (list, tuple)) and len(dim) >= 3:
                    frames = int(dim[2])
                    if frames > 1:
                        candidateIndexes.append(frames // 2)
                        candidateIndexes.append(max(0, frames // 2 - 1))
        except Exception:
            pass

        candidateIndexes.extend([0, 1])

        try:
            reader = ImageReadersRegistry.open(str(resolvedPath))

            try:
                image = reader.getCentralImage(pilImage=True)
                if image is not None:
                    return self._normalizePilImage(image)
            except Exception:
                pass

            for idx in self._uniqueInts(candidateIndexes):
                try:
                    image = reader.getImage(index=idx, pilImage=True)
                    if image is not None:
                        return self._normalizePilImage(image)
                except Exception:
                    continue

        except Exception:
            pass

        try:
            from pwem.emlib.image import ImageHandler

            imageHandler = ImageHandler()

            for idx in self._uniqueInts(candidateIndexes):
                try:
                    imageObj = imageHandler.read((idx + 1, str(resolvedPath)))
                    data = imageObj.getData()
                    if data is not None:
                        arr = np.asarray(data)
                        arr = np.squeeze(arr)
                        if arr.ndim == 2:
                            return self._arrayToImage(arr)
                except Exception:
                    continue

            try:
                imageObj = imageHandler.read(str(resolvedPath))
                data = imageObj.getData()
                if data is not None:
                    arr = np.asarray(data)
                    arr = np.squeeze(arr)

                    if arr.ndim == 3:
                        arr = arr[arr.shape[0] // 2]

                    if arr.ndim == 2:
                        return self._arrayToImage(arr)
            except Exception:
                pass

        except Exception:
            pass

        return None

    def _read2dTile(
        self,
        filePath: Path,
        sliceIndex: Optional[int] = None,
        preferCentral: bool = False,
        thumbSize: int = maxThumbSize,
    ) -> Optional[np.ndarray]:
        try:
            if not filePath or not filePath.exists():
                return None
            imageStack = ImageReadersRegistry.open(str(filePath))
        except Exception:
            return None

        pilImg = None
        try:
            if sliceIndex is not None:
                idx0 = max(0, int(sliceIndex) - 1)
                pilImg = imageStack.getImage(index=idx0, pilImage=True)
            elif preferCentral:
                try:
                    pilImg = imageStack.getCentralImage(pilImage=True)
                except Exception:
                    pilImg = imageStack.getImage(index=0, pilImage=True)
            else:
                try:
                    pilImg = imageStack.getImage(index=0, pilImage=True)
                except Exception:
                    pilImg = imageStack.getCentralImage(pilImage=True)
        except Exception:
            pilImg = None

        if pilImg is None:
            return None
        return self._pilTo2dTile(imageStack, pilImg, thumbSize=thumbSize)

    def _pilTo2dTile(self, imageStack, pilImg, thumbSize=maxThumbSize) -> Optional[np.ndarray]:
        try:
            width, height = pilImg.size
            scale = min(thumbSize / float(width), thumbSize / float(height), 1.0)
            thumbWidth = max(1, int(round(width * scale)))
            thumbHeight = max(1, int(round(height * scale)))

            pilGray = pilImg if pilImg.mode in ("L", "I;16", "F") else pilImg.convert("L")
            if thumbWidth < width or thumbHeight < height:
                pilGray = pilGray.copy()
                pilGray.thumbnail((thumbWidth, thumbHeight))

            arr = np.asarray(pilGray, dtype=np.float32)
            arr = np.squeeze(arr)
            if arr.ndim != 2 or arr.size == 0:
                return None

            try:
                arr = imageStack.highlightSlice(arr)
                arr = imageStack.normalizeSlice(arr)
            except Exception:
                pass

            amin = float(np.min(arr))
            amax = float(np.max(arr))
            if not np.isfinite(amin) or not np.isfinite(amax) or amax <= amin:
                return np.zeros_like(arr, dtype=np.uint8)
            arr = (arr - amin) / (amax - amin + 1e-12)
            return (255.0 * arr).astype(np.uint8)
        except Exception:
            return None

    def _arrayToImage(self, array2d: np.ndarray, cmapName: Optional[str] = None) -> Optional[Image.Image]:
        try:
            gray = self._normalizeArrayToUint8(array2d)
            if cmapName:
                rgb = self._applyColormap(gray, cmapName=cmapName)
                return self._rgbTileToImage(rgb)
            return self._grayTileToImage(gray)
        except Exception:
            return None

    def _grayTileToImage(self, gray: np.ndarray) -> Optional[Image.Image]:
        try:
            arr = np.asarray(gray)
            if arr.ndim != 2:
                return None
            if arr.dtype != np.uint8:
                arr = self._normalizeArrayToUint8(arr)
            return Image.fromarray(arr, mode="L").convert("RGB")
        except Exception:
            return None

    def _rgbTileToImage(self, rgb: np.ndarray) -> Optional[Image.Image]:
        try:
            arr = np.asarray(rgb)
            if arr.ndim != 3 or arr.shape[-1] != 3:
                return None
            if arr.dtype != np.uint8:
                arr = np.clip(arr, 0, 255).astype(np.uint8)
            return Image.fromarray(arr, mode="RGB")
        except Exception:
            return None

    def _normalizePilImage(self, pilImage: Image.Image) -> Image.Image:
        if pilImage.mode not in ("L", "I;16", "F"):
            pilImage = pilImage.convert("L")

        arr = np.asarray(pilImage, dtype=np.float32)
        arr = np.squeeze(arr)
        if arr.ndim == 3:
            arr = np.mean(arr, axis=-1)
        arr = self._normalizeArrayToUint8(arr)
        return Image.fromarray(arr, mode="L").convert("RGB")

    def _normalizeArrayToUint8(self, array: np.ndarray) -> np.ndarray:
        arr = np.asarray(array, dtype=np.float32)
        if arr.size == 0:
            return np.zeros((64, 64), dtype=np.uint8)

        finiteMask = np.isfinite(arr)
        if not finiteMask.all():
            fillValue = float(np.nanmedian(arr[finiteMask])) if finiteMask.any() else 0.0
            arr = np.where(finiteMask, arr, fillValue)

        low = float(np.percentile(arr, 2))
        high = float(np.percentile(arr, 98))
        if not np.isfinite(low) or not np.isfinite(high) or high <= low:
            low = float(np.min(arr))
            high = float(np.max(arr))
        if not np.isfinite(low) or not np.isfinite(high) or high <= low:
            return np.zeros_like(arr, dtype=np.uint8)

        arr = (arr - low) / (high - low + 1e-12)
        arr = np.clip(arr, 0.0, 1.0)
        return (255.0 * arr).astype(np.uint8)

    def _applyColormap(self, grayTile: np.ndarray, cmapName: str = "viridis") -> np.ndarray:
        arr = np.asarray(grayTile, dtype=np.float32)
        if arr.ndim != 2:
            return np.zeros((64, 64, 3), dtype=np.uint8)

        if not np.isfinite(arr).all():
            finite = np.isfinite(arr)
            if finite.any():
                arr = arr.copy()
                arr[~finite] = np.nanmedian(arr[finite])
            else:
                arr = np.zeros_like(arr, dtype=np.float32)

        aMin = float(np.min(arr))
        aMax = float(np.max(arr))
        if not np.isfinite(aMin) or not np.isfinite(aMax) or aMax <= aMin:
            arr = np.zeros_like(arr, dtype=np.float32)
        else:
            arr = (arr - aMin) / (aMax - aMin)

        try:
            from matplotlib import cm as mplCm
            cmap = mplCm.get_cmap(cmapName)
        except Exception:
            from matplotlib import cm as mplCm
            cmap = mplCm.get_cmap("viridis")

        rgba = cmap(np.clip(arr, 0.0, 1.0), bytes=True)
        return rgba[..., :3].copy()

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------
    def _pickSampleRows(self, objectManager, tableName: str, want: int) -> List[Any]:
        rowCount = objectManager.getTableRowCount(tableName) or 0
        if rowCount <= 0:
            return []

        n = max(1, min(int(want), int(rowCount)))
        if rowCount <= n:
            return objectManager.getRows(tableName, 0, n) or []

        indices = np.linspace(0, rowCount - 1, num=n, dtype=int).tolist()
        dedupIndices: List[int] = []
        seen = set()
        for idx in indices:
            idxInt = int(idx)
            if idxInt not in seen:
                seen.add(idxInt)
                dedupIndices.append(idxInt)

        rows: List[Any] = []
        for idx in dedupIndices:
            chunk = objectManager.getRows(tableName, idx, 1) or []
            if chunk:
                rows.append(chunk[0])
        return rows

    def _getRenderColumnIndex(self, renderField: Sequence[str], columns) -> int:
        tokens = [str(token).strip() for token in (renderField or []) if str(token).strip()]
        for fallback in ["stack", "_filename", "micrograph", "micName", "file", "path"]:
            if fallback not in tokens:
                tokens.append(fallback)

        colNames = [(col.getName() or "") for col in columns]
        colLower = [name.lower() for name in colNames]

        for candidate in tokens:
            if candidate in colNames:
                return colNames.index(candidate)
        for candidate in tokens:
            lower = candidate.lower()
            if lower in colLower:
                return colLower.index(lower)
        for candidate in tokens:
            lower = candidate.lower()
            for index, name in enumerate(colLower):
                if lower in name and colNames[index]:
                    return index
        raise ValueError("Render field not found. Tried: %s" % ", ".join(tokens))

    def _extractPathFromRow(self, row: Any, renderIdx: int) -> Tuple[Optional[str], Optional[int]]:
        values = getattr(row, "_values", None)
        if values is None or renderIdx >= len(values):
            return None, None
        raw = values[renderIdx]
        if raw is None:
            return None, None

        text = str(raw).strip()
        if not text:
            return None, None
        if "@" in text:
            idxStr, relPath = text.split("@", 1)
            try:
                sliceIndex = int(idxStr)
            except ValueError:
                sliceIndex = None
            return relPath, sliceIndex
        return text, None

    # ------------------------------------------------------------------
    # Paths and caches
    # ------------------------------------------------------------------
    def _getCacheDir(self) -> Path:
        projectPath = self._getProjectPath()
        if projectPath is None:
            raise ValueError("Cannot resolve current project path for thumbnails")
        cacheDir = Path(projectPath) / ".thumbnail_cache"
        cacheDir.mkdir(parents=True, exist_ok=True)
        return cacheDir

    def _sanitizeCacheToken(self, value: Optional[str]) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[^a-z0-9._-]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("._-")
        return text or "default"

    def _slugOutputName(self, outputName: Optional[str]) -> str:
        if not outputName:
            return "best"

        value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(outputName).strip())
        value = value.strip("._")
        return value or "best"

    def _getProtocolCachePath(self, protocolId: int, size: int, outputName: Optional[str] = None) -> Path:
        outputSlug = self._slugOutputName(outputName)
        return self._getCacheDir() / f"protocol_{int(protocolId)}_{outputSlug}_{int(size)}_{self.CACHE_VERSION}.png"

    def _getProjectCachePath(self, size: int, maxProtocols: int) -> Path:
        return self._getCacheDir() / f"project_{int(size)}_{int(maxProtocols)}_{self.CACHE_VERSION}.png"

    def _saveImage(self, image: Image.Image, outputPath: Path):
        outputPath.parent.mkdir(parents=True, exist_ok=True)

        tmpPath = outputPath.with_name(
            f".{outputPath.name}.{os.getpid()}.{id(image)}.tmp"
        )

        try:
            image.save(str(tmpPath), format="PNG")
            os.replace(str(tmpPath), str(outputPath))
        finally:
            try:
                if tmpPath.exists():
                    tmpPath.unlink()
            except Exception:
                pass

    def _getProjectPath(self) -> Optional[str]:
        if self.currentProject is None:
            return None

        getPathFn = getattr(self.currentProject, "getPath", None)
        if callable(getPathFn):
            try:
                return str(getPathFn())
            except Exception:
                return None

        pathValue = getattr(self.currentProject, "path", None)
        if pathValue:
            return str(pathValue)
        return None

    def _resolveFilePath(self, protocol, maybeRelative: str) -> Optional[Path]:
        if not maybeRelative:
            return None

        path = Path(str(maybeRelative)).expanduser()
        if path.is_absolute():
            try:
                resolved = path.resolve()
            except Exception:
                resolved = path
            return resolved if resolved.exists() else None

        candidates: List[Path] = []
        for attr in ("getWorkingDir", "getTmpPath", "getPath"):
            if hasattr(protocol, attr):
                try:
                    root = getattr(protocol, attr)()
                    if root:
                        candidates.append(Path(root))
                except Exception:
                    pass

        for attr in ("getPath", "path", "projPath", "projDir", "projectPath"):
            if hasattr(self.currentProject, attr):
                try:
                    value = getattr(self.currentProject, attr)
                    root = Path(value() if callable(value) else value)
                    candidates.append(root)
                except Exception:
                    pass

        candidates.append(Path.cwd())

        for root in candidates:
            try:
                candidate = (root / path).resolve()
            except Exception:
                candidate = root / path
            if candidate.exists():
                return candidate

        finalCandidate = (Path.cwd() / path).resolve()
        return finalCandidate if finalCandidate.exists() else None

    def _collectDirectVolumePaths(self, protocol, output, maxItems: int = 6) -> List[Path]:
        paths: List[Path] = []
        try:
            getFileNameFn = getattr(output, "getFileName", None)
            if callable(getFileNameFn):
                filePath = self._resolveFilePath(protocol, getFileNameFn())
                if filePath is not None and filePath.exists():
                    paths.append(filePath)
        except Exception:
            pass

        if isinstance(output, EMSet):
            for item in self._iterPreviewItems(output, maxItems=maxItems):
                try:
                    getFileNameFn = getattr(item, "getFileName", None)
                    if not callable(getFileNameFn):
                        continue
                    filePath = self._resolveFilePath(protocol, getFileNameFn())
                    if filePath is not None and filePath.exists():
                        paths.append(filePath)
                    if len(paths) >= maxItems:
                        break
                except Exception:
                    continue

        dedup: List[Path] = []
        seen = set()
        for path in paths:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            dedup.append(path)
        return dedup[:maxItems]

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def _getProtocolLabel(self, protocol) -> str:
        getObjLabelFn = getattr(protocol, "getObjLabel", None)
        if callable(getObjLabelFn):
            try:
                label = getObjLabelFn()
                if label:
                    return str(label)
            except Exception:
                pass
        try:
            return str(protocol)
        except Exception:
            return "Protocol %s" % getattr(protocol, "getObjId", lambda: "?")()

    def _getProtocolStatus(self, protocol) -> str:
        getStatusFn = getattr(protocol, "getStatus", None)
        if callable(getStatusFn):
            try:
                return str(getStatusFn())
            except Exception:
                return "unknown"
        return "unknown"

    def _getOutputClassName(self, output) -> str:
        getClassNameFn = getattr(output, "getClassName", None)
        if callable(getClassNameFn):
            try:
                className = getClassNameFn()
                if className:
                    return str(className)
            except Exception:
                pass
        return output.__class__.__name__

    def _safeOutputSize(self, output) -> Optional[int]:
        getSizeFn = getattr(output, "getSize", None)
        if callable(getSizeFn):
            try:
                return int(getSizeFn())
            except Exception:
                return None
        return None

    def _isEnabled(self, item) -> bool:
        isEnabledFn = getattr(item, "isEnabled", None)
        if callable(isEnabledFn):
            try:
                return bool(isEnabledFn())
            except Exception:
                return True
        return True

    def _projectProtocolSize(self, size: int, maxProtocols: int) -> int:
        if maxProtocols <= 1:
            return max(400, int(round(size * 0.58)))
        if maxProtocols <= 3:
            return max(340, int(round(size * 0.46)))
        return max(300, int(round(size * 0.38)))

    def _volumeColormapName(self) -> str:
        return os.getenv("SCIPION_THUMB_COLORMAP", "viridis")

    def _isLikelyPreviewFile(self, lowerName: str) -> bool:
        if any(
            token in lowerName
            for token in (
                "thumb",
                "thumbnail",
                "preview",
                "gallery",
                "mosaic",
                "average",
                "class",
                "micrograph",
                "particle",
                "volume",
                "map",
                "tomogram",
                "slice",
            )
        ):
            return True
        if lowerName.endswith((
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".tif",
            ".tiff",
            ".mrc",
            ".map",
            ".mrcs",
            ".stk",
            ".vol",
            ".em",
            ".hdf",
            ".h5",
        )):
            return True
        return False

    def _filesystemPreviewSortKey(self, path: Path) -> Tuple[int, int, str]:
        name = path.name.lower()
        priority = 0
        if "thumb" in name or "thumbnail" in name or "preview" in name:
            priority += 220
        if "mosaic" in name or "gallery" in name:
            priority += 180
        if "average" in name or "class" in name:
            priority += 140
        if "micrograph" in name or "particle" in name:
            priority += 120
        if "volume" in name or "map" in name or "tomogram" in name:
            priority += 100
        if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
            priority += 70
        if name.endswith((".mrc", ".map", ".mrcs", ".stk", ".vol", ".em", ".hdf", ".h5")):
            priority += 40
        try:
            sizeScore = int(path.stat().st_size)
        except Exception:
            sizeScore = 0
        return (-priority, -sizeScore, name)

    def _statusAccent(self, statusText: str) -> Tuple[int, int, int]:
        status = (statusText or "").lower()
        if any(token in status for token in ("finished", "done", "success", "complete")):
            return (75, 170, 96)
        if any(token in status for token in ("running", "launched", "active", "progress")):
            return (59, 130, 246)
        if any(token in status for token in ("scheduled", "queued", "waiting")):
            return (202, 138, 4)
        if any(token in status for token in ("failed", "error", "aborted", "stopped")):
            return (220, 38, 38)
        return (148, 163, 184)

    def _mixColor(
        self,
        rgbA: Tuple[int, int, int],
        rgbB: Tuple[int, int, int],
        alpha: float,
    ) -> Tuple[int, int, int]:
        alpha = max(0.0, min(1.0, float(alpha)))
        return (
            int(round(rgbA[0] * (1.0 - alpha) + rgbB[0] * alpha)),
            int(round(rgbA[1] * (1.0 - alpha) + rgbB[1] * alpha)),
            int(round(rgbA[2] * (1.0 - alpha) + rgbB[2] * alpha)),
        )

    def _uniqueInts(self, values: Sequence[int]) -> List[int]:
        result: List[int] = []
        seen = set()
        for value in values:
            try:
                ivalue = int(value)
            except Exception:
                continue
            if ivalue < 0 or ivalue in seen:
                continue
            seen.add(ivalue)
            result.append(ivalue)
        return result

    def _volumeLikeExtensions(self) -> Set[str]:
        return {
            ".mrc",
            ".map",
            ".mrcs",
            ".stk",
            ".vol",
            ".em",
            ".hdf",
            ".h5",
        }