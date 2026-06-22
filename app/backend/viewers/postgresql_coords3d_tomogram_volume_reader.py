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
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from app.backend.utils.volume_utils import readVolumeArray3d
from app.backend.viewers.postgresql_coords3d_reader import PostgresqlCoords3dReader


class PostgresqlCoords3dTomogramVolumeReader:
    """Expose tomograms resolved from a SetOfCoordinates3D as volume-like items."""

    def __init__(self, db, projectId: int, protocolId: int, outputName: str):
        self.db = db
        self.projectId = int(projectId)
        self.protocolId = int(protocolId)
        self.outputName = str(outputName)
        self.coordsReader = PostgresqlCoords3dReader(
            db=db,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )
        self.lastSkipReason = None
        self._volumes = None

    def hasOutput(self) -> bool:
        return bool(self.listVolumes())

    def listVolumes(self) -> Optional[List[Dict[str, Any]]]:
        self.lastSkipReason = None

        if self._volumes is not None:
            return self._volumes

        tomograms = self.coordsReader.listTomograms()
        if not tomograms:
            self.lastSkipReason = getattr(self.coordsReader, "lastSkipReason", None) or "coords3d_tomograms_not_found"
            return None

        volumes = []

        for index, tomogram in enumerate(tomograms):
            volume = self._buildVolumeFromTomogram(tomogram, index)
            if volume is not None:
                volumes.append(volume)

        if not volumes:
            self.lastSkipReason = "coords3d_tomograms_without_volume_files"
            return None

        self._volumes = volumes
        return self._volumes

    def getVolumeInfo(self, volumeId: Union[int, str]) -> Optional[Dict[str, Any]]:
        self.lastSkipReason = None

        volumes = self.listVolumes()
        if not volumes:
            self.lastSkipReason = self.lastSkipReason or "volume_list_empty"
            return None

        volume = self._findVolume(volumeId, volumes)
        if volume is None:
            self.lastSkipReason = "volume_not_found volumeId=%s" % str(volumeId)
            return None

        info = dict(volume)
        volumeFile = self.getVolumeFile(volume.get("id"))
        if volumeFile is None:
            return info

        info.update(volumeFile)
        self._ensureVolumeInfoFromFile(info)
        return info

    def getVolumeFile(self, volumeId: Union[int, str]) -> Optional[Dict[str, Any]]:
        volumes = self.listVolumes()
        if not volumes:
            self.lastSkipReason = self.lastSkipReason or "volume_list_empty"
            return None

        volume = self._findVolume(volumeId, volumes)
        if volume is None:
            self.lastSkipReason = "volume_not_found volumeId=%s" % str(volumeId)
            return None

        info = dict(volume)
        fileName = info.get("fileName") or info.get("path")
        if not fileName:
            self.lastSkipReason = "volume_file_not_found volumeId=%s" % str(volumeId)
            return None

        resolvedPath = self._resolveExistingPath(fileName)
        if resolvedPath is None:
            self.lastSkipReason = "volume_file_missing fileName=%s" % str(fileName)
            return None

        info["fileName"] = resolvedPath
        info["path"] = resolvedPath
        return info

    def getVolumeArray(
            self,
            volumeId: Union[int, str],
    ) -> Optional[Tuple[np.ndarray, Dict[str, Any], Dict[str, Any]]]:
        info = self.getVolumeFile(volumeId)
        if info is None:
            return None

        volumePath = info.get("fileName") or info.get("path")
        if not volumePath:
            self.lastSkipReason = "volume_file_not_found volumeId=%s" % str(volumeId)
            return None

        try:
            array, props = readVolumeArray3d(str(volumePath))
        except Exception as exc:
            self.lastSkipReason = "volume_read_failed volumeId=%s error=%s" % (
                str(volumeId),
                str(exc),
            )
            return None

        props = props if isinstance(props, dict) else {}
        return array, props, info

    def getHistogram(
            self,
            volumeId: Union[int, str],
            bins: int = 128,
    ) -> Optional[Dict[str, Any]]:
        result = self.getVolumeArray(volumeId)
        if result is None:
            return None

        array, _props, _info = result
        cleanArray = np.asarray(array, dtype=np.float32)
        cleanArray = cleanArray[np.isfinite(cleanArray)]

        if cleanArray.size == 0:
            return {
                "binEdges": [],
                "counts": [],
            }

        counts, binEdges = np.histogram(cleanArray, bins=max(4, int(bins or 128)))

        return {
            "binEdges": [float(value) for value in binEdges.tolist()],
            "counts": [int(value) for value in counts.tolist()],
        }

    def _buildVolumeFromTomogram(
            self,
            tomogram: Dict[str, Any],
            index: int,
    ) -> Optional[Dict[str, Any]]:
        fileName, locationIndex = self._extractTomogramFile(tomogram)
        if not fileName:
            return None

        volumeId = (
                tomogram.get("volumeId")
                or tomogram.get("objectId")
                or tomogram.get("id")
                or tomogram.get("tomoId")
                or tomogram.get("label")
                or index
        )

        tomoId = tomogram.get("tomoId") or tomogram.get("id") or volumeId
        label = tomogram.get("label") or tomogram.get("name") or tomoId or Path(str(fileName)).name

        volume: Dict[str, Any] = {
            "id": str(volumeId),
            "index": int(index),
            "name": str(label),
            "label": str(label),
            "relPath": str(label),
            "tomoId": str(tomoId),
            "fileName": str(fileName),
            "path": str(fileName),
            "source": "coordinates3d",
        }

        if locationIndex is not None:
            volume["locationIndex"] = locationIndex

        for key in (
                "objectId",
                "scipionItemId",
                "tsId",
                "tiltSeriesId",
                "nCoords",
                "count",
                "sourceTomoId",
        ):
            value = tomogram.get(key)
            if value is not None:
                volume[key] = value

        dims = self._normalizeDims(tomogram.get("dims"))
        if dims is not None:
            volume["dims"] = dims

        voxelSize = self._normalizeVoxelSize(tomogram.get("voxelSize"))
        if voxelSize is not None:
            volume["voxelSize"] = voxelSize
            volume["pixelSize"] = voxelSize[0]
            volume["samplingRate"] = voxelSize[0]

        return volume

    def _extractTomogramFile(self, tomogram: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
        for key in (
                "fileName",
                "filename",
                "path",
                "tomogramFile",
                "tomogramFileName",
                "tomoFile",
                "tomoFileName",
                "volumeFile",
                "volumeFileName",
                "location",
        ):
            value = tomogram.get(key)
            if value is None:
                continue

            fileName, locationIndex = self._parseLocation(value)
            if fileName:
                return fileName, locationIndex

        return None, None

    def _parseLocation(self, raw: Any) -> Tuple[Optional[str], Optional[int]]:
        if isinstance(raw, dict):
            pathValue = None
            for key in ("fileName", "filename", "path", "location", "stack"):
                if key in raw:
                    pathValue = raw.get(key)
                    break

            indexValue = None
            for key in ("index", "locationIndex", "slice", "itemIndex"):
                if key in raw:
                    indexValue = raw.get(key)
                    break

            fileName, embeddedIndex = self._parseLocation(pathValue)
            locationIndex = self._toOptionalInt(indexValue)
            if locationIndex is None:
                locationIndex = embeddedIndex

            return fileName, locationIndex

        if isinstance(raw, (list, tuple)):
            if len(raw) >= 2:
                return self._toText(raw[1]), self._toOptionalInt(raw[0])
            if len(raw) == 1:
                return self._parseLocation(raw[0])
            return None, None

        text = self._toText(raw)
        if not text:
            return None, None

        locationIndex = None
        fileName = text

        if "@" in text:
            indexText, pathText = text.split("@", 1)
            parsedIndex = self._toOptionalInt(indexText)
            if parsedIndex is not None:
                locationIndex = parsedIndex
                fileName = pathText

        return fileName, locationIndex

    def _findVolume(
            self,
            volumeId: Union[int, str],
            volumes: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        requested = self._toText(volumeId)
        if requested is None:
            return None

        for volume in volumes:
            for key in ("id", "index", "tomoId", "volumeId", "objectId", "scipionItemId", "name", "label"):
                if self._toText(volume.get(key)) == requested:
                    return volume

        requestedInt = self._toOptionalInt(requested)
        if requestedInt is not None and 0 <= requestedInt < len(volumes):
            return volumes[requestedInt]

        return None

    def _ensureVolumeInfoFromFile(self, volume: Dict[str, Any]) -> None:
        fileName = volume.get("fileName") or volume.get("path")
        resolvedPath = self._resolveExistingPath(fileName)
        if resolvedPath is None:
            return

        volume["fileName"] = resolvedPath
        volume["path"] = resolvedPath

        try:
            array, props = readVolumeArray3d(resolvedPath)
        except Exception:
            return

        if getattr(array, "ndim", None) == 3:
            zDim, yDim, xDim = array.shape
            volume["dims"] = [int(zDim), int(yDim), int(xDim)]
            volume["xyzDims"] = [int(xDim), int(yDim), int(zDim)]

        props = props if isinstance(props, dict) else {}

        if "samplingRate" not in volume:
            samplingRate = self._extractSamplingRate(props)
            if samplingRate is not None:
                volume["samplingRate"] = samplingRate
                volume["pixelSize"] = samplingRate
                volume["voxelSize"] = [samplingRate, samplingRate, samplingRate]

        try:
            finite = np.asarray(array, dtype=np.float32)
            finite = finite[np.isfinite(finite)]
            if finite.size:
                volume["min"] = float(np.min(finite))
                volume["max"] = float(np.max(finite))
                volume["mean"] = float(np.mean(finite))
        except Exception:
            pass

    def _resolveExistingPath(self, fileName: Any) -> Optional[str]:
        text = self._toText(fileName)
        if not text:
            return None

        path = Path(text).expanduser()
        candidates = []

        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.append(path)
            candidates.append(Path.cwd() / path)

        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                if resolved.exists():
                    return str(resolved)
            except Exception:
                continue

        return None

    def _normalizeDims(self, value: Any) -> Optional[List[int]]:
        if isinstance(value, dict):
            value = [
                value.get("x") or value.get("X") or value.get("nx"),
                value.get("y") or value.get("Y") or value.get("ny"),
                value.get("z") or value.get("Z") or value.get("nz"),
            ]

        if isinstance(value, (list, tuple)) and len(value) >= 3:
            dims = []
            for item in value[:3]:
                intValue = self._toOptionalInt(item)
                if intValue is None or intValue <= 0:
                    return None
                dims.append(intValue)
            return dims

        return None

    def _normalizeVoxelSize(self, value: Any) -> Optional[List[float]]:
        if value is None:
            return None

        if isinstance(value, dict):
            for key in ("x", "X", "samplingRate", "pixelSize", "voxelSize", "apix"):
                number = self._toOptionalFloat(value.get(key))
                if number is not None:
                    return [number, number, number]
            return None

        if isinstance(value, (list, tuple)):
            if len(value) == 1:
                number = self._toOptionalFloat(value[0])
                return [number, number, number] if number is not None else None

            if len(value) >= 3:
                voxelSize = []
                for item in value[:3]:
                    number = self._toOptionalFloat(item)
                    if number is None:
                        return None
                    voxelSize.append(number)
                return voxelSize

        number = self._toOptionalFloat(value)
        return [number, number, number] if number is not None else None

    def _extractSamplingRate(self, values: Dict[str, Any]) -> Optional[float]:
        for key in ("samplingRate", "pixelSize", "voxelSize", "apix"):
            number = self._toOptionalFloat(values.get(key))
            if number is not None:
                return number
        return None

    def _toOptionalInt(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None

        try:
            return int(value)
        except Exception:
            try:
                return int(float(value))
            except Exception:
                return None

    def _toOptionalFloat(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None

        try:
            return float(value)
        except Exception:
            return None

    def _toText(self, value: Any) -> Optional[str]:
        if value is None:
            return None

        text = str(value).strip()
        return text or None