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

from typing import Any, Dict, List, Optional

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


# The values a row of the list reads (see _buildCtfRow), by the end of their key
LISTED_VALUE_SUFFIXES = (
    "defocusu", "df1", "defocusv", "df2", "defocusratio", "micname", "micrographname", "defocusangle",
    "astigangle", "phaseshift", "resolution", "estres", "fitquality", "ccvalue", "cc", "psdfile", "psdpath",
)
LISTED_VALUE_PATTERN = "(%s)$" % "|".join(LISTED_VALUE_SUFFIXES)

# setId -> (its version: updatedAt and items, the listed CTFs): a viewer opened again on an unchanged Set
# does not read its thousands of items again
_listCache: Dict[int, tuple] = {}
_LIST_CACHE_SIZE = 8


class PostgresqlCtfReader:
    def __init__(self, db, projectId: int, protocolId: int, outputName: str):
        self.db = db
        self.projectId = projectId
        self.protocolId = protocolId
        self.outputName = outputName
        self.setMapper = ScipionSetPostgresqlMapper(db)
        self._storedSet = None
        self._storedSetMeta = None
        self.lastSkipReason = None

    def hasOutput(self) -> bool:
        storedSet = self._getStoredSet()
        return storedSet is not None and self._isCtfStoredSet(storedSet)

    def listCtfs(self) -> Optional[Dict[str, Any]]:
        self.lastSkipReason = None

        storedSet = self._getStoredSetMeta()
        if storedSet is None:
            self.lastSkipReason = "stored_set_not_found"
            return None

        if not self._isCtfStoredSet(storedSet):
            self.lastSkipReason = "stored_set_is_not_setofctf"
            return None

        properties = self._normalizeJsonObject(storedSet.get("properties"))
        version = (str(storedSet.get("updatedAt")), properties.get("itemsCount"))
        cached = _listCache.get(int(storedSet["id"]))
        if cached is not None and cached[0] == version:
            return cached[1]

        # Only the values a row shows, not every value of every item
        items = self.setMapper.listStoredSetItemsWithKeys(storedSet["id"], LISTED_VALUE_PATTERN)
        ctfs = [self._buildCtfRow(item, position) for position, item in enumerate(items)]
        payload = {"ctfs": ctfs, "total": len(ctfs)}
        if len(_listCache) >= _LIST_CACHE_SIZE:
            _listCache.pop(next(iter(_listCache)))
        _listCache[int(storedSet["id"])] = (version, payload)
        return payload

    def getCtf(self, ctfId: Any) -> Optional[Dict[str, Any]]:
        self.lastSkipReason = None

        # One item, not the whole Set: a PSD is asked for at every row clicked
        storedSet = self._getStoredSetMeta()
        if storedSet is None:
            self.lastSkipReason = "stored_set_not_found"
            return None

        if not self._isCtfStoredSet(storedSet):
            self.lastSkipReason = "stored_set_is_not_setofctf"
            return None

        scipionItemId = self._toOptionalInt(ctfId)
        item = None if scipionItemId is None else self.setMapper.getStoredSetItem(storedSet["id"], scipionItemId)
        if item is None:
            self.lastSkipReason = "ctf_not_found ctfId=%s" % str(ctfId)
            return None
        # Its position in the list is not known without reading the Set; whoever needs it has the list
        return self._buildCtfRow(item, None)

    def getMicrographImageInfo(self, ctfId: Any) -> Optional[Dict[str, Any]]:
        self.lastSkipReason = None

        # Only the Set's id is needed: its items are not read
        storedSet = self._getStoredSetMeta()
        if storedSet is None:
            self.lastSkipReason = "stored_set_not_found"
            return None

        scipionItemId = self._toOptionalInt(ctfId)
        if scipionItemId is None:
            self.lastSkipReason = "invalid_ctf_id ctfId=%s" % str(ctfId)
            return None

        micrographRow = None
        storedSetId = self._toOptionalInt(storedSet.get("id"))

        if storedSetId is not None:
            micrographRow = self.setMapper.getStoredSetItemBySourceRelation(
                projectId=self.projectId,
                childSetId=storedSetId,
                scipionItemId=scipionItemId,
            )

        if micrographRow is None:
            micrographRow = self.setMapper.getStoredMicrographItemFromProtocolInputGraph(
                projectId=self.projectId,
                protocolDbId=self.protocolId,
                scipionItemId=scipionItemId,
            )

        if micrographRow is None:
            self.lastSkipReason = (
                "micrograph_not_found ctfId=%s"
                % str(ctfId)
            )
            return None

        values = self._normalizeJsonObject(
            micrographRow.get("values")
        )

        fileName = self._firstValueBySuffix(
            values,
            [
                "filename",
                "filepath",
                "imagefilename",
                "micfilename",
                "micrographfilename",
            ],
        )

        locationIndex = self._toOptionalInt(
            self._firstValueBySuffix(
                values,
                [
                    "locationindex",
                    "imageindex",
                ],
            )
        )

        if not fileName:
            locationValue = self._firstValueBySuffix(
                values,
                ["location"],
            )

            parsedIndex, parsedFileName = self._parseImageLocation(
                locationValue
            )

            if locationIndex is None:
                locationIndex = parsedIndex

            if parsedFileName:
                fileName = parsedFileName

        if not fileName:
            self.lastSkipReason = (
                "micrograph_file_not_found ctfId=%s"
                % str(ctfId)
            )
            return None

        label = (
                self._firstValueBySuffix(
                    values,
                    [
                        "micname",
                        "micrographname",
                        "objlabel",
                    ],
                )
                or micrographRow.get("label")
                or "Micrograph %s" % str(ctfId)
        )

        return {
            "micrographId": str(ctfId),
            "micrographName": str(label),
            "fileName": str(fileName),
            "locationIndex": locationIndex,
        }

    def _buildCtfRow(
            self,
            item: Dict[str, Any],
            position: Optional[int],
    ) -> Dict[str, Any]:
        values = self._normalizeJsonObject(
            item.get("values")
        )

        ctfId = item.get("scipionItemId")

        defocusU = self._toOptionalFloat(
            self._firstValueBySuffix(
                values,
                ["defocusu", "df1"],
            )
        )

        defocusV = self._toOptionalFloat(
            self._firstValueBySuffix(
                values,
                ["defocusv", "df2"],
            )
        )

        failed = self._isFailedCtf(
            defocusU,
            defocusV,
        )

        defocusRatio = self._toOptionalFloat(
            self._firstValueBySuffix(
                values,
                ["defocusratio"],
            )
        )

        if (
                defocusRatio is None
                and not failed
                and defocusU is not None
                and defocusV is not None
                and defocusV > 0
        ):
            defocusRatio = defocusU / defocusV

        astigmatism = None

        if (
                not failed
                and defocusU is not None
                and defocusV is not None
        ):
            astigmatism = defocusU - defocusV

        enabled = self._toOptionalBool(
            item.get("enabled")
        )

        micrographName = (
            item.get("label")
            or self._firstValueBySuffix(
                values,
                ["micname", "micrographname"],
            )
            or "Micrograph %s" % str(ctfId)
        )

        row: Dict[str, Any] = {
            "ctfId": str(ctfId),
            "position": None if position is None else int(position),
            "micrographId": str(ctfId),
            "micrographName": str(micrographName),
            "excluded": not enabled if enabled is not None else False,
            "failed": failed,
        }

        optionalValues = {
            "defocusU": defocusU,
            "defocusV": defocusV,
            "astigmatism": astigmatism,
            "defocusAngle": self._toOptionalFloat(
                self._firstValueBySuffix(
                    values,
                    ["defocusangle", "astigangle"],
                )
            ),
            "defocusRatio": defocusRatio,
            "phaseShift": self._toOptionalFloat(
                self._firstValueBySuffix(
                    values,
                    ["phaseshift"],
                )
            ),
            "resolution": self._toOptionalFloat(
                self._firstValueBySuffix(
                    values,
                    ["resolution", "estres"],
                )
            ),
            "fitQuality": self._toOptionalFloat(
                self._firstValueBySuffix(
                    values,
                    [
                        "fitquality",
                        "ccvalue",
                        "cc",
                    ],
                )
            ),
        }

        for key, value in optionalValues.items():
            if value is not None:
                row[key] = value

        psdFile = self._firstValueBySuffix(
            values,
            [
                "psdfile",
                "psdpath",
            ],
        )

        if psdFile:
            row["psdFile"] = str(psdFile)

        return row

    def _getStoredSet(self) -> Optional[Dict[str, Any]]:
        if self._storedSet is None:
            self._storedSet = self.setMapper.getStoredSet(
                projectId=self.projectId,
                protocolDbId=self.protocolId,
                outputName=self.outputName,
            )

        return self._storedSet

    def _getStoredSetMeta(self) -> Optional[Dict[str, Any]]:
        """The Set without its items (or with them, when a full read already happened)."""
        if self._storedSet is not None:
            return self._storedSet
        if self._storedSetMeta is None:
            self._storedSetMeta = self.setMapper.getStoredSet(
                projectId=self.projectId,
                protocolDbId=self.protocolId,
                outputName=self.outputName,
                limit=0,
            )
        return self._storedSetMeta

    def _isCtfStoredSet(
            self,
            storedSet: Dict[str, Any],
    ) -> bool:
        classText = (
            "%s %s"
            % (
                storedSet.get("setClassName") or "",
                storedSet.get("itemClassName") or "",
            )
        ).replace(" ", "").replace("_", "").lower()

        if "ctftomo" in classText:
            return False

        return (
            "setofctf" in classText
            or "ctfmodel" in classText
        )

    @staticmethod
    def _isFailedCtf(
            defocusU: Optional[float],
            defocusV: Optional[float],
    ) -> bool:
        if defocusU is None or defocusV is None:
            return False

        return (
            abs(defocusU + 999.0) < 1e-6
            and abs(defocusV + 1.0) < 1e-6
        )

    def _firstValueBySuffix(
            self,
            values: Dict[str, Any],
            suffixes: List[str],
    ) -> Any:
        normalizedSuffixes = [
            str(suffix)
            .replace("_", "")
            .replace(".", "")
            .lower()
            for suffix in suffixes
        ]

        for key, value in (values or {}).items():
            normalizedKey = (
                str(key)
                .replace("_", "")
                .replace(".", "")
                .lower()
            )

            for suffix in normalizedSuffixes:
                if normalizedKey.endswith(suffix):
                    return value

        return None

    def _normalizeJsonObject(
            self,
            value: Any,
    ) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)

        if isinstance(value, str):
            text = value.strip()

            if not text:
                return {}

            try:
                parsed = json.loads(text)
            except Exception:
                return {}

            if isinstance(parsed, dict):
                return dict(parsed)

        return {}

    def _parseImageLocation(
            self,
            value: Any,
    ):
        if isinstance(value, dict):
            fileName = (
                value.get("fileName")
                or value.get("filename")
                or value.get("path")
            )

            locationIndex = self._toOptionalInt(
                value.get("index")
                or value.get("locationIndex")
                or value.get("imageIndex")
            )

            return (
                locationIndex,
                str(fileName) if fileName else None,
            )

        if isinstance(value, (list, tuple)):
            if len(value) >= 2:
                return (
                    self._toOptionalInt(value[0]),
                    str(value[1]) if value[1] else None,
                )

            if len(value) == 1:
                return self._parseImageLocation(value[0])

            return None, None

        text = str(value or "").strip()

        if not text:
            return None, None

        if "@" in text:
            indexText, fileName = text.split("@", 1)

            locationIndex = self._toOptionalInt(
                indexText
            )

            if locationIndex is not None and fileName:
                return locationIndex, fileName

        return None, text

    @staticmethod
    def _toOptionalFloat(
            value: Any,
    ) -> Optional[float]:
        if value is None or value == "":
            return None

        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _toOptionalInt(
            value: Any,
    ) -> Optional[int]:
        if value is None or value == "":
            return None

        try:
            return int(value)
        except Exception:
            try:
                return int(float(value))
            except Exception:
                return None

    @staticmethod
    def _toOptionalBool(
            value: Any,
    ) -> Optional[bool]:
        if value is None or value == "":
            return None

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return bool(value)

        text = str(value).strip().lower()

        if text in {"1", "true", "yes", "on"}:
            return True

        if text in {"0", "false", "no", "off"}:
            return False

        return None