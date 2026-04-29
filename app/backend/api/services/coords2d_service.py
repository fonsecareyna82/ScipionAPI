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

import io
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, Response, status
from PIL import Image, ImageEnhance, ImageOps
from pwem.emlib.image.image_readers import ImageReadersRegistry

from app.backend.api.services.project_service import ProjectService
from app.backend.mapper.postgresql import PostgresqlFlatMapper

logger = logging.getLogger(__name__)


class Coords2dService:
    def __init__(self):
        self.projectService = ProjectService()

    def _loadCoordinatesOutput(
        self,
        mapper: PostgresqlFlatMapper,
        projectId: int,
        currentUser: Any,
        protocolId: int,
        outputName: str,
    ) -> Tuple[Any, Any]:
        project = self.projectService.getProjectById(
            mapper,
            projectId,
            currentUser,
            refresh=False,
            checkPid=False,
        )
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        currentProject = self.projectService.currentProject
        if currentProject is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Project could not be loaded",
            )

        try:
            protocol = currentProject.getProtocol(int(protocolId))
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol '{protocolId}' not found: {e}",
            )

        if protocol is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol '{protocolId}' not found",
            )

        if not hasattr(protocol, outputName):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Output '{outputName}' not found in protocol '{protocolId}'",
            )

        coordinatesSet = getattr(protocol, outputName)
        if coordinatesSet is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Output '{outputName}' is empty",
            )

        if not hasattr(coordinatesSet, "getMicrographs") or not hasattr(coordinatesSet, "iterCoordinates"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Output '{outputName}' is not a SetOfCoordinates output",
            )

        return protocol, coordinatesSet

    @staticmethod
    def _safeCall(obj: Any, methodName: str, default: Any = None) -> Any:
        try:
            method = getattr(obj, methodName, None)
            if not callable(method):
                return default
            value = method()
            return default if value is None else value
        except Exception:
            return default

    @staticmethod
    def _safeNumber(value: Any, default: Optional[float] = None) -> Optional[float]:
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _tryInt(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _micrographId(micrograph: Any) -> str:
        value = Coords2dService._safeCall(micrograph, "getObjId", None)
        return str(value) if value is not None else ""

    @staticmethod
    def _splitLocationValue(location: Any) -> Tuple[Optional[int], str]:
        if location is None:
            return None, ""

        if isinstance(location, (tuple, list)) and len(location) >= 2:
            first = location[0]
            second = location[1]

            firstIndex = Coords2dService._tryInt(first)
            secondIndex = Coords2dService._tryInt(second)

            if firstIndex is not None:
                return firstIndex, str(second or "")

            if secondIndex is not None:
                return secondIndex, str(first or "")

            return None, str(second or first or "")

        locationText = str(location or "").strip()
        if not locationText:
            return None, ""

        if "@" in locationText:
            rawIndex, rawFileName = locationText.split("@", 1)
            imageIndex = Coords2dService._tryInt(rawIndex)
            return imageIndex, rawFileName

        return None, locationText

    @staticmethod
    def _micrographLocation(micrograph: Any) -> Tuple[Optional[int], str]:
        location = Coords2dService._safeCall(micrograph, "getLocation", None)
        imageIndex, fileName = Coords2dService._splitLocationValue(location)

        if fileName:
            return imageIndex, fileName

        fileName = str(Coords2dService._safeCall(micrograph, "getFileName", "") or "")
        parsedIndex, parsedFileName = Coords2dService._splitLocationValue(fileName)

        if parsedFileName:
            return parsedIndex if parsedIndex is not None else imageIndex, parsedFileName

        return imageIndex, fileName

    @staticmethod
    def _micrographFileName(micrograph: Any) -> str:
        _, fileName = Coords2dService._micrographLocation(micrograph)
        return fileName

    @staticmethod
    def _micrographName(micrograph: Any) -> str:
        micName = Coords2dService._safeCall(micrograph, "getMicName", None)
        if micName:
            return str(micName)

        label = Coords2dService._safeCall(micrograph, "getObjLabel", None)
        if label:
            return str(label)

        _, fileName = Coords2dService._micrographLocation(micrograph)
        return os.path.basename(str(fileName)) or "Untitled"

    @staticmethod
    def _micrographDims(micrograph: Any) -> Tuple[Optional[int], Optional[int]]:
        dims = Coords2dService._safeCall(micrograph, "getDim", None)
        if not dims:
            return None, None

        try:
            width = int(dims[0]) if len(dims) > 0 and dims[0] is not None else None
            height = int(dims[1]) if len(dims) > 1 and dims[1] is not None else None
            return width, height
        except Exception:
            return None, None

    @staticmethod
    def _coordinateMicId(coordinate: Any) -> Optional[str]:
        value = Coords2dService._safeCall(coordinate, "getMicId", None)
        return str(value) if value is not None else None

    @staticmethod
    def _extractCoordinateScore(coordinate: Any) -> Optional[float]:
        for methodName in ("getScore", "getWeight"):
            value = Coords2dService._safeCall(coordinate, methodName, None)
            score = Coords2dService._safeNumber(value, None)
            if score is not None:
                return score
        return None

    @staticmethod
    def _extractCoordinateClassLabel(coordinate: Any) -> Optional[str]:
        for methodName in ("getClassId", "getObjLabel"):
            value = Coords2dService._safeCall(coordinate, methodName, None)
            if value is not None and str(value).strip():
                return str(value)
        return None

    @staticmethod
    def _micrographSortKey(micId: str):
        try:
            return 0, int(micId)
        except Exception:
            return 1, str(micId).lower()

    def _buildMicrographMap(self, coordinatesSet: Any) -> Dict[str, Any]:
        try:
            micrographsSet = coordinatesSet.getMicrographs()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not load coordinate micrographs: {e}",
            )

        micrographs: Dict[str, Any] = {}
        try:
            iterator = micrographsSet.iterItems()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not iterate micrographs: {e}",
            )

        for micrograph in iterator:
            micId = self._micrographId(micrograph)
            if micId:
                micrographs[micId] = micrograph.clone()

        return micrographs

    def _countCoordinatesByMicrograph(self, coordinatesSet: Any) -> Dict[str, int]:
        counts: Dict[str, int] = {}

        try:
            for coordinate in coordinatesSet.iterItems():
                micId = self._coordinateMicId(coordinate)
                if not micId:
                    continue
                counts[micId] = counts.get(micId, 0) + 1
            return counts
        except Exception:
            pass

        try:
            micrographs = self._buildMicrographMap(coordinatesSet)
            for micId in micrographs:
                counts[micId] = len(list(coordinatesSet.iterCoordinates(int(micId))))
            return counts
        except Exception:
            return counts

    def listMicrographs(
        self,
        mapper: PostgresqlFlatMapper,
        projectId: int,
        currentUser: Any,
        protocolId: int,
        outputName: str,
    ) -> Dict[str, Any]:
        _, coordinatesSet = self._loadCoordinatesOutput(
            mapper,
            projectId,
            currentUser,
            protocolId,
            outputName,
        )

        micrographMap = self._buildMicrographMap(coordinatesSet)
        counts = self._countCoordinatesByMicrograph(coordinatesSet)
        boxSize = self._safeCall(coordinatesSet, "getBoxSize", None)
        totalPicks = self._safeCall(coordinatesSet, "getSize", None)

        micrographs: List[Dict[str, Any]] = []
        sortedMicIds = sorted(micrographMap.keys(), key=self._micrographSortKey)

        for index, micId in enumerate(sortedMicIds, start=1):
            micrograph = micrographMap[micId]
            imageIndex, fileName = self._micrographLocation(micrograph)
            width, height = self._micrographDims(micrograph)

            micrographs.append({
                "id": micId,
                "index": index,
                "fileName": fileName,
                "label": self._micrographName(micrograph),
                "particles": int(counts.get(micId, 0)),
                "updated": False,
                "width": width,
                "height": height,
                "locationIndex": imageIndex,
                "thumbnailUrl": None,
            })

        if totalPicks is None:
            totalPicks = sum(int(item.get("particles") or 0) for item in micrographs)

        return {
            "micrographs": micrographs,
            "totalMicrographs": len(micrographs),
            "totalPicks": int(totalPicks or 0),
            "boxSize": int(boxSize) if boxSize else None,
        }

    def _findMicrograph(self, coordinatesSet: Any, micId: str) -> Any:
        micrograph = self._buildMicrographMap(coordinatesSet).get(str(micId))
        if micrograph is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Micrograph '{micId}' not found in coordinates output",
            )
        return micrograph

    def listCoordinatesForMicrograph(
        self,
        mapper: PostgresqlFlatMapper,
        projectId: int,
        currentUser: Any,
        protocolId: int,
        outputName: str,
        micId: str,
    ) -> Dict[str, Any]:
        _, coordinatesSet = self._loadCoordinatesOutput(
            mapper,
            projectId,
            currentUser,
            protocolId,
            outputName,
        )

        self._findMicrograph(coordinatesSet, micId)

        try:
            coordinatesIterator = coordinatesSet.iterCoordinates(int(micId))
        except Exception:
            coordinatesIterator = []
            try:
                coordinatesIterator = [
                    coordinate
                    for coordinate in coordinatesSet.iterItems()
                    if self._coordinateMicId(coordinate) == str(micId)
                ]
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Could not iterate coordinates for micrograph '{micId}': {e}",
                )

        coordinates: List[Dict[str, Any]] = []
        for index, coordinate in enumerate(coordinatesIterator):
            x = self._safeNumber(self._safeCall(coordinate, "getX", None), None)
            y = self._safeNumber(self._safeCall(coordinate, "getY", None), None)
            if x is None or y is None:
                continue

            objId = self._safeCall(coordinate, "getObjId", None)
            coordinates.append({
                "id": objId if objId is not None else f"{micId}:{index}",
                "micId": str(micId),
                "x": x,
                "y": y,
                "score": self._extractCoordinateScore(coordinate),
                "classLabel": self._extractCoordinateClassLabel(coordinate),
            })

        return {"coordinates": coordinates}

    @staticmethod
    def _normalizeImageFormat(fmt: str) -> Tuple[str, str]:
        value = (fmt or "png").strip().lower()
        if value in {"jpg", "jpeg"}:
            return "JPEG", "image/jpeg"
        if value == "webp":
            return "WEBP", "image/webp"
        return "PNG", "image/png"

    @staticmethod
    def _prepareImage(image: Image.Image, size: int) -> Image.Image:
        if image.mode not in {"L", "RGB", "RGBA"}:
            image = image.convert("L")

        if image.mode == "L":
            image = ImageOps.autocontrast(image)
            image = ImageEnhance.Contrast(image).enhance(1.6)
        elif image.mode == "RGBA":
            image = image.convert("RGB")

        if size and size > 0:
            image.thumbnail((int(size), int(size)), Image.Resampling.LANCZOS)

        return image

    @staticmethod
    def _readMicrographImage(imagePath: str, imageIndex: Optional[int]) -> Image.Image:
        imageStack = ImageReadersRegistry.open(imagePath)

        if imageIndex is None:
            return imageStack.getImage(pilImage=True)

        try:
            return imageStack.getImage(index=imageIndex, pilImage=True)
        except Exception:
            pass

        try:
            return imageStack.getImage(imageIndex, pilImage=True)
        except Exception:
            pass

        if imageIndex > 0:
            zeroBasedIndex = imageIndex - 1

            try:
                return imageStack.getImage(index=zeroBasedIndex, pilImage=True)
            except Exception:
                pass

            try:
                return imageStack.getImage(zeroBasedIndex, pilImage=True)
            except Exception:
                pass

        return imageStack.getImage(pilImage=True)

    def renderMicrographImage(
        self,
        mapper: PostgresqlFlatMapper,
        projectId: int,
        currentUser: Any,
        protocolId: int,
        outputName: str,
        micId: str,
        size: int = 2200,
        fmt: str = "png",
    ) -> Response:
        _, coordinatesSet = self._loadCoordinatesOutput(
            mapper,
            projectId,
            currentUser,
            protocolId,
            outputName,
        )

        micrograph = self._findMicrograph(coordinatesSet, micId)
        imageIndex, imagePath = self._micrographLocation(micrograph)

        if not imagePath:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Micrograph '{micId}' does not have a file path",
            )

        imagePath = os.path.abspath(imagePath)
        if not os.path.exists(imagePath):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Micrograph image file not found: {imagePath}",
            )

        try:
            image = self._readMicrographImage(imagePath, imageIndex)
            originalWidth, originalHeight = image.size
            image = self._prepareImage(image, size)
        except Exception as e:
            logger.exception("Failed to render coords2d micrograph image: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to render micrograph image: {e}",
            )

        imageFormat, mediaType = self._normalizeImageFormat(fmt)
        buffer = io.BytesIO()
        saveOptions: Dict[str, Any] = {}

        if imageFormat == "JPEG":
            if image.mode != "RGB":
                image = image.convert("RGB")
            saveOptions["quality"] = 90
        elif imageFormat == "WEBP":
            saveOptions["quality"] = 85

        image.save(buffer, format=imageFormat, **saveOptions)

        scaleX = image.width / originalWidth if originalWidth else 1
        scaleY = image.height / originalHeight if originalHeight else 1

        headers = {
            "X-Preview-Width": str(image.width),
            "X-Preview-Height": str(image.height),
            "X-Preview-Original-Width": str(originalWidth),
            "X-Preview-Original-Height": str(originalHeight),
            "X-Preview-Scale-X": f"{scaleX:.8f}",
            "X-Preview-Scale-Y": f"{scaleY:.8f}",
            "X-Preview-Origin": "top-left",
            "X-Preview-Orientation": "scipion-top-left-no-flip",
            "X-Preview-MicrographId": str(micId),
            "X-Preview-Source-Index": "" if imageIndex is None else str(imageIndex),
            "X-Preview-Source-File": os.path.basename(imagePath),
            "X-Preview-Format": imageFormat,
            "Cache-Control": "no-store",
        }

        return Response(
            content=buffer.getvalue(),
            media_type=mediaType,
            headers=headers,
        )