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
from uuid import uuid4

from fastapi import HTTPException, Response, status
from PIL import Image, ImageEnhance, ImageOps
from pwem.emlib.image.image_readers import ImageReadersRegistry
from pwem.objects import Coordinate

from app.backend.api.services.project_service import ProjectService, _thumbnailProjectLock
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

        return self._resolveCoordinatesOutput(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

    def _resolveCoordinatesOutput(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            protocolId: int,
            outputName: str,
    ) -> Tuple[Any, Any]:
        protocol = self.projectService._getScipionProtocolForRuntime(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
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
            iterator = micrographsSet.iterItems(iterate=False)
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
            for coordinate in coordinatesSet.iterItems(iterate=False):
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

    def _getPostgresqlCoords2dReaderIfAvailable(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            protocolId: int,
            outputName: str,
    ):
        if mapper is None:
            return None

        try:
            from app.backend.viewers.postgresql_coords2d_reader import PostgresqlCoords2dReader

            readerProtocolId = self.projectService._resolvePostgresqlReaderProtocolId(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

            reader = PostgresqlCoords2dReader(
                db=mapper.db,
                projectId=projectId,
                protocolId=readerProtocolId,
                outputName=outputName,
            )

            if reader.hasOutput():
                return reader

        except Exception:
            logger.exception(
                "Failed to initialize PostgreSQL Coords2D reader. projectId=%s protocolId=%s outputName=%s",
                projectId,
                protocolId,
                outputName,
            )

        return None

    def listMicrographs(
        self,
        mapper: PostgresqlFlatMapper,
        projectId: int,
        currentUser: Any,
        protocolId: int,
        outputName: str,
    ) -> Dict[str, Any]:
        pgReader = self._getPostgresqlCoords2dReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            payload = pgReader.listMicrographs()
            if payload is not None:
                return payload

        if mapper is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Coordinates2D output is not available in PostgreSQL metadata"
                    if pgReader is None
                    else "Coordinates2D micrographs are not available in PostgreSQL metadata: %s"
                         % getattr(pgReader, "lastSkipReason", None)
                ),
            )

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

    def _loadPostgresqlMicrograph(
        self,
        mapper: PostgresqlFlatMapper,
        projectId: int,
        currentUser: Any,
        protocolId: int,
        outputName: str,
        micId: str,
    ) -> Any:
        with _thumbnailProjectLock:
            projectRow = self.projectService.getProjectDbRow(
                mapper=mapper,
                projectId=projectId,
                currentUser=currentUser,
            )

            if not projectRow:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Project not found",
                )

            self.projectService.loadProjectForThumbnails(
                projectRow,
                mapper=mapper,
            )

            _, coordinatesSet = self._resolveCoordinatesOutput(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
            )

            return self._findMicrograph(
                coordinatesSet,
                micId,
            )

    def listCoordinatesForMicrograph(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            currentUser: Any,
            protocolId: int,
            outputName: str,
            micId: str,
    ) -> Dict[str, Any]:
        pgReader = self._getPostgresqlCoords2dReaderIfAvailable(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if pgReader is not None:
            payload = pgReader.listCoordinatesForMicrograph(micId)
            if payload is not None:
                return payload

        if mapper is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Coordinates2D output is not available in PostgreSQL metadata"
                    if pgReader is None
                    else "Coordinates2D coordinates are not available in PostgreSQL metadata: %s"
                         % getattr(pgReader, "lastSkipReason", None)
                ),
            )

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
                    for coordinate in coordinatesSet.iterItems(iterate=False)
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

    def _resolveMicrographById(self, micrographsSet: Any, micId: str) -> Any:
        try:
            return micrographsSet[int(micId)]
        except Exception:
            pass

        try:
            for micrograph in micrographsSet.iterItems(iterate=False):
                if self._micrographId(micrograph) == str(micId):
                    return micrograph
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Micrograph '{micId}' not found in source micrographs",
        )

    def _newCoordinateLike(self, coordinatesSet: Any) -> Any:
        try:
            firstItem = coordinatesSet.getFirstItem()
            if firstItem is not None:
                return firstItem.clone()
        except Exception:
            pass

        return Coordinate()

    def _appendCoordinateToSet(
        self,
        coordinatesSet: Any,
        coordSet: Any,
        micrographsSet: Any,
        micId: str,
        x: float,
        y: float,
        objId: int,
    ) -> None:
        coordinate = self._newCoordinateLike(coordinatesSet)

        try:
            coordinate.setObjId(objId)
        except Exception:
            pass

        micrograph = self._resolveMicrographById(micrographsSet, micId)

        try:
            coordinate.setMicrograph(micrograph)
        except Exception:
            pass

        try:
            coordinate.setPosition(float(x), float(y))
        except Exception:
            try:
                coordinate.setX(float(x))
                coordinate.setY(float(y))
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid coordinate for micrograph '{micId}': {e}",
                )

        coordSet.append(coordinate)

    def createCoordinatesOutput(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            currentUser: Any,
            protocolId: int,
            outputName: str,
            payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = payload or {}

        protocol, coordinatesSet = self._loadCoordinatesOutput(
            mapper,
            projectId,
            currentUser,
            protocolId,
            outputName,
        )

        try:
            micrographsSet = coordinatesSet.getMicrographs()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not load source micrographs: {e}",
            )

        replacementMap: Dict[str, Dict[str, Any]] = {}

        for item in payload.get("micrographs") or []:
            if not isinstance(item, dict):
                continue

            rawMicId = item.get("id", item.get("micId"))
            if rawMicId is None:
                continue

            micId = str(rawMicId)
            existingCoordinates: Dict[int, Dict[str, float]] = {}
            newCoordinates: List[Dict[str, float]] = []

            for point in item.get("coordinates") or []:
                if not isinstance(point, dict):
                    continue

                x = self._safeNumber(point.get("x"), None)
                y = self._safeNumber(point.get("y"), None)

                if x is None or y is None:
                    continue

                pointId = self._tryInt(point.get("id"))
                if pointId is None:
                    newCoordinates.append({"x": x, "y": y})
                else:
                    existingCoordinates[pointId] = {"x": x, "y": y}

            replacementMap[micId] = {
                "existing": existingCoordinates,
                "new": newCoordinates,
            }

        if not replacementMap:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No coordinate changes provided",
            )

        try:
            originalCoordinates = list(coordinatesSet.iterItems(iterate=False))
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not read original coordinates: {e}",
            )

        try:
            maxObjId = coordinatesSet.aggregate(["MAX"], "_objId")[0]["MAX"] or 0
        except Exception:
            maxObjId = 0
            for coordinate in originalCoordinates:
                objId = self._tryInt(self._safeCall(coordinate, "getObjId", None))
                if objId is not None:
                    maxObjId = max(maxObjId, objId)

        try:
            suffix = f"{protocol.getOutputsSize()}_{uuid4().hex[:8]}"
            coordSet = protocol._createSetOfCoordinates(micrographsSet, suffix=suffix)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not create coordinates output: {e}",
            )

        try:
            coordSet.copyInfo(coordinatesSet)
        except Exception:
            pass

        boxSize = payload.get("boxSize", None)
        if boxSize is not None:
            try:
                coordSet.setBoxSize(int(boxSize))
            except Exception:
                pass

        totalCoordinates = 0

        try:
            for coordinate in originalCoordinates:
                micId = self._coordinateMicId(coordinate)
                if not micId:
                    continue

                objId = self._tryInt(self._safeCall(coordinate, "getObjId", None))
                if objId is None:
                    continue

                if micId in replacementMap:
                    existingCoordinates = replacementMap[micId]["existing"]

                    if objId not in existingCoordinates:
                        continue

                    x = existingCoordinates[objId]["x"]
                    y = existingCoordinates[objId]["y"]
                else:
                    x = self._safeNumber(self._safeCall(coordinate, "getX", None), None)
                    y = self._safeNumber(self._safeCall(coordinate, "getY", None), None)

                    if x is None or y is None:
                        continue

                coord = Coordinate()
                coord.setObjId(objId)
                coord.setMicrograph(self._resolveMicrographById(micrographsSet, micId))
                coord.setPosition(float(x), float(y))
                coordSet.append(coord)
                totalCoordinates += 1

            coordinateTemplate = self._newCoordinateLike(coordinatesSet)

            for micId, replacement in replacementMap.items():
                micrograph = self._resolveMicrographById(micrographsSet, micId)

                for point in replacement["new"]:
                    maxObjId += 1
                    newCoordinate = coordinateTemplate.clone()
                    newCoordinate.setObjId(maxObjId)
                    newCoordinate.setMicrograph(micrograph)
                    newCoordinate.setPosition(float(point["x"]), float(point["y"]))
                    coordSet.append(newCoordinate)
                    totalCoordinates += 1

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not append coordinates: {e}",
            )

        try:
            coordSet.write()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not write coordinates output: {e}",
            )

        requestedOutputName = str(payload.get("outputName") or "").strip()

        if requestedOutputName and not hasattr(protocol, requestedOutputName):
            nextOutputName = requestedOutputName
        else:
            try:
                nextOutputName = protocol.getNextOutputName("coordinates_")
            except Exception:
                nextOutputName = f"coordinates_{protocol.getOutputsSize()}"

        try:
            protocol._defineOutputs(**{nextOutputName: coordSet})
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not define coordinates output: {e}",
            )

        try:
            protocol._defineSourceRelation(micrographsSet, coordSet)
        except Exception:
            logger.warning("Could not define source relation for coords2d output", exc_info=True)

        return {
            "success": True,
            "outputName": nextOutputName,
            "totalCoordinates": int(totalCoordinates),
            "message": f"The new set of coordinates has been created: {nextOutputName}",
        }

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
        micrograph = self._loadPostgresqlMicrograph(
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
            protocolId=protocolId,
            outputName=outputName,
            micId=micId,
        )
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