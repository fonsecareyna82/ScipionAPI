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

from fastapi import HTTPException, status
from pyworkflow.protocol import (
    MODE_RESUME,
    MODE_RESTART,
    STATUS_LAUNCHED,
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
            usesPostgresqlRuntimeCallback: Callable[[], bool],
            preparePostgresqlRuntimePointerOutputsForLaunchCallback: Callable,
            syncProjectProtocolsAndDependenciesCallback: Callable,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback: Callable,
            syncPostgresqlRuntimeProtocolCallback: Callable,
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
                usesPostgresqlRuntimeCallback=usesPostgresqlRuntimeCallback,
                syncProjectProtocolsAndDependenciesCallback=syncProjectProtocolsAndDependenciesCallback,
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

        usingPostgresqlRuntime = usesPostgresqlRuntimeCallback()
        postgresqlLaunchPointerReport = None

        if usingPostgresqlRuntime:
            postgresqlLaunchPointerReport = preparePostgresqlRuntimePointerOutputsForLaunchCallback(
                mapper=mapper,
                projectId=projectId,
                protocol=protocol,
                allowMissingParentOutputs=False,
            )

            if postgresqlLaunchPointerReport.get("errors"):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(
                            "Failed to prepare PostgreSQL runtime pointer outputs for launch: %s"
                            % postgresqlLaunchPointerReport.get("errors")
                    ),
                )

            if postgresqlLaunchPointerReport.get("skipped"):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "message": (
                            "PostgreSQL runtime pointer preparation was skipped. "
                            "The protocol cannot be launched safely because its "
                            "runtime inputs may not be restored in the execution DB."
                        ),
                        "report": postgresqlLaunchPointerReport,
                    },
                )

        if protocol.useQueue():
            queueName = params.get("_queueName")
            queueParams = params.get("_queueParams")
            protocol.setQueueParams([queueName, queueParams])

        if usingPostgresqlRuntime:
            self._storePreparedPostgresqlRuntimeProtocol(
                currentProject=currentProject,
                protocol=protocol,
                protocolId=protocolId,
                projectId=projectId,
                postgresqlLaunchPointerReport=postgresqlLaunchPointerReport,
            )

        self._validateProtocol(
            protocol=protocol,
            errors=errors,
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            usingPostgresqlRuntime=usingPostgresqlRuntime,
            syncProjectProtocolsAndDependenciesCallback=syncProjectProtocolsAndDependenciesCallback,
        )

        self._syncBeforeLaunchIfNeeded(
            mapper=mapper,
            projectId=projectId,
            protocol=protocol,
            protocolId=protocolId,
            usingPostgresqlRuntime=usingPostgresqlRuntime,
            syncProjectProtocolsAndDependenciesCallback=syncProjectProtocolsAndDependenciesCallback,
        )

        return self._executeProtocol(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            protocol=protocol,
            executeMode=executeMode,
            currentProject=currentProject,
            usingPostgresqlRuntime=usingPostgresqlRuntime,
            postgresqlLaunchPointerReport=postgresqlLaunchPointerReport,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback=(
                deletePersistedProtocolOutputsForRuntimeProtocolsCallback
            ),
            syncPostgresqlRuntimeProtocolCallback=syncPostgresqlRuntimeProtocolCallback,
            syncProjectProtocolsAndDependenciesCallback=syncProjectProtocolsAndDependenciesCallback,
        )

    def _stopProtocol(
            self,
            *,
            mapper,
            projectId: int,
            protocolId,
            stopProtocolCallback: Callable,
            usesPostgresqlRuntimeCallback: Callable[[], bool],
            syncProjectProtocolsAndDependenciesCallback: Callable,
    ) -> Dict[str, Any]:
        try:
            result = stopProtocolCallback(mapper, projectId, [protocolId])

            if usesPostgresqlRuntimeCallback():
                return result

            return syncProjectProtocolsAndDependenciesCallback(
                mapper,
                projectId,
                refresh=True,
                checkPid=True,
            )

        except HTTPException:
            raise

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e

    def _storePreparedPostgresqlRuntimeProtocol(
            self,
            *,
            currentProject,
            protocol,
            protocolId,
            projectId: int,
            postgresqlLaunchPointerReport: Optional[Dict[str, Any]],
    ) -> None:
        try:
            currentProject._storeProtocol(protocol)

            if postgresqlLaunchPointerReport is not None:
                postgresqlLaunchPointerReport["storedPreparedProtocol"] = True

        except Exception as e:
            logger.exception(
                "Failed to persist PostgreSQL-prepared protocol pointers before launch. "
                "projectId=%s protocolId=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                        "Failed to persist PostgreSQL-prepared protocol pointers before launch: %s"
                        % str(e)
                ),
            )

    def _validateProtocol(
            self,
            *,
            protocol,
            errors,
            mapper,
            projectId: int,
            protocolId,
            usingPostgresqlRuntime: bool,
            syncProjectProtocolsAndDependenciesCallback: Callable,
    ) -> None:
        try:
            validationErrors = protocol._validate()
            if validationErrors:
                errors += validationErrors

        except Exception:
            logger.exception("Unexpected error during protocol validation")
            errors += [
                "**Other errors:** There are other validation errors that may be resolved by correcting the previous ones."
            ]

        if not errors:
            return

        if not usingPostgresqlRuntime:
            try:
                syncProjectProtocolsAndDependenciesCallback(
                    mapper,
                    projectId,
                    refresh=True,
                    checkPid=True,
                )
            except Exception:
                logger.exception(
                    "Failed to sync protocol graph after validation errors. projectId=%s protocolId=%s",
                    projectId,
                    getattr(protocol, "getObjId", lambda: protocolId)(),
                )
        else:
            logger.info(
                "Skipping legacy graph sync after PostgreSQL runtime validation errors. "
                "projectId=%s protocolId=%s errors=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
                errors,
            )

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=errors,
        )

    def _syncBeforeLaunchIfNeeded(
            self,
            *,
            mapper,
            projectId: int,
            protocol,
            protocolId,
            usingPostgresqlRuntime: bool,
            syncProjectProtocolsAndDependenciesCallback: Callable,
    ) -> None:
        if not usingPostgresqlRuntime:
            syncProjectProtocolsAndDependenciesCallback(
                mapper,
                projectId,
                refresh=True,
                checkPid=False,
            )
            return

        logger.info(
            "Skipping legacy pre-launch graph sync for PostgreSQL runtime protocol. "
            "projectId=%s protocolId=%s",
            projectId,
            getattr(protocol, "getObjId", lambda: protocolId)(),
        )

    def _executeProtocol(
            self,
            *,
            mapper,
            projectId: int,
            protocolId,
            protocol,
            executeMode,
            currentProject,
            usingPostgresqlRuntime: bool,
            postgresqlLaunchPointerReport: Optional[Dict[str, Any]],
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback: Callable,
            syncPostgresqlRuntimeProtocolCallback: Callable,
            syncProjectProtocolsAndDependenciesCallback: Callable,
    ) -> Dict[str, Any]:
        try:
            if executeMode == "schedule":
                currentProject.scheduleProtocol(protocol)

            else:
                modeToRunMode = {
                    "launch": MODE_RESUME,
                    "restart": MODE_RESTART,
                }

                runMode = modeToRunMode[executeMode]
                protocol.runMode.set(runMode)

                if executeMode == "restart":
                    cleanupInfo = deletePersistedProtocolOutputsForRuntimeProtocolsCallback(
                        mapper=mapper,
                        projectId=projectId,
                        protocols=[protocol],
                    )

                    logger.info(
                        "Deleted persisted protocol outputs before restart. projectId=%s protocolId=%s cleanup=%s",
                        projectId,
                        getattr(protocol, "getObjId", lambda: protocolId)(),
                        cleanupInfo,
                    )

                if usingPostgresqlRuntime:
                    self._ensureProtocolExistsInSqliteExecutionDb(
                        currentProject=currentProject,
                        protocol=protocol,
                        protocolId=protocolId,
                        projectId=projectId,
                    )

                currentProject.launchProtocol(protocol)

                if usingPostgresqlRuntime:
                    launchedProtocolId = getattr(protocol, "getObjId", lambda: protocolId)()

                    try:
                        protocol.setStatus(STATUS_LAUNCHED)
                    except Exception:
                        statusAttr = getattr(protocol, "status", None)
                        setter = getattr(statusAttr, "set", None)
                        if callable(setter):
                            setter(STATUS_LAUNCHED)

                    currentProject._storeProtocol(protocol)

                    return {
                        "protocols": 1,
                        "dependencies": 0,
                        "postgresqlRuntimeLaunch": True,
                        "launchAccepted": True,
                        "protocolId": str(launchedProtocolId),
                        "protocolStatus": STATUS_LAUNCHED,
                        "postgresqlLaunchPointerReport": postgresqlLaunchPointerReport,
                    }

            if usingPostgresqlRuntime:
                return self._syncPostgresqlRuntimeAfterLaunch(
                    mapper=mapper,
                    projectId=projectId,
                    protocol=protocol,
                    protocolId=protocolId,
                    postgresqlLaunchPointerReport=postgresqlLaunchPointerReport,
                    syncPostgresqlRuntimeProtocolCallback=syncPostgresqlRuntimeProtocolCallback,
                )

            return syncProjectProtocolsAndDependenciesCallback(
                mapper,
                projectId,
                refresh=True,
                checkPid=True,
            )

        except HTTPException:
            raise

        except Exception as e:
            logger.exception(
                "Failed to sync protocol graph after execute. projectId=%s protocolId=%s executeMode=%s",
                projectId,
                getattr(protocol, "getObjId", lambda: protocolId)(),
                executeMode,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{e}",
            )

    def _ensureProtocolExistsInSqliteExecutionDb(
            self,
            *,
            currentProject,
            protocol,
            protocolId,
            projectId: int,
    ) -> None:
        runtimeMapper = None

        try:
            runtimeMapper = currentProject.getPostgresqlRuntimeMapper()
        except Exception:
            runtimeMapper = None

        protocolRuntimeId = getattr(protocol, "getObjId", lambda: protocolId)()

        if runtimeMapper is not None and not runtimeMapper._existsInWriteFallback(protocolRuntimeId):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                        "Protocol %s exists in PostgreSQL but not in the SQLite execution DB. "
                        "It was probably saved without PostgreSQL runtime write fallback enabled. "
                        "Delete/recreate or resave it after enabling write fallback."
                        % protocolRuntimeId
                ),
            )

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