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

    def hasOutput(self) -> bool:
        return self._getStoredSet() is not None

    def listTiltSeries(self) -> List[Dict[str, Any]]:
        storedSet = self._getStoredSet()
        if storedSet is None:
            return []

        result = []
        for index, item in enumerate(storedSet.get("items") or []):
            result.append(self._buildTiltSeriesSummary(item, index))

        return result

    def getTiltSeriesFrames(self, tiltSeriesId: Any) -> Optional[Dict[str, Any]]:
        seriesItem = self._findTiltSeriesItem(tiltSeriesId)
        if seriesItem is None:
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

    def _getStoredSet(self) -> Optional[Dict[str, Any]]:
        if self._storedSet is None:
            self._storedSet = self.setMapper.getStoredSet(
                projectId=self.projectId,
                protocolDbId=self.protocolId,
                outputName=self.outputName,
            )
        return self._storedSet

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

        dims = self._firstValueBySuffix(
            values,
            ["dim", "dims", "dimensions"],
        )
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
            if isinstance(matrix, list) and len(matrix) >= 2:
                m00 = float(matrix[0][0])
                m10 = float(matrix[1][0])
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
                return json.loads(text)
            except Exception:
                pass

            try:
                return ast.literal_eval(text)
            except Exception:
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