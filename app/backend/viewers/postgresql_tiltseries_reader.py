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
import ast
import json
import math
import re

from typing import Any, Dict, List, Optional

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class PostgresqlTiltSeriesReader:
    def __init__(self, db, projectId: int, protocolId: int, outputName: str):
        self.db = db
        self.projectId = projectId
        self.protocolId = protocolId
        self.outputName = outputName
        self.setMapper = ScipionSetPostgresqlMapper(db)
        self._storedSet = None
        self._logicalTables = None
        self.lastSkipReason = None

    def hasOutput(self) -> bool:
        storedSet = self._getStoredSet()
        return storedSet is not None and self._isTiltSeriesStoredSet(storedSet)

    def listTiltSeries(self) -> List[Dict[str, Any]]:
        storedSet = self._getStoredSet()
        if storedSet is None or not self._isTiltSeriesStoredSet(storedSet):
            return []

        result = []
        for index, item in enumerate(storedSet.get("items") or []):
            result.append(self._buildTiltSeriesSummary(item, index))

        return result

    def getTiltSeriesFrames(self, tiltSeriesId: Any) -> Optional[Dict[str, Any]]:
        self.lastSkipReason = None

        storedSet = self._getStoredSet()
        if storedSet is None or not self._isTiltSeriesStoredSet(storedSet):
            self.lastSkipReason = "tiltseries_stored_set_not_found"
            return None

        seriesItem = self._findTiltSeriesItem(tiltSeriesId)
        if seriesItem is None:
            self.lastSkipReason = (
                    "tiltseries_item_not_found tiltSeriesId=%s"
                    % str(tiltSeriesId)
            )
            return None

        seriesSummary = self._buildTiltSeriesSummary(seriesItem, 0)
        childTable = self._findChildTableForParentItem(seriesItem.get("scipionItemId"))

        frames: List[Dict[str, Any]] = []
        if childTable is not None:
            childItems = self.setMapper.getStoredSetTableItems(int(childTable["id"]))
            for index, item in enumerate(childItems):
                frames.append(self._buildTiltImageFrame(item, index))

        payload: Dict[str, Any] = {
            "tiltSeriesId": seriesSummary.get("tiltSeriesId") or str(tiltSeriesId),
            "label": seriesSummary.get("label") or str(tiltSeriesId),
            "frames": frames,
        }

        if "tiltAxisAngle" in seriesSummary:
            payload["tiltAxisAngle"] = seriesSummary["tiltAxisAngle"]

        return payload

    def getTiltImageFrame(self, tiltSeriesId: Any, index: Any) -> Optional[Dict[str, Any]]:
        self.lastSkipReason = None

        storedSet = self._getStoredSet()
        if storedSet is None or not self._isTiltSeriesStoredSet(storedSet):
            self.lastSkipReason = "tiltseries_stored_set_not_found"
            return None

        seriesItem = self._findTiltSeriesItem(tiltSeriesId)
        if seriesItem is None:
            self.lastSkipReason = (
                    "tiltseries_item_not_found tiltSeriesId=%s"
                    % str(tiltSeriesId)
            )
            return None

        childTable = self._findChildTableForParentItem(seriesItem.get("scipionItemId"))
        if childTable is None:
            self.lastSkipReason = (
                    "tiltseries_child_table_not_found tiltSeriesId=%s"
                    % str(tiltSeriesId)
            )
            return None

        childItems = self.setMapper.getStoredSetTableItems(int(childTable["id"]))
        if not childItems:
            self.lastSkipReason = (
                    "tiltseries_child_items_empty tiltSeriesId=%s"
                    % str(tiltSeriesId)
            )
            return None

        targetIndex = self._toOptionalInt(index)
        if targetIndex is None:
            self.lastSkipReason = (
                    "tilt_image_frame_invalid_index tiltSeriesId=%s index=%s"
                    % (str(tiltSeriesId), str(index))
            )
            return None

        for position, item in enumerate(childItems):
            frame = self._buildTiltImageFrame(item, position)
            frameIndex = self._toOptionalInt(frame.get("index"))

            if frameIndex == targetIndex:
                return frame

        if 0 <= targetIndex < len(childItems):
            return self._buildTiltImageFrame(childItems[targetIndex], targetIndex)

        self.lastSkipReason = (
                "tilt_image_frame_not_found tiltSeriesId=%s index=%s"
                % (str(tiltSeriesId), str(index))
        )
        return None

    def _getStoredSet(self) -> Optional[Dict[str, Any]]:
        if self._storedSet is None:
            self._storedSet = self.setMapper.getStoredSet(
                projectId=self.projectId,
                protocolDbId=self.protocolId,
                outputName=self.outputName,
            )
        return self._storedSet

    def _isTiltSeriesStoredSet(self, storedSet: Dict[str, Any]) -> bool:
        classText = self._getStoredSetClassText(storedSet)
        return "tiltseries" in classText and "ctftomo" not in classText

    def _getStoredSetClassText(self, storedSet: Dict[str, Any]) -> str:
        return ("%s %s" % (
            storedSet.get("setClassName") or "",
            storedSet.get("itemClassName") or "",
        )).replace(" ", "").lower()

    def _getLogicalTables(self) -> List[Dict[str, Any]]:
        if self._logicalTables is None:
            storedSet = self._getStoredSet()
            if storedSet is None:
                self._logicalTables = []
            else:
                self._logicalTables = self.setMapper.listStoredSetTables(
                    int(storedSet["id"])
                )
        return self._logicalTables

    def _extractDims(self, values: Dict[str, Any]) -> Optional[List[int]]:
        raw = self._firstValueBySuffix(
            values,
            [
                "dim",
                "dims",
                "dimensions",
                "imageDim",
                "imageDims",
                "xDim",
                "xyDim",
                "_dim",
            ],
        )

        numbers = self._parseNumericSequence(raw)
        if numbers is None or len(numbers) < 2:
            return None

        dims: List[int] = []
        for value in numbers[:3]:
            intValue = self._toOptionalInt(value)
            if intValue is None or intValue <= 0:
                return None
            dims.append(intValue)

        return dims

    def _parseNumericSequence(self, value: Any) -> Optional[List[float]]:
        if value is None or value == "":
            return None

        if isinstance(value, (list, tuple)):
            rawValues = list(value)
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return None

            parsed = None
            if text.startswith("[") or text.startswith("("):
                try:
                    parsed = json.loads(text)
                except Exception:
                    try:
                        parsed = ast.literal_eval(text)
                    except Exception:
                        parsed = None

            if isinstance(parsed, (list, tuple)):
                rawValues = list(parsed)
            else:
                cleaned = text.strip("[]()")
                tokens = [
                    token.strip()
                    for token in re.split(r"[\s,;xX]+", cleaned)
                    if token.strip()
                ]
                rawValues = tokens
        else:
            rawValues = [value]

        values: List[float] = []
        for rawValue in rawValues:
            number = self._toOptionalFloat(rawValue)
            if number is None:
                return None
            values.append(number)

        return values or None

    def _buildTiltSeriesSummary(self, item: Dict[str, Any], index: int) -> Dict[str, Any]:
        values = item.get("values") or {}
        itemId = item.get("scipionItemId")

        tiltSeriesId = self._firstValue(
            values,
            ["_tsId", "tsId", "tiltSeriesId", "id"],
        )
        if tiltSeriesId is None:
            tiltSeriesId = item.get("label") or itemId or index

        summary: Dict[str, Any] = {
            "tiltSeriesId": str(tiltSeriesId),
            "label": "TiltSeries %s" % str(tiltSeriesId),
        }

        childTable = self._findChildTableForParentItem(itemId)
        if childTable is not None:
            childItems = self.setMapper.getStoredSetTableItems(int(childTable["id"]))
            summary["nViews"] = len(childItems)

        dims = self._extractDims(values)
        if dims is not None:
            summary["dims"] = dims

        pixelSize = self._firstValueBySuffix(
            values,
            ["samplingrate", "pixelSize", "pixel_size"],
        )
        if pixelSize is not None:
            summary["pixelSize"] = self._toOptionalFloat(pixelSize)

        tiltAxisAngle = self._firstValueBySuffix(
            values,
            ["tiltaxisangle"],
        )
        if tiltAxisAngle is not None:
            summary["tiltAxisAngle"] = self._toOptionalFloat(tiltAxisAngle)

        return summary

    def _findTiltSeriesItem(self, tiltSeriesId: Any) -> Optional[Dict[str, Any]]:
        storedSet = self._getStoredSet()
        if storedSet is None:
            return None

        targetKey = str(tiltSeriesId)

        for index, item in enumerate(storedSet.get("items") or []):
            itemTiltSeriesId = self._getTiltSeriesIdFromItem(item, index)
            if str(itemTiltSeriesId) == targetKey:
                return item

        return None

    def _getTiltSeriesIdFromItem(self, item: Dict[str, Any], index: int) -> Any:
        values = item.get("values") or {}
        tiltSeriesId = self._firstValue(
            values,
            ["_tsId", "tsId", "tiltSeriesId", "id"],
        )

        if tiltSeriesId is not None:
            return tiltSeriesId

        return item.get("label") or item.get("scipionItemId") or index

    def _buildTiltImageFrame(self, item: Dict[str, Any], position: int) -> Dict[str, Any]:
        values = item.get("values") or {}

        frame: Dict[str, Any] = {
            "viewId": item.get("scipionItemId"),
            "index": position,
        }

        imageIndex = self._firstValueBySuffix(values, ["index"])
        imageIndexInt = self._toOptionalInt(imageIndex)
        if imageIndexInt is not None:
            frame["index"] = imageIndexInt

        order = self._firstValueBySuffix(
            values,
            ["acquisitionorder", "acqorder", "order"],
        )
        orderInt = self._toOptionalInt(order)
        if orderInt is not None:
            frame["order"] = orderInt

        tiltAngle = self._firstValueBySuffix(values, ["tiltangle"])
        tiltAngleFloat = self._toOptionalFloat(tiltAngle)
        if tiltAngleFloat is not None:
            frame["tiltAngle"] = tiltAngleFloat

        excluded = self._getFrameExcluded(item, values)
        frame["excluded"] = excluded

        dose = self._firstValueBySuffix(values, ["accumdose", "dose"])
        doseFloat = self._toOptionalFloat(dose)
        if doseFloat is not None:
            frame["dose"] = doseFloat

        imagePath = self._firstValueBySuffix(
            values,
            ["filename", "filepath", "path"],
        )
        if imagePath:
            frame["path"] = "%s@%s" % (str(frame["index"]), str(imagePath))

        transformValues = self._getFrameTransform(values)
        frame.update(transformValues)

        return frame

    def _findChildTableForParentItem(self, parentItemId: Any) -> Optional[Dict[str, Any]]:
        if parentItemId is None:
            return None

        for table in self._getLogicalTables():
            if table.get("tableKind") != "child":
                continue
            if str(table.get("parentItemId")) == str(parentItemId):
                return table

        return None

    def _firstValue(self, values: Dict[str, Any], keys: List[str]) -> Any:
        for key in keys:
            if key in values:
                return values.get(key)
        return None

    def _firstValueBySuffix(self, values: Dict[str, Any], suffixes: List[str]) -> Any:
        normalizedSuffixes = [
            str(suffix).replace("_", "").replace(".", "").lower()
            for suffix in suffixes
        ]

        for key, value in values.items():
            normalizedKey = str(key).replace("_", "").replace(".", "").lower()
            for suffix in normalizedSuffixes:
                if normalizedKey.endswith(suffix):
                    return value

        return None

    def _toOptionalFloat(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _getFrameExcluded(self, item: Dict[str, Any], values: Dict[str, Any]) -> bool:
        excludedValue = self._firstValueBySuffix(
            values,
            ["excluded", "skip"],
        )
        if excludedValue is not None:
            return bool(self._toOptionalBool(excludedValue))

        enabledValue = item.get("enabled")
        if enabledValue is None:
            enabledValue = self._firstValueBySuffix(values, ["enabled", "isenabled"])

        enabled = self._toOptionalBool(enabledValue)
        if enabled is None:
            return False

        return not enabled

    def _getFrameTransform(self, values: Dict[str, Any]) -> Dict[str, Any]:
        matrixValue = self._firstValueBySuffix(values, ["matrix"])
        matrix = self._parseMatrix(matrixValue)
        if not matrix:
            return {}

        flat = self._flattenMatrix(matrix)
        result: Dict[str, Any] = {}

        if len(flat) >= 6:
            result["shiftX"] = flat[2]
            result["shiftY"] = flat[5]

        try:
            if len(flat) >= 4:
                m00 = float(flat[0])
                m10 = float(flat[3]) if len(flat) >= 6 else float(flat[2])
                result["rot"] = math.degrees(-math.atan2(m10, m00))
        except Exception:
            pass

        return result

    def _parseMatrix(self, value: Any) -> Optional[Any]:
        if value is None or value == "":
            return None

        if isinstance(value, list):
            return value

        if isinstance(value, tuple):
            return list(value)

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None

            try:
                parsed = json.loads(text)
                if isinstance(parsed, (list, tuple)):
                    return list(parsed)
            except Exception:
                pass

            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, (list, tuple)):
                    return list(parsed)
            except Exception:
                pass

            numbers = self._parseNumericSequence(text)
            if numbers is None:
                return None

            # IMOD/Scipion-like affine 2D matrix usually appears as:
            #   a11,a12,shiftX,a21,a22,shiftY
            if len(numbers) >= 6:
                return [
                    [numbers[0], numbers[1], numbers[2]],
                    [numbers[3], numbers[4], numbers[5]],
                ]

            # Sometimes only the linear part is stored.
            if len(numbers) >= 4:
                return [
                    [numbers[0], numbers[1]],
                    [numbers[2], numbers[3]],
                ]

            return None

        return None

    def _flattenMatrix(self, matrix: Any) -> List[float]:
        values: List[float] = []

        if not isinstance(matrix, list):
            return values

        for row in matrix:
            if isinstance(row, list):
                for value in row:
                    parsedValue = self._toOptionalFloat(value)
                    if parsedValue is not None:
                        values.append(parsedValue)
            else:
                parsedValue = self._toOptionalFloat(row)
                if parsedValue is not None:
                    values.append(parsedValue)

        return values

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

    def _toOptionalBool(self, value: Any) -> Optional[bool]:
        if value is None or value == "":
            return None

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return bool(value)

        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "y", "on", "enabled"):
            return True
        if text in ("0", "false", "no", "n", "off", "disabled"):
            return False

        return None