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
from tomo.objects import SetOfTiltSeries

from app.backend.utils.constants import maxThumbSize
from app.backend.utils.volume_utils import readVolumeArray3d

from pwem.emlib.image.image_readers import ImageReadersRegistry
from pwem.objects import (
    EMSet,
    SetOfClasses2D,
    SetOfClasses3D,
    SetOfFSCs,
    SetOfMicrographs,
    SetOfParticles,
    SetOfVolumes,
)
from pwem.viewers import RENDER
from pwem.viewers.mdviewer.readers import ScipionImageReader
from pwem.viewers.mdviewer.sqlite_dao import ScipionSetsDAO
from pwem.viewers.mdviewer.star_dao import StarFile
from pwem.viewers.viewers_data import RegistryViewerConfig

logger = logging.getLogger(__name__)
_thumbnailBuildLocksGuard = threading.Lock()
_thumbnailBuildLocks: Dict[str, threading.Lock] = {}


class ThumbnailService:
    CACHE_VERSION = "v1"
    PROTOCOL_ASPECT_RATIO = 0.68

    def __init__(self, currentProject):
        self.currentProject = currentProject

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
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

        if not hasattr(protocol, outputName):
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

        output = getattr(protocol, outputName, None)
        if output is None:
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

        outputClassName = self._getOutputClassName(output)
        score = self._scoreOutput(outputName, output)

        if score <= 0 and not self._looksRenderableOutput(output):
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

    def _iterOutputAttributes(self, protocol) -> Iterable[Tuple[str, Any]]:
        try:
            for outputName, output in protocol.iterOutputAttributes():
                if output is None:
                    continue
                yield outputName, output
        except Exception:
            return

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
        elif "class2d" in className or "average" in className:
            score = 182
        elif "class3d" in className:
            score = 176
        elif "setofparticle" in className or "particle" in className:
            score = 168
        elif "ctftomo" in className or "setofctftomo" in className:
            score = 156
        elif "setofvolume" in className or "volume" in className:
            score = 164
        elif "tomogram" in className:
            score = 164
        elif "setoftiltseries" in className or "tiltseries" in className:
            score = 150
        elif "coordinate3d" in className or "coordinates3d" in className or "setofcoordinates3d" in className:
            score = 128
        elif "setofcoordinate" in className or "coordinate" in className:
            score = 126
        elif "fsc" in className:
            score = 112
        elif self._looksRenderableOutput(output):
            score = 70
        else:
            score = 0

        if "mask" in className:
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
                            f"/projects/{int(projectId)}/protocols/{protocolId}/outputs/{quote(str(outputName))}/thumbnail"
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
            if isinstance(output, (SetOfParticles, SetOfClasses2D)):
                return self._renderParticlesOrClasses2dPreview(protocol, output, size=size)
            if isinstance(output, (SetOfClasses3D, SetOfVolumes)):
                return self._renderClasses3dOrVolumesPreview(protocol, output, size=size)
            if isinstance(output, SetOfTiltSeries) or isinstance(output, SetOfTiltSeriesM):
                return self._renderTiltSeriesPreview(protocol, output, size=size)
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

            if "tomogram" in className or "volume" in className or "class3d" in className:
                image = self._renderVolumeLikePreview(protocol, output, size=size)
                if image is not None:
                    return image
            if "tiltseries" in className:
                image = self._renderTiltSeriesPreview(protocol, output, size=size)
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

    def _renderTiltSeriesPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        tiles: List[Image.Image] = []
        seriesList: List[Any]

        if isinstance(output, SetOfTiltSeries):
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
                frames = list(self._iterPreviewItems(tiltSeries, maxItems=3))
                if not frames:
                    continue

                pivot = frames[len(frames) // 2]
                sourcePath, sourceIndex = self._resolveImageSourceFromItem(pivot)
                if not sourcePath:
                    continue

                tile = self._readImagePreview(protocol, sourcePath, sourceIndex)
                if tile is not None:
                    tiles.append(tile)
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

    def _renderCoordinates2dPreview(self, protocol, output, size: int) -> Optional[Image.Image]:
        points: List[Tuple[float, float]] = []
        maxPoints = 1200

        for item in self._iterItemsDirect(output):
            try:
                xValue = self._readCoordinateScalar(item, "getX")
                yValue = self._readCoordinateScalar(item, "getY")

                if xValue is None or yValue is None:
                    continue

                if not np.isfinite(xValue) or not np.isfinite(yValue):
                    continue

                points.append((xValue, yValue))

                if len(points) >= maxPoints:
                    break
            except Exception:
                continue

        if not points:
            return None

        return self._buildCoordinatesScatterImage(
            title=self._getOutputClassName(output),
            points=points,
            zValues=None,
            is3d=False,
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
            getFileNameFn = getattr(candidate, "getFileName", None)
            if not callable(getFileNameFn):
                continue
            try:
                fileName = getFileNameFn()
            except Exception:
                fileName = None
            if not fileName:
                continue

            indexValue = None
            getIndexFn = getattr(candidate, "getIndex", None)
            if callable(getIndexFn):
                try:
                    indexValue = int(getIndexFn())
                except Exception:
                    indexValue = None
            return str(fileName), indexValue

        return None, None

    # ------------------------------------------------------------------
    # Low level readers
    # ------------------------------------------------------------------
    def _readImagePreview(self, protocol, filePath: str, index: Optional[int]) -> Optional[Image.Image]:
        resolvedPath = self._resolveFilePath(protocol, filePath)
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