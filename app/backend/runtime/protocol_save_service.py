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
            usesPostgresqlRuntimeCallback: Callable[[], bool],
            resolvePointerParentProtocolCallback: Callable,
            resolveParentOutputCallback: Callable,
            syncPostgresqlRuntimeProtocolInputsAndDependenciesCallback: Callable,
            syncProjectProtocolsAndDependenciesCallback: Callable,
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

        errorList.extend(
            self._applyScalarParams(
                protocol=protocol,
                params=params,
            )
        )

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

        usingPostgresqlRuntime = usesPostgresqlRuntimeCallback()

        if (
                errorList
                and usingPostgresqlRuntime
                and not setToSave
        ):
            logger.warning(
                "Blocking protocol execution because "
                "parameter application produced errors. "
                "projectId=%s protocolId=%s "
                "protocolClassName=%s errors=%s",
                projectId,
                getattr(
                    protocol,
                    "getObjId",
                    lambda: protocolId,
                )(),
                protocolClassName,
                errorList,
            )

            return protocol, errorList

        deferPersistenceToNativeLaunch = (
                usingPostgresqlRuntime
                and not setToSave
                and protocolId not in (None, "")
        )

        if deferPersistenceToNativeLaunch:
            logger.info(
                "Deferring existing PostgreSQL runtime protocol persistence "
                "to Scipion native launch. projectId=%s protocolId=%s",
                projectId,
                getattr(
                    protocol,
                    "getObjId",
                    lambda: protocolId,
                )(),
            )

        else:
            self._persistProtocolInScipion(
                currentProject=currentProject,
                protocol=protocol,
                protocolId=protocolId,
                projectId=projectId,
                protocolClassName=protocolClassName,
            )

        if usingPostgresqlRuntime:
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

        self._syncLegacyGraphAfterSaveIfNeeded(
            mapper=mapper,
            projectId=projectId,
            protocol=protocol,
            protocolId=protocolId,
            protocolClassName=protocolClassName,
            setToSave=setToSave,
            usingPostgresqlRuntime=usingPostgresqlRuntime,
            syncProjectProtocolsAndDependenciesCallback=(
                syncProjectProtocolsAndDependenciesCallback
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
    ) -> List[str]:
        errorList: List[str] = []

        for key, value in params.items():
            if key in self.nonFormParamNames:
                continue

            param = protocol.getParam(key)

            if param is None:
                logger.warning("[WARN] Param not found: %s", key)
                continue

            if isinstance(param, (PointerParam, MultiPointerParam, RelationParam)):
                continue

            try:
                castedValue = castProtocolParamValue(param, value)
                errors = param.validate(castedValue) if hasattr(param, "validate") else []

                if errors:
                    errorList += [
                        "**" + param.label.get() + "** " + error
                        for error in errors
                    ]

                protocol.setAttributeValue(
                    key,
                    castedValue,
                )

                if key == "runName":
                    protocol.runName.set(castedValue)

                logger.info("[INFO] Set param %s = %s", key, castedValue)

            except Exception as e:
                cleaned = re.sub(
                    r"[^A-Za-z0-9\s+\-*/=<>!&|^%()\[\]{}_,.;:]",
                    "",
                    str(e),
                )
                errorList.append("**" + param.label.get() + "** " + cleaned)

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

            if not isinstance(param, (PointerParam, MultiPointerParam, RelationParam)):
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
                Pointer(parentProtocol, extended=outputName)
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

        value = f"{parentScipionProtocolId}.{outputName}"
        pointer = getattr(protocol, inputName, None)

        if not isinstance(
                pointer,
                Pointer,
        ):
            pointer = Pointer(
                parentProtocol,
                extended=outputName,
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

    def _persistProtocolInScipion(
            self,
            *,
            currentProject,
            protocol,
            protocolId,
            projectId: int,
            protocolClassName: str,
    ) -> None:
        try:
            isNewProtocol = not protocolId

            if isNewProtocol:
                # Important in PostgreSQL runtime mode:
                # A new protocol can already have an objId assigned by the runtime mapper,
                # but that does not mean it exists as a root object in Scipion's legacy SQLite.
                # _setupProtocol is the correct path for new protocols.
                currentProject._setupProtocol(protocol)
            else:
                currentProject._storeProtocol(protocol)

        except Exception as e:
            logger.exception(
                "Failed to persist protocol in Scipion. projectId=%s protocolId=%s protocolClassName=%s",
                projectId,
                protocolId,
                protocolClassName,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to persist protocol in Scipion: {e}",
            )

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

    def _syncLegacyGraphAfterSaveIfNeeded(
            self,
            *,
            mapper,
            projectId: int,
            protocol,
            protocolId,
            protocolClassName: str,
            setToSave: bool,
            usingPostgresqlRuntime: bool,
            syncProjectProtocolsAndDependenciesCallback: Callable,
    ) -> None:
        if setToSave and not usingPostgresqlRuntime:
            try:
                syncProjectProtocolsAndDependenciesCallback(
                    mapper,
                    projectId,
                    refresh=True,
                    checkPid=True,
                )

            except Exception as e:
                logger.exception(
                    "Failed to sync protocol graph after save. projectId=%s protocolId=%s protocolClassName=%s",
                    projectId,
                    getattr(protocol, "getObjId", lambda: protocolId)(),
                    protocolClassName,
                )

                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Protocol was saved in Scipion but graph sync to PostgreSQL failed: {e}",
                )

        elif setToSave:
            logger.info(
                "Skipping legacy graph sync after PostgreSQL runtime save. "
                "projectId=%s protocolId=%s protocolClassName=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
                protocolClassName,
            )