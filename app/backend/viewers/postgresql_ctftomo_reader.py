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
from typing import Any, Dict, List, Optional

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class PostgresqlCtftomoReader:
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

    def listCtftomoSeries(self) -> List[Dict[str, Any]]:
        storedSet = self._getStoredSet()
        if storedSet is None:
            return []

        result = []
        for index, item in enumerate(storedSet.get("items") or []):
            summary = self._buildCtftomoSeriesSummary(item, index)
            result.append(summary)

        return result

    def getCtftomoSeriesViews(self, tiltSeriesId: Any) -> Optional[Dict[str, Any]]:
        seriesItem = self._findCtftomoSeriesItem(tiltSeriesId)
        if seriesItem is None:
            return None

        summary = self._buildCtftomoSeriesSummary(seriesItem, 0)
        childTable = self._findChildTableForParentItem(seriesItem.get("scipionItemId"))

        frames: List[Dict[str, Any]] = []
        if childTable is not None:
            childItems = self.setMapper.getStoredSetTableItems(int(childTable["id"]))
            for index, item in enumerate(childItems):
                frames.append(self._buildCtftomoMeasurementFrame(item, index))

        summary["frames"] = frames
        summary["tiltSeriesId"] = summary.get("tiltSeriesId") or str(tiltSeriesId)
        summary["ctfSeriesId"] = (
                summary.get("ctfSeriesId")
                or summary.get("tiltSeriesId")
                or str(tiltSeriesId)
        )
        summary["nViews"] = len(frames)

        return summary

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

    def _buildCtftomoSeriesSummary(self, item: Dict[str, Any], index: int) -> Dict[str, Any]:
        values = item.get("values") or {}
        itemId = item.get("scipionItemId")

        tiltSeriesId = self._firstValue(
            values,
            ["_tsId", "tsId", "tiltSeriesId", "id"],
        )
        if tiltSeriesId is None:
            tiltSeriesId = item.get("label") or itemId or index

        label = self._firstValueBySuffix(
            values,
            ["objlabel", "label", "name"],
        )
        if label is None:
            label = str(item.get("label") or "CTFTomoSeries %s" % str(tiltSeriesId))

        summary: Dict[str, Any] = {
            "ctfSeriesId": str(tiltSeriesId),
            "tiltSeriesId": str(tiltSeriesId),
            "label": str(label),
            "index": index,
        }

        childTable = self._findChildTableForParentItem(itemId)
        if childTable is not None:
            childItems = self.setMapper.getStoredSetTableItems(int(childTable["id"]))
            summary["nViews"] = len(childItems)

        dims = self._firstValueBySuffix(values, ["dim", "dims", "dimensions", "getDim"])
        if dims is not None:
            summary["dims"] = dims

        pixelSize = self._firstValueBySuffix(
            values,
            ["samplingrate", "pixelSize", "pixel_size"],
        )
        if pixelSize is not None:
            summary["pixelSize"] = self._toOptionalFloat(pixelSize)

        tiltAxisAngle = self._firstValueBySuffix(values, ["tiltaxisangle"])
        if tiltAxisAngle is not None:
            summary["tiltAxisAngle"] = self._toOptionalFloat(tiltAxisAngle)

        return summary

    def _findCtftomoSeriesItem(self, tiltSeriesId: Any) -> Optional[Dict[str, Any]]:
        storedSet = self._getStoredSet()
        if storedSet is None:
            return None

        targetKey = str(tiltSeriesId).strip()
        if not targetKey:
            return None

        for index, item in enumerate(storedSet.get("items") or []):
            if targetKey in self._getCtftomoSeriesItemMatchKeys(item, index):
                return item

        return None

    def _getCtftomoSeriesItemMatchKeys(self, item: Dict[str, Any], index: int) -> set:
        values = item.get("values") or {}

        candidates = [
            self._getTiltSeriesIdFromItem(item, index),
            self._firstValue(values, ["_tsId", "tsId", "tiltSeriesId", "ctfSeriesId", "id"]),
            self._firstValueBySuffix(values, ["tsid", "tiltseriesid", "ctfseriesid"]),
            self._firstValueBySuffix(values, ["objlabel", "label", "name"]),
            item.get("label"),
            item.get("scipionItemId"),
            item.get("id"),
            index,
        ]

        keys = set()
        for candidate in candidates:
            if candidate is None:
                continue

            text = str(candidate).strip()
            if text:
                keys.add(text)

        return keys

    def _getTiltSeriesIdFromItem(self, item: Dict[str, Any], index: int) -> Any:
        values = item.get("values") or {}
        tiltSeriesId = self._firstValue(
            values,
            ["_tsId", "tsId", "tiltSeriesId", "id"],
        )

        if tiltSeriesId is not None:
            return tiltSeriesId

        return item.get("label") or item.get("scipionItemId") or index

    def _buildCtftomoMeasurementFrame(self, item: Dict[str, Any], position: int) -> Dict[str, Any]:
        values = item.get("values") or {}
        viewId = item.get("scipionItemId") or position

        frame: Dict[str, Any] = {
            "viewId": viewId,
            "index": position,
            "viewIndex": position,
        }

        tiltAngle = self._firstValueBySuffix(values, ["tiltangle"])
        tiltAngleFloat = self._toOptionalFloat(tiltAngle)
        if tiltAngleFloat is not None:
            frame["tiltAngle"] = tiltAngleFloat

        dose = self._firstValueBySuffix(values, ["accumdose", "dose"])
        doseFloat = self._toOptionalFloat(dose)
        if doseFloat is not None:
            frame["dose"] = doseFloat

        defocusU = self._firstValueBySuffix(values, ["defocusu"])
        defocusUFloat = self._toOptionalFloat(defocusU)
        if defocusUFloat is not None:
            frame["defocusU"] = defocusUFloat

        defocusV = self._firstValueBySuffix(values, ["defocusv"])
        defocusVFloat = self._toOptionalFloat(defocusV)
        if defocusVFloat is not None:
            frame["defocusV"] = defocusVFloat

        if defocusUFloat is not None and defocusVFloat is not None:
            frame["astigmatism"] = defocusUFloat - defocusVFloat

        defocusAngle = self._firstValueBySuffix(values, ["defocusangle"])
        defocusAngleFloat = self._toOptionalFloat(defocusAngle)
        if defocusAngleFloat is not None:
            frame["defocusAngle"] = defocusAngleFloat

        resolution = self._firstValueBySuffix(values, ["resolution"])
        resolutionFloat = self._toOptionalFloat(resolution)
        if resolutionFloat is not None:
            frame["resolution"] = resolutionFloat

        phaseShift = self._firstValueBySuffix(values, ["phaseshift"])
        phaseShiftFloat = self._toOptionalFloat(phaseShift)
        if phaseShiftFloat is not None:
            frame["phaseShift"] = phaseShiftFloat

        acquisitionOrder = self._firstValueBySuffix(
            values,
            ["acquisitionorder", "acqorder", "order"],
        )
        acquisitionOrderInt = self._toOptionalInt(acquisitionOrder)
        if acquisitionOrderInt is not None:
            frame["order"] = acquisitionOrderInt

        psdFile = self._firstValueBySuffix(
            values,
            ["psdfile", "psdfilename", "psdpath"],
        )
        if psdFile:
            frame["psdFile"] = str(psdFile)

        enabled = self._firstValueBySuffix(values, ["enabled", "isenabled"])
        enabledBool = self._toOptionalBool(enabled)
        frame["excluded"] = False if enabledBool is None else not enabledBool

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

    def _hasCtftomoViewerContract(self, payload: Dict[str, Any]) -> bool:
        frames = payload.get("frames") or []
        if not frames:
            return False

        if not payload.get("dims"):
            return False

        requiredNumericKeys = (
            "tiltAngle",
            "defocusU",
            "defocusV",
            "defocusAngle",
            "resolution",
            "order",
        )

        for frame in frames:
            for key in requiredNumericKeys:
                if self._toOptionalFloat(frame.get(key)) is None:
                    return False

            if not frame.get("psdFile"):
                return False

        return True