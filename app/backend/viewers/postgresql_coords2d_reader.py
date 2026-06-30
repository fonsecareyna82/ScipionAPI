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
from typing import Any, Dict, List, Optional, Set

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class PostgresqlCoords2dReader:
    def __init__(self, db, projectId: int, protocolId: int, outputName: str):
        self.db = db
        self.projectId = projectId
        self.protocolId = protocolId
        self.outputName = outputName
        self.setMapper = ScipionSetPostgresqlMapper(db)
        self._storedSet = None
        self.lastSkipReason = None

    def hasOutput(self) -> bool:
        storedSet = self._getStoredSet()
        return storedSet is not None and self._isCoords2dStoredSet(storedSet)

    def listMicrographs(self) -> Optional[Dict[str, Any]]:
        self.lastSkipReason = None

        storedSet = self._getStoredSet()
        if storedSet is None:
            self.lastSkipReason = "stored_set_not_found"
            return None

        if not self._isCoords2dStoredSet(storedSet):
            self.lastSkipReason = "stored_set_is_not_coordinates2d"
            return None

        countsByMicId: Dict[str, int] = {}
        micrographsById: Dict[str, Dict[str, Any]] = {}

        for item in storedSet.get("items") or []:
            values = item.get("values") or {}
            micId = self._extractMicId(item, values)

            if not micId:
                continue

            countsByMicId[micId] = countsByMicId.get(micId, 0) + 1

            if micId not in micrographsById:
                micrographsById[micId] = self._buildMicrographSummary(
                    micId=micId,
                    item=item,
                    values=values,
                )

        if not micrographsById:
            self.lastSkipReason = "micrographs_not_resolved_from_coordinates"
            return None

        micrographs: List[Dict[str, Any]] = []
        for index, micId in enumerate(sorted(micrographsById.keys(), key=self._micrographSortKey), start=1):
            summary = dict(micrographsById[micId])
            summary["index"] = index
            summary["particles"] = int(countsByMicId.get(micId, 0))
            micrographs.append(summary)

        boxSize = self._extractBoxSize(storedSet)
        totalPicks = sum(int(item.get("particles") or 0) for item in micrographs)

        return {
            "micrographs": micrographs,
            "totalMicrographs": len(micrographs),
            "totalPicks": totalPicks,
            "boxSize": boxSize,
        }

    def listCoordinatesForMicrograph(self, micId: Any) -> Optional[Dict[str, Any]]:
        self.lastSkipReason = None

        storedSet = self._getStoredSet()
        if storedSet is None:
            self.lastSkipReason = "stored_set_not_found"
            return None

        if not self._isCoords2dStoredSet(storedSet):
            self.lastSkipReason = "stored_set_is_not_coordinates2d"
            return None

        targetMicId = str(micId)
        coordinates: List[Dict[str, Any]] = []

        for index, item in enumerate(storedSet.get("items") or []):
            values = item.get("values") or {}
            itemMicId = self._extractMicId(item, values)

            if str(itemMicId) != targetMicId:
                continue

            point = self._buildCoordinatePoint(
                item=item,
                values=values,
                micId=targetMicId,
                fallbackIndex=index,
            )

            if point is not None:
                coordinates.append(point)

        if not coordinates:
            self.lastSkipReason = "coordinates_not_found_for_micrograph micId=%s" % targetMicId
            return None

        return {"coordinates": coordinates}

    def _getStoredSet(self) -> Optional[Dict[str, Any]]:
        if self._storedSet is None:
            self._storedSet = self.setMapper.getStoredSet(
                projectId=self.projectId,
                protocolDbId=self.protocolId,
                outputName=self.outputName,
            )
        return self._storedSet

    def _isCoords2dStoredSet(self, storedSet: Dict[str, Any]) -> bool:
        classText = ("%s %s" % (
            storedSet.get("setClassName") or "",
            storedSet.get("itemClassName") or "",
        )).replace(" ", "").lower()

        if "coordinate" not in classText:
            return False

        if "coordinates3d" in classText or "coordinate3d" in classText:
            return False

        if "tomogram" in classText or "tomo" in classText:
            return False

        return True

    def _buildMicrographSummary(
            self,
            micId: str,
            item: Dict[str, Any],
            values: Dict[str, Any],
    ) -> Dict[str, Any]:
        label = (
            self._firstValueBySuffix(values, ["micname", "micrographname", "filename", "filepath"])
            or item.get("label")
            or "Micrograph %s" % micId
        )

        fileName = self._firstValueBySuffix(
            values,
            ["filename", "filepath", "micfilename", "micrographfilename", "path"],
        )

        width = self._toOptionalInt(
            self._firstValueBySuffix(values, ["width", "xdim", "dimx"])
        )
        height = self._toOptionalInt(
            self._firstValueBySuffix(values, ["height", "ydim", "dimy"])
        )

        return {
            "id": str(micId),
            "fileName": str(fileName) if fileName else "",
            "label": str(label),
            "particles": 0,
            "updated": False,
            "width": width,
            "height": height,
            "locationIndex": self._toOptionalInt(
                self._firstValueBySuffix(values, ["locationindex", "imageindex", "index"])
            ),
            "thumbnailUrl": None,
        }

    def _buildCoordinatePoint(
            self,
            item: Dict[str, Any],
            values: Dict[str, Any],
            micId: str,
            fallbackIndex: int,
    ) -> Optional[Dict[str, Any]]:
        x = self._extractCoordinateValue(values, ["_x", "x", "coordx", "coordinatex", "positionx"])
        y = self._extractCoordinateValue(values, ["_y", "y", "coordy", "coordinatey", "positiony"])

        if x is None or y is None:
            return None

        objId = item.get("scipionItemId")
        if objId is None:
            objId = item.get("id")
        if objId is None:
            objId = "%s:%s" % (micId, fallbackIndex)

        return {
            "id": objId,
            "micId": str(micId),
            "x": x,
            "y": y,
            "score": self._toOptionalFloat(
                self._firstValueBySuffix(values, ["score", "weight"])
            ),
            "classLabel": self._optionalString(
                self._firstValueBySuffix(values, ["classid", "classlabel", "objlabel"])
            ),
        }

    def _extractMicId(self, item: Dict[str, Any], values: Dict[str, Any]) -> Optional[str]:
        value = self._firstValue(
            values,
            [
                "_micId",
                "micId",
                "micrographId",
                "micrograph.id",
                "micrograph._objId",
                "_mic._objId",
                "_micrograph._objId",
            ],
        )

        if value is None:
            value = self._firstValueBySuffix(
                values,
                ["micid", "micrographid", "micobjid", "micrographobjid"],
            )

        if value is None:
            value = self._findNestedValueBySuffix(
                values,
                ["micid", "micrographid", "objid"],
            )

        if value is None:
            return None

        return str(value)

    def _extractBoxSize(self, storedSet: Dict[str, Any]) -> Optional[int]:
        properties = storedSet.get("properties") or {}
        setProperties = storedSet.get("setProperties") or []

        value = None
        if isinstance(properties, dict):
            value = self._firstValueBySuffix(properties, ["boxsize", "box"])

        if value is None:
            for row in setProperties:
                key = str((row or {}).get("key") or "").replace("_", "").lower()
                if key.endswith("boxsize") or key == "box":
                    value = (row or {}).get("value")
                    break

        return self._toOptionalInt(value)

    def _extractCoordinateValue(self, values: Dict[str, Any], names: List[str]) -> Optional[float]:
        value = self._firstValue(values, names)
        if value is None:
            value = self._firstValueBySuffix(values, names)
        return self._toOptionalFloat(value)

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

        for key, value in (values or {}).items():
            normalizedKey = str(key).replace("_", "").replace(".", "").lower()
            for suffix in normalizedSuffixes:
                if normalizedKey.endswith(suffix):
                    return value

        return None

    def _findNestedValueBySuffix(self, value: Any, suffixes: List[str]) -> Any:
        normalizedSuffixes = [
            str(suffix).replace("_", "").replace(".", "").lower()
            for suffix in suffixes
        ]

        def walk(node: Any, path: str = "") -> Any:
            if isinstance(node, dict):
                for key, child in node.items():
                    nextPath = "%s.%s" % (path, key) if path else str(key)
                    normalizedPath = nextPath.replace("_", "").replace(".", "").lower()
                    for suffix in normalizedSuffixes:
                        if normalizedPath.endswith(suffix):
                            return child

                    found = walk(child, nextPath)
                    if found is not None:
                        return found

            if isinstance(node, list):
                for index, child in enumerate(node):
                    found = walk(child, "%s.%s" % (path, index))
                    if found is not None:
                        return found

            return None

        return walk(value)

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

    def _optionalString(self, value: Any) -> Optional[str]:
        if value is None:
            return None

        text = str(value).strip()
        return text or None

    def _micrographSortKey(self, micId: str):
        try:
            return 0, int(micId)
        except Exception:
            return 1, str(micId).lower()