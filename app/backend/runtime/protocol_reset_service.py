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
from typing import Any, Callable, Dict, List, Tuple

from fastapi import HTTPException, status
from pyworkflow.object import (
    Pointer,
    PointerList,
)
from pyworkflow.protocol import (
    MODE_RESTART,
    STATUS_SAVED,
)
from pyworkflow.protocol.params import (
    MultiPointerParam,
    PointerParam,
    RelationParam,
)
from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)
from app.backend.runtime.protocol_identity import (
    ProtocolIdentityResolver,
)
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)


logger = logging.getLogger(__name__)


class RuntimeProtocolResetService:
    """
    Reset a selected protocol and its downstream subworkflow.
    Runtime reset never uses project.sqlite, run.db or steps.sqlite.
    """

    @staticmethod
    def _workflowItems(
            workflowProtocolMap,
    ) -> List[Tuple[Any, int]]:
        items = []

        values = (
            workflowProtocolMap.values()
            if isinstance(
                workflowProtocolMap,
                dict,
            )
            else workflowProtocolMap or []
        )

        for value in values:
            if (
                    isinstance(
                        value,
                        (
                            tuple,
                            list,
                        ),
                    )
                    and value
            ):
                protocol = value[0]

                level = int(
                    value[1]
                    if len(value) > 1
                    else 0
                )

            else:
                protocol = value
                level = 0

            if protocol is not None:
                items.append(
                    (
                        protocol,
                        level,
                    )
                )

        items.sort(
            key=lambda item: (
                item[1],
                int(
                    item[0].getObjId()
                ),
            )
        )

        return items

    @staticmethod
    def _getProtocolStatus(
            protocol,
    ) -> str:
        return str(protocol.getStatus() or "").strip().lower()

    @staticmethod
    def _detachOutputs(
            protocol,
            outputNames,
    ) -> None:
        """
        Remove only outputs owned by the protocol being reset.

        Parent protocol outputs are never attached, replaced
        or modified.
        """
        for outputName in outputNames or []:
            if hasattr(protocol, outputName):
                delattr(protocol, outputName)

        outputs = getattr(protocol, "_outputs", None)

        if outputs is not None:
            outputs.clear()

    @staticmethod
    def _detachRuntimeInputPointers(
            protocol,
            pointerParams,
    ) -> None:
        """
        Detach in-memory pointer objects before persisting
        the reset protocol.

        Authoritative protocol_input_refs rows are deliberately
        preserved. No parent protocol or parent output is changed.
        """
        for paramName, pointerKind in pointerParams or []:
            if pointerKind == "multi":
                setattr(protocol, paramName, PointerList())
            else:
                setattr(protocol, paramName, Pointer())

    @staticmethod
    def _setScalarValue(
            protocol,
            attributeName: str,
            value,
    ) -> None:
        attribute = getattr(
            protocol,
            attributeName,
            None,
        )

        setter = getattr(
            attribute,
            "set",
            None,
        )

        if callable(setter):
            setter(
                value
            )

    def _validatePostgresqlSubworkflow(
            self,
            *,
            mapper,
            projectId: int,
            workflowProtocolMap,
            currentProject,
    ) -> Dict[str, Any]:
        runtimeMapper = (
            currentProject
            .getPostgresqlRuntimeMapper()
        )

        if runtimeMapper is None:
            raise RuntimeError(
                "PostgreSQL runtime mapper "
                "is not available"
            )

        identityResolver = (
            ProtocolIdentityResolver(
                mapper=mapper,
                projectId=projectId,
            )
        )

        resetItems = []
        skippedItems = []
        errors = []
        seenProtocolIds = set()

        for protocol, level in (
                self._workflowItems(
                    workflowProtocolMap
                )
        ):
            protocolId = getattr(
                protocol,
                "getObjId",
                lambda: None,
            )()

            try:
                protocolId = int(
                    protocolId
                )

            except (
                    TypeError,
                    ValueError,
            ):
                errors.append({
                    "protocolId": (
                        str(protocolId)
                        if protocolId is not None
                        else None
                    ),
                    "error": (
                        "Protocol does not have "
                        "a valid runtime id"
                    ),
                })

                continue

            if protocolId in seenProtocolIds:
                continue

            seenProtocolIds.add(
                protocolId
            )

            protocolDbId = identityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
                protocolId
            )

            if protocolDbId is None:
                errors.append({
                    "protocolId": str(
                        protocolId
                    ),
                    "error": (
                        "Protocol was not found "
                        "in PostgreSQL"
                    ),
                })

                continue

            try:
                protocolStatus = self._getProtocolStatus(protocol)
            except Exception as error:
                errors.append({
                    "protocolId": str(protocolId),
                    "error": "Could not read protocol runtime status: %s" % error,
                })
                continue

            try:
                outputNames = [
                    outputName
                    for outputName, _
                    in list(protocol.iterOutputAttributes())
                ]
            except Exception as error:
                errors.append({
                    "protocolId": str(protocolId),
                    "error": "Could not enumerate protocol runtime outputs: %s" % error,
                })
                continue

            try:
                definition = protocol.getDefinition()
                pointerParams = []

                for paramName, param in list(definition.iterParams()):
                    if isinstance(param, MultiPointerParam):
                        pointerParams.append((paramName, "multi"))
                    elif isinstance(param, (PointerParam, RelationParam)):
                        pointerParams.append((paramName, "single"))
            except Exception as error:
                errors.append({
                    "protocolId": str(protocolId),
                    "error": "Could not enumerate protocol runtime input parameters: %s" % error,
                })
                continue

            item = {
                "protocol": protocol,
                "protocolId": protocolId,
                "protocolDbId": int(protocolDbId),
                "level": int(level),
                "status": protocolStatus,
                "outputNames": outputNames,
                "pointerParams": pointerParams,
            }

            if (
                    item["status"]
                    == str(
                        STATUS_SAVED
                    ).strip().lower()
            ):
                skippedItems.append({
                    "protocolId": str(
                        protocolId
                    ),
                    "protocolDbId": int(
                        protocolDbId
                    ),
                    "level": int(
                        level
                    ),
                    "status": item[
                        "status"
                    ],
                    "reason": (
                        "protocol_already_saved"
                    ),
                })

                continue

            resetItems.append(
                item
            )

        return {
            "runtimeMapper": runtimeMapper,
            "resetItems": resetItems,
            "skipped": skippedItems,
            "errors": errors,
            "parentProtocolsModified": False,
        }

    def _resetPostgresqlProtocol(
            self,
            *,
            mapper,
            projectId: int,
            runtimeMapper,
            item,
    ) -> Dict[str, Any]:
        protocol = item[
            "protocol"
        ]

        protocolId = int(
            item["protocolId"]
        )

        protocolDbId = int(
            item["protocolDbId"]
        )

        # Only the selected protocol subtree is modified.
        self._detachOutputs(
            protocol,
            item.get("outputNames"),
        )

        # Preserve authoritative input refs while avoiding
        # persistent object graphs containing parent protocols.
        self._detachRuntimeInputPointers(
            protocol,
            item.get("pointerParams"),
        )

        protocol.setSaved()

        protocol.runMode.set(
            MODE_RESTART
        )

        protocol.cleanExecutionAttributes()

        protocol._steps = []

        self._setScalarValue(
            protocol,
            "_stepsDone",
            0,
        )

        self._setScalarValue(
            protocol,
            "_numberOfSteps",
            0,
        )

        self._setScalarValue(
            protocol,
            "_cpuTime",
            0,
        )

        protocol.cleanWorkingDir()
        protocol.makeWorkingDir()

        # Delete only relations created by this protocol.
        runtimeMapper.deleteRelations(
            protocol
        )

        mapper.deleteProtocolSteps(
            projectId=projectId,
            protocolId=protocolId,
        )

        ProtocolGraphRepository().setProtocolRelationsSynchronized(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            synchronized=False,
        )

        protocol.setStatus(
            STATUS_SAVED
        )

        runtimeMapper.store(
            protocol
        )

        runtimeMapper.commit()

        runtimeMetadata = (
            RuntimeProtocolStatusSyncService()
            .resetProtocolRuntimeMetadata(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )
        )

        return {
            "protocolId": str(
                protocolId
            ),
            "protocolDbId": (
                protocolDbId
            ),
            "level": int(
                item["level"]
            ),
            "statusBefore": item[
                "status"
            ],
            "statusAfter": str(
                STATUS_SAVED
            ),
            "runMode": "restart",
            "stepsDeleted": True,
            "outputsDetached": True,
            "workingDirectoryCleaned": True,
            "runtimeMetadata": (
                runtimeMetadata
            ),
            "parentProtocolsModified": False,
        }

    def _resetPostgresqlSubworkflow(
            self,
            *,
            mapper,
            projectId: int,
            workflowProtocolMap,
            currentProject,
            stopPostgresqlProtocolsCallback: Callable,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback: Callable,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback: Callable,
            buildProtocolMutationResultCallback: Callable,
    ) -> Dict[str, Any]:
        validationInfo = (
            self
            ._validatePostgresqlSubworkflow(
                mapper=mapper,
                projectId=projectId,
                workflowProtocolMap=(
                    workflowProtocolMap
                ),
                currentProject=(
                    currentProject
                ),
            )
        )

        if validationInfo.get(
                "errors"
        ):
            raise HTTPException(
                status_code=(
                    status
                    .HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail=validationInfo[
                    "errors"
                ],
            )

        resetItems = list(
            validationInfo.get(
                "resetItems"
            )
            or []
        )

        protocolsToReset = [
            item["protocol"]
            for item in resetItems
        ]

        activeProtocolIds = [
            str(
                item["protocolId"]
            )
            for item in resetItems
            if (
                    item["status"]
                    in RuntimeProtocolStatusSyncService
                    .ACTIVE_STATUS_TEXTS
            )
        ]

        stopInfo = None

        if activeProtocolIds:
            # Reuse the already validated PostgreSQL-native
            # process/SLURM stop implementation.
            stopInfo = (
                stopPostgresqlProtocolsCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocolIds=(
                        activeProtocolIds
                    ),
                )
            )

            stopErrors = list(
                (
                    stopInfo
                    or {}
                ).get(
                    "errors"
                )
                or []
            )

            if stopErrors:
                raise HTTPException(
                    status_code=(
                        status
                        .HTTP_500_INTERNAL_SERVER_ERROR
                    ),
                    detail=stopErrors,
                )

        cleanupInfo = {
            "protocolsCount": 0,
            "setsDeleted": 0,
            "objectsDeleted": 0,
            "filesDeleted": 0,
            "filesSkipped": [],
            "fileErrors": [],
            "items": [],
        }

        refCleanupInfo = {
            "updated": 0,
            "parentProtocolDbIds": [],
        }

        runtimeMapper = validationInfo[
            "runtimeMapper"
        ]

        resetReports = []

        for item in resetItems:
            try:
                protocol = item["protocol"]

                itemCleanupInfo = deletePersistedProtocolOutputsForRuntimeProtocolsCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=[protocol],
                )

                cleanupInfo["protocolsCount"] += int(itemCleanupInfo.get("protocolsCount") or 0)
                cleanupInfo["setsDeleted"] += int(itemCleanupInfo.get("setsDeleted") or 0)
                cleanupInfo["objectsDeleted"] += int(itemCleanupInfo.get("objectsDeleted") or 0)
                cleanupInfo["filesDeleted"] += int(itemCleanupInfo.get("filesDeleted") or 0)
                cleanupInfo["filesSkipped"].extend(itemCleanupInfo.get("filesSkipped") or [])
                cleanupInfo["fileErrors"].extend(itemCleanupInfo.get("fileErrors") or [])
                cleanupInfo["items"].extend(itemCleanupInfo.get("items") or [])

                itemRefCleanupInfo = clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=[protocol],
                )

                refCleanupInfo["updated"] += int(itemRefCleanupInfo.get("updated") or 0)

                for parentProtocolDbId in itemRefCleanupInfo.get("parentProtocolDbIds") or []:
                    if parentProtocolDbId not in refCleanupInfo["parentProtocolDbIds"]:
                        refCleanupInfo["parentProtocolDbIds"].append(parentProtocolDbId)

                resetReports.append(
                    self._resetPostgresqlProtocol(
                        mapper=mapper,
                        projectId=projectId,
                        runtimeMapper=runtimeMapper,
                        item=item,
                    )
                )

            except Exception as error:
                protocolId = item.get(
                    "protocolId"
                )

                logger.exception(
                    "Failed to reset PostgreSQL "
                    "runtime protocol. "
                    "projectId=%s protocolId=%s",
                    projectId,
                    protocolId,
                )

                raise HTTPException(
                    status_code=(
                        status
                        .HTTP_500_INTERNAL_SERVER_ERROR
                    ),
                    detail={
                        "message": (
                            "Failed to reset "
                            "PostgreSQL runtime protocol"
                        ),
                        "protocolId": str(
                            protocolId
                        ),
                        "error": str(
                            error
                        ),
                    },
                ) from error

        return (
            buildProtocolMutationResultCallback(
                "Protocol subtree reset successfully",
                protocolsCount=len(
                    resetReports
                ),
                dependenciesCount=0,
                postgresqlRuntimeReset=True,
                parentProtocolsModified=False,
                postgresqlStop=stopInfo,
                postgresqlCleanup=cleanupInfo,
                postgresqlInputRefCleanup=refCleanupInfo,
                postgresqlReset={
                    "items": (
                        resetReports
                    ),
                    "skipped": (
                        validationInfo.get(
                            "skipped"
                        )
                        or []
                    ),
                },
            )
        )

    def resetProtocolSubworkflow(
            self,
            *,
            mapper,
            projectId: int,
            protocolId,
            currentProject,
            getPostgresqlRuntimeSubworkflowCallback: Callable,
            stopPostgresqlProtocolsCallback: Callable,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback: Callable,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback: Callable,
            buildProtocolMutationResultCallback: Callable,
            includeRoot: bool = True,
    ) -> Dict[str, Any]:
        try:
            workflowProtocolMap = getPostgresqlRuntimeSubworkflowCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )
        except Exception as error:
            logger.exception(
                "Failed to resolve subworkflow for reset-from. "
                "projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to resolve protocol subworkflow: %s" % error,
            ) from error

        if not includeRoot:
            rootProtocolId = str(protocolId)
            workflowProtocolMap = {key: value for key, value in workflowProtocolMap.items() if
                                   str(getattr(value[0] if isinstance(value, (tuple, list)) and value else value,
                                               "getObjId", lambda: None)()) != rootProtocolId}

            if not workflowProtocolMap:
                return buildProtocolMutationResultCallback("No descendant protocols require reset", protocolsCount=0,
                                                           dependenciesCount=0, postgresqlRuntimeReset=True,
                                                           parentProtocolsModified=False)

        return self._resetPostgresqlSubworkflow(
            mapper=mapper,
            projectId=projectId,
            workflowProtocolMap=workflowProtocolMap,
            currentProject=currentProject,
            stopPostgresqlProtocolsCallback=stopPostgresqlProtocolsCallback,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback=(
                deletePersistedProtocolOutputsForRuntimeProtocolsCallback
            ),
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=(
                clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback
            ),
            buildProtocolMutationResultCallback=buildProtocolMutationResultCallback,
        )