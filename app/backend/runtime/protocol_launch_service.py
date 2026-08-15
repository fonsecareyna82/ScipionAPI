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
from typing import Any, Callable, Dict, Optional

from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)

from fastapi import HTTPException, status
from pyworkflow.protocol import (
    MODE_RESUME,
    MODE_RESTART,
    STATUS_SCHEDULED,
)

logger = logging.getLogger(__name__)


class RuntimeProtocolLaunchService:
    """
    Orchestrates protocol launch/restart/schedule/stop.

    This service intentionally receives ProjectService callbacks instead of
    importing ProjectService. The goal is to move orchestration out of the
    god-service without creating circular dependencies.
    """

    def launchProtocol(
            self,
            *,
            mapper,
            projectId: int,
            protocolId,
            protocolClassName: str,
            params: Dict[str, Any],
            executeMode,
            currentProject,
            saveProtocolCallback: Callable,
            stopProtocolCallback: Callable,
            preparePostgresqlRuntimePointerOutputsForLaunchCallback: Callable,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback: Callable,
            syncPostgresqlRuntimeProtocolCallback: Callable,
            currentUserId: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Save, validate, and execute a protocol action.

        Supported execute modes:
          - launch
          - restart
          - schedule
          - stop
        """
        modeAliases = {
            None: "launch",
            "resume": "launch",
        }

        executeMode = modeAliases.get(executeMode, executeMode)
        params = params or {}
        protocolIdToken = "" if protocolId is None else str(protocolId).strip().lower()
        isNewProtocolRequest = protocolIdToken in {"", "none", "null", "undefined"}

        allowedModes = {"launch", "restart", "schedule", "stop"}

        if executeMode not in allowedModes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown executeMode: {executeMode}",
            )

        if executeMode == "stop":
            return self._stopProtocol(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
                stopProtocolCallback=stopProtocolCallback,
            )

        elapsedBeforeLaunchSeconds = 0.0

        if (
                executeMode in {"launch", "restart"}
                and protocolId not in (None, "")
        ):
            elapsedBeforeLaunchSeconds = RuntimeProtocolStatusSyncService().getStoredElapsedTimeSeconds(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

        protocol, errors = saveProtocolCallback(
            mapper,
            projectId,
            protocolId,
            protocolClassName,
            params,
            setToSave=False,
        )

        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=errors,
            )

        createdProtocolId = getattr(protocol, "getObjId", lambda: None)()

        try:
            postgresqlLaunchPointerReport = preparePostgresqlRuntimePointerOutputsForLaunchCallback(mapper=mapper,
                                                                                                    projectId=projectId,
                                                                                                    protocol=protocol,
                                                                                                    allowMissingParentOutputs=False)

            if postgresqlLaunchPointerReport.get("errors"):
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                    detail="Failed to prepare PostgreSQL runtime pointer outputs for launch: %s" % postgresqlLaunchPointerReport.get(
                                        "errors"))

            if postgresqlLaunchPointerReport.get("skipped"):
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={
                    "message": "PostgreSQL runtime pointer preparation was skipped. The protocol cannot be launched safely because its runtime inputs may not be restored in the execution DB.",
                    "report": postgresqlLaunchPointerReport})

            if protocol.useQueue():
                queueName = params.get("_queueName")
                queueParams = params.get("_queueParams")
                protocol.setQueueParams([queueName, queueParams])

            postgresqlLaunchPointerReport["storedPreparedProtocol"] = False
            postgresqlLaunchPointerReport["persistenceDeferredToNativeLaunch"] = True

            self._validateProtocol(protocol=protocol, errors=errors)

            return self._executeProtocol(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
                protocol=protocol,
                executeMode=executeMode,
                elapsedBeforeLaunchSeconds=elapsedBeforeLaunchSeconds,
                currentProject=currentProject,
                postgresqlLaunchPointerReport=postgresqlLaunchPointerReport,
                deletePersistedProtocolOutputsForRuntimeProtocolsCallback=
                deletePersistedProtocolOutputsForRuntimeProtocolsCallback,
                syncPostgresqlRuntimeProtocolCallback=
                syncPostgresqlRuntimeProtocolCallback,
                currentUserId=currentUserId,
            )

        except HTTPException as error:
            if isNewProtocolRequest and createdProtocolId not in (None, ""):
                errorItems = error.detail if isinstance(error.detail, list) else [error.detail]
                raise HTTPException(status_code=error.status_code,
                                    detail={"errors": errorItems, "protocolId": str(createdProtocolId)}) from error

            raise

    def _stopProtocol(
            self,
            *,
            mapper,
            projectId: int,
            protocolId,
            stopProtocolCallback: Callable,
    ) -> Dict[str, Any]:
        try:
            return stopProtocolCallback(
                mapper,
                projectId,
                [protocolId],
            )
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error

    def _validateProtocol(
            self,
            *,
            protocol,
            errors,
    ) -> None:
        try:
            validationErrors = protocol._validate()

            if validationErrors:
                errors += validationErrors

        except Exception:
            logger.exception(
                "Unexpected error during protocol validation"
            )

            errors += [
                "**Other errors:** There are other validation errors that may be resolved by correcting the previous ones."
            ]

        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=errors,
            )

    def _executeProtocol(
            self,
            *,
            mapper,
            projectId: int,
            protocolId,
            protocol,
            executeMode,
            elapsedBeforeLaunchSeconds: float,
            currentProject,
            postgresqlLaunchPointerReport: Optional[Dict[str, Any]],
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback: Callable,
            syncPostgresqlRuntimeProtocolCallback: Callable,
            currentUserId: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            if executeMode == "schedule":
                currentProject.scheduleProtocol(
                    protocol
                )

                if currentUserId is not None:
                    RuntimeProtocolStatusSyncService().persistProtocolExecutionUser(
                        mapper=mapper,
                        projectId=projectId,
                        protocolId=getattr(
                            protocol,
                            "getObjId",
                            lambda: protocolId,
                        )(),
                        userId=currentUserId,
                    )

                return self._syncPostgresqlRuntimeAfterLaunch(
                    mapper=mapper,
                    projectId=projectId,
                    protocol=protocol,
                    protocolId=protocolId,
                    postgresqlLaunchPointerReport=postgresqlLaunchPointerReport,
                    syncPostgresqlRuntimeProtocolCallback=syncPostgresqlRuntimeProtocolCallback,
                )

            modeToRunMode = {
                "launch": MODE_RESUME,
                "restart": MODE_RESTART,
            }

            protocol.runMode.set(
                modeToRunMode[executeMode]
            )

            if executeMode == "restart":
                cleanupInfo = deletePersistedProtocolOutputsForRuntimeProtocolsCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=[protocol],
                )

                logger.info(
                    "Deleted persisted protocol outputs before restart. "
                    "projectId=%s protocolId=%s cleanup=%s",
                    projectId,
                    getattr(protocol, "getObjId", lambda: protocolId)(),
                    cleanupInfo,
                )

            currentProject.launchProtocol(
                protocol
            )

            launchedProtocolId = getattr(
                protocol,
                "getObjId",
                lambda: protocolId,
            )()

            if currentUserId is not None:
                RuntimeProtocolStatusSyncService().persistProtocolExecutionUser(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=launchedProtocolId,
                    userId=currentUserId,
                )

            # The PostgreSQL worker owns the execution lifecycle.
            # While it waits for dependencies, the authoritative
            # status must remain scheduled. The worker marks it as
            # launched immediately before local or queue execution.
            storedProtocolRow = mapper.getProjectProtocolByProtocolId(
                projectId=projectId,
                protocolId=launchedProtocolId,
            ) or {}

            currentStatus = str(
                storedProtocolRow.get("status")
                or STATUS_SCHEDULED
            )

            return {
                "protocols": 1,
                "dependencies": 0,
                "postgresqlRuntimeLaunch": True,
                "launchAccepted": True,
                "protocolId": str(launchedProtocolId),
                "protocolStatus": currentStatus,
                "postgresqlLaunchPointerReport": postgresqlLaunchPointerReport,
                "elapsedTiming": {
                    "deferredToWorker": True,
                    "baseElapsedTimeSeconds": elapsedBeforeLaunchSeconds,
                    "resetElapsed": executeMode == "restart",
                },
            }

        except HTTPException:
            raise

        except Exception as error:
            logger.exception(
                "Failed to execute PostgreSQL runtime protocol. "
                "projectId=%s protocolId=%s executeMode=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
                executeMode,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(error),
            ) from error

    def _syncPostgresqlRuntimeAfterLaunch(
            self,
            *,
            mapper,
            projectId: int,
            protocol,
            protocolId,
            postgresqlLaunchPointerReport: Optional[Dict[str, Any]],
            syncPostgresqlRuntimeProtocolCallback: Callable,
    ) -> Dict[str, Any]:
        try:
            syncResult = syncPostgresqlRuntimeProtocolCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=getattr(protocol, "getObjId", lambda: protocolId)(),
                registerOutputs=False,
            )

        except Exception:
            logger.exception(
                "Failed to sync PostgreSQL runtime protocol immediately after launch. "
                "projectId=%s protocolId=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
            )

            syncResult = {
                "protocols": 1,
                "dependencies": 0,
                "postgresqlRuntimeSync": False,
                "syncError": "Immediate runtime sync failed",
            }

        syncResult.update({
            "postgresqlRuntimeLaunch": True,
            "launchAccepted": True,
            "syncSkipped": False,
            "syncSkippedReason": None,
            "postgresqlLaunchPointerReport": postgresqlLaunchPointerReport,
        })

        return syncResult