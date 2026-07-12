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
from typing import Any, Callable, Dict, List

from pyworkflow.object import CsvList
from pyworkflow.protocol import (
    MultiPointerParam,
    PointerParam,
    RelationParam,
)
from pyworkflow.protocol.params import (
    BooleanParam,
    EnumParam,
    FloatParam,
    IntParam,
    StringParam,
)

from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)
from app.utils.scipion_helper import serializeToJson


logger = logging.getLogger(__name__)


class ProtocolFormSerializer:
    """Serialize Scipion protocol parameters for the web form."""

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
            usingPostgresqlRuntime: bool,
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

            if protVar is not None:
                if isinstance(param, MultiPointerParam):
                    valueList = []

                    if (
                            mapper is not None
                            and projectId is not None
                            and protocol is not None
                            and usingPostgresqlRuntime
                    ):
                        protocolId = (
                            getScipionObjectIdCallback(
                                protocol
                            )
                        )

                        protocolDbId = (
                            resolvePostgresqlProtocolDbIdCallback(
                                mapper=mapper,
                                projectId=projectId,
                                protocolId=protocolId,
                            )
                        )

                        if protocolDbId is not None:
                            protocolGraphRepository = (
                                ProtocolGraphRepository()
                            )

                            valueList = (
                                protocolGraphRepository
                                .loadInputRefPointerValues(
                                    mapper=mapper,
                                    projectId=projectId,
                                    protocolDbId=protocolDbId,
                                    inputName=paramName,
                                )
                            )

                            if valueList:
                                paramDict["readOnly"] = True

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
                            and usingPostgresqlRuntime
                    ):
                        protocolId = (
                            getScipionObjectIdCallback(
                                protocol
                            )
                        )

                        protocolDbId = (
                            resolvePostgresqlProtocolDbIdCallback(
                                mapper=mapper,
                                projectId=projectId,
                                protocolId=protocolId,
                            )
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

                        if pointerValueInfo:
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
                                paramDict["parentId"] = (
                                    parentId
                                )

                            paramDict["readOnly"] = True

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

    def serializeProtocolInputs(
            self,
            *,
            protocol,
            splitPointerValueCallback: Callable,
    ) -> List[Dict[str, Any]]:
        """
        Serialize the protocol input attributes for the web context.

        This operation only reads pointer information. It does not modify
        protocols, parent protocols, outputs or persisted input references.
        """
        inputs = []

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
    ) -> List[Dict[str, Any]]:
        """Serialize the protocol output attributes for the web context."""
        outputs = []

        for key, attr in protocol.iterOutputAttributes():
            outputData = {
                "outputName": key,
                "paramClass": "PointerParam",
                "pointerClass": attr.__class__.__name__,
                "info": "",
                "value": f"{protocolName}.{key}",
                "parentId": protocol.getObjId(),
            }

            try:
                outputData["info"] = str(attr)
            except Exception:
                outputData["info"] = ""

            outputs.append(outputData)

        return outputs

    @staticmethod
    def castParamValue(param, rawValue):
        """Cast a raw form value to its Scipion parameter type."""
        if isinstance(param, EnumParam):
            if isinstance(rawValue, int):
                return rawValue

            try:
                return param.choices.index(
                    str(rawValue)
                )

            except ValueError:
                for index, choice in enumerate(
                        param.choices
                ):
                    if (
                            str(choice).lower()
                            == str(rawValue).lower()
                    ):
                        return index

                return 0

        elif isinstance(param, IntParam):
            return (
                int(rawValue)
                if rawValue not in (None, "")
                else None
            )

        elif isinstance(param, FloatParam):
            return (
                float(rawValue)
                if rawValue not in (None, "")
                else None
            )

        elif isinstance(param, BooleanParam):
            return str(rawValue).lower() in (
                "true",
                "1",
                "yes",
                "y",
            )

        elif isinstance(
                param,
                (StringParam, EnumParam),
        ):
            return (
                str(rawValue)
                if rawValue is not None
                else None
            )

        elif isinstance(param, CsvList):
            return [rawValue]

        return rawValue