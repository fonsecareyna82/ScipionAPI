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

from pyworkflow.object import PointerList


class RuntimePointerResolver:
    """
    Normalize Scipion pointer values used by the PostgreSQL runtime migration.

    This class does not resolve parent protocols or outputs. It only converts the
    different frontend/runtime shapes into stable pointer values like:

        123.outputParticles
    """

    emptyPointerTexts = ("", "none", "null", "undefined")

    def splitPointerValue(self, value):
        valueText = str(value or "").strip()

        if not valueText:
            return "", ""

        if "." not in valueText:
            return "", valueText

        parentId, outputName = valueText.split(".", 1)
        return parentId.strip(), outputName.strip()

    def normalizePointerParamValues(self, rawValue: Any) -> List[str]:
        """
        Normalize PointerParam/MultiPointerParam values coming from the frontend.

        Supported shapes:
          "1.outputTSMovies"
          {"editableValue": "1.outputTSMovies"}
          {"value": "1.outputTSMovies"}
          {"parentId": 1, "value": "outputTSMovies"}
          {"parentId": 1, "outputName": "outputTSMovies"}
          {"parentProtocolId": 1, "parentOutputName": "outputTSMovies"}
          [{"editableValue": "1.outputA"}, {"parentId": 2, "value": "outputB"}]
        """
        if rawValue is None:
            return []

        if isinstance(rawValue, str) and not rawValue.strip():
            return []

        if isinstance(rawValue, (list, tuple, set)):
            result: List[str] = []

            for item in rawValue:
                result.extend(self.normalizePointerParamValues(item))

            return result

        if isinstance(rawValue, dict):
            parentId = (
                    rawValue.get("parentId")
                    or rawValue.get("protocolId")
                    or rawValue.get("parentProtocolId")
            )

            outputName = (
                    rawValue.get("outputName")
                    or rawValue.get("parentOutputName")
                    or rawValue.get("extended")
            )

            if parentId not in (None, ""):
                # If value/editableValue already has "1.outputX", keep that.
                for key in ("editableValue", "value", "default", "objValue", "name"):
                    candidate = rawValue.get(key)

                    if candidate in (None, "", []):
                        continue

                    candidateText = str(candidate).strip()

                    if "." in candidateText:
                        return self.normalizePointerParamValues(candidateText)

                    if outputName in (None, ""):
                        outputName = candidateText

                    break

                if outputName not in (None, ""):
                    return [f"{parentId}.{outputName}"]

            # Direct textual value case, without separate parentId.
            for key in ("editableValue", "value", "default", "objValue"):
                value = rawValue.get(key)

                if value in (None, "", []):
                    continue

                return self.normalizePointerParamValues(value)

            return []

        valueText = str(rawValue or "").strip()
        return [valueText] if valueText else []

    def normalizePointerValuesFromProtocolAttribute(self, attr: Any) -> List[str]:
        """
        Extract normalized pointer values from an already-applied Scipion pointer
        attribute.

        This protects PostgreSQL runtime dependency sync from partial launch
        payloads: if a pointer is already present on the protocol object, we
        should preserve it even if it is not present in the current request params.
        """
        if attr is None:
            return []

        if isinstance(attr, str) and not attr.strip():
            return []

        result: List[str] = []

        def addValue(parentId, outputName):
            if parentId in (None, "") or outputName in (None, ""):
                return

            value = "%s.%s" % (str(parentId).strip(), str(outputName).strip())
            if value not in result:
                result.append(value)

        # PointerList / MultiPointer-like case.
        try:
            if isinstance(attr, PointerList):
                for item in attr:
                    for value in self.normalizePointerValuesFromProtocolAttribute(item):
                        if value not in result:
                            result.append(value)

                return result
        except Exception:
            pass

        # Plain list/tuple fallback, just in case.
        if isinstance(attr, (list, tuple, set)):
            for item in attr:
                for value in self.normalizePointerValuesFromProtocolAttribute(item):
                    if value not in result:
                        result.append(value)

            return result

        # Raw value already stored as frontend-like representation.
        if isinstance(attr, (str, dict)):
            return self.normalizePointerParamValues(attr)

        targetObj = None
        objValue = None
        extended = None

        try:
            targetObj = attr.get() if hasattr(attr, "get") else None
        except Exception:
            targetObj = None

        try:
            objValue = attr.getObjValue() if hasattr(attr, "getObjValue") else None
        except Exception:
            objValue = None

        try:
            extended = attr.getExtended() if hasattr(attr, "getExtended") else None
        except Exception:
            extended = None

        # Sometimes the pointer target itself is a raw string: "1175.outputTiltSeriesM".
        if isinstance(targetObj, str):
            return self.normalizePointerParamValues(targetObj)

        parentId = None

        # Normal Pointer: objValue is the parent protocol.
        if objValue is not None:
            try:
                parentId = objValue.getObjId()
            except Exception:
                parentId = None

        # Sometimes attr.get() returns the pointed output object.
        if parentId is None and targetObj is not None:
            try:
                parentId = targetObj.getObjParentId()
            except Exception:
                parentId = None

        if parentId is None and targetObj is not None:
            try:
                parentObj = targetObj.getObjParent()
                if parentObj is not None:
                    parentId = parentObj.getObjId()
            except Exception:
                parentId = None

        addValue(parentId, extended)

        return result

    def mergePointerParamsWithProtocolState(
            self,
            protocol,
            params: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Merge request params with pointer values already present in the protocol.

        Important:
          - If a param is explicitly present in params, respect the request value.
          - If a pointer param is missing from params, preserve the value already
            applied on the protocol object.
        """
        mergedParams: Dict[str, Any] = dict(params or {})
        explicitParamNames = set(mergedParams.keys())

        try:
            inputAttributes = list(protocol.iterInputAttributes())
        except Exception:
            inputAttributes = []

        for inputName, attr in inputAttributes:
            if inputName in explicitParamNames:
                # The request explicitly sent this param. Do not resurrect old values
                # if the frontend intentionally cleared it.
                continue

            pointerValues = self.normalizePointerValuesFromProtocolAttribute(attr)

            if not pointerValues:
                continue

            mergedParams[inputName] = pointerValues[0] if len(pointerValues) == 1 else pointerValues

        return mergedParams

    def filterEmptyPointerValues(self, pointerValues: List[Any]) -> List[Any]:
        return [
            value for value in pointerValues
            if str(value or "").strip().lower() not in self.emptyPointerTexts
        ]