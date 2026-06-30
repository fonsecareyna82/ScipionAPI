import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np

from app.backend.utils.volume_utils import readVolumeArray3d


class PostgresqlVolumeReader:
    """Read Volume, VolumeMask and SetOfVolumes outputs from PostgreSQL."""

    def __init__(self, db, projectId: int, protocolId: int, outputName: str):
        self.db = db
        self.projectId = int(projectId)
        self.protocolId = int(protocolId)
        self.outputName = str(outputName)
        self.lastSkipReason = None
        self._protocolDbId = None
        self._storedSet = None
        self._storedObjectTree = None
        self._volumes = None

    def hasOutput(self) -> bool:
        if self._getStoredSet() is not None:
            return True

        return bool(self._getStoredObjectTree())

    def listVolumes(self) -> Optional[List[Dict[str, Any]]]:
        self.lastSkipReason = None

        if self._volumes is not None:
            return self._volumes

        storedSet = self._getStoredSet()
        if storedSet is not None:
            volumes = self._listSetVolumes(storedSet)
            if volumes:
                self._volumes = volumes
                return self._volumes

        objectTree = self._getStoredObjectTree()
        if objectTree:
            volume = self._buildSingleVolumeFromObjectTree(objectTree)
            if volume is not None:
                self._volumes = [volume]
                return self._volumes

        self.lastSkipReason = "volume_output_not_resolved"
        return None

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
        self._ensureVolumeInfoFromFile(info)
        return info

    def getVolumeFile(self, volumeId: Union[int, str]) -> Optional[Dict[str, Any]]:
        info = self.getVolumeInfo(volumeId)
        if info is None:
            return None

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

    def _listSetVolumes(self, storedSet: Dict[str, Any]) -> List[Dict[str, Any]]:
        volumes: List[Dict[str, Any]] = []

        for index, item in enumerate(storedSet.get("items") or []):
            values = self._normalizeJsonObject(item.get("values"))
            volume = self._buildVolumeFromSetItem(
                item=item,
                values=values,
                index=index,
            )

            if volume is not None:
                volumes.append(volume)

        return volumes

    def _buildVolumeFromSetItem(
            self,
            item: Dict[str, Any],
            values: Dict[str, Any],
            index: int,
    ) -> Optional[Dict[str, Any]]:
        fileName, locationIndex = self._extractVolumeFile(values)
        scipionItemId = item.get("scipionItemId")

        rawLabel = (
                item.get("label")
                or self._firstValueBySuffix(values, ["objLabel", "label", "name", "volName"])
        )

        label = self._normalizeVolumeDisplayName(
            label=rawLabel,
            fileName=fileName,
            index=index,
        )

        volume: Dict[str, Any] = {
            "id": int(index),
            "index": int(index),
            "name": str(label),
            "label": str(label),
            "relPath": str(label),
        }

        if scipionItemId is not None:
            volume["objectId"] = scipionItemId
            volume["scipionItemId"] = scipionItemId

        className = item.get("className") or self._firstValueBySuffix(values, ["className"])
        if className:
            volume["className"] = str(className)

        if fileName:
            volume["fileName"] = fileName
            volume["path"] = fileName

        if locationIndex is not None:
            volume["locationIndex"] = locationIndex

        tsId = self._firstValueBySuffix(
            values,
            ["tsId", "tiltSeriesId"],
        )
        if tsId is not None:
            volume["tsId"] = tsId
            volume["tiltSeriesId"] = tsId

        tomoId = self._firstValueBySuffix(
            values,
            ["tomoId", "tomogramId"],
        )
        if tomoId is not None:
            volume["tomoId"] = tomoId
            volume["tomogramId"] = tomoId

        dims = self._extractDims(values)
        if dims is not None:
            volume["dims"] = dims

        samplingRate = self._extractSamplingRate(values)
        if samplingRate is not None:
            self._attachSamplingRate(volume, samplingRate)

        return volume

    def _buildSingleVolumeFromObjectTree(
            self,
            rows: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        root = None
        valuesByPath: Dict[str, Any] = {}

        for row in rows:
            path = str(row.get("path") or "")
            if path == self.outputName:
                root = row
                continue

            if path.startswith(self.outputName + "."):
                suffix = path[len(self.outputName) + 1:]
                valuesByPath[suffix] = row.get("value")

        if root is None:
            return None

        fileName, locationIndex = self._extractVolumeFile(valuesByPath)
        rawLabel = root.get("label") or root.get("name") or self.outputName
        label = self._normalizeVolumeDisplayName(
            label=rawLabel,
            fileName=fileName,
            index=0,
        )

        volume: Dict[str, Any] = {
            "id": 0,
            "index": 0,
            "name": str(label),
            "label": str(label),
            "relPath": str(label),
        }

        objectId = root.get("scipionObjId")
        if objectId is not None:
            volume["objectId"] = objectId
            volume["scipionItemId"] = objectId

        className = root.get("className")
        if className:
            volume["className"] = str(className)

        if fileName:
            volume["fileName"] = fileName
            volume["path"] = fileName

        if locationIndex is not None:
            volume["locationIndex"] = locationIndex

        tsId = self._firstValueBySuffix(
            valuesByPath,
            ["tsId", "tiltSeriesId"],
        )
        if tsId is not None:
            volume["tsId"] = tsId
            volume["tiltSeriesId"] = tsId

        tomoId = self._firstValueBySuffix(
            valuesByPath,
            ["tomoId", "tomogramId"],
        )
        if tomoId is not None:
            volume["tomoId"] = tomoId
            volume["tomogramId"] = tomoId

        dims = self._extractDims(valuesByPath)
        if dims is not None:
            volume["dims"] = dims

        samplingRate = self._extractSamplingRate(valuesByPath)
        if samplingRate is not None:
            self._attachSamplingRate(volume, samplingRate)

        return volume

    def _findVolume(
            self,
            volumeId: Union[int, str],
            volumes: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        requested = self._toText(volumeId)
        if requested is None:
            return None

        for volume in volumes:
            if self._toText(volume.get("id")) == requested:
                return volume

        for volume in volumes:
            if self._toText(volume.get("index")) == requested:
                return volume

        requestedInt = self._toOptionalInt(requested)
        if requestedInt is not None and 0 <= requestedInt < len(volumes):
            return volumes[requestedInt]

        for volume in volumes:
            for key in ("objectId", "scipionItemId"):
                if self._toText(volume.get(key)) == requested:
                    return volume

        for volume in volumes:
            for key in ("name", "label"):
                if self._toText(volume.get(key)) == requested:
                    return volume

        return None

    def _ensureVolumeInfoFromFile(self, volume: Dict[str, Any]) -> None:
        fileName = volume.get("fileName") or volume.get("path")
        if not fileName:
            return

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

        if "samplingRate" not in volume:
            samplingRate = self._extractSamplingRate(props if isinstance(props, dict) else {})
            if samplingRate is not None:
                self._attachSamplingRate(volume, samplingRate)

        try:
            finite = np.asarray(array, dtype=np.float32)
            finite = finite[np.isfinite(finite)]
            if finite.size:
                volume["min"] = float(np.min(finite))
                volume["max"] = float(np.max(finite))
                volume["mean"] = float(np.mean(finite))
        except Exception:
            pass

    def _getStoredSet(self) -> Optional[Dict[str, Any]]:
        if self._storedSet is not None:
            return self._storedSet

        protocolDbId = self._resolveProtocolDbId()
        if protocolDbId is None:
            return None

        storedSet = self.db.fetchOne(
            """
            SELECT id, "projectId", "protocolDbId", "objectId", "outputName",
                   "setClassName", "itemClassName", properties, "createdAt", "updatedAt"
              FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND "outputName" = %s
            """,
            (self.projectId, protocolDbId, self.outputName),
        )

        if storedSet is None:
            return None

        items = self.db.fetchAll(
            """
            SELECT id, "setId", "scipionItemId", enabled, label, comment,
                   creation, "values", "createdAt", "updatedAt"
              FROM scipion_set_items
             WHERE "setId" = %s
             ORDER BY "scipionItemId" ASC NULLS LAST, id ASC
            """,
            (storedSet["id"],),
        )

        storedSet["items"] = items or []
        self._storedSet = storedSet
        return self._storedSet

    def _getStoredObjectTree(self) -> List[Dict[str, Any]]:
        if self._storedObjectTree is not None:
            return self._storedObjectTree

        protocolDbId = self._resolveProtocolDbId()
        if protocolDbId is None:
            self._storedObjectTree = []
            return self._storedObjectTree

        rootPath = str(self.outputName)
        rows = self.db.fetchAll(
            """
            SELECT id, "projectId", "protocolDbId", "scipionObjId", "parentObjectId",
                   name, path, "className", value, label, comment, creation,
                   metadata, "createdAt", "updatedAt"
              FROM scipion_objects
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND (path = %s OR path LIKE %s)
             ORDER BY path ASC
            """,
            (self.projectId, protocolDbId, rootPath, rootPath + ".%"),
        )

        self._storedObjectTree = rows or []
        return self._storedObjectTree

    def _resolveProtocolDbId(self) -> Optional[int]:
        if self._protocolDbId is not None:
            return self._protocolDbId

        row = self.db.fetchOne(
            """
            SELECT id
              FROM protocols
             WHERE id = %s
               AND "projectId" = %s
            """,
            (self.protocolId, self.projectId),
        )

        if row is not None:
            self._protocolDbId = int(row["id"])
            return self._protocolDbId

        row = self.db.fetchOne(
            """
            SELECT id
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
            """,
            (self.projectId, str(self.protocolId)),
        )

        if row is not None:
            self._protocolDbId = int(row["id"])
            return self._protocolDbId

        self.lastSkipReason = "protocol_not_found"
        return None

    def _extractVolumeFile(self, values: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
        raw = self._firstValueBySuffix(
            values,
            [
                "fileName",
                "filename",
                "location",
                "path",
                "stack",
            ],
        )

        return self._parseLocation(raw)

    def _parseLocation(self, raw: Any) -> Tuple[Optional[str], Optional[int]]:
        parsed = self._parseJsonValue(raw)

        if isinstance(parsed, dict):
            pathValue = None
            for key in ("fileName", "filename", "path", "location", "stack"):
                if key in parsed:
                    pathValue = parsed.get(key)
                    break

            indexValue = None
            for key in ("index", "locationIndex", "slice", "itemIndex"):
                if key in parsed:
                    indexValue = parsed.get(key)
                    break

            fileName, embeddedIndex = self._parseLocation(pathValue)
            locationIndex = self._toOptionalInt(indexValue)
            if locationIndex is None:
                locationIndex = embeddedIndex

            return fileName, locationIndex

        if isinstance(parsed, (list, tuple)):
            if len(parsed) >= 2:
                locationIndex = self._toOptionalInt(parsed[0])
                fileName = self._toText(parsed[1])
                return fileName, locationIndex

            if len(parsed) == 1:
                return self._parseLocation(parsed[0])

            return None, None

        text = self._toText(parsed)
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

    def _extractDims(self, values: Dict[str, Any]) -> Optional[List[int]]:
        raw = self._firstValueBySuffix(
            values,
            [
                "dim",
                "dims",
                "dimensions",
                "volumeDim",
                "volumeDims",
                "xyzDims",
                "size",
                "_dim",
            ],
        )

        parsed = self._parseJsonValue(raw)
        if isinstance(parsed, dict):
            parsed = [
                parsed.get("x") or parsed.get("X") or parsed.get("nx"),
                parsed.get("y") or parsed.get("Y") or parsed.get("ny"),
                parsed.get("z") or parsed.get("Z") or parsed.get("nz"),
            ]

        numbers = self._parseNumericSequence(parsed)
        if numbers is None or len(numbers) < 3:
            return None

        dims: List[int] = []
        for value in numbers[:3]:
            intValue = self._toOptionalInt(value)
            if intValue is None or intValue <= 0:
                return None
            dims.append(intValue)

        return dims

    def _extractSamplingRate(self, values: Any) -> Optional[float]:
        if isinstance(values, dict):
            raw = self._firstValueBySuffix(
                values,
                [
                    "samplingRate",
                    "pixelSize",
                    "voxelSize",
                    "sampling",
                    "apix",
                    "_samplingRate",
                ],
            )
        else:
            raw = values

        parsed = self._parseJsonValue(raw)

        if isinstance(parsed, dict):
            for key in ("x", "X", "samplingRate", "pixelSize", "voxelSize", "apix"):
                value = parsed.get(key)
                number = self._toOptionalFloat(value)
                if number is not None:
                    return number
            return None

        numbers = self._parseNumericSequence(parsed)
        if numbers:
            return self._toOptionalFloat(numbers[0])

        return self._toOptionalFloat(parsed)

    def _attachSamplingRate(self, volume: Dict[str, Any], samplingRate: float) -> None:
        samplingRate = float(samplingRate)
        volume["samplingRate"] = samplingRate
        volume["pixelSize"] = samplingRate
        volume["voxelSize"] = [samplingRate, samplingRate, samplingRate]

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

    def _normalizeVolumeDisplayName(
            self,
            label: Any,
            fileName: Optional[str],
            index: int,
    ) -> str:
        labelText = self._toText(label)

        if labelText:
            if self._looksLikePath(labelText):
                return Path(labelText).name
            return labelText

        if fileName:
            return Path(str(fileName)).name

        return "Volume %s" % (int(index) + 1)

    def _looksLikePath(self, value: Any) -> bool:
        text = str(value or "").strip()
        if not text:
            return False

        if "/" in text or "\\" in text:
            return True

        suffix = Path(text).suffix.lower()
        return suffix in {
            ".mrc",
            ".map",
            ".mrcs",
            ".rec",
            ".ali",
            ".vol",
            ".spi",
            ".stk",
        }

    def _makeVolumeLabel(self, fileName: Optional[str], index: int) -> str:
        if fileName:
            try:
                return Path(str(fileName)).name
            except Exception:
                pass

        return "Volume %s" % (int(index) + 1)

    def _getVolumeApiKeys(self, volume: Dict[str, Any]) -> Set[str]:
        return {
            text
            for text in (
                self._toText(volume.get("id")),
                self._toText(volume.get("index")),
            )
            if text
        }

    def _firstValueBySuffix(self, values: Dict[str, Any], suffixes: List[str]) -> Any:
        if not isinstance(values, dict):
            return None

        normalizedSuffixes = [
            self._normalizeKey(suffix)
            for suffix in suffixes
            if suffix is not None
        ]

        for suffix in normalizedSuffixes:
            for key, value in values.items():
                normalizedKey = self._normalizeKey(key)
                if normalizedKey == suffix or normalizedKey.endswith(suffix):
                    return value

        return None

    def _normalizeJsonObject(self, value: Any) -> Dict[str, Any]:
        parsed = self._parseJsonValue(value)
        if isinstance(parsed, dict):
            return parsed
        return {}

    def _parseNumericSequence(self, value: Any) -> Optional[List[float]]:
        parsed = self._parseJsonValue(value)

        if parsed is None or parsed == "":
            return None

        if isinstance(parsed, np.ndarray):
            rawValues = parsed.ravel().tolist()
        elif isinstance(parsed, (list, tuple)):
            rawValues = list(parsed)
        elif isinstance(parsed, str):
            text = parsed.strip()
            if not text:
                return None

            cleaned = text.strip("[]()")
            if not cleaned:
                return None

            # Accept:
            #   "128,128,64"
            #   "128 128 64"
            #   "128;128;64"
            #   "128x128x64"
            tokens = [
                token.strip()
                for token in re.split(r"[\s,;xX]+", cleaned)
                if token.strip()
            ]
            rawValues = tokens
        else:
            rawValues = [parsed]

        values: List[float] = []
        for rawValue in rawValues:
            try:
                number = float(rawValue)
            except Exception:
                return None

            if not np.isfinite(number):
                return None

            values.append(number)

        return values or None

    def _parseJsonValue(self, value: Any) -> Any:
        if isinstance(value, (dict, list, tuple)):
            return value

        if not isinstance(value, str):
            return value

        text = value.strip()
        if not text:
            return value

        if not (
            text.startswith("{")
            or text.startswith("[")
            or text.startswith('"')
        ):
            return value

        try:
            return json.loads(text)
        except Exception:
            return value

    def _normalizeKey(self, value: Any) -> str:
        return (
            str(value or "")
            .replace("_", "")
            .replace(".", "")
            .replace("-", "")
            .lower()
        )

    def _toText(self, value: Any) -> Optional[str]:
        if value is None:
            return None

        getter = getattr(value, "get", None)
        if callable(getter):
            try:
                value = getter()
            except Exception:
                return None

        text = str(value).strip()
        return text or None

    def _toOptionalInt(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None

        try:
            return int(value)
        except Exception:
            pass

        try:
            return int(float(value))
        except Exception:
            return None

    def _toOptionalFloat(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None

        try:
            number = float(value)
        except Exception:
            return None

        if not np.isfinite(number):
            return None

        return number