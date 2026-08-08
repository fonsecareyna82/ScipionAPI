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
import copy
import logging
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException, status

from pyworkflow.protocol.params import (
    MultiPointerParam,
    PointerParam,
    RelationParam,
)
from pyworkflow.object import Pointer, PointerList
from pyworkflow.protocol import MODE_RESTART
from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository
from app.backend.runtime.protocol_identity import ProtocolIdentityResolver
from app.backend.runtime.pointer_resolver import RuntimePointerResolver

logger = logging.getLogger(__name__)


class RuntimeProtocolDuplicateState:
    """Mutable state collected while duplicating PostgreSQL runtime protocols."""

    def __init__(self):
        self.duplicated: List[Dict[str, Any]] = []
        self.syncReports: List[Dict[str, Any]] = []
        self.dependenciesCount: int = 0
        self.duplicatedItems: List[Dict[str, Any]] = []
        self.sourceToDuplicatedProtocolId: Dict[str, str] = {}
        self.sourceDbToDuplicatedDbId: Dict[int, int] = {}


class RuntimeProtocolDuplicateService:
    """Runtime helpers for PostgreSQL protocol duplication."""

    runtimeParamKeysToDrop = (
        "status",
        "initTime",
        "endTime",
        "_error",
        "_resultFiles",
        "_outputs",
        "_useOutputList",
        "_jobId",
        "_pid",
        "_stepsDone",
        "_cpuTime",
        "_numberOfSteps",
        "lastUpdateTimeStamp",
    )

    def createDuplicateState(self) -> RuntimeProtocolDuplicateState:
        return RuntimeProtocolDuplicateState()

    def duplicatePostgresqlRuntimeProtocols(
            self,
            *,
            mapper,
            projectId: int,
            protocols,
            getScipionProtocolForRuntimeCallback: Callable,
            getScipionProtocolByRuntimeIdCallback: Callable,
            getScipionObjectIdCallback: Callable,
            saveProtocolCallback: Callable,
            syncPostgresqlRuntimeProtocolCallback: Callable,
            storeProtocolCallback: Callable,
            buildProtocolMutationResultCallback: Callable,
    ):
        duplicateState = self.createDuplicateState()

        # ------------------------------------------------------------------
        # Phase 1: resolve all source protocols and create all duplicated
        # protocol rows, without copying refs yet.
        # ------------------------------------------------------------------
        protocolGraphRepository = ProtocolGraphRepository()

        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        for item in protocols or []:
            sourceProtocolId = getattr(item, "id", None)

            if sourceProtocolId is None:
                continue

            sourceProtocol = getScipionProtocolForRuntimeCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=sourceProtocolId,
            )

            sourceScipionProtocolId = getScipionObjectIdCallback(sourceProtocol)

            sourceProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
                sourceScipionProtocolId
            )

            if sourceProtocolDbId is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Source protocol %s was not found in PostgreSQL" % sourceProtocolId,
                )

            sourceRow = protocolGraphRepository.getProtocolRuntimeInfoByDbId(
                mapper=mapper,
                projectId=projectId,
                protocolDbId=sourceProtocolDbId,
            )

            if not sourceRow:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Source protocol row was not found: %s"
                           % sourceProtocolId,
                )
            # The source protocol and its PostgreSQL graph are strictly
            # read-only during duplication. Input refs and dependencies
            # are copied from their persisted PostgreSQL snapshot below.

            protocolClassName = sourceRow.get(
                "protocolClassName"
            )
            sourceParams = sourceRow.get("params") or {}

            params = self.buildDuplicatedProtocolParams(
                sourceProtocol=sourceProtocol,
                sourceParams=sourceParams,
            )

            newProtocol, saveErrors = saveProtocolCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=None,
                protocolClassName=protocolClassName,
                params=params,
                setToSave=False,
            )

            if saveErrors:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=saveErrors,
                )

            newProtocol.setSaved()
            newProtocol.runMode.set(MODE_RESTART)
            duplicatedProtocolId = getScipionObjectIdCallback(newProtocol)

            duplicatedProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
                duplicatedProtocolId
            )

            if duplicatedProtocolDbId is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Duplicated protocol %s was not found in PostgreSQL" % duplicatedProtocolId,
                )

            self.registerDuplicatedProtocol(
                state=duplicateState,
                sourceScipionProtocolId=sourceScipionProtocolId,
                sourceProtocolDbId=sourceProtocolDbId,
                duplicatedProtocol=newProtocol,
                duplicatedProtocolId=duplicatedProtocolId,
                duplicatedProtocolDbId=duplicatedProtocolDbId,
            )

        if not self.hasDuplicatedProtocols(duplicateState):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No valid protocols to duplicate",
            )

        # ------------------------------------------------------------------
        # Phase 2: copy refs/dependencies using the full old -> new map.
        # ------------------------------------------------------------------
        for item in duplicateState.duplicatedItems:
            syncContext = self.buildDuplicatedProtocolSyncContext(item)

            newProtocol = syncContext["duplicatedProtocol"]
            sourceScipionProtocolId = syncContext["sourceScipionProtocolId"]
            duplicatedProtocolId = syncContext["duplicatedProtocolId"]

            try:
                protocolSync = syncPostgresqlRuntimeProtocolCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=duplicatedProtocolId,
                    registerOutputs=False,
                    syncRelations=False,
                    protocol=newProtocol,
                )

                dependencySync = self.copyPostgresqlInputRefsForDuplicatedProtocol(
                    state=duplicateState,
                    mapper=mapper,
                    projectId=projectId,
                    sourceProtocolId=sourceScipionProtocolId,
                    duplicatedProtocolId=duplicatedProtocolId,
                )

                logger.info(
                    "Copied PostgreSQL input refs for duplicated protocol. projectId=%s report=%s",
                    projectId,
                    dependencySync,
                )

                pointerRestore = self.restorePostgresqlPointerInputsBeforeCopy(
                    mapper=mapper,
                    projectId=projectId,
                    protocol=newProtocol,
                    getScipionProtocolByRuntimeIdCallback=getScipionProtocolByRuntimeIdCallback,
                )

                if pointerRestore.get("errors"):
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to restore duplicated protocol pointers: %s"
                               % pointerRestore.get("errors"),
                    )

                storeProtocolCallback(newProtocol)

                self.registerDuplicatedProtocolSyncReport(
                    state=duplicateState,
                    sourceScipionProtocolId=sourceScipionProtocolId,
                    duplicatedProtocolId=duplicatedProtocolId,
                    protocolSync=protocolSync,
                    dependencySync=dependencySync,
                    pointerRestore=pointerRestore,
                )

            except HTTPException:
                raise

            except Exception as e:
                logger.exception(
                    "Failed to sync duplicated PostgreSQL runtime protocol. "
                    "projectId=%s sourceProtocolId=%s duplicatedProtocolId=%s",
                    projectId,
                    sourceScipionProtocolId,
                    duplicatedProtocolId,
                )

                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(
                            "Protocol was duplicated but PostgreSQL runtime sync failed: %s"
                            % e
                    ),
                )

        resultPayload = self.buildPostgresqlRuntimeDuplicateResultPayload(
            state=duplicateState,
        )

        return buildProtocolMutationResultCallback(
            "Protocol was duplicated successfully",
            **resultPayload,
        )

    @staticmethod
    def _getScipionObjectId(obj) -> Optional[int]:
        for getterName in ("getObjId", "getId"):
            getter = getattr(obj, getterName, None)

            if not callable(getter):
                continue

            try:
                value = getter()
            except Exception:
                continue

            if value is None:
                continue

            try:
                return int(value)
            except Exception:
                continue

        return None

    def sanitizeProtocolPointerTargetsForPersistence(
            self,
            protocol,
    ) -> Dict[str, Any]:
        """
        Clear textual Pointer placeholders before rebuilding persisted inputs.
        PostgreSQL snapshots may temporarily expose pointer values as strings
        such as:
            8.outputTiltSeries
        These placeholders must be cleared before restoring the real Scipion
        object targets from protocol_input_refs.
        """
        cleared = []
        errors = []
        visited = set()

        def visit(obj, path=""):
            if obj is None:
                return

            objectIdentity = id(obj)

            if objectIdentity in visited:
                return

            visited.add(objectIdentity)

            try:
                attributes = list(
                    obj.getAttributesToStore()
                )
            except Exception:
                attributes = []

            for attributeName, attribute in attributes:
                if attribute is None:
                    continue

                attributePath = (
                    "%s.%s" % (path, attributeName)
                    if path
                    else str(attributeName)
                )

                try:
                    isPointer = bool(
                        attribute.isPointer()
                    )
                except Exception:
                    isPointer = False

                if isPointer:
                    try:
                        pointerValue = (
                            attribute.getObjValue()
                        )
                    except Exception as error:
                        errors.append({
                            "path": attributePath,
                            "error": str(error),
                        })
                        continue

                    if isinstance(pointerValue, str):
                        try:
                            attribute.set(None)

                            cleared.append({
                                "path": attributePath,
                                "value": pointerValue,
                            })

                        except Exception as error:
                            errors.append({
                                "path": attributePath,
                                "value": pointerValue,
                                "error": str(error),
                            })

                    continue

                visit(
                    attribute,
                    attributePath,
                )

        visit(protocol)

        return {
            "cleared": cleared,
            "errors": errors,
        }

    def validateProtocolPointerTargetsForPersistence(
            self,
            protocol,
    ) -> Dict[str, Any]:
        """
        Verify that every non-empty Pointer target is a Scipion object.
        This validation must run before the duplicated protocol is persisted.
        """
        errors = []
        visited = set()

        def visit(obj, path=""):
            if obj is None:
                return

            objectIdentity = id(obj)

            if objectIdentity in visited:
                return

            visited.add(objectIdentity)

            try:
                attributes = list(
                    obj.getAttributesToStore()
                )
            except Exception:
                attributes = []

            for attributeName, attribute in attributes:
                if attribute is None:
                    continue

                attributePath = (
                    "%s.%s" % (path, attributeName)
                    if path
                    else str(attributeName)
                )

                try:
                    isPointer = bool(
                        attribute.isPointer()
                    )
                except Exception:
                    isPointer = False

                if isPointer:
                    try:
                        hasValue = bool(
                            attribute.hasValue()
                        )
                    except Exception:
                        hasValue = False

                    if not hasValue:
                        continue

                    try:
                        pointerValue = (
                            attribute.getObjValue()
                        )
                    except Exception as error:
                        errors.append({
                            "path": attributePath,
                            "error": str(error),
                        })
                        continue

                    if pointerValue is None:
                        continue

                    hasObjId = getattr(
                        pointerValue,
                        "hasObjId",
                        None,
                    )

                    if not callable(hasObjId):
                        errors.append({
                            "path": attributePath,
                            "value": str(pointerValue),
                            "valueClass": (
                                pointerValue
                                .__class__
                                .__name__
                            ),
                            "error": (
                                "Pointer target is not a "
                                "Scipion object"
                            ),
                        })

                    continue

                visit(
                    attribute,
                    attributePath,
                )

        visit(protocol)

        return {
            "valid": not errors,
            "errors": errors,
        }

    def buildDuplicatedProtocolParams(
            self,
            sourceProtocol,
            sourceParams: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build params for a duplicated protocol.

        Duplicates must keep configuration params, but must not carry runtime
        state, output attrs or pointer values. Pointers are restored later from
        protocol_input_refs.
        """
        params = copy.deepcopy(sourceParams or {})

        for key in list(params.keys()):
            try:
                param = sourceProtocol.getParam(key)
            except Exception:
                param = None

            if isinstance(param, (PointerParam, MultiPointerParam, RelationParam)):
                params.pop(key, None)
                continue

            if str(key).startswith("object."):
                params.pop(key, None)
                continue

            if str(key).startswith("_outputs"):
                params.pop(key, None)
                continue

            if key in self.runtimeParamKeysToDrop:
                params.pop(key, None)

        self._markRunNameAsCopy(params)

        return params

    @staticmethod
    def _markRunNameAsCopy(params: Dict[str, Any]) -> None:
        try:
            runName = params.get("runName")

            if isinstance(runName, dict):
                oldValue = runName.get("value") or runName.get("editableValue")

                if oldValue:
                    runName["value"] = "%s copy" % oldValue
                    runName["editableValue"] = "%s copy" % oldValue

            elif runName:
                params["runName"] = "%s copy" % runName

        except Exception:
            pass

    def buildPostgresqlRuntimeDuplicateResultPayload(
            self,
            state: RuntimeProtocolDuplicateState,
    ) -> Dict[str, Any]:
        return {
            "protocolsCount": len(state.duplicated or []),
            "dependenciesCount": int(state.dependenciesCount or 0),
            "duplicated": state.duplicated or [],
            "errors": [],
            "postgresqlRuntimeDuplicate": True,
            "syncReports": state.syncReports or [],
            "duplicateRemap": {
                "protocolIds": state.sourceToDuplicatedProtocolId or {},
                "protocolDbIds": {
                    str(k): str(v)
                    for k, v in (state.sourceDbToDuplicatedDbId or {}).items()
                },
            },
        }

    def registerDuplicatedProtocol(
            self,
            state: RuntimeProtocolDuplicateState,
            sourceScipionProtocolId,
            sourceProtocolDbId,
            duplicatedProtocol,
            duplicatedProtocolId,
            duplicatedProtocolDbId,
    ) -> None:
        state.sourceToDuplicatedProtocolId[str(sourceScipionProtocolId)] = str(duplicatedProtocolId)
        state.sourceDbToDuplicatedDbId[int(sourceProtocolDbId)] = int(duplicatedProtocolDbId)

        state.duplicatedItems.append({
            "sourceScipionProtocolId": sourceScipionProtocolId,
            "duplicatedProtocol": duplicatedProtocol,
            "duplicatedProtocolId": duplicatedProtocolId,
        })

        state.duplicated.append({
            "sourceId": str(sourceScipionProtocolId),
            "newId": str(duplicatedProtocolId),
        })

    def hasDuplicatedProtocols(
            self,
            state: RuntimeProtocolDuplicateState,
    ) -> bool:
        return bool(state.duplicatedItems)

    def buildDuplicatedProtocolSyncContext(
            self,
            duplicatedItem: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "duplicatedProtocol": duplicatedItem["duplicatedProtocol"],
            "sourceScipionProtocolId": duplicatedItem["sourceScipionProtocolId"],
            "duplicatedProtocolId": duplicatedItem["duplicatedProtocolId"],
        }

    def registerDuplicatedProtocolSyncReport(
            self,
            state: RuntimeProtocolDuplicateState,
            sourceScipionProtocolId,
            duplicatedProtocolId,
            protocolSync: Dict[str, Any],
            dependencySync: Dict[str, Any],
            pointerRestore: Dict[str, Any],
    ) -> None:
        state.syncReports.append({
            "sourceProtocolId": str(sourceScipionProtocolId),
            "duplicatedProtocolId": str(duplicatedProtocolId),
            "protocolSync": protocolSync,
            "dependencySync": dependencySync,
            "pointerRestore": pointerRestore,
        })

        state.dependenciesCount = int(state.dependenciesCount or 0) + int(
            (dependencySync or {}).get("dependenciesSaved", 0) or 0
        )

    def copyPostgresqlInputRefsForDuplicatedProtocol(
            self,
            state: RuntimeProtocolDuplicateState,
            mapper,
            projectId: int,
            sourceProtocolId,
            duplicatedProtocolId,
    ) -> Dict[str, Any]:
        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        sourceProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
            sourceProtocolId
        )

        duplicatedProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
            duplicatedProtocolId
        )

        if sourceProtocolDbId is None:
            raise ValueError(
                "Source protocol %s was not found in PostgreSQL"
                % sourceProtocolId
            )

        if duplicatedProtocolDbId is None:
            raise ValueError(
                "Duplicated protocol %s was not found in PostgreSQL"
                % duplicatedProtocolId
            )

        sourceToDuplicatedProtocolId = {
            str(k): str(v)
            for k, v in (state.sourceToDuplicatedProtocolId or {}).items()
            if k is not None and v is not None
        }

        sourceDbToDuplicatedDbId = {
            int(k): int(v)
            for k, v in (state.sourceDbToDuplicatedDbId or {}).items()
            if k is not None and v is not None
        }

        protocolGraphRepository = ProtocolGraphRepository()
        rows = protocolGraphRepository.loadInputRefsForProtocolCopy(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=sourceProtocolDbId,
        )

        refs = []
        parentProtocolDbIds = []
        parentProtocolIds = []

        for row in rows or []:
            originalParentProtocolDbId = row.get("parentProtocolDbId")
            originalParentProtocolId = row.get("parentProtocolId")

            parentProtocolDbId = originalParentProtocolDbId
            parentProtocolId = originalParentProtocolId
            remappedToDuplicatedParent = False

            if originalParentProtocolDbId not in (None, ""):
                try:
                    originalParentProtocolDbIdInt = int(originalParentProtocolDbId)

                    if originalParentProtocolDbIdInt in sourceDbToDuplicatedDbId:
                        parentProtocolDbId = sourceDbToDuplicatedDbId[originalParentProtocolDbIdInt]
                        remappedToDuplicatedParent = True
                    else:
                        parentProtocolDbId = originalParentProtocolDbIdInt

                except Exception:
                    parentProtocolDbId = originalParentProtocolDbId

            if originalParentProtocolId not in (None, ""):
                originalParentProtocolIdText = str(originalParentProtocolId).strip()

                if originalParentProtocolIdText in sourceToDuplicatedProtocolId:
                    parentProtocolId = sourceToDuplicatedProtocolId[originalParentProtocolIdText]
                    remappedToDuplicatedParent = True
                else:
                    parentProtocolId = originalParentProtocolIdText

            if parentProtocolDbId in (None, "") and parentProtocolId not in (None, ""):
                parentProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
                    parentProtocolId
                )

            if parentProtocolDbId not in (None, ""):
                try:
                    parentProtocolDbId = int(parentProtocolDbId)

                    if parentProtocolDbId not in parentProtocolDbIds:
                        parentProtocolDbIds.append(parentProtocolDbId)
                except Exception:
                    pass

            if parentProtocolId not in (None, ""):
                try:
                    cleanParentProtocolId = int(parentProtocolId)

                    if cleanParentProtocolId not in parentProtocolIds:
                        parentProtocolIds.append(cleanParentProtocolId)
                except Exception:
                    pass

            refs.append({
                "projectId": int(projectId),
                "protocolDbId": int(duplicatedProtocolDbId),
                "protocolId": str(duplicatedProtocolId),
                "inputName": row.get("inputName"),
                "itemIndex": row.get("itemIndex"),
                "parentProtocolDbId": parentProtocolDbId,
                "parentProtocolId": str(parentProtocolId) if parentProtocolId not in (None, "") else None,
                "parentOutputName": row.get("parentOutputName"),
                "objectClassName": row.get("objectClassName"),
                "objectId": None if remappedToDuplicatedParent else row.get("objectId"),
            })

        dependenciesSaved = protocolGraphRepository.replaceDependenciesForProtocol(
            mapper=mapper,
            projectId=projectId,
            childProtocolDbId=int(duplicatedProtocolDbId),
            parentProtocolDbIds=parentProtocolDbIds,
        )

        inputRefsSaved = protocolGraphRepository.replaceInputRefsForProtocol(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=int(duplicatedProtocolDbId),
            refs=refs,
        )

        protocolGraphRepository.updateProtocolParentIds(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=int(duplicatedProtocolDbId),
            parentProtocolIds=parentProtocolIds,
        )

        return {
            "sourceProtocolId": str(sourceProtocolId),
            "sourceProtocolDbId": int(sourceProtocolDbId),
            "duplicatedProtocolId": str(duplicatedProtocolId),
            "duplicatedProtocolDbId": int(duplicatedProtocolDbId),
            "inputRefsSaved": inputRefsSaved,
            "dependenciesSaved": dependenciesSaved,
            "parentProtocolIds": parentProtocolIds,
            "parentProtocolDbIds": parentProtocolDbIds,
        }

    def restorePostgresqlPointerInputsBeforeCopy(
            self,
            mapper,
            projectId: int,
            protocol,
            getScipionProtocolByRuntimeIdCallback: Callable,
            parentProtocolsById: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Restore PointerParam/MultiPointerParam attributes from
        protocol_input_refs before storing a protocol through Scipion's
        runtime mapper.
        """
        protocolId = self._getScipionObjectId(
            protocol
        )

        if protocolId is None:
            return {
                "protocolId": None,
                "restored": 0,
                "skipped": True,
                "reason": "protocol_without_id",
            }

        protocolIdentityResolver = (
            ProtocolIdentityResolver(
                mapper=mapper,
                projectId=projectId,
            )
        )

        protocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
            protocolId
        )

        if protocolDbId is None:
            return {
                "protocolId": str(protocolId),
                "protocolDbId": None,
                "restored": 0,
                "skipped": True,
                "reason": (
                    "protocol_not_found_in_postgresql"
                ),
            }

        protocolGraphRepository = (
            ProtocolGraphRepository()
        )

        selfInputRefs = (
            protocolGraphRepository
            .loadSelfInputRefs(
                mapper=mapper,
                projectId=projectId,
                protocolDbId=protocolDbId,
            )
        )

        if selfInputRefs:
            raise ValueError(
                "Protocol %s has PostgreSQL runtime "
                "self input refs: %s"
                % (
                    protocolId,
                    selfInputRefs,
                )
            )

        inputNames = []

        try:
            for inputName, _attribute in (
                    protocol.iterInputAttributes()
            ):
                if (
                        inputName
                        and inputName not in inputNames
                ):
                    inputNames.append(
                        inputName
                    )

        except Exception:
            pass

        sanitization = (
            self
            .sanitizeProtocolPointerTargetsForPersistence(
                protocol
            )
        )

        pointerResolver = (
            RuntimePointerResolver()
        )

        refsByInputName = (
            pointerResolver
            .loadInputRefsByInputName(
                mapper=mapper,
                projectId=projectId,
                protocolDbId=protocolDbId,
            )
        )

        for inputName in refsByInputName:
            if inputName not in inputNames:
                inputNames.append(
                    inputName
                )

        restored = []
        clearedInputs = []
        errors = list(
            sanitization.get("errors")
            or []
        )

        def resolveParentProtocol(
                parentProtocolId,
        ):
            parentScipionProtocolId = protocolIdentityResolver.toOptionalInt(parentProtocolId)

            if parentScipionProtocolId is None:
                raise ValueError(
                    "Invalid Scipion parent protocol id: %s"
                    % parentProtocolId
                )

            parentProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
                parentScipionProtocolId
            )

            if parentProtocolDbId is None:
                raise ValueError(
                    "Parent protocol %s was not found in PostgreSQL"
                    % parentScipionProtocolId
                )

            parentProtocol = None

            if parentProtocolsById:
                parentProtocol = (
                        parentProtocolsById.get(str(parentScipionProtocolId))
                        or parentProtocolsById.get(parentScipionProtocolId)
                )

            if parentProtocol is None:
                parentProtocol = getScipionProtocolByRuntimeIdCallback(parentScipionProtocolId)

            if parentProtocol is None:
                raise ValueError(
                    "Parent protocol %s was not found in Scipion runtime"
                    % parentScipionProtocolId
                )

            return parentScipionProtocolId, parentProtocol

        for inputName in inputNames:
            try:
                param = protocol.getParam(
                    inputName
                )
            except Exception:
                param = None

            if not isinstance(
                    param,
                    (
                        PointerParam,
                        MultiPointerParam,
                        RelationParam,
                    ),
            ):
                continue

            inputRefs = (
                refsByInputName.get(
                    inputName
                )
                or []
            )

            if not inputRefs:
                try:
                    if isinstance(
                            param,
                            MultiPointerParam,
                    ):
                        setattr(
                            protocol,
                            inputName,
                            PointerList(),
                        )
                    else:
                        setattr(
                            protocol,
                            inputName,
                            Pointer(),
                        )

                    clearedInputs.append(
                        inputName
                    )

                except Exception as error:
                    errors.append({
                        "inputName": inputName,
                        "error": str(error),
                    })

                continue

            try:
                restoreReport = (
                    pointerResolver
                    .restorePointerAttributeFromInputRefs(
                        protocol=protocol,
                        inputName=inputName,
                        inputRefs=inputRefs,
                        isMultiPointer=isinstance(
                            param,
                            MultiPointerParam,
                        ),
                        resolveParentProtocolCallback=(
                            resolveParentProtocol
                        ),
                    )
                )

                restored.extend(
                    restoreReport.get(
                        "restored"
                    )
                    or []
                )

            except Exception as error:
                logger.exception(
                    "Failed to restore PostgreSQL pointer "
                    "input before protocol persistence. "
                    "projectId=%s protocolId=%s "
                    "inputName=%s",
                    projectId,
                    protocolId,
                    inputName,
                )

                errors.append({
                    "inputName": inputName,
                    "error": str(error),
                })

        validation = (
            self
            .validateProtocolPointerTargetsForPersistence(
                protocol
            )
        )

        for validationError in (
                validation.get("errors")
                or []
        ):
            errors.append({
                "inputName": validationError.get(
                    "path"
                ),
                "error": (
                    "Unresolved pointer target: %s"
                    % validationError
                ),
            })

        report = {
            "protocolId": str(protocolId),
            "protocolDbId": int(protocolDbId),
            "restored": len(restored),
            "items": restored,
            "clearedInputs": clearedInputs,
            "sanitizedPointers": (
                sanitization.get("cleared")
                or []
            ),
            "validation": validation,
            "errors": errors,
            "skipped": False,
        }

        logger.info(
            "Restored PostgreSQL pointer inputs before "
            "protocol persistence. "
            "projectId=%s protocolId=%s report=%s",
            projectId,
            protocolId,
            report,
        )

        return report