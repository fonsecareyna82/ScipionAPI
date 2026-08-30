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
import re
from typing import Any, Callable, Dict, List, Tuple

from fastapi import HTTPException, status

from app.utils.protocol_param import castProtocolParamValue
from pyworkflow.object import Pointer, PointerList
from pyworkflow.protocol.params import PointerParam, MultiPointerParam, RelationParam

from app.backend.runtime.pointer_resolver import RuntimePointerResolver

logger = logging.getLogger(__name__)


class RuntimeProtocolSaveService:
    """
    Handles protocol save orchestration.

    This service receives callbacks from ProjectService to avoid circular imports
    while moving real save/pointer/persistence responsibility out of the god-service.
    """

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
    def _isScalarPointerPayload(value) -> bool:
        return (
            isinstance(value, dict)
            and value.get("pointerMode") is True
        )

    @staticmethod
    def _getScalarPayloadValue(value):
        if (
                isinstance(value, dict)
                and "pointerMode" in value
        ):
            return value.get("value")

        return value


    protectedParams = [
        "_objComment",
        "_useQueue",
        "_prerequisites",
        "gpuList",
        "numberOfThreads",
    ]

    nonFormParamNames = set(protectedParams) | {
        "expertLevel",
        "_scipionWebRuntime",
        "_queueName",
        "_queueParams",
    }

    def saveProtocol(
            self,
            *,
            mapper,
            projectId: int,
            protocolId,
            protocolClassName: str,
            params: Dict[str, Any],
            setToSave: bool,
            currentProject,
            getScipionProtocolForRuntimeCallback: Callable,
            resolvePointerParentProtocolCallback: Callable,
            resolveParentOutputCallback: Callable,
            syncPostgresqlRuntimeProtocolInputsAndDependenciesCallback: Callable,
            validateParams: bool = True,
    ) -> Tuple[Any, List[str]]:
        params = params or {}
        errorList: List[str] = []

        if currentProject is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Protocol runtime project context is not loaded. "
                    "PostgreSQL protocol mutations must load a "
                    "PostgresqlProject before saving."
                ),
            )

        protocol = self._createOrLoadProtocol(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            protocolClassName=protocolClassName,
            currentProject=currentProject,
            getScipionProtocolForRuntimeCallback=getScipionProtocolForRuntimeCallback,
        )

        self._applyProtectedParams(
            protocol=protocol,
            params=params,
        )

        errorList.extend(self._applyScalarParams(protocol=protocol,
                                                 params=params,
                                                 validateParams=validateParams))

        errorList.extend(
            self.applyPointerParamsToProtocol(
                mapper=mapper,
                projectId=projectId,
                protocol=protocol,
                params=params,
                resolvePointerParentProtocolCallback=resolvePointerParentProtocolCallback,
                resolveParentOutputCallback=resolveParentOutputCallback,
            )
        )

        if errorList and not setToSave:
            logger.warning(
                "Blocking protocol execution because parameter application produced errors. "
                "projectId=%s protocolId=%s protocolClassName=%s errors=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
                protocolClassName,
                errorList,
            )

            return protocol, errorList

        deferPersistenceToNativeLaunch = (
                not setToSave
                and protocolId not in (None, "")
        )

        if deferPersistenceToNativeLaunch:
            logger.info(
                "Deferring existing PostgreSQL runtime protocol persistence "
                "to Scipion native launch. projectId=%s protocolId=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
            )

        else:
            self._persistProtocolInRuntime(
                currentProject=currentProject,
                protocol=protocol,
                protocolId=protocolId,
                projectId=projectId,
                protocolClassName=protocolClassName,
            )

        self._syncPostgresqlRuntimeInputsAndDependencies(
            mapper=mapper,
            projectId=projectId,
            protocol=protocol,
            protocolId=protocolId,
            params=params,
            syncPostgresqlRuntimeProtocolInputsAndDependenciesCallback=(
                syncPostgresqlRuntimeProtocolInputsAndDependenciesCallback
            ),
        )

        return protocol, errorList

    def _createOrLoadProtocol(
            self,
            *,
            mapper,
            projectId: int,
            protocolId,
            protocolClassName: str,
            currentProject,
            getScipionProtocolForRuntimeCallback: Callable,
    ):
        if not protocolId:
            protClass = currentProject.getDomain().getProtocols().get(protocolClassName)

            if protClass is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Protocol class not found: {protocolClassName}",
                )

            return currentProject.newProtocol(protClass)

        return getScipionProtocolForRuntimeCallback(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

    def _applyProtectedParams(
            self,
            *,
            protocol,
            params: Dict[str, Any],
    ) -> None:
        for paramName in self.protectedParams:
            protVar = getattr(protocol, paramName, None)

            if protVar is None or paramName not in params:
                continue

            value = params[paramName]

            try:
                protVar.set(value)
            except Exception:
                setattr(protocol, paramName, value)

    def _applyScalarParams(
            self,
            *,
            protocol,
            params: Dict[str, Any],
            validateParams: bool = True
    ) -> List[str]:
        errorList: List[str] = []

        for key, value in params.items():
            if key in self.nonFormParamNames:
                continue

            param = protocol.getParam(key)

            if param is None:
                logger.warning(
                    "[WARN] Param not found: %s",
                    key,
                )
                continue

            if isinstance(
                    param,
                    (
                            PointerParam,
                            MultiPointerParam,
                            RelationParam,
                    ),
            ):
                continue

            allowsScalarPointers = (
                self._allowsScalarPointers(
                    param
                )
            )

            if (
                    allowsScalarPointers
                    and self._isScalarPointerPayload(
                value
            )
            ):
                continue

            try:
                rawValue = (
                    self._getScalarPayloadValue(
                        value
                    )
                    if allowsScalarPointers
                    else value
                )

                castedValue = (
                    castProtocolParamValue(
                        param,
                        rawValue,
                    )
                )

                errors = (
                    param.validate(
                        castedValue
                    )
                    if (
                            validateParams
                            and hasattr(
                        param,
                        "validate",
                    )
                    )
                    else []
                )

                if errors:
                    errorList += [
                        "**"
                        + param.label.get()
                        + "** "
                        + error
                        for error in errors
                    ]

                if allowsScalarPointers:
                    protVar = getattr(
                        protocol,
                        key,
                        None,
                    )

                    setPointer = getattr(
                        protVar,
                        "setPointer",
                        None,
                    )

                    if callable(setPointer):
                        setPointer(None)

                protocol.setAttributeValue(
                    key,
                    castedValue,
                )

                if key == "runName":
                    protocol.runName.set(
                        castedValue
                    )

                logger.info(
                    "[INFO] Set param %s = %s",
                    key,
                    castedValue,
                )

            except Exception as e:
                cleaned = re.sub(
                    r"[^A-Za-z0-9\s+\-*/=<>!&|^%()\[\]{}_,.;:]",
                    "",
                    str(e),
                )

                errorList.append(
                    "**"
                    + param.label.get()
                    + "** "
                    + cleaned
                )

        return errorList

    def applyPointerParamsToProtocol(
            self,
            *,
            mapper,
            projectId: int,
            protocol,
            params: Dict[str, Any],
            resolvePointerParentProtocolCallback: Callable,
            resolveParentOutputCallback: Callable,
    ) -> List[str]:
        errorList: List[str] = []
        pointerResolver = RuntimePointerResolver()

        for key, value in params.items():
            param = protocol.getParam(key)

            if param is None:
                continue

            scalarPointer = (
                    self._allowsScalarPointers(param)
                    and self._isScalarPointerPayload(
                value
            )
            )

            if (
                    not isinstance(
                        param,
                        (
                                PointerParam,
                                MultiPointerParam,
                                RelationParam,
                        ),
                    )
                    and not scalarPointer
            ):
                continue

            if isinstance(param, MultiPointerParam):
                errorList.extend(
                    self._applyMultiPointerParam(
                        mapper=mapper,
                        projectId=projectId,
                        protocol=protocol,
                        inputName=key,
                        rawValue=value,
                        param=param,
                        pointerResolver=pointerResolver,
                        resolvePointerParentProtocolCallback=resolvePointerParentProtocolCallback,
                        resolveParentOutputCallback=resolveParentOutputCallback,
                    )
                )

            elif isinstance(param, PointerParam):
                errorList.extend(
                    self._applyPointerParam(
                        mapper=mapper,
                        projectId=projectId,
                        protocol=protocol,
                        inputName=key,
                        rawValue=value,
                        param=param,
                        pointerResolver=pointerResolver,
                        resolvePointerParentProtocolCallback=resolvePointerParentProtocolCallback,
                        resolveParentOutputCallback=resolveParentOutputCallback,
                    )
                )

            elif scalarPointer:
                errorList.extend(
                    self._applyScalarPointerParam(
                        mapper=mapper,
                        projectId=projectId,
                        protocol=protocol,
                        inputName=key,
                        rawValue=value,
                        param=param,
                        pointerResolver=pointerResolver,
                        resolvePointerParentProtocolCallback=(
                            resolvePointerParentProtocolCallback
                        ),
                        resolveParentOutputCallback=(
                            resolveParentOutputCallback
                        ),
                    )
                )

        return errorList

    def _applyScalarPointerParam(
            self,
            *,
            mapper,
            projectId: int,
            protocol,
            inputName: str,
            rawValue,
            param,
            pointerResolver: RuntimePointerResolver,
            resolvePointerParentProtocolCallback: Callable,
            resolveParentOutputCallback: Callable,
    ) -> List[str]:
        errorList: List[str] = []

        pointerValues = (
            pointerResolver
            .completePointerValuesFromInputRefs(
                mapper=mapper,
                projectId=projectId,
                protocol=protocol,
                inputName=inputName,
                rawValue=rawValue,
            )
        )

        pointerValues = (
            pointerResolver
            .filterEmptyPointerValues(
                pointerValues
            )
        )

        if not pointerValues:
            errorList.append(
                "**"
                + param.label.get()
                + "** pointer value is empty."
            )
            return errorList

        resolvedPointerTarget = (
            pointerResolver
            .resolvePointerTarget(
                mapper=mapper,
                projectId=projectId,
                pointerValue=pointerValues[0],
                paramLabel=param.label.get(),
                getParentProtocolCallback=(
                    resolvePointerParentProtocolCallback
                ),
                resolveParentOutputCallback=(
                    resolveParentOutputCallback
                ),
            )
        )

        if not resolvedPointerTarget.get("ok"):
            errorList.append(
                resolvedPointerTarget.get("error")
            )
            return errorList

        parentProtocol = resolvedPointerTarget.get(
            "parentProtocol"
        )

        outputName = resolvedPointerTarget.get(
            "outputName"
        )

        resolvedOutput = (
                resolvedPointerTarget.get(
                    "resolvedOutput"
                )
                or {}
        )

        if not outputName:
            errorList.append(
                "**"
                + param.label.get()
                + "** scalar pointer must reference a protocol output."
            )
            return errorList

        protVar = getattr(
            protocol,
            inputName,
            None,
        )

        setValue = getattr(
            protVar,
            "set",
            None,
        )

        setPointer = getattr(
            protVar,
            "setPointer",
            None,
        )

        if (
                not callable(setValue)
                or not callable(setPointer)
        ):
            errorList.append(
                "**"
                + param.label.get()
                + "** runtime scalar does not support pointer restoration."
            )
            return errorList

        pointer = Pointer(
            parentProtocol,
            extended=outputName,
        )

        pointedValue = None

        try:
            pointedValue = pointer.get()
        except Exception:
            pass

        if pointedValue is not None:
            valueGetter = getattr(
                pointedValue,
                "get",
                None,
            )

            scalarValue = (
                valueGetter()
                if callable(valueGetter)
                else pointedValue
            )

            setValue(
                scalarValue
            )

            setPointer(
                pointer
            )

        else:
            outputInfo = (
                    resolvedOutput.get(
                        "outputInfo"
                    )
                    or {}
            )

            if (
                    outputInfo.get("kind")
                    != "object"
                    or "value" not in outputInfo
            ):
                errorList.append(
                    "**"
                    + param.label.get()
                    + "** could not resolve scalar value from pointer "
                    + str(pointerValues[0])
                    + "."
                )
                return errorList

            setValue(
                outputInfo.get(
                    "value"
                )
            )

            # The parent runtime protocol does not expose the
            # output attribute. Keep the scalar value usable and
            # let protocol_input_refs restore the real pointer
            # before validation/execution.
            setPointer(None)

        logger.info(
            "[INFO] Scalar param %s set from pointer %s with value %s",
            inputName,
            pointerValues[0],
            protVar.getObjValue(),
        )

        return errorList

    def _applyMultiPointerParam(
            self,
            *,
            mapper,
            projectId: int,
            protocol,
            inputName: str,
            rawValue,
            param,
            pointerResolver: RuntimePointerResolver,
            resolvePointerParentProtocolCallback: Callable,
            resolveParentOutputCallback: Callable,
    ) -> List[str]:
        errorList: List[str] = []
        newInputs = PointerList()

        pointerValues = pointerResolver.completePointerValuesFromInputRefs(
            mapper=mapper,
            projectId=projectId,
            protocol=protocol,
            inputName=inputName,
            rawValue=rawValue,
        )

        pointerValues = pointerResolver.filterEmptyPointerValues(pointerValues)

        if not pointerValues:
            logger.info(
                "Skipping empty multipointer param without clearing existing value. "
                "projectId=%s protocolId=%s inputName=%s value=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: None)(),
                inputName,
                rawValue,
            )
            return errorList

        for pointerValue in pointerValues:
            resolvedPointerTarget = pointerResolver.resolvePointerTarget(
                mapper=mapper,
                projectId=projectId,
                pointerValue=pointerValue,
                paramLabel=param.label.get(),
                getParentProtocolCallback=resolvePointerParentProtocolCallback,
                resolveParentOutputCallback=resolveParentOutputCallback,
            )

            if not resolvedPointerTarget.get("ok"):
                errorList.append(resolvedPointerTarget.get("error"))
                continue

            parentScipionProtocolId = resolvedPointerTarget.get("parentScipionProtocolId")
            parentProtocol = resolvedPointerTarget.get("parentProtocol")
            outputName = resolvedPointerTarget.get("outputName")
            resolvedOutput = resolvedPointerTarget.get("resolvedOutput") or {}

            newInputs.append(
                Pointer(
                    parentProtocol,
                    extended=outputName,
                )
                if outputName
                else Pointer(
                    parentProtocol
                )
            )

            logger.debug(
                "MultiPointer param %s set from parent %s output %s source=%s hasRuntimeAttribute=%s",
                inputName,
                parentScipionProtocolId,
                outputName,
                resolvedOutput.get("source"),
                resolvedOutput.get("hasRuntimeAttribute"),
            )

            logger.info(
                "[INFO] MultiPointer param %s set from parent %s output %s",
                inputName,
                parentScipionProtocolId,
                outputName,
            )

        if newInputs.isEmpty() and not param.allowsNull.get():
            errorList.append("**" + param.label.get() + "** it must not be empty.")

        setattr(
            protocol,
            inputName,
            newInputs,
        )

        return errorList

    def _applyPointerParam(
            self,
            *,
            mapper,
            projectId: int,
            protocol,
            inputName: str,
            rawValue,
            param,
            pointerResolver: RuntimePointerResolver,
            resolvePointerParentProtocolCallback: Callable,
            resolveParentOutputCallback: Callable,
    ) -> List[str]:
        errorList: List[str] = []

        pointerValues = pointerResolver.completePointerValuesFromInputRefs(
            mapper=mapper,
            projectId=projectId,
            protocol=protocol,
            inputName=inputName,
            rawValue=rawValue,
        )

        pointerValues = pointerResolver.filterEmptyPointerValues(pointerValues)

        # Important:
        # If the frontend sends an empty pointer for an existing protocol,
        # do NOT clear the current protocol attribute. This is common when launching
        # duplicated protocols: the real pointer is already restored/copied from
        # protocol_input_refs.
        if not pointerValues:
            logger.info(
                "Skipping empty pointer param without clearing existing value. "
                "projectId=%s protocolId=%s inputName=%s value=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: None)(),
                inputName,
                rawValue,
            )
            return errorList

        pointerValue = pointerValues[0]

        resolvedPointerTarget = pointerResolver.resolvePointerTarget(
            mapper=mapper,
            projectId=projectId,
            pointerValue=pointerValue,
            paramLabel=param.label.get(),
            getParentProtocolCallback=resolvePointerParentProtocolCallback,
            resolveParentOutputCallback=resolveParentOutputCallback,
        )

        if not resolvedPointerTarget.get("ok"):
            errorList.append(resolvedPointerTarget.get("error"))
            return errorList

        parentScipionProtocolId = resolvedPointerTarget.get("parentScipionProtocolId")
        parentProtocol = resolvedPointerTarget.get("parentProtocol")
        outputName = resolvedPointerTarget.get("outputName")
        resolvedOutput = resolvedPointerTarget.get("resolvedOutput") or {}

        value = (
            f"{parentScipionProtocolId}.{outputName}"
            if outputName
            else str(parentScipionProtocolId)
        )
        pointer = getattr(protocol, inputName, None)

        if not isinstance(
                pointer,
                Pointer,
        ):
            pointer = (
                Pointer(
                    parentProtocol,
                    extended=outputName,
                )
                if outputName
                else Pointer(
                    parentProtocol
                )
            )

            setattr(
                protocol,
                inputName,
                pointer,
            )

        else:
            pointer.set(
                parentProtocol
            )

            pointer.setExtended(
                outputName
            )

        # Keep the form/default textual representation if available,
        # but do not call param.set(value), because that stores the input as string.
        try:
            param.default.set(value)
        except Exception:
            pass

        logger.debug(
            "Pointer param %s set. childProtocol=%s parentProtocol=%s output=%s "
            "source=%s hasRuntimeAttribute=%s pointer=%s pointerObj=%s extended=%s targetObjId=%s target=%s",
            inputName,
            getattr(protocol, "getObjId", lambda: None)(),
            parentScipionProtocolId,
            outputName,
            resolvedOutput.get("source"),
            resolvedOutput.get("hasRuntimeAttribute"),
            pointer,
            getattr(pointer, "getObjValue", lambda: None)() if pointer is not None else None,
            getattr(pointer, "getExtended", lambda: None)() if pointer is not None else None,
            getattr(
                getattr(pointer, "getObjValue", lambda: None)(),
                "getObjId",
                lambda: None,
            )() if pointer is not None else None,
            getattr(pointer, "get", lambda: None)() if pointer is not None else None,
        )

        return errorList

    def _persistProtocolInRuntime(
            self,
            *,
            currentProject,
            protocol,
            protocolId,
            projectId: int,
            protocolClassName: str,
    ) -> None:
        try:
            isNewProtocol = protocolId in (None, "")

            if isNewProtocol:
                currentProject._setupProtocol(protocol)
            else:
                currentProject._storeProtocol(protocol)

        except Exception as error:
            logger.exception(
                "Failed to persist PostgreSQL runtime protocol. "
                "projectId=%s protocolId=%s protocolClassName=%s",
                projectId,
                protocolId,
                protocolClassName,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to persist PostgreSQL runtime protocol: %s" % error,
            ) from error

    def _syncPostgresqlRuntimeInputsAndDependencies(
            self,
            *,
            mapper,
            projectId: int,
            protocol,
            protocolId,
            params: Dict[str, Any],
            syncPostgresqlRuntimeProtocolInputsAndDependenciesCallback: Callable,
    ) -> None:
        try:
            dependencySync = syncPostgresqlRuntimeProtocolInputsAndDependenciesCallback(
                mapper=mapper,
                projectId=projectId,
                protocol=protocol,
                params=params,
            )

            logger.info(
                "Synced PostgreSQL runtime protocol inputs/dependencies after save. "
                "projectId=%s protocolId=%s sync=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
                dependencySync,
            )

        except Exception as e:
            logger.exception(
                "Failed to sync PostgreSQL runtime protocol inputs/dependencies after save. "
                "projectId=%s protocolId=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to sync PostgreSQL runtime protocol dependencies after save: {e}",
            )

