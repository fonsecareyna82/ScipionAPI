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
# * All comments concerning this program package may be sent to the
# * e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
import logging
from typing import Any, Callable, Dict, List, Tuple

import pyworkflow
import pyworkflow.utils as pwutils
from pyworkflow.protocol import (
    Group,
    Line,
    MultiPointerParam,
    PointerParam,
    RelationParam,
)

from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)
from app.utils.scipion_helper import serializeToJson


logger = logging.getLogger(__name__)


class ProtocolFormSerializer:
    """Serialize Scipion protocol parameters for the web form."""

    @staticmethod
    def _allowsScalarPointers(param) -> bool:
        return (
            bool(getattr(param, "allowsPointers", False))
            and not isinstance(
                param,
                (
                    PointerParam,
                    MultiPointerParam,
                    RelationParam,
                ),
            )
        )

    @staticmethod
    def _getScalarPointerClassName(param):
        paramClass = getattr(param, "paramClass", None)

        if paramClass is None:
            return None

        return getattr(
            paramClass,
            "__name__",
            str(paramClass),
        )

    def serializeParam(
            self,
            *,
            param,
            paramName,
            wizards,
            viewerDict,
            visualize,
            protVar,
            mapper=None,
            projectId=None,
            protocol=None,
            getScipionObjectIdCallback: Callable,
            resolvePostgresqlProtocolDbIdCallback: Callable,
            splitPointerValueCallback: Callable,
    ):
        """
        Serialize a protocol parameter.

        Pointer values persisted in PostgreSQL are read from
        protocol_input_refs. This operation is read-only: no protocol,
        parent protocol, output or input-reference row is modified.
        """
        try:
            paramDict = {}
            paramValue = ""

            # Keep current behavior for RelationParam.
            if isinstance(param, RelationParam):
                return {}, None

            paramDict["name"] = paramName

            wizardItems = (
                wizards.get(paramName, [])
                if wizards
                else []
            )

            paramDict["hasWizard"] = bool(wizardItems)
            paramDict["wizards"] = wizardItems
            paramDict["wizard"] = (
                wizardItems[0]
                if wizardItems
                else None
            )

            # Public attributes.
            for name, value in param.getAttributes():
                paramDict[name] = value.get()

            # Protected attributes currently exposed by the form.
            for name, value in vars(param).items():
                if name == "choices" or name == "gpuList":
                    paramDict[name] = serializeToJson(value)

            paramClass = param.__class__.__name__

            if paramClass == "LabelParam":
                paramClass = "Label"

            paramDict["paramClass"] = paramClass

            allowsScalarPointers = (
                self._allowsScalarPointers(
                    param
                )
            )

            paramDict["allowsPointers"] = (
                allowsScalarPointers
            )

            if allowsScalarPointers:
                pointerClass = (
                    self
                    ._getScalarPointerClassName(
                        param
                    )
                )

                if pointerClass:
                    paramDict["pointerClass"] = (
                        pointerClass
                    )

            if protVar is not None:
                if isinstance(param, MultiPointerParam):
                    valueList = []

                    protocolDbId = None

                    if (
                            mapper is not None
                            and projectId is not None
                            and protocol is not None
                            and getScipionObjectIdCallback is not None
                            and resolvePostgresqlProtocolDbIdCallback is not None
                    ):
                        protocolId = getScipionObjectIdCallback(
                            protocol
                        )

                        if protocolId not in (None, ""):
                            protocolDbId = resolvePostgresqlProtocolDbIdCallback(
                                mapper=mapper,
                                projectId=projectId,
                                protocolId=protocolId,
                            )

                    if protocolDbId is not None:
                        protocolGraphRepository = ProtocolGraphRepository()

                        valueList = protocolGraphRepository.loadInputRefPointerValues(
                            mapper=mapper,
                            projectId=projectId,
                            protocolDbId=protocolDbId,
                            inputName=paramName,
                        )

                        paramDict["readOnly"] = True

                        # PostgreSQL is authoritative,
                        # including an empty pointer list.
                        return paramDict, valueList

                    for pointer in protVar:
                        value = None

                        try:
                            targetObj = pointer.get()
                        except Exception:
                            targetObj = None

                        try:
                            objValue = pointer.getObjValue()
                        except Exception:
                            objValue = None

                        try:
                            extended = pointer.getExtended()
                        except Exception:
                            extended = None

                        if isinstance(targetObj, str):
                            value = targetObj

                        elif targetObj is not None:
                            try:
                                parentId = (
                                    objValue.getObjId()
                                    if objValue is not None
                                    else None
                                )
                            except Exception:
                                parentId = None

                            if parentId is None:
                                try:
                                    parentId = (
                                        targetObj
                                        .getObjParentId()
                                    )
                                except Exception:
                                    parentId = None

                            value = (
                                "%s.%s" % (
                                    parentId,
                                    extended,
                                )
                                if (
                                    parentId is not None
                                    and extended
                                )
                                else None
                            )

                        valueList.append(value)

                    paramValue = valueList
                    paramDict["readOnly"] = True

                elif isinstance(param, PointerParam):
                    parentId = None
                    paramValue = None
                    protocolDbId = None

                    if (
                            mapper is not None
                            and projectId is not None
                            and protocol is not None
                            and getScipionObjectIdCallback is not None
                            and resolvePostgresqlProtocolDbIdCallback is not None
                    ):
                        protocolId = getScipionObjectIdCallback(
                            protocol
                        )

                        if protocolId not in (None, ""):
                            protocolDbId = resolvePostgresqlProtocolDbIdCallback(
                                mapper=mapper,
                                projectId=projectId,
                                protocolId=protocolId,
                            )

                    if protocolDbId is not None:
                        protocolGraphRepository = (
                            ProtocolGraphRepository()
                        )

                        pointerValueInfo = (
                            protocolGraphRepository
                            .loadInputRefPointerValue(
                                mapper=mapper,
                                projectId=projectId,
                                protocolDbId=protocolDbId,
                                inputName=paramName,
                            )
                        )

                        paramDict["readOnly"] = True

                        if not pointerValueInfo:
                            return paramDict, None

                        parentId = pointerValueInfo.get(
                            "parentId"
                        )
                        paramValue = pointerValueInfo.get(
                            "value"
                        )

                        try:
                            paramDict["parentId"] = int(
                                parentId
                            )
                        except Exception:
                            paramDict["parentId"] = parentId

                        return paramDict, paramValue

                    try:
                        targetObj = (
                            protVar.get()
                            if protVar is not None
                            else None
                        )
                    except Exception:
                        targetObj = None

                    try:
                        objValue = (
                            protVar.getObjValue()
                            if protVar is not None
                            else None
                        )
                    except Exception:
                        objValue = None

                    try:
                        extended = (
                            protVar.getExtended()
                            if protVar is not None
                            else None
                        )
                    except Exception:
                        extended = None

                    if isinstance(targetObj, str):
                        # PostgreSQL runtime pointer can arrive
                        # as a raw value such as:
                        #   "1.outputTSMovies"
                        parentIdText, outputName = (
                            splitPointerValueCallback(
                                targetObj
                            )
                        )

                        if parentIdText:
                            try:
                                parentId = int(
                                    parentIdText
                                )
                            except Exception:
                                parentId = parentIdText

                        if outputName and not extended:
                            extended = outputName

                        paramValue = targetObj

                    elif targetObj is not None:
                        # Use the protocol ID stored by the Pointer
                        # before falling back to the output parent ID.
                        try:
                            parentId = (
                                objValue.getObjId()
                                if objValue is not None
                                else None
                            )
                        except Exception:
                            parentId = None

                        if parentId is None:
                            try:
                                parentId = (
                                    targetObj
                                    .getObjParentId()
                                )
                            except Exception:
                                parentId = None

                        paramValue = (
                            "%s.%s" % (
                                parentId,
                                extended,
                            )
                            if (
                                parentId is not None
                                and extended
                            )
                            else ""
                        )

                    elif objValue is not None:
                        try:
                            parentId = objValue.getObjId()
                        except Exception:
                            parentId = None

                        paramValue = (
                            "%s.%s" % (
                                parentId,
                                extended,
                            )
                            if (
                                parentId is not None
                                and extended
                            )
                            else ""
                        )

                    else:
                        paramValue = None

                    if parentId is not None:
                        paramDict["parentId"] = parentId

                    paramDict["readOnly"] = True

                elif allowsScalarPointers:
                    paramDict["pointerMode"] = False
                    protocolDbId = None
                    if (
                            mapper is not None
                            and projectId is not None
                            and protocol is not None
                            and getScipionObjectIdCallback is not None
                            and resolvePostgresqlProtocolDbIdCallback is not None
                    ):
                        protocolId = (
                            getScipionObjectIdCallback(
                                protocol
                            )
                        )
                        if protocolId not in (
                                None,
                                "",
                        ):
                            protocolDbId = (
                                resolvePostgresqlProtocolDbIdCallback(
                                    mapper=mapper,
                                    projectId=projectId,
                                    protocolId=protocolId,
                                )
                            )
                    if protocolDbId is not None:
                        pointerValueInfo = (
                            ProtocolGraphRepository()
                            .loadInputRefPointerValue(
                                mapper=mapper,
                                projectId=projectId,
                                protocolDbId=protocolDbId,
                                inputName=paramName,
                            )
                        )

                        if pointerValueInfo:
                            paramDict["pointerMode"] = True
                            parentId = (
                                pointerValueInfo.get(
                                    "parentId"
                                )
                            )
                            if parentId is not None:
                                try:
                                    paramDict["parentId"] = int(
                                        parentId
                                    )
                                except Exception:
                                    paramDict["parentId"] = (
                                        parentId
                                    )
                            return (
                                paramDict,
                                pointerValueInfo.get(
                                    "value"
                                ),
                            )
                    hasPointer = False
                    try:
                        hasPointer = bool(
                            protVar.hasPointer()
                        )
                    except Exception:
                        pass
                    if hasPointer:
                        pointer = (
                            protVar.getPointer()
                        )
                        paramDict["pointerMode"] = True
                        try:
                            paramValue = (
                                pointer.getUniqueId()
                            )
                        except Exception:
                            paramValue = None
                    else:
                        paramValue = (
                            protVar.get()
                            if protVar.get() is not None
                            else None
                        )

                elif allowsScalarPointers:
                    paramDict["pointerMode"] = False
                    protocolDbId = None
                    if (
                            mapper is not None
                            and projectId is not None
                            and protocol is not None
                            and getScipionObjectIdCallback is not None
                            and resolvePostgresqlProtocolDbIdCallback is not None
                    ):
                        protocolId = (
                            getScipionObjectIdCallback(
                                protocol
                            )
                        )
                        if protocolId not in (
                                None,
                                "",
                        ):
                            protocolDbId = (
                                resolvePostgresqlProtocolDbIdCallback(
                                    mapper=mapper,
                                    projectId=projectId,
                                    protocolId=protocolId,
                                )
                            )

                    if protocolDbId is not None:
                        pointerValueInfo = (
                            ProtocolGraphRepository()
                            .loadInputRefPointerValue(
                                mapper=mapper,
                                projectId=projectId,
                                protocolDbId=protocolDbId,
                                inputName=paramName,
                            )
                        )

                        if pointerValueInfo:
                            paramDict["pointerMode"] = True
                            parentId = (
                                pointerValueInfo.get(
                                    "parentId"
                                )
                            )

                            if parentId is not None:
                                try:
                                    paramDict["parentId"] = int(
                                        parentId
                                    )
                                except Exception:
                                    paramDict["parentId"] = (
                                        parentId
                                    )
                            return (
                                paramDict,
                                pointerValueInfo.get(
                                    "value"
                                ),
                            )
                    hasPointer = False
                    try:
                        hasPointer = bool(
                            protVar.hasPointer()
                        )

                    except Exception:
                        pass
                    if hasPointer:
                        pointer = (
                            protVar.getPointer()
                        )
                        paramDict["pointerMode"] = True
                        try:
                            paramValue = (
                                pointer.getUniqueId()
                            )
                        except Exception:
                            paramValue = None
                    else:
                        paramValue = (
                            protVar.get()
                            if protVar.get() is not None
                            else None
                        )
                else:
                    paramValue = (
                        protVar.get()
                        if protVar.get() is not None
                        else None
                    )

            return paramDict, paramValue

        except Exception:
            logger.error(
                "ERROR with param: " + paramName
            )
            raise

    def serializeProtocolSections(
            self,
            *,
            protocol,
            wizards,
            mapper,
            projectId,
            headerParams: List[str],
            runName,
            getScipionObjectIdCallback: Callable,
            resolvePostgresqlProtocolDbIdCallback: Callable,
            splitPointerValueCallback: Callable,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Serialize the protocol form sections and their current values."""
        paramsData = []
        paramsValue = {}

        def serializeFormParam(param, paramName, protVar):
            return self.serializeParam(
                param=param,
                paramName=paramName,
                wizards=wizards,
                viewerDict=None,
                visualize=0,
                protVar=protVar,
                mapper=mapper,
                projectId=projectId,
                protocol=protocol,
                getScipionObjectIdCallback=getScipionObjectIdCallback,
                resolvePostgresqlProtocolDbIdCallback=resolvePostgresqlProtocolDbIdCallback,
                splitPointerValueCallback=splitPointerValueCallback,
            )

        for section in protocol._definition.iterSections():
            sectionLabel = section.getLabel()

            if sectionLabel == "Parallelization":
                continue

            sectionData = {
                "label": sectionLabel,
                "params": [],
            }

            if sectionLabel != "General":
                for paramName, param in section.iterParams():
                    if paramName in headerParams:
                        continue

                    protVar = getattr(
                        protocol,
                        paramName,
                        None,
                    )

                    if protVar is None:
                        if isinstance(param, Group):
                            group, _ = serializeFormParam(
                                param,
                                paramName,
                                protVar,
                            )

                            if group is not None:
                                group["collapsed"] = False
                                group["params"] = []

                                for paramGroupName, paramGroup in param.iterParams():
                                    protVar = getattr(
                                        protocol,
                                        paramGroupName,
                                        None,
                                    )

                                    if isinstance(paramGroup, Line):
                                        for paramLineName, paramLine in paramGroup.iterParams():
                                            protVar = getattr(
                                                protocol,
                                                paramLineName,
                                                None,
                                            )

                                            if protVar:
                                                paramChild, paramValue = serializeFormParam(
                                                    paramLine,
                                                    paramLineName,
                                                    protVar,
                                                )

                                                if paramChild:
                                                    group["params"].append(
                                                        paramChild
                                                    )
                                                    paramsValue[paramLineName] = (
                                                        paramValue
                                                    )

                                    elif protVar:
                                        paramChild, paramValue = serializeFormParam(
                                            paramGroup,
                                            paramGroupName,
                                            protVar,
                                        )

                                        if paramChild:
                                            group["params"].append(
                                                paramChild
                                            )
                                            paramsValue[paramGroupName] = (
                                                paramValue
                                            )

                                if group:
                                    sectionData["params"].append(
                                        group
                                    )

                        elif isinstance(param, Line):
                            line, _ = serializeFormParam(
                                param,
                                paramName,
                                protVar,
                            )

                            if line is not None:
                                line["params"] = []

                                for paramLineName, paramLine in param.iterParams():
                                    protVar = getattr(
                                        protocol,
                                        paramLineName,
                                        None,
                                    )

                                    if protVar:
                                        paramChild, paramValue = serializeFormParam(
                                            paramLine,
                                            paramLineName,
                                            protVar,
                                        )

                                        if paramChild:
                                            line["params"].append(
                                                paramChild
                                            )
                                            paramsValue[paramLineName] = (
                                                paramValue
                                            )

                                if line:
                                    sectionData["params"].append(
                                        line
                                    )

                    else:
                        paramProcessed, paramValue = serializeFormParam(
                            param,
                            paramName,
                            protVar,
                        )

                        if paramProcessed:
                            sectionData["params"].append(
                                paramProcessed
                            )
                            paramsValue[paramName] = paramValue

            if sectionLabel == "General":
                for paramName in headerParams:
                    paramProcessed = {
                        "name": paramName,
                    }
                    paramValue = getattr(
                        protocol,
                        paramName,
                        None,
                    )

                    if paramName == "_objComment":
                        paramProcessed.setdefault(
                            paramName,
                            {},
                        )
                        paramProcessed["label"] = "Comment"
                        paramProcessed["expertLevel"] = 0
                        paramProcessed["condition"] = None
                        paramProcessed["_isImportant"] = True
                        paramProcessed["help"] = "Protocol comments"
                        paramProcessed["paramClass"] = "StringParam"
                        paramProcessed["default"] = ""
                        paramProcessed["readOnly"] = False
                        paramProcessed["hasWizard"] = False
                        paramProcessed["wizards"] = []
                        paramProcessed["wizard"] = None

                        sectionData["params"].append(
                            paramProcessed
                        )
                        paramsValue[paramName] = paramValue

                    elif paramName == "_useQueue":
                        paramProcessed["label"] = "Use a queue engine?"
                        paramProcessed["expertLevel"] = 0
                        paramProcessed["condition"] = None
                        paramProcessed["_isImportant"] = True
                        paramProcessed["help"] = (
                            pwutils.Message.HELP_USEQUEUE
                            % (
                                pyworkflow.Config.SCIPION_HOSTS,
                                pyworkflow.DOCSITEURLS.HOST_CONFIG,
                            )
                        )
                        paramProcessed["paramClass"] = "BooleanParam"
                        paramProcessed["default"] = False
                        paramProcessed["readOnly"] = False
                        paramProcessed["hasWizard"] = False
                        paramProcessed["wizards"] = []
                        paramProcessed["wizard"] = None

                        sectionData["params"].append(
                            paramProcessed
                        )
                        paramsValue[paramName] = paramValue.get()

                    elif paramName == "_prerequisites":
                        paramProcessed.setdefault(
                            paramName,
                            {},
                        )
                        paramProcessed["label"] = "Wait for"
                        paramProcessed["expertLevel"] = 0
                        paramProcessed["condition"] = None
                        paramProcessed["_isImportant"] = True
                        paramProcessed["help"] = (
                            pwutils.Message.HELP_WAIT_FOR
                            % pyworkflow.DOCSITEURLS.WAIT_FOR
                        )
                        paramProcessed["paramClass"] = "StringParam"
                        paramProcessed["default"] = []
                        paramProcessed["readOnly"] = False
                        paramProcessed["hasWizard"] = False
                        paramProcessed["wizards"] = []
                        paramProcessed["wizard"] = None

                        sectionData["params"].append(
                            paramProcessed
                        )
                        paramsValue[paramName] = paramValue

                    elif paramName == "expertLevel":
                        paramProcessed["label"] = "Expert Level"
                        paramProcessed["display"] = 0
                        paramProcessed["choices"] = [
                            "Normal",
                            "Advanced",
                        ]
                        paramProcessed["condition"] = None
                        paramProcessed["_isImportant"] = True
                        paramProcessed["paramClass"] = "EnumParam"
                        paramProcessed["default"] = 0
                        paramProcessed["readOnly"] = False
                        paramProcessed["hasWizard"] = False
                        paramProcessed["wizards"] = []
                        paramProcessed["wizard"] = None

                        sectionData["params"].append(
                            paramProcessed
                        )
                        paramsValue[paramName] = 0

                    elif paramName == "runMode":
                        paramProcessed["label"] = "Run Mode"
                        paramProcessed["display"] = 0
                        paramProcessed["choices"] = [
                            "Continue",
                            "Restart",
                        ]
                        paramProcessed["condition"] = None
                        paramProcessed["_isImportant"] = True
                        paramProcessed["paramClass"] = "EnumParam"
                        paramProcessed["default"] = 0
                        paramProcessed["readOnly"] = False
                        paramProcessed["hasWizard"] = False
                        paramProcessed["wizards"] = []
                        paramProcessed["wizard"] = None

                        sectionData["params"].append(
                            paramProcessed
                        )
                        paramsValue[paramName] = 0

                    else:
                        param = protocol.getParam(
                            paramName
                        )

                        if param is not None:
                            if paramName == "gpuList":
                                param.label.set("GPU IDs")
                                param.condition.set(None)

                            paramProcessed, paramValue = serializeFormParam(
                                param,
                                paramName,
                                None,
                            )

                            if paramProcessed:
                                if paramName == "runName":
                                    paramProcessed["default"] = ""
                                    paramValue = runName

                                elif paramName == "numberOfThreads":
                                    paramValue = (
                                        protocol.getScipionThreads()
                                    )

                                elif paramName == "gpuList":
                                    paramValue = (
                                        protocol.gpuList.get()
                                    )

                                elif paramName == "numberOfMpi":
                                    paramValue = protocol.getMPIs()

                                sectionData["params"].append(
                                    paramProcessed
                                )

                            paramsValue[paramName] = paramValue

            paramsData.append(sectionData)

        return paramsData, paramsValue

    def serializeProtocolInputs(
            self,
            *,
            protocol,
            mapper=None,
            projectId=None,
            getScipionObjectIdCallback: Callable = None,
            resolvePostgresqlProtocolDbIdCallback: Callable = None,
            splitPointerValueCallback: Callable,
    ) -> List[Dict[str, Any]]:
        """
        Serialize the protocol input attributes for the web context.

        This operation only reads pointer information. It does not modify
        protocols, parent protocols, outputs or persisted input references.
        """
        inputs = []
        protocolDbId = None

        if (
                mapper is not None
                and projectId is not None
                and getScipionObjectIdCallback is not None
                and resolvePostgresqlProtocolDbIdCallback is not None
        ):
            protocolId = getScipionObjectIdCallback(
                protocol
            )

            if protocolId not in (None, ""):
                protocolDbId = resolvePostgresqlProtocolDbIdCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                )

        if protocolDbId is not None:
            protocolGraphRepository = ProtocolGraphRepository()

            inputRefs = protocolGraphRepository.loadInputRefsForProtocolCopy(
                mapper=mapper,
                projectId=projectId,
                protocolDbId=protocolDbId,
            )

            for inputRef in inputRefs:
                inputName = str(
                    inputRef.get("inputName")
                    or ""
                ).strip()

                parentProtocolId = inputRef.get(
                    "parentProtocolId"
                )

                parentOutputName = str(
                    inputRef.get("parentOutputName")
                    or ""
                ).strip()

                if (
                        not inputName
                        or parentProtocolId in (None, "")
                        or not parentOutputName
                ):
                    continue

                try:
                    normalizedParentId = int(
                        parentProtocolId
                    )
                except Exception:
                    normalizedParentId = parentProtocolId

                pointerValue = "%s.%s" % (
                    normalizedParentId,
                    parentOutputName,
                )

                inputs.append({
                    "inputName": inputName,
                    "paramClass": "PointerParam",
                    "pointerClass": (
                        inputRef.get("objectClassName")
                        or ""
                    ),
                    "info": pointerValue,
                    "value": pointerValue,
                    "parentId": normalizedParentId,
                })

            # PostgreSQL is authoritative.
            # An empty list means the protocol has no inputs.
            return inputs

        for key, attr in protocol.iterInputAttributes():
            inputData = {
                "inputName": key,
                "paramClass": "PointerParam",
                "pointerClass": "",
                "info": "",
                "value": "",
                "parentId": None,
            }

            targetObj = None
            objValue = None
            extended = None

            try:
                targetObj = attr.get() if attr else None
            except Exception:
                targetObj = None

            try:
                objValue = attr.getObjValue() if attr else None
            except Exception:
                objValue = None

            try:
                extended = attr.getExtended() if attr else None
            except Exception:
                extended = None

            # PostgreSQL runtime can restore a pointer as a raw value:
            #   "1.outputTiltSeriesM"
            if isinstance(targetObj, str):
                rawValue = targetObj.strip()
                parentId, outputName = splitPointerValueCallback(rawValue)

                inputData["info"] = rawValue
                inputData["value"] = rawValue

                if parentId:
                    try:
                        inputData["parentId"] = int(parentId)
                    except Exception:
                        inputData["parentId"] = parentId

                if outputName and not extended:
                    extended = outputName

            elif targetObj is not None:
                getClassName = getattr(
                    targetObj,
                    "getClassName",
                    None,
                )

                if callable(getClassName):
                    try:
                        inputData["pointerClass"] = (
                            getClassName() or ""
                        )
                    except Exception:
                        inputData["pointerClass"] = ""

                try:
                    inputData["info"] = str(targetObj)
                except Exception:
                    inputData["info"] = ""

            if objValue is not None:
                getObjId = getattr(
                    objValue,
                    "getObjId",
                    None,
                )

                if callable(getObjId):
                    try:
                        parentObjId = getObjId()

                        if parentObjId is not None:
                            inputData["parentId"] = (
                                parentObjId
                            )

                    except Exception:
                        pass

            if not inputData["value"]:
                if (
                        inputData["parentId"] is not None
                        and extended
                ):
                    inputData["value"] = "%s.%s" % (
                        str(inputData["parentId"]),
                        str(extended),
                    )

                elif isinstance(targetObj, str):
                    inputData["value"] = targetObj

            inputs.append(inputData)

        return inputs

    def serializeProtocolOutputs(
            self,
            *,
            protocol,
            protocolName: str,
            persistedOutputs: Dict[
                str,
                Dict[str, Any],
            ] = None,
    ) -> List[Dict[str, Any]]:
        """
        Serialize protocol outputs for the web context.

        Runtime attributes are used when available. PostgreSQL
        metadata is authoritative for outputs that are not attached
        to the reconstructed protocol object.
        """
        outputs = []
        outputsByName = {}

        try:
            parentId = protocol.getObjId()
        except Exception:
            parentId = None

        for key, attr in (
                protocol.iterOutputAttributes()
        ):
            outputName = str(
                key
                or ""
            ).strip()

            if not outputName:
                continue

            outputData = {
                "outputName": outputName,
                "paramClass": "PointerParam",
                "pointerClass": (
                    attr.__class__.__name__
                ),
                "info": "",
                "value": (
                    f"{protocolName}."
                    f"{outputName}"
                ),
                "parentId": parentId,
            }

            try:
                outputData["info"] = str(
                    attr
                )
            except Exception:
                outputData["info"] = ""

            outputs.append(
                outputData
            )

            outputsByName[
                outputName
            ] = outputData

        for outputName, persistedOutput in sorted(
                (
                        persistedOutputs
                        or {}
                ).items()
        ):
            normalizedOutputName = str(
                outputName
                or ""
            ).strip()

            if not normalizedOutputName:
                continue

            existingOutput = (
                outputsByName.get(
                    normalizedOutputName
                )
            )

            persistedClassName = str(
                persistedOutput.get(
                    "className"
                )
                or persistedOutput.get(
                    "rootObjectClassName"
                )
                or ""
            )

            persistedInfo = str(
                persistedOutput.get(
                    "info"
                )
                or ""
            )

            if existingOutput is not None:
                if not existingOutput.get(
                        "pointerClass"
                ):
                    existingOutput[
                        "pointerClass"
                    ] = persistedClassName

                if not existingOutput.get(
                        "info"
                ):
                    existingOutput[
                        "info"
                    ] = persistedInfo

                continue

            outputData = {
                "outputName": (
                    normalizedOutputName
                ),
                "paramClass": (
                    "PointerParam"
                ),
                "pointerClass": (
                    persistedClassName
                ),
                "info": persistedInfo,
                "value": (
                    f"{protocolName}."
                    f"{normalizedOutputName}"
                ),
                "parentId": parentId,
            }

            outputs.append(
                outputData
            )

            outputsByName[
                normalizedOutputName
            ] = outputData

        return outputs
