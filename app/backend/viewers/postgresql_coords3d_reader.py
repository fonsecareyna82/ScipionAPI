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
import json
import os
import re
from typing import Any, Dict, List, Optional, Set

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class PostgresqlCoords3dReader:
    def __init__(self, db, projectId: int, protocolId: int, outputName: str):
        self.db = db
        self.projectId = projectId
        self.protocolId = protocolId
        self.outputName = outputName
        self.setMapper = ScipionSetPostgresqlMapper(db)
        self._storedSet = None
        self.lastSkipReason = None

    def hasOutput(self) -> bool:
        return self._getStoredSet() is not None

    def listTomograms(self) -> Optional[List[Dict[str, Any]]]:
        self.lastSkipReason = None

        storedSet = self._getStoredSet()
        if storedSet is None:
            self.lastSkipReason = "stored_set_not_found"
            return None

        countsByKey = self._countCoordinatesByTomogramKey(storedSet)
        coordinateKeys = set(countsByKey.keys())

        linkedTomograms = self._getLinkedTomogramsFromProperties(storedSet)
        payload = self._buildTomogramPayloadFromLinkedTomograms(
            linkedTomograms=linkedTomograms,
            countsByKey=countsByKey,
        )

        if payload is not None:
            return payload

        payload = self._buildTomogramPayloadFromProjectSets(
            coordinateKeys=coordinateKeys,
            countsByKey=countsByKey,
        )

        if payload is not None:
            return payload

        if not linkedTomograms:
            self.lastSkipReason = (
                "linked_tomograms_not_found "
                "and_project_tomograms_not_resolved "
                "coordinateKeys=%s"
            ) % sorted(coordinateKeys)
        else:
            self.lastSkipReason = (
                "linked_tomograms_invalid "
                "and_project_tomograms_not_resolved "
                "coordinateKeys=%s"
            ) % sorted(coordinateKeys)

        return None

    def getPoints(self, tomogramId: Any) -> Optional[List[Dict[str, Any]]]:
        self.lastSkipReason = None

        storedSet = self._getStoredSet()
        if storedSet is None:
            self.lastSkipReason = "stored_set_not_found"
            return None

        targetKeys = self._resolveTomogramTargetKeys(storedSet, tomogramId)
        if not targetKeys:
            self.lastSkipReason = "tomogram_target_keys_not_resolved tomogramId=%s" % str(tomogramId)
            return None

        boxSize = self._extractBoxSize(storedSet)
        points: List[Dict[str, Any]] = []

        for item in storedSet.get("items") or []:
            values = item.get("values") or {}
            coordinateKeys = set(self._extractCoordinateTomogramKeys(values))

            if not coordinateKeys.intersection(targetKeys):
                continue

            point = self._buildCoordinatePoint(
                item=item,
                values=values,
                tomogramId=tomogramId,
                boxSize=boxSize,
            )

            if point is not None:
                points.append(point)

        if not points:
            self.lastSkipReason = (
                "coordinates_not_found_for_tomogram "
                "tomogramId=%s targetKeys=%s"
            ) % (str(tomogramId), sorted(targetKeys))
            return None

        return points

    def _getStoredSet(self) -> Optional[Dict[str, Any]]:
        if self._storedSet is None:
            self._storedSet = self.setMapper.getStoredSet(
                projectId=self.projectId,
                protocolDbId=self.protocolId,
                outputName=self.outputName,
            )
        return self._storedSet

    def _buildTomogramPayloadFromLinkedTomograms(
            self,
            linkedTomograms: List[Dict[str, Any]],
            countsByKey: Dict[str, int],
    ) -> Optional[List[Dict[str, Any]]]:
        if not linkedTomograms:
            return None

        result = []
        for item in linkedTomograms:
            normalized = self._normalizeLinkedTomogramItem(item)
            if normalized is None:
                continue

            count = self._findTomogramCount(normalized, countsByKey)
            if count is not None:
                normalized["nCoords"] = count
                normalized["count"] = count

            result.append(normalized)

        if not result:
            return None

        if not self._hasTomogramViewerContract(result):
            return None

        return result

    def _buildTomogramPayloadFromProjectSets(
            self,
            coordinateKeys: Set[str],
            countsByKey: Dict[str, int],
    ) -> Optional[List[Dict[str, Any]]]:
        if not coordinateKeys:
            return None

        rows = self._getProjectTomogramRows()
        if not rows:
            return None

        resultById: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            summary = self._buildTomogramSummaryFromStoredItem(row)
            if summary is None:
                continue

            matchKeys = self._getTomogramMatchKeys(summary)
            if not matchKeys.intersection(coordinateKeys):
                continue

            count = self._findTomogramCount(summary, countsByKey)
            if count is not None:
                summary["nCoords"] = count
                summary["count"] = count

            resultKey = str(summary.get("id"))
            existing = resultById.get(resultKey)

            if existing is None:
                resultById[resultKey] = summary
                continue

            resultById[resultKey] = self._mergeTomogramSummaries(existing, summary)

        result = list(resultById.values())
        if not result:
            return None

        if not self._hasTomogramViewerContract(result):
            return None

        return result

    def _getProjectTomogramRows(self) -> List[Dict[str, Any]]:
        try:
            return self.db.fetchAll(
                """
                SELECT
                    s.id AS "setId",
                    s."projectId",
                    s."protocolDbId",
                    s."outputName",
                    s."setClassName",
                    s."itemClassName",
                    s.properties AS "setProperties",
                    i.id AS "itemRowId",
                    i."scipionItemId",
                    i.enabled,
                    i.label,
                    i.comment,
                    i.creation,
                    i."values",
                    i."createdAt",
                    i."updatedAt"
                FROM scipion_sets s
                JOIN scipion_set_items i
                  ON i."setId" = s.id
                WHERE s."projectId" = %s
                  AND (
                        LOWER(COALESCE(s."setClassName", '')) LIKE '%%tomogram%%'
                     OR LOWER(COALESCE(s."itemClassName", '')) LIKE '%%tomogram%%'
                     OR LOWER(COALESCE(s."setClassName", '')) LIKE '%%volume%%'
                     OR LOWER(COALESCE(s."itemClassName", '')) LIKE '%%volume%%'
                  )
                ORDER BY
                    CASE
                        WHEN LOWER(COALESCE(s."itemClassName", '')) LIKE '%%tomogram%%' THEN 0
                        WHEN LOWER(COALESCE(s."setClassName", '')) LIKE '%%tomogram%%' THEN 1
                        ELSE 2
                    END,
                    s."protocolDbId" ASC,
                    s."outputName" ASC,
                    i."scipionItemId" ASC
                """,
                (self.projectId,),
            )
        except Exception:
            return []

    def _buildTomogramSummaryFromStoredItem(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        values = row.get("values") or {}
        objectId = row.get("scipionItemId")
        objectIdText = self._toTextCandidate(objectId)

        tsId = self._firstValueBySuffix(
            values,
            ["tsid", "tiltseriesid", "tilt_series_id"],
        )

        tomoId = self._firstValueBySuffix(
            values,
            ["tomoid", "tomogramid", "tomo_id", "tomogram_id"],
        )

        nameId = self._firstValueBySuffix(
            values,
            ["nameid", "name_id"],
        )

        labelValue = self._firstValueBySuffix(
            values,
            ["objlabel", "label"],
        )

        stableId = (
            self._toTextCandidate(tsId)
            or self._toTextCandidate(tomoId)
            or self._toTextCandidate(labelValue)
            or self._toTextCandidate(nameId)
            or objectIdText
        )

        if not stableId:
            return None

        dims = self._extractDims(values)
        if dims is None:
            return None

        name = (
            self._toTextCandidate(nameId)
            or self._toTextCandidate(labelValue)
            or self._extractFileBasename(values)
            or stableId
        )

        summary: Dict[str, Any] = {
            "id": stableId,
            "tomoId": stableId,
            "label": str(tsId or stableId),
            "name": str(name),
            "dims": dims,
        }

        voxelSize = self._extractVoxelSize(values)
        if voxelSize is not None:
            summary["voxelSize"] = voxelSize

        fileName = self._extractTomogramFile(values)
        if fileName:
            summary["fileName"] = str(fileName)

        if objectIdText:
            summary["objectId"] = objectIdText
            summary["volumeId"] = objectIdText

        if tsId is not None:
            summary["tsId"] = str(tsId)
            summary["tiltSeriesId"] = str(tsId)

        if tomoId is not None:
            summary["sourceTomoId"] = str(tomoId)

        summary["sourceOutputName"] = str(row.get("outputName") or "")
        summary["sourceProtocolId"] = str(row.get("protocolDbId") or "")

        return summary

    def _mergeTomogramSummaries(
            self,
            current: Dict[str, Any],
            candidate: Dict[str, Any],
    ) -> Dict[str, Any]:
        currentScore = self._getTomogramSummaryScore(current)
        candidateScore = self._getTomogramSummaryScore(candidate)

        if candidateScore > currentScore:
            base = dict(candidate)
            for key in ("nCoords", "count"):
                if key in current and key not in base:
                    base[key] = current[key]
            return base

        base = dict(current)
        for key, value in candidate.items():
            if value is not None and key not in base:
                base[key] = value
        return base

    def _getTomogramSummaryScore(self, item: Dict[str, Any]) -> int:
        score = 0

        if item.get("dims"):
            score += 10

        if item.get("voxelSize"):
            score += 5

        if item.get("fileName"):
            score += 3

        classText = " ".join(
            [
                str(item.get("sourceOutputName") or ""),
                str(item.get("sourceProtocolId") or ""),
            ]
        ).lower()

        if "tomogram" in classText:
            score += 2

        return score

    def _hasTomogramViewerContract(self, items: List[Dict[str, Any]]) -> bool:
        for item in items:
            dims = item.get("dims")
            if not isinstance(dims, list) or len(dims) < 3:
                return False

            for value in dims[:3]:
                intValue = self._toOptionalInt(value)
                if intValue is None or intValue <= 0:
                    return False

        return True

    def _getLinkedTomogramsFromProperties(self, storedSet: Dict[str, Any]) -> List[Dict[str, Any]]:
        properties = self._normalizeJsonObject(storedSet.get("properties"))

        linkedTomograms = properties.get("linkedTomograms")
        if isinstance(linkedTomograms, list):
            return [
                item
                for item in linkedTomograms
                if isinstance(item, dict)
            ]

        setProperties = storedSet.get("setProperties") or []
        for item in setProperties:
            if str(item.get("key")) != "linkedTomograms":
                continue

            parsed = self._parseJsonValue(item.get("value"))
            if isinstance(parsed, list):
                return [
                    entry
                    for entry in parsed
                    if isinstance(entry, dict)
                ]

        return []

    def _normalizeLinkedTomogramItem(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        tomoId = item.get("tomoId") or item.get("id") or item.get("tsId") or item.get("label")
        if tomoId is None:
            return None

        dims = self._normalizeDims(item.get("dims"))
        if dims is None:
            return None

        normalized: Dict[str, Any] = {
            "id": str(tomoId),
            "tomoId": str(tomoId),
            "label": str(item.get("label") or tomoId),
            "name": str(item.get("name") or item.get("label") or tomoId),
            "dims": dims,
        }

        voxelSize = self._normalizeVoxelSize(item.get("voxelSize"))
        if voxelSize is not None:
            normalized["voxelSize"] = voxelSize

        for key in ("objectId", "volumeId", "tsId", "tiltSeriesId", "fileName"):
            value = item.get(key)
            if value is not None:
                normalized[key] = str(value)

        return normalized

    def _countCoordinatesByTomogramKey(self, storedSet: Dict[str, Any]) -> Dict[str, int]:
        counts: Dict[str, int] = {}

        for item in storedSet.get("items") or []:
            values = item.get("values") or {}
            keys = self._extractCoordinateTomogramKeys(values)

            for key in keys:
                counts[key] = counts.get(key, 0) + 1

        return counts

    def _extractCoordinateTomogramKeys(self, values: Dict[str, Any]) -> List[str]:
        candidates = []

        for suffixes in (
            ["volid", "volumeid", "volumeobjid", "volume_obj_id"],
            ["tomoid", "tomogramid", "tomo_id", "tomogram_id"],
            ["tsid", "tiltseriesid", "tilt_series_id"],
            ["volname", "volumename", "tomoname", "tomogramname"],
        ):
            value = self._firstValueBySuffix(values, suffixes)
            text = self._toTextCandidate(value)
            if text:
                candidates.append(text)

        for key, value in values.items():
            normalizedKey = self._normalizeKey(key)
            if normalizedKey not in {
                "volid",
                "volumeid",
                "volumeobjid",
                "tomoid",
                "tomogramid",
                "tsid",
                "tiltseriesid",
                "volname",
                "volumename",
                "tomoname",
                "tomogramname",
            }:
                continue

            text = self._toTextCandidate(value)
            if text:
                candidates.append(text)

        return self._uniqueStrings(candidates)

    def _findTomogramCount(self, item: Dict[str, Any], countsByKey: Dict[str, int]) -> Optional[int]:
        candidates = [
            item.get("id"),
            item.get("tomoId"),
            item.get("label"),
            item.get("name"),
            item.get("tsId"),
            item.get("tiltSeriesId"),
            item.get("objectId"),
            item.get("volumeId"),
            item.get("sourceTomoId"),
        ]

        for candidate in candidates:
            if candidate is None:
                continue

            key = str(candidate)
            if key in countsByKey:
                return countsByKey[key]

        return None

    def _getTomogramMatchKeys(self, item: Dict[str, Any]) -> Set[str]:
        keys = set()

        for key in (
            "id",
            "tomoId",
            "label",
            "name",
            "tsId",
            "tiltSeriesId",
            "objectId",
            "volumeId",
            "sourceTomoId",
        ):
            value = item.get(key)
            if value is not None and str(value).strip():
                keys.add(str(value).strip())

        return keys

    def _extractTomogramId(self, values: Dict[str, Any]) -> Optional[Any]:
        value = self._firstValueBySuffix(
            values,
            [
                "tomoid",
                "tomogramid",
                "tomoName",
                "tomogramName",
                "volumeid",
                "volid",
                "volname",
                "tsid",
                "tiltseriesid",
            ],
        )
        return value

    def _extractTomogramLabel(self, values: Dict[str, Any], fallback: str) -> str:
        label = self._firstValueBySuffix(
            values,
            [
                "nameid",
                "tomoname",
                "tomogramname",
                "volumename",
                "volname",
                "objlabel",
                "label",
                "name",
            ],
        )

        if label:
            return str(label)

        fileName = self._extractTomogramFile(values)
        if fileName:
            return str(fileName).split("/")[-1]

        return str(fallback)

    def _extractTomogramFile(self, values: Dict[str, Any]) -> Optional[Any]:
        return self._firstValueBySuffix(
            values,
            [
                "filename",
                "fileName",
                "filepath",
                "filePath",
                "volumefile",
                "tomogramfile",
                "location",
            ],
        )

    def _extractFileBasename(self, values: Dict[str, Any]) -> Optional[str]:
        fileName = self._extractTomogramFile(values)
        if not fileName:
            return None

        try:
            return os.path.basename(str(fileName))
        except Exception:
            return str(fileName)

    def _extractDims(self, values: Dict[str, Any]) -> Optional[List[int]]:
        raw = self._firstValueBySuffix(
            values,
            [
                "dim",
                "dims",
                "dimensions",
                "volumedim",
                "tomogramdim",
                "getdim",
            ],
        )

        return self._normalizeDims(raw)

    def _extractVoxelSize(self, values: Dict[str, Any]) -> Optional[List[float]]:
        raw = self._firstValueBySuffix(
            values,
            [
                "voxelsize",
                "voxel_size",
                "samplingrate",
                "samplingRate",
                "pixelSize",
                "pixel_size",
            ],
        )

        return self._normalizeVoxelSize(raw)

    def _normalizeDims(self, value: Any) -> Optional[List[int]]:
        parsed = self._parseNumberList(value)
        if parsed is None or len(parsed) < 3:
            return None

        dims = []
        for item in parsed[:3]:
            intValue = self._toOptionalInt(item)
            if intValue is None or intValue <= 0:
                return None
            dims.append(intValue)

        return dims

    def _normalizeVoxelSize(self, value: Any) -> Optional[List[float]]:
        parsed = self._parseNumberList(value)
        if parsed is None:
            floatValue = self._toOptionalFloat(value)
            if floatValue is None:
                return None
            return [floatValue, floatValue, floatValue]

        if len(parsed) == 1:
            floatValue = self._toOptionalFloat(parsed[0])
            if floatValue is None:
                return None
            return [floatValue, floatValue, floatValue]

        if len(parsed) >= 3:
            voxelSize = []
            for item in parsed[:3]:
                floatValue = self._toOptionalFloat(item)
                if floatValue is None:
                    return None
                voxelSize.append(floatValue)
            return voxelSize

        return None

    def _parseNumberList(self, value: Any) -> Optional[List[Any]]:
        if value is None or value == "":
            return None

        parsed = self._parseJsonValue(value)
        if isinstance(parsed, (list, tuple)):
            return list(parsed)

        if isinstance(value, (list, tuple)):
            return list(value)

        text = str(value).strip()
        if not text:
            return None

        numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
        if not numbers:
            return None

        return numbers

    def _firstValue(self, values: Dict[str, Any], keys: List[str]) -> Any:
        for key in keys:
            if key in values:
                return values.get(key)
        return None

    def _firstValueBySuffix(self, values: Dict[str, Any], suffixes: List[str]) -> Any:
        normalizedSuffixes = [
            self._normalizeKey(suffix)
            for suffix in suffixes
        ]

        for key, value in values.items():
            if value is None:
                continue

            normalizedKey = self._normalizeKey(key)
            for suffix in normalizedSuffixes:
                if normalizedKey.endswith(suffix):
                    return value

        return None

    def _normalizeKey(self, value: Any) -> str:
        return str(value).replace("_", "").replace(".", "").replace("-", "").lower()

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

    def _toTextCandidate(self, value: Any) -> Optional[str]:
        if value is None:
            return None

        if isinstance(value, dict):
            for key in (
                "id",
                "objId",
                "objectId",
                "volumeId",
                "volId",
                "tomoId",
                "tomogramId",
                "tsId",
                "name",
                "label",
            ):
                if key in value:
                    text = self._toTextCandidate(value.get(key))
                    if text:
                        return text
            return None

        if isinstance(value, (list, tuple)):
            if len(value) == 1:
                return self._toTextCandidate(value[0])
            return None

        text = str(value).strip()
        return text or None

    def _uniqueStrings(self, values: List[str]) -> List[str]:
        seen = set()
        out = []

        for value in values:
            text = str(value).strip()
            if not text or text in seen:
                continue

            seen.add(text)
            out.append(text)

        return out

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

    def _normalizeJsonObject(self, value: Any) -> Dict[str, Any]:
        parsed = self._parseJsonValue(value)
        if isinstance(parsed, dict):
            return parsed
        return {}

    def _resolveTomogramTargetKeys(
            self,
            storedSet: Dict[str, Any],
            tomogramId: Any,
    ) -> Set[str]:
        requested = self._toTextCandidate(tomogramId)
        if not requested:
            return set()

        targetKeys = {requested}

        linkedTomograms = self._getLinkedTomogramsFromProperties(storedSet)
        for item in linkedTomograms:
            normalized = self._normalizeLinkedTomogramItem(item)
            if normalized is None:
                continue

            matchKeys = self._getTomogramMatchKeys(normalized)
            if requested in matchKeys:
                targetKeys.update(matchKeys)

        countsByKey = self._countCoordinatesByTomogramKey(storedSet)
        coordinateKeys = set(countsByKey.keys())

        payload = self._buildTomogramPayloadFromProjectSets(
            coordinateKeys=coordinateKeys,
            countsByKey=countsByKey,
        )

        for item in payload or []:
            matchKeys = self._getTomogramMatchKeys(item)
            if requested in matchKeys:
                targetKeys.update(matchKeys)

        return {
            str(value)
            for value in targetKeys
            if value is not None and str(value).strip()
        }

    def _buildCoordinatePoint(
            self,
            item: Dict[str, Any],
            values: Dict[str, Any],
            tomogramId: Any,
            boxSize: Optional[float],
    ) -> Optional[Dict[str, Any]]:
        x = self._getCoordinateValue(values, "x")
        y = self._getCoordinateValue(values, "y")
        z = self._getCoordinateValue(values, "z")

        if x is None or y is None or z is None:
            return None

        point: Dict[str, Any] = {
            "x": float(x),
            "y": float(y),
            "z": float(z),
            "tomoId": tomogramId,
        }

        objId = item.get("scipionItemId")
        if objId is not None:
            point["id"] = objId

        classId = self._extractPointClassId(values)
        if classId is not None:
            point["classId"] = classId

        score = self._extractPointScore(values)
        if score is not None:
            point["score"] = score

        label = item.get("label") or self._firstValueBySuffix(values, ["objlabel", "label"])
        if label not in (None, ""):
            point["label"] = str(label)

        matrix = self._extractPointMatrix(values)
        if matrix is not None:
            point["matrix"] = matrix
        else:
            point["matrix"] = []

        if boxSize is not None:
            point["radius"] = float(boxSize)

        return point

    def _getCoordinateValue(self, values: Dict[str, Any], axis: str) -> Optional[float]:
        normalizedAxis = self._normalizeKey(axis)

        preferredKeys = {
            "x": "bottomleftx",
            "y": "bottomlefty",
            "z": "bottomleftz",
        }

        preferredKey = preferredKeys.get(normalizedAxis)
        if preferredKey is None:
            return None

        for key, value in values.items():
            if self._normalizeKey(key) == preferredKey:
                return self._toOptionalFloat(value)

        return None

    def _extractPointClassId(self, values: Dict[str, Any]) -> Optional[Any]:
        return self._firstValueBySuffix(
            values,
            [
                "classid",
                "class",
                "groupid",
                "group",
            ],
        )

    def _extractPointScore(self, values: Dict[str, Any]) -> Optional[float]:
        raw = self._firstValueBySuffix(
            values,
            [
                "score",
                "weight",
                "prob",
                "probability",
                "confidence",
            ],
        )

        return self._toOptionalFloat(raw)

    def _extractPointMatrix(self, values: Dict[str, Any]) -> Optional[Any]:
        raw = self._firstValueBySuffix(
            values,
            [
                "matrix",
                "transform",
                "transformmatrix",
                "transformationmatrix",
            ],
        )

        if raw is None:
            return None

        parsed = self._parseJsonValue(raw)
        if isinstance(parsed, list):
            return parsed

        return None

    def _extractBoxSize(self, storedSet: Dict[str, Any]) -> Optional[float]:
        properties = self._normalizeJsonObject(storedSet.get("properties"))

        raw = self._firstValueBySuffix(
            properties,
            [
                "boxsize",
                "box_size",
                "radius",
            ],
        )

        value = self._toOptionalFloat(raw)
        if value is not None:
            return value

        for item in storedSet.get("setProperties") or []:
            key = item.get("key")
            if self._normalizeKey(key) not in {"boxsize", "radius"}:
                continue

            value = self._toOptionalFloat(item.get("value"))
            if value is not None:
                return value

        return None

    def getTomogramFile(self, tomogramId: Any) -> Optional[Dict[str, Any]]:
        self.lastSkipReason = None

        storedSet = self._getStoredSet()
        if storedSet is None:
            self.lastSkipReason = "stored_set_not_found"
            return None

        requested = self._toTextCandidate(tomogramId)
        if not requested:
            self.lastSkipReason = "empty_tomogram_id"
            return None

        linkedTomograms = self._getLinkedTomogramsFromProperties(storedSet)
        for item in linkedTomograms:
            normalized = self._normalizeLinkedTomogramItem(item)
            if normalized is None:
                continue

            matchKeys = self._getTomogramMatchKeys(normalized)
            if requested not in matchKeys:
                continue

            fileName = normalized.get("fileName")
            if not fileName:
                self.lastSkipReason = "tomogram_file_not_found_in_linked_metadata tomogramId=%s" % requested
                return None

            return {
                "id": normalized.get("id"),
                "tomoId": normalized.get("tomoId"),
                "label": normalized.get("label"),
                "name": normalized.get("name"),
                "fileName": str(fileName),
                "dims": normalized.get("dims"),
                "voxelSize": normalized.get("voxelSize"),
            }

        payload = self._buildTomogramPayloadFromProjectSets(
            coordinateKeys={requested},
            countsByKey={},
        )

        for item in payload or []:
            matchKeys = self._getTomogramMatchKeys(item)
            if requested not in matchKeys:
                continue

            fileName = item.get("fileName")
            if not fileName:
                continue

            return {
                "id": item.get("id"),
                "tomoId": item.get("tomoId"),
                "label": item.get("label"),
                "name": item.get("name"),
                "fileName": str(fileName),
                "dims": item.get("dims"),
                "voxelSize": item.get("voxelSize"),
            }

        self.lastSkipReason = "tomogram_file_not_resolved tomogramId=%s" % requested
        return None
