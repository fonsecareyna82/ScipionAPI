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
import re
from typing import Any, Dict, List, Optional

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository
from app.backend.viewers.postgresql_tiltseries_reader import PostgresqlTiltSeriesReader


class PostgresqlCtftomoReader:
    def __init__(self, db, projectId: int, protocolId: int, outputName: str):
        self.db = db
        self.projectId = projectId
        self.protocolId = protocolId
        self.outputName = outputName
        self.setMapper = ScipionSetPostgresqlMapper(db)
        self._storedSet = None
        self._logicalTables = None
        self._associatedTiltSeriesFramesBySeriesId = {}
        self.lastSkipReason = None

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
        self.lastSkipReason = None
        seriesItem = self._findCtftomoSeriesItem(tiltSeriesId)
        if seriesItem is None:
            self.lastSkipReason = (
                    "ctftomo_series_item_not_found tiltSeriesId=%s"
                    % str(tiltSeriesId)
            )
            return None

        summary = self._buildCtftomoSeriesSummary(seriesItem, 0)
        childTable = self._findChildTableForParentItem(seriesItem.get("scipionItemId"))

        associatedTiltFrames = self._getAssociatedTiltSeriesFrames(
            summary.get("tiltSeriesId") or tiltSeriesId
        )

        frames: List[Dict[str, Any]] = []
        if childTable is not None:
            childItems = self.setMapper.getStoredSetTableItems(int(childTable["id"]))
            for index, item in enumerate(childItems):
                frame = self._buildCtftomoMeasurementFrame(item, index)
                tiltFrame = self._findAssociatedTiltSeriesFrame(
                    ctfFrame=frame,
                    position=index,
                    tiltFrames=associatedTiltFrames,
                )
                self._mergeTiltSeriesFrameIntoCtftomoFrame(frame, tiltFrame)
                frames.append(frame)

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

    def _getAssociatedTiltSeriesFrames(self, tiltSeriesId: Any) -> List[Dict[str, Any]]:
        seriesKey = str(tiltSeriesId)
        if seriesKey in self._associatedTiltSeriesFramesBySeriesId:
            return self._associatedTiltSeriesFramesBySeriesId[seriesKey]

        frames = self._loadAssociatedTiltSeriesFrames(tiltSeriesId)
        self._associatedTiltSeriesFramesBySeriesId[seriesKey] = frames
        return frames

    def _loadAssociatedTiltSeriesFrames(self, tiltSeriesId: Any) -> List[Dict[str, Any]]:
        storedSet = self._getStoredSet()
        rootProtocolDbId = storedSet.get("protocolDbId") if storedSet else self.protocolId

        tiltStoredSet = self._findRegularTiltSeriesStoredSetForProtocol(rootProtocolDbId)
        if tiltStoredSet is None:
            return []

        protocolDbId = tiltStoredSet.get("protocolDbId")
        outputName = tiltStoredSet.get("outputName")

        if protocolDbId is None or not outputName:
            return []

        reader = PostgresqlTiltSeriesReader(
            db=self.db,
            projectId=self.projectId,
            protocolId=protocolDbId,
            outputName=outputName,
        )

        payload = reader.getTiltSeriesFrames(tiltSeriesId)
        if not payload:
            return []

        return payload.get("frames") or []

    def _findRegularTiltSeriesStoredSetForProtocol(
            self,
            protocolDbId: Any,
            visited: Optional[set] = None,
    ) -> Optional[Dict[str, Any]]:
        if protocolDbId is None:
            return None

        if visited is None:
            visited = set()

        protocolKey = str(protocolDbId)
        if protocolKey in visited:
            return None

        visited.add(protocolKey)

        sameProtocolStoredSet = self._findRegularTiltSeriesStoredSetInProtocol(protocolDbId)
        if sameProtocolStoredSet is not None:
            return sameProtocolStoredSet

        inputRefs = self._listProtocolInputRefs(protocolDbId)

        for inputRef in inputRefs:
            if self._getInputRefKind(inputRef) != "tiltSeries":
                continue

            storedSet = self._getStoredSetFromInputRef(inputRef)
            if self._isRegularTiltSeriesStoredSet(storedSet):
                return storedSet

        for inputRef in inputRefs:
            if self._getInputRefKind(inputRef) != "ctf":
                continue

            parentProtocolDbId = inputRef.get("parentProtocolDbId")
            storedSet = self._findRegularTiltSeriesStoredSetForProtocol(
                parentProtocolDbId,
                visited=visited,
            )

            if storedSet is not None:
                return storedSet

        return None

    def _findRegularTiltSeriesStoredSetInProtocol(
            self,
            protocolDbId: Any,
    ) -> Optional[Dict[str, Any]]:
        try:
            storedSets = self.setMapper.listProtocolStoredSets(
                projectId=self.projectId,
                protocolDbId=int(protocolDbId),
            )
        except Exception:
            return None

        for storedSet in storedSets or []:
            storedSetDict = dict(storedSet)
            if self._isRegularTiltSeriesStoredSet(storedSetDict):
                return storedSetDict

        return None

    def _listProtocolInputRefs(
            self,
            protocolDbId: Any,
    ) -> List[Dict[str, Any]]:
        if protocolDbId is None:
            return []

        try:
            return ProtocolGraphRepository().loadInputRefsForProtocol(
                mapper=self.setMapper,
                projectId=self.projectId,
                protocolDbId=int(protocolDbId),
            )
        except Exception:
            return []

    def _getInputRefKind(self, inputRef: Dict[str, Any]) -> Optional[str]:
        text = self._normalizeClassText(inputRef.get("objectClassName"))

        if "ctftomo" in text:
            return "ctf"

        if self._isTiltSeriesMClassText(text):
            return "tiltSeriesM"

        if self._isRegularTiltSeriesClassText(text):
            return "tiltSeries"

        return None

    def _isRegularTiltSeriesStoredSet(self, storedSet: Optional[Dict[str, Any]]) -> bool:
        if storedSet is None:
            return False

        classText = self._normalizeClassText(
            "%s %s" % (
                storedSet.get("setClassName") or "",
                storedSet.get("itemClassName") or "",
            )
        )

        return self._isRegularTiltSeriesClassText(classText)

    def _isRegularTiltSeriesClassText(self, text: Any) -> bool:
        classText = self._normalizeClassText(text)

        if self._isTiltSeriesMClassText(classText):
            return False

        if "ctftomo" in classText:
            return False

        return "tiltseries" in classText

    def _isTiltSeriesMClassText(self, text: Any) -> bool:
        classText = self._normalizeClassText(text)

        return (
                "setoftiltseriesm" in classText
                or "tiltseriesm" in classText
                or "tiltimagem" in classText
                or "movie" in classText
                or "movies" in classText
        )

    def _normalizeClassText(self, value: Any) -> str:
        return str(value or "").replace(" ", "").replace("_", "").replace(".", "").lower()

    def _getStoredSetFromInputRef(self, inputRef: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        parentProtocolDbId = inputRef.get("parentProtocolDbId")
        if parentProtocolDbId is None:
            return None

        for outputName in self._expandInputRefOutputNames(inputRef.get("parentOutputName")):
            storedSet = self.setMapper.getStoredSet(
                projectId=self.projectId,
                protocolDbId=parentProtocolDbId,
                outputName=outputName,
                limit=None,
                offset=0,
            )

            if storedSet is not None:
                return storedSet

        return None

    def _expandInputRefOutputNames(self, outputName: Any) -> List[str]:
        outputNameText = str(outputName or "").strip()
        if not outputNameText:
            return []

        outputNames = [outputNameText]

        if "." in outputNameText:
            outputNames.append(outputNameText.split(".", 1)[0])

        result = []
        seen = set()

        for item in outputNames:
            if item in seen:
                continue

            seen.add(item)
            result.append(item)

        return result

    def _findAssociatedTiltSeriesFrame(
            self,
            ctfFrame: Dict[str, Any],
            position: int,
            tiltFrames: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not tiltFrames:
            return None

        orderKey = self._toTextKey(ctfFrame.get("order"))
        if orderKey:
            for tiltFrame in tiltFrames:
                if self._toTextKey(tiltFrame.get("order")) == orderKey:
                    return tiltFrame

        if 0 <= position < len(tiltFrames):
            return tiltFrames[position]

        return None

    def _mergeTiltSeriesFrameIntoCtftomoFrame(
            self,
            ctfFrame: Dict[str, Any],
            tiltFrame: Optional[Dict[str, Any]],
    ) -> None:
        if tiltFrame is None:
            return

        for key in ("tiltAngle", "dose", "order"):
            if ctfFrame.get(key) is None and tiltFrame.get(key) is not None:
                ctfFrame[key] = tiltFrame.get(key)

    def _toTextKey(self, value: Any) -> Optional[str]:
        if value is None:
            return None

        text = str(value).strip()
        return text or None

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

        summary["excluded"] = (
            self._getFrameExcluded(
                item=item,
                values=values,
            )
        )

        childTable = self._findChildTableForParentItem(itemId)
        if childTable is not None:
            childItems = self.setMapper.getStoredSetTableItems(int(childTable["id"]))
            summary["nViews"] = len(childItems)

        dims = self._extractDims(values)
        if dims is not None:
            summary["dims"] = dims

        pixelSize = self._extractSamplingRate(values)
        if pixelSize is not None:
            summary["pixelSize"] = pixelSize

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

        viewId = item.get(
            "scipionItemId"
        )

        if viewId is None:
            viewId = position

        ctfIndex = self._firstValue(
            values,
            [
                "_index",
                "index",
            ],
        )

        if ctfIndex is None:
            ctfIndex = (
                self._firstValueBySuffix(
                    values,
                    [
                        "index",
                    ],
                )
            )

        ctfIndex = (
            self._toOptionalInt(
                ctfIndex
            )
        )

        if ctfIndex is None:
            ctfIndex = position

        frame: Dict[str, Any] = {
            "viewId": viewId,
            "index": ctfIndex,
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

        defocusU = self._firstValueBySuffix(
            values,
            ["defocusu", "defocus1", "dfu", "df1"],
        )
        defocusUFloat = self._toOptionalFloat(defocusU)
        if defocusUFloat is not None:
            frame["defocusU"] = defocusUFloat

        defocusV = self._firstValueBySuffix(
            values,
            ["defocusv", "defocus2", "dfv", "df2"],
        )
        defocusVFloat = self._toOptionalFloat(defocusV)
        if defocusVFloat is not None:
            frame["defocusV"] = defocusVFloat

        if defocusUFloat is not None and defocusVFloat is not None:
            frame["astigmatism"] = defocusUFloat - defocusVFloat

        defocusAngle = self._firstValueBySuffix(
            values,
            ["defocusangle", "astigangle", "astigmatismangle", "angast"],
        )
        defocusAngleFloat = self._toOptionalFloat(defocusAngle)
        if defocusAngleFloat is not None:
            frame["defocusAngle"] = defocusAngleFloat

        resolution = self._firstValueBySuffix(
            values,
            ["resolution", "estimatedresolution", "estres", "estresolution"],
        )
        resolutionFloat = self._toOptionalFloat(resolution)
        if resolutionFloat is not None:
            frame["resolution"] = resolutionFloat

        cc = self._firstValueBySuffix(
            values,
            ["cc", "crosscorrelation", "ctffitcc"],
        )
        ccFloat = self._toOptionalFloat(cc)
        if ccFloat is not None:
            frame["cc"] = ccFloat

        phaseShift = self._firstValueBySuffix(
            values,
            ["phaseshift", "phase_shift"],
        )
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

        frame["excluded"] = self._getFrameExcluded(
            item=item,
            values=values,
        )

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

    def _getFrameExcluded(
            self,
            item: Dict[str, Any],
            values: Dict[str, Any],
    ) -> bool:
        excludedValue = self._firstValueBySuffix(
            values,
            [
                "excluded",
                "skip",
            ],
        )

        if excludedValue is not None:
            excluded = self._toOptionalBool(
                excludedValue
            )

            return bool(
                excluded
            ) if excluded is not None else False

        enabledValue = item.get(
            "enabled"
        )

        if enabledValue is None:
            enabledValue = self._firstValueBySuffix(
                values,
                [
                    "enabled",
                    "isenabled",
                ],
            )

        enabled = self._toOptionalBool(
            enabledValue
        )

        if enabled is None:
            return False

        return not enabled

    def _extractDims(self, values: Dict[str, Any]) -> Optional[List[int]]:
        raw = self._firstValueBySuffix(
            values,
            [
                "dim",
                "dims",
                "dimensions",
                "getDim",
                "imageDim",
                "imageDims",
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

    def _extractSamplingRate(self, values: Dict[str, Any]) -> Optional[float]:
        raw = self._firstValueBySuffix(
            values,
            [
                "samplingrate",
                "samplingRate",
                "pixelSize",
                "pixel_size",
                "voxelSize",
                "apix",
            ],
        )

        numbers = self._parseNumericSequence(raw)
        if numbers:
            return self._toOptionalFloat(numbers[0])

        return self._toOptionalFloat(raw)

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