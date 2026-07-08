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
import logging
from typing import Any, Dict, List, Optional

from pyworkflow.object import Pointer, PointerList
from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository
from app.backend.runtime.protocol_identity import ProtocolIdentityResolver


logger = logging.getLogger(__name__)


class RuntimePointerResolver:
    """
    Normalize Scipion pointer values used by the PostgreSQL runtime migration.

    This class owns pointer value semantics and may resolve parent protocol
    identities through ProtocolIdentityResolver. It may also look up persisted
    output metadata through ProtocolGraphRepository when building input refs.
    """

    emptyPointerTexts = ("", "none", "null", "undefined")

    @staticmethod
    def _getScipionObjectId(obj) -> Optional[int]:
        if obj is None:
            return None

        for methodName in ("getObjId", "getId"):
            method = getattr(obj, methodName, None)

            if method is None:
                continue

            try:
                value = method()
            except Exception:
                continue

            if value not in (None, ""):
                try:
                    return int(value)
                except Exception:
                    return None

        for attrName in ("objId", "_objId", "id"):
            value = getattr(obj, attrName, None)

            if value not in (None, ""):
                try:
                    return int(value)
                except Exception:
                    return None

        return None

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

    def completePointerValuesFromInputRefs(
            self,
            mapper,
            projectId: int,
            protocol,
            inputName: str,
            rawValue: Any,
    ) -> List[str]:
        """
        Complete pointer values that arrive without parent protocol id.

        Example:
            "outputTiltSeries"

        becomes:
            "123.outputTiltSeries"

        using protocol_input_refs for this protocol/inputName.
        """
        pointerValues = self.normalizePointerParamValues(rawValue)

        if not pointerValues:
            return []

        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        protocolId = protocolIdentityResolver.resolveScipionProtocolId(
            self._getScipionObjectId(protocol),
        )

        protocolDbId = None
        if protocolId is not None:
            protocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbId(
                protocolId,
            )

        completeValues = []
        missingParentOutputNames = []

        for pointerValue in pointerValues:
            parentId, outputName = self.splitPointerValue(pointerValue)

            if parentId:
                completeValues.append(pointerValue)
                continue

            if outputName:
                missingParentOutputNames.append(outputName)

        if not missingParentOutputNames:
            return completeValues

        db = getattr(mapper, "db", None)

        if protocolDbId in (None, "") or db is None:
            return completeValues + missingParentOutputNames

        rows = db.fetchAll(
            """
            SELECT
                "itemIndex",
                "parentProtocolId",
                "parentOutputName"
              FROM protocol_input_refs
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND "inputName" = %s
             ORDER BY "itemIndex"
            """,
            (
                int(projectId),
                int(protocolDbId),
                str(inputName),
            ),
        )

        refsByOutputName = {}

        for row in rows or []:
            parentProtocolId = row.get("parentProtocolId")
            parentOutputName = str(row.get("parentOutputName") or "").strip()

            if parentProtocolId in (None, "") or not parentOutputName:
                continue

            refsByOutputName.setdefault(parentOutputName, []).append(row)

        for outputName in missingParentOutputNames:
            candidates = refsByOutputName.get(outputName) or []

            if len(candidates) == 1:
                parentProtocolId = candidates[0].get("parentProtocolId")
                completedValue = "%s.%s" % (
                    str(parentProtocolId).strip(),
                    str(outputName).strip(),
                )

                if completedValue not in completeValues:
                    completeValues.append(completedValue)

                logger.info(
                    "Completed pointer value from PostgreSQL input refs. "
                    "projectId=%s protocolId=%s protocolDbId=%s inputName=%s value=%s",
                    projectId,
                    protocolId,
                    protocolDbId,
                    inputName,
                    completedValue,
                )

            else:
                # Keep original value. The caller will produce a validation error.
                if outputName not in completeValues:
                    completeValues.append(outputName)

        return completeValues

    def loadInputRefsByInputName(
            self,
            mapper,
            projectId: int,
            protocolDbId,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Load PostgreSQL input refs grouped by input name.

        This is used when restoring Pointer/PointerList attributes before
        Scipion copyProtocol(), where Scipion expects real Pointer objects.
        """
        db = getattr(mapper, "db", None)

        if db is None or protocolDbId in (None, ""):
            return {}

        rows = db.fetchAll(
            """
            SELECT
                r."inputName",
                r."itemIndex",
                parent."protocolId" AS "parentProtocolId",
                r."parentOutputName"
              FROM protocol_input_refs r
         LEFT JOIN protocols parent
                ON parent."projectId" = r."projectId"
               AND parent.id = r."parentProtocolDbId"
             WHERE r."projectId" = %s
               AND r."protocolDbId" = %s
             ORDER BY r."inputName", r."itemIndex"
            """,
            (
                int(projectId),
                int(protocolDbId),
            ),
        )

        refsByInputName: Dict[str, List[Dict[str, Any]]] = {}

        for row in rows or []:
            inputName = str(row.get("inputName") or "").strip()
            parentProtocolId = row.get("parentProtocolId")
            parentOutputName = str(row.get("parentOutputName") or "").strip()

            if not inputName or parentProtocolId in (None, "") or not parentOutputName:
                continue

            refsByInputName.setdefault(inputName, []).append(dict(row))

        return refsByInputName

    def restorePointerAttributeFromInputRefs(
            self,
            protocol,
            inputName: str,
            inputRefs: List[Dict[str, Any]],
            isMultiPointer: bool,
            resolveParentProtocolCallback,
    ) -> Dict[str, Any]:
        """
        Restore a Scipion Pointer/PointerList attribute from input refs.

        This is used before Scipion copyProtocol(), because copyProtocol() expects
        real Pointer objects, not PostgreSQL textual values.
        """
        restoredItems = []

        if isMultiPointer:
            pointerList = PointerList()

            for ref in inputRefs:
                parentProtocolId = ref.get("parentProtocolId")
                parentOutputName = str(ref.get("parentOutputName") or "").strip()

                if parentProtocolId in (None, "") or not parentOutputName:
                    continue

                parentScipionProtocolId, parentProtocol = resolveParentProtocolCallback(parentProtocolId)

                pointerList.append(
                    Pointer(parentProtocol, extended=parentOutputName)
                )

                restoredItems.append({
                    "inputName": inputName,
                    "kind": "multipointer",
                    "parentProtocolId": str(parentScipionProtocolId),
                    "parentOutputName": parentOutputName,
                })

            setattr(protocol, inputName, pointerList)

            return {
                "restored": restoredItems,
                "skipped": False,
            }

        if not inputRefs:
            return {
                "restored": [],
                "skipped": True,
                "reason": "empty_input_refs",
            }

        ref = inputRefs[0]
        parentProtocolId = ref.get("parentProtocolId")
        parentOutputName = str(ref.get("parentOutputName") or "").strip()

        if parentProtocolId in (None, "") or not parentOutputName:
            return {
                "restored": [],
                "skipped": True,
                "reason": "invalid_input_ref",
            }

        parentScipionProtocolId, parentProtocol = resolveParentProtocolCallback(parentProtocolId)

        pointer = Pointer(parentProtocol, extended=parentOutputName)
        setattr(protocol, inputName, pointer)

        restoredItems.append({
            "inputName": inputName,
            "kind": "pointer",
            "parentProtocolId": str(parentScipionProtocolId),
            "parentOutputName": parentOutputName,
        })

        return {
            "restored": restoredItems,
            "skipped": False,
        }

    def resolvePointerTarget(
            self,
            mapper,
            projectId: int,
            pointerValue: Any,
            paramLabel: str,
            getParentProtocolCallback,
            resolveParentOutputCallback,
    ) -> Dict[str, Any]:
        """
        Resolve one normalized pointer value into its parent protocol and output.

        This method owns pointer target identity resolution. The caller still
        provides project/runtime access for loading parent protocols and
        resolving parent output objects during this refactor step.
        """
        parentId, outputName = self.splitPointerValue(pointerValue)

        if outputName and not parentId:
            return {
                "ok": False,
                "error": "**%s** could not resolve parent protocol for input %s"
                         % (paramLabel, pointerValue),
                "parentId": parentId,
                "outputName": outputName,
            }

        if not outputName:
            return {
                "ok": False,
                "error": "**%s** could not resolve empty pointer input %s"
                         % (paramLabel, pointerValue),
                "parentId": parentId,
                "outputName": outputName,
            }

        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        try:
            parentScipionProtocolId, parentProtocol = getParentProtocolCallback(
                mapper=mapper,
                projectId=projectId,
                parentId=parentId,
            )

            parentProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbId(
                parentScipionProtocolId,
            )

            if parentProtocolDbId is None:
                return {
                    "ok": False,
                    "error": "**%s** parent protocol %s was not found in PostgreSQL."
                             % (paramLabel, parentScipionProtocolId),
                    "parentId": parentId,
                    "outputName": outputName,
                    "parentScipionProtocolId": parentScipionProtocolId,
                    "parentProtocol": parentProtocol,
                    "parentProtocolDbId": None,
                }

            resolvedOutput = resolveParentOutputCallback(
                mapper=mapper,
                projectId=projectId,
                parentProtocolDbId=int(parentProtocolDbId),
                parentScipionProtocolId=parentScipionProtocolId,
                parentProtocol=parentProtocol,
                outputName=outputName,
            )

            if not resolvedOutput.get("exists"):
                return {
                    "ok": False,
                    "error": "**%s** parent protocol %s does not have output %s in PostgreSQL or runtime."
                             % (paramLabel, parentScipionProtocolId, outputName),
                    "parentId": parentId,
                    "outputName": outputName,
                    "parentScipionProtocolId": parentScipionProtocolId,
                    "parentProtocol": parentProtocol,
                    "parentProtocolDbId": parentProtocolDbId,
                    "resolvedOutput": resolvedOutput,
                }

            return {
                "ok": True,
                "parentId": parentId,
                "outputName": outputName,
                "parentScipionProtocolId": parentScipionProtocolId,
                "parentProtocol": parentProtocol,
                "parentProtocolDbId": int(parentProtocolDbId),
                "resolvedOutput": resolvedOutput,
            }

        except Exception as e:
            logger.exception(
                "Could not resolve runtime pointer target. projectId=%s pointerValue=%s",
                projectId,
                pointerValue,
            )

            return {
                "ok": False,
                "error": "**%s** could not resolve input %s: %s"
                         % (paramLabel, pointerValue, e),
                "parentId": parentId,
                "outputName": outputName,
                "exception": e,
            }

    def buildInputRefsFromPointerParams(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
            protocolId,
            params: Dict[str, Any],
            getParamCallback,
            isPointerParamCallback,
    ) -> Dict[str, Any]:
        """
        Build PostgreSQL input refs from normalized pointer params.

        This method does not persist anything. It only inspects params and returns:
          - parentProtocolDbIds
          - parentProtocolIds
          - inputRefs
          - detectedPointerParams
        """
        parentProtocolDbIds: List[int] = []
        parentProtocolIds: List[int] = []
        inputRefs: List[Dict[str, Any]] = []
        detectedPointerParams = []

        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        protocolGraphRepository = ProtocolGraphRepository()

        for inputName, rawParamValue in params.items():
            try:
                param = getParamCallback(inputName)
            except Exception:
                param = None

            if not isPointerParamCallback(param):
                continue

            pointerValues = self.normalizePointerParamValues(rawParamValue)

            if not pointerValues:
                continue

            validPointerValues = []

            for pointerValue in pointerValues:
                parentId, outputName = self.splitPointerValue(pointerValue)

                if parentId and outputName:
                    validPointerValues.append(pointerValue)

            if not validPointerValues:
                continue

            detectedPointerParams.append({
                "inputName": inputName,
                "paramClass": param.__class__.__name__ if param is not None else None,
                "isPointerParam": isPointerParamCallback(param),
                "rawValue": rawParamValue,
                "pointerValues": validPointerValues,
            })

            for itemIndex, pointerValue in enumerate(pointerValues):
                parentId, outputName = self.splitPointerValue(pointerValue)

                if not parentId or not outputName:
                    continue

                try:
                    parentScipionProtocolId = protocolIdentityResolver.resolveScipionProtocolId(
                        parentId,
                    )
                except Exception:
                    logger.exception(
                        "Could not resolve parent protocol id from pointer param. "
                        "projectId=%s childProtocolId=%s inputName=%s value=%s",
                        projectId,
                        protocolId,
                        inputName,
                        pointerValue,
                    )
                    continue

                parentProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbId(
                    parentScipionProtocolId,
                )

                if parentProtocolDbId is None:
                    logger.warning(
                        "Parent protocol row not found while syncing runtime dependency. "
                        "projectId=%s childProtocolId=%s parentProtocolId=%s inputName=%s outputName=%s",
                        projectId,
                        protocolId,
                        parentScipionProtocolId,
                        inputName,
                        outputName,
                    )
                    continue

                parentProtocolDbId = int(parentProtocolDbId)
                parentScipionProtocolId = int(parentScipionProtocolId)

                if parentProtocolDbId not in parentProtocolDbIds:
                    parentProtocolDbIds.append(parentProtocolDbId)

                if parentScipionProtocolId not in parentProtocolIds:
                    parentProtocolIds.append(parentScipionProtocolId)

                outputInfo = protocolGraphRepository.getPersistedOutputInfoForInputRef(
                    mapper=mapper,
                    projectId=projectId,
                    parentProtocolDbId=parentProtocolDbId,
                    outputName=outputName,
                )

                inputRefs.append({
                    "projectId": int(projectId),
                    "protocolDbId": int(protocolDbId),
                    "protocolId": str(protocolId),
                    "inputName": str(inputName),
                    "itemIndex": int(itemIndex),
                    "parentProtocolDbId": parentProtocolDbId,
                    "parentProtocolId": str(parentScipionProtocolId),
                    "parentOutputName": str(outputName),
                    "objectClassName": outputInfo.get("className"),
                    "objectId": outputInfo.get("objectId"),
                })

        return {
            "parentProtocolDbIds": parentProtocolDbIds,
            "parentProtocolIds": parentProtocolIds,
            "inputRefs": inputRefs,
            "detectedPointerParams": detectedPointerParams,
        }

    def filterEmptyPointerValues(self, pointerValues: List[Any]) -> List[Any]:
        return [
            value for value in pointerValues
            if str(value or "").strip().lower() not in self.emptyPointerTexts
        ]