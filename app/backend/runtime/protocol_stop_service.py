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
import os
import signal
import time
from typing import Any, Callable, Dict

from fastapi import HTTPException, status
from pyworkflow.protocol.constants import STATUS_SCHEDULED
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)


logger = logging.getLogger(__name__)


class RuntimeProtocolStopService:
    """Orchestrate stopping one or more runtime protocols."""

    @staticmethod
    def _getProtocolPid(protocol):
        """Return the protocol execution PID when available."""
        for attrName in ("_pid", "pid"):
            attr = getattr(protocol, attrName, None)

            if attr is None:
                continue

            try:
                value = (
                    attr.get()
                    if hasattr(attr, "get")
                    else attr
                )
            except Exception:
                value = None

            if value not in (None, "", 0, "0"):
                try:
                    return int(value)
                except Exception:
                    return None

        try:
            value = protocol.getPid()

            if value not in (None, "", 0, "0"):
                return int(value)

        except Exception:
            pass

        return None

    @staticmethod
    def _isPidAlive(pid) -> bool:
        """Return whether the supplied local process is still alive."""
        if not pid:
            return False

        try:
            os.kill(int(pid), 0)
            return True

        except ProcessLookupError:
            return False

        except PermissionError:
            return True

        except Exception:
            return False

    def _killPid(self, pid) -> bool:
        """
        Terminate a local process.

        Send SIGTERM first and use SIGKILL only when the process remains alive.
        """
        if not pid:
            return False

        try:
            os.kill(int(pid), signal.SIGTERM)

        except ProcessLookupError:
            return True

        except Exception:
            logger.exception(
                "Could not send SIGTERM to protocol pid=%s",
                pid,
            )
            return False

        for _ in range(10):
            if not self._isPidAlive(pid):
                return True

            try:
                time.sleep(0.2)
            except Exception:
                break

        try:
            os.kill(int(pid), signal.SIGKILL)

        except ProcessLookupError:
            return True

        except Exception:
            logger.exception(
                "Could not send SIGKILL to protocol pid=%s",
                pid,
            )
            return False

        return not self._isPidAlive(pid)

    def stopProtocols(
            self,
            *,
            mapper,
            projectId: int,
            protocolIds,
            usingPostgresqlRuntime: bool,
            currentProject,
            getScipionProtocolForRuntimeCallback: Callable,
            restorePostgresqlRuntimePointersForProtocolsCallback: Callable,
            loadProtocolFromRuntimeDbCallback: Callable,
            syncPostgresqlRuntimeProtocolsAfterMutationCallback: Callable,
            buildProtocolMutationResultCallback: Callable,
    ) -> Dict[str, Any]:
        """
        Stop the selected runtime protocols.

        The operation only mutates the selected protocols:

        - External parent protocols are never persisted.
        - Parent outputs are never replaced, repaired or deleted.
        - PostgreSQL pointer restoration may only update input Pointer
          attributes belonging to the selected protocol.
        - Output persistence is not performed during the final sync.
        """
        resolvedProtocols = []

        for protocolId in protocolIds or []:
            protocol = getScipionProtocolForRuntimeCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

            resolvedProtocols.append(protocol)

        if not resolvedProtocols:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No valid protocols to stop",
            )

        pointerRestoreInfo = None

        if usingPostgresqlRuntime:
            pointerRestoreInfo = (
                restorePostgresqlRuntimePointersForProtocolsCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=resolvedProtocols,
                    prepareOutputsForLaunch=True,
                    allowMissingParentOutputs=True,
                )
            )

            if pointerRestoreInfo.get("errors"):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(
                        "Failed to restore PostgreSQL runtime pointers "
                        "before stop: %s"
                        % pointerRestoreInfo.get("errors")
                    ),
                )

        try:
            scheduledStopped = []
            nativeStopped = []

            runtimeElapsedService = (
                RuntimeProtocolStatusSyncService()
                if usingPostgresqlRuntime
                else None
            )

            elapsedSnapshots = {}
            stoppedAtByProtocolId = {}

            for protocol in resolvedProtocols:
                protocolStatus = None

                try:
                    protocolStatus = protocol.getStatus()

                except Exception:
                    statusAttr = getattr(
                        protocol,
                        "status",
                        None,
                    )

                    try:
                        protocolStatus = (
                            statusAttr.get()
                            if statusAttr is not None
                            else None
                        )
                    except Exception:
                        protocolStatus = None

                protocolRuntimeId = getattr(
                    protocol,
                    "getObjId",
                    lambda: None,
                )()

                if (
                        runtimeElapsedService
                        is not None
                        and protocolRuntimeId
                        not in (None, "")
                ):
                    elapsedSnapshots[
                        str(protocolRuntimeId)
                    ] = (
                        runtimeElapsedService
                        .captureProtocolElapsedState(
                            mapper=mapper,
                            projectId=projectId,
                            protocolId=(
                                protocolRuntimeId
                            ),
                        )
                    )

                isScheduledProtocol = (
                    usingPostgresqlRuntime
                    and protocolStatus == STATUS_SCHEDULED
                )

                protocolToStop = protocol

                if usingPostgresqlRuntime:
                    try:
                        executionProtocol = (
                            loadProtocolFromRuntimeDbCallback(
                                protocolId=protocolRuntimeId,
                            )
                        )

                        if executionProtocol is not None:
                            protocolToStop = executionProtocol

                    except Exception:
                        logger.debug(
                            "Could not reload protocol from execution DB "
                            "before stop. projectId=%s protocolId=%s",
                            projectId,
                            protocolRuntimeId,
                            exc_info=True,
                        )

                    pointerRestoreInfo = (
                        restorePostgresqlRuntimePointersForProtocolsCallback(
                            mapper=mapper,
                            projectId=projectId,
                            protocols=[protocolToStop],
                            prepareOutputsForLaunch=True,
                            allowMissingParentOutputs=True,
                        )
                    )

                    if pointerRestoreInfo.get("errors"):
                        raise HTTPException(
                            status_code=(
                                status.HTTP_500_INTERNAL_SERVER_ERROR
                            ),
                            detail=(
                                "Failed to restore PostgreSQL runtime "
                                "pointers before stop: %s"
                                % pointerRestoreInfo.get("errors")
                            ),
                        )

                pidBeforeStop = self._getProtocolPid(
                    protocolToStop
                )

                currentProject.stopProtocol(
                    protocolToStop
                )

                if (
                        runtimeElapsedService
                        is not None
                        and protocolRuntimeId
                        not in (None, "")
                ):
                    stoppedAtByProtocolId[
                        str(protocolRuntimeId)
                    ] = time.time()

                if (
                        usingPostgresqlRuntime
                        and pidBeforeStop
                        and self._isPidAlive(pidBeforeStop)
                ):
                    killed = self._killPid(
                        pidBeforeStop
                    )

                    if not killed:
                        raise HTTPException(
                            status_code=(
                                status.HTTP_500_INTERNAL_SERVER_ERROR
                            ),
                            detail=(
                                "Protocol %s was marked as stopped but "
                                "process pid=%s is still alive."
                                % (
                                    protocolRuntimeId,
                                    pidBeforeStop,
                                )
                            ),
                        )

                if isScheduledProtocol:
                    scheduledStopped.append(
                        str(protocolRuntimeId)
                    )
                else:
                    nativeStopped.append(
                        str(protocolRuntimeId)
                    )

            postgresqlSync = None
            elapsedTimingReports = []

            if usingPostgresqlRuntime:
                postgresqlSync = (
                    syncPostgresqlRuntimeProtocolsAfterMutationCallback(
                        mapper=mapper,
                        projectId=projectId,
                        protocols=resolvedProtocols,
                        registerOutputs=False,
                    )
                )

            elapsedTimingReports = []

            for protocol in resolvedProtocols:
                protocolRuntimeId = getattr(
                    protocol,
                    "getObjId",
                    lambda: None,
                )()

                protocolIdText = str(
                    protocolRuntimeId
                )

                elapsedSnapshot = (
                    elapsedSnapshots.get(
                        protocolIdText
                    )
                )

                stoppedAtEpochSeconds = (
                    stoppedAtByProtocolId.get(
                        protocolIdText
                    )
                )

                if (
                        elapsedSnapshot is None
                        or stoppedAtEpochSeconds
                        is None
                ):
                    continue

                elapsedTimingReports.append(
                    runtimeElapsedService
                    .finalizeProtocolElapsedTime(
                        mapper=mapper,
                        projectId=projectId,
                        protocolId=(
                            protocolRuntimeId
                        ),
                        elapsedSnapshot=(
                            elapsedSnapshot
                        ),
                        stoppedAtEpochSeconds=(
                            stoppedAtEpochSeconds
                        ),
                    )
                )

            return buildProtocolMutationResultCallback(
                "Protocol stopped successfully",
                protocolsCount=(
                    int(
                        postgresqlSync.get(
                            "protocolsCount",
                            0,
                        ) or 0
                    )
                    if postgresqlSync
                    else len(resolvedProtocols)
                ),
                dependenciesCount=0,
                postgresqlPointerRestore=pointerRestoreInfo,
                postgresqlRuntimeStop=True,
                postgresqlRuntimeSync=postgresqlSync,
                scheduledStopped=scheduledStopped,
                nativeStopped=nativeStopped,
                postgresqlRuntimeElapsed=(
                    elapsedTimingReports
                ),
            )

        except Exception as exc:
            logger.exception(
                "Failed to stop protocols. "
                "projectId=%s protocolIds=%s",
                projectId,
                protocolIds,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Failed to stop protocols: %s"
                    % str(exc)
                ),
            )