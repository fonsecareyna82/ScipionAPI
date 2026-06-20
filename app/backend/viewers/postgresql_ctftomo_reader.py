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
            "tiltSeriesId": str(tiltSeriesId),
            "label": str(label),
            "index": index,
        }

        childTable = self._findChildTableForParentItem(itemId)
        if childTable is not None:
            childItems = self.setMapper.getStoredSetTableItems(int(childTable["id"]))
            summary["nViews"] = len(childItems)

        dims = self._firstValueBySuffix(values, ["dim", "dims", "dimensions"])
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