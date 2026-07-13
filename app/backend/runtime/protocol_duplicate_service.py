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
from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository
from app.backend.runtime.protocol_identity import ProtocolIdentityResolver
from app.backend.runtime.pointer_resolver import RuntimePointerResolver
from app.backend.runtime.protocol_input_ref_builder_service import (
    RuntimeProtocolInputRefBuilderService,
)

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

    def detachProtocolOutputsForCopy(self, protocol) -> List[Dict[str, Any]]:
        """
        Temporarily detach output attributes before calling Scipion copyProtocol().

        A duplicated protocol must copy only configuration/inputs, not produced outputs.
        If outputs remain attached, Scipion may try to persist/copy sets such as
        295.Tomograms and fail with errors like:

            Object 295.Tomograms has no sampling rate!!!
        """
        detached = []

        try:
            outputAttrs = list(protocol.iterOutputAttributes())
        except Exception:
            outputAttrs = []

        for outputName, outputObj in outputAttrs:
            if not outputName:
                continue

            hadAttribute = hasattr(protocol, outputName)

            detached.append({
                "name": outputName,
                "object": outputObj,
                "hadAttribute": hadAttribute,
            })

            if hadAttribute:
                try:
                    delattr(protocol, outputName)
                except Exception:
                    try:
                        setattr(protocol, outputName, None)
                    except Exception:
                        logger.debug(
                            "Could not detach protocol output before copy. "
                            "protocol=%s output=%s",
                            getattr(protocol, "getObjId", lambda: None)(),
                            outputName,
                            exc_info=True,
                        )

        logger.info(
            "Detached protocol outputs before duplicate. protocolId=%s outputs=%s",
            getattr(protocol, "getObjId", lambda: None)(),
            [item["name"] for item in detached],
        )

        return detached

    def restoreProtocolOutputsAfterCopy(
            self,
            protocol,
            detachedOutputs: List[Dict[str, Any]],
    ) -> None:
        """
        Restore outputs detached by detachProtocolOutputsForCopy.

        This only restores the in-memory source protocol object.
        """
        for item in detachedOutputs or []:
            outputName = item.get("name")
            outputObj = item.get("object")

            if not outputName:
                continue

            try:
                setattr(protocol, outputName, outputObj)
            except Exception:
                logger.debug(
                    "Could not restore protocol output after copy. "
                    "protocol=%s output=%s",
                    getattr(protocol, "getObjId", lambda: None)(),
                    outputName,
                    exc_info=True,
                )

    def duplicatePostgresqlRuntimeProtocols(
            self,
            *,
            mapper,
            projectId: int,
            protocols,
            getScipionProtocolForRuntimeCallback: Callable,
            getScipionObjectIdCallback: Callable,
            resolvePostgresqlProtocolDbIdCallback: Callable,
            saveProtocolCallback: Callable,
            syncPostgresqlRuntimeProtocolCallback: Callable,
            getParentProtocolForPointerCallback: Callable,
            storeProtocolCallback: Callable,
            buildProtocolMutationResultCallback: Callable,
    ):
        duplicateState = self.createDuplicateState()

        # ------------------------------------------------------------------
        # Phase 1: resolve all source protocols and create all duplicated
        # protocol rows, without copying refs yet.
        # ------------------------------------------------------------------
        protocolGraphRepository = ProtocolGraphRepository()

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

            sourceProtocolDbId = resolvePostgresqlProtocolDbIdCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=sourceScipionProtocolId,
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

            sourceInputRefsRepair = self.refreshSourceProtocolInputRefs(
                mapper=mapper,
                projectId=projectId,
                sourceProtocol=sourceProtocol,
                sourceProtocolDbId=sourceProtocolDbId,
            )

            logger.info(
                "Refreshed source protocol input refs before duplicate. "
                "projectId=%s protocolId=%s report=%s",
                projectId,
                sourceScipionProtocolId,
                sourceInputRefsRepair,
            )

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

            duplicatedProtocolId = getScipionObjectIdCallback(newProtocol)

            duplicatedProtocolDbId = resolvePostgresqlProtocolDbIdCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=duplicatedProtocolId,
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
                    getParentProtocolCallback=getParentProtocolForPointerCallback,
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

    def duplicateLegacyProtocols(
            self,
            *,
            mapper,
            projectId: int,
            protocols,
            getScipionProtocolForRuntimeCallback: Callable,
            copyProtocolsCallback: Callable,
            syncProjectProtocolsAndDependenciesCallback: Callable,
            buildProtocolMutationResultCallback: Callable,
    ):
        protocolList = []
        sourceIds = []
        duplicated = []
        errors = []

        for item in protocols or []:
            protocolId = getattr(item, "id", None)

            if protocolId is None:
                continue

            sourceIds.append(protocolId)

            protocol = getScipionProtocolForRuntimeCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

            protocolList.append(protocol)

        if not protocolList:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No valid protocols to duplicate",
            )

        try:
            protListResult = copyProtocolsCallback(protocolList)

        except Exception as e:
            protocolIds = [
                getattr(protocol, "getObjId", lambda: None)()
                for protocol in protocolList
            ]

            logger.exception(
                "Failed to duplicate protocols. projectId=%s protocolIds=%s",
                projectId,
                protocolIds,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to duplicate protocols: {e}",
            )

        for index, protocol in enumerate(protListResult):
            protocolId = str(protocol.getObjId())

            duplicated.append({
                "sourceId": sourceIds[index],
                "newId": protocolId,
            })

        try:
            syncResult = syncProjectProtocolsAndDependenciesCallback(
                mapper,
                projectId,
                refresh=True,
                checkPid=True,
            )

        except HTTPException:
            raise

        except Exception as e:
            errors.append(
                "Failed to sync protocol graph after duplication. projectId=%s"
                % projectId
            )

            logger.exception(
                "Failed to sync protocol graph after duplication. projectId=%s",
                projectId,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                        "Protocols were duplicated in Scipion but graph sync "
                        "to PostgreSQL failed: %s" % e
                ),
            )

        return buildProtocolMutationResultCallback(
            "Protocol was duplicated successfully",
            protocolsCount=int(syncResult.get("protocols", 0)),
            dependenciesCount=int(syncResult.get("dependencies", 0)),
            duplicated=duplicated,
            errors=errors,
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

        sourceProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbId(
            sourceProtocolId,
        )

        duplicatedProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbId(
            duplicatedProtocolId,
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
                parentProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbId(
                    parentProtocolId,
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

    def refreshSourceProtocolInputRefs(
            self,
            mapper,
            projectId: int,
            sourceProtocol,
            sourceProtocolDbId: int,
    ) -> Dict[str, Any]:
        """
        Rebuild the source protocol input refs from its fully hydrated Scipion
        runtime object before duplicating it.

        This repairs imported protocols whose MultiPointer items were previously
        persisted with the same itemIndex.
        """
        rows = mapper.db.fetchAll(
            """
            SELECT id, "protocolId"
              FROM protocols
             WHERE "projectId" = %s
             ORDER BY id
            """,
            (int(projectId),),
        )

        protocolDbIdByScipionId = {
            str(row["protocolId"]): int(row["id"])
            for row in rows or []
            if row.get("protocolId") not in (None, "")
            and row.get("id") not in (None, "")
        }

        sourceProtocolId = self._getScipionObjectId(
            sourceProtocol
        )

        if sourceProtocolId is None:
            raise ValueError(
                "Cannot rebuild source input refs without protocol id"
            )

        protocolDbIdByScipionId[
            str(sourceProtocolId)
        ] = int(sourceProtocolDbId)

        inputRefBuilder = (
            RuntimeProtocolInputRefBuilderService()
        )

        inputRefs = (
            inputRefBuilder
            .buildProtocolInputRefsForPostgresql(
                projectId=projectId,
                protocol=sourceProtocol,
                protocolDbIdByScipionId=protocolDbIdByScipionId,
            )
        )

        parentProtocolDbIds = []
        parentProtocolIds = []

        for ref in inputRefs:
            parentProtocolDbId = ref.get(
                "parentProtocolDbId"
            )
            parentProtocolId = ref.get(
                "parentProtocolId"
            )

            if parentProtocolDbId not in (None, ""):
                parentProtocolDbId = int(
                    parentProtocolDbId
                )

                if parentProtocolDbId not in parentProtocolDbIds:
                    parentProtocolDbIds.append(
                        parentProtocolDbId
                    )

            if parentProtocolId not in (None, ""):
                parentProtocolId = int(
                    parentProtocolId
                )

                if parentProtocolId not in parentProtocolIds:
                    parentProtocolIds.append(
                        parentProtocolId
                    )

        graphRepository = ProtocolGraphRepository()

        graphReport = graphRepository.replaceInputGraphForProtocol(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=int(sourceProtocolDbId),
            parentProtocolDbIds=parentProtocolDbIds,
            parentProtocolIds=parentProtocolIds,
            inputRefs=inputRefs,
        )

        return {
            "protocolId": str(sourceProtocolId),
            "protocolDbId": int(sourceProtocolDbId),
            "inputRefs": len(inputRefs),
            "dependencies": graphReport.get(
                "dependencies",
                0,
            ),
        }

    def restorePostgresqlPointerInputsBeforeCopy(
            self,
            mapper,
            projectId: int,
            protocol,
            getParentProtocolCallback: Callable,
            parentProtocolsById: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Restore PointerParam/MultiPointerParam attributes from protocol_input_refs
        before storing a duplicated protocol through Scipion's runtime mapper.
        """
        protocolId = self._getScipionObjectId(protocol)

        if protocolId is None:
            return {
                "protocolId": None,
                "restored": 0,
                "skipped": True,
                "reason": "protocol_without_id",
            }

        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        protocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbId(
            protocolId,
        )

        if protocolDbId is None:
            return {
                "protocolId": str(protocolId),
                "protocolDbId": None,
                "restored": 0,
                "skipped": True,
                "reason": "protocol_not_found_in_postgresql",
            }

        protocolGraphRepository = ProtocolGraphRepository()
        selfInputRefs = protocolGraphRepository.loadSelfInputRefs(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
        )

        if selfInputRefs:
            raise ValueError(
                "Protocol %s has PostgreSQL runtime self input refs: %s"
                % (protocolId, selfInputRefs)
            )

        pointerResolver = RuntimePointerResolver()

        refsByInputName = pointerResolver.loadInputRefsByInputName(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
        )

        restored = []
        errors = []

        def resolveParentProtocol(parentProtocolId):
            parentScipionProtocolId = protocolIdentityResolver.resolveScipionProtocolId(
                parentProtocolId,
            )

            parentProtocol = None

            if parentProtocolsById:
                parentProtocol = (
                        parentProtocolsById.get(str(parentScipionProtocolId))
                        or parentProtocolsById.get(parentScipionProtocolId)
                )

            if parentProtocol is None:
                parentScipionProtocolId, parentProtocol = getParentProtocolCallback(
                    mapper=mapper,
                    projectId=projectId,
                    parentId=parentProtocolId,
                )

            return parentScipionProtocolId, parentProtocol

        for inputName, inputRefs in refsByInputName.items():
            try:
                param = protocol.getParam(inputName)
            except Exception:
                param = None

            if not isinstance(param, (PointerParam, MultiPointerParam, RelationParam)):
                continue

            try:
                restoreReport = pointerResolver.restorePointerAttributeFromInputRefs(
                    protocol=protocol,
                    inputName=inputName,
                    inputRefs=inputRefs,
                    isMultiPointer=isinstance(param, MultiPointerParam),
                    resolveParentProtocolCallback=resolveParentProtocol,
                )

                restored.extend(restoreReport.get("restored") or [])

            except Exception as e:
                logger.exception(
                    "Failed to restore PostgreSQL pointer input before protocol copy. "
                    "projectId=%s protocolId=%s inputName=%s",
                    projectId,
                    protocolId,
                    inputName,
                )

                errors.append({
                    "inputName": inputName,
                    "error": str(e),
                })

        report = {
            "protocolId": str(protocolId),
            "protocolDbId": int(protocolDbId),
            "restored": len(restored),
            "items": restored,
            "errors": errors,
            "skipped": False,
        }

        logger.info(
            "Restored PostgreSQL pointer inputs before protocol copy. "
            "projectId=%s protocolId=%s report=%s",
            projectId,
            protocolId,
            report,
        )

        return report