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
import datetime
import logging
import os
import signal
import psutil
import subprocess
import time
from typing import Any, Callable, Dict, List

from fastapi import HTTPException, status
from pyworkflow.object import Set as ScipionSet
from pyworkflow.protocol import STATUS_ABORTED

from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)


logger = logging.getLogger(__name__)


class RuntimeProtocolStopService:
    """
    Stop Scipion runtime protocols.

    PostgreSQL runtime mode is completely independent from:

    - project.sqlite
    - logs/run.db
    - steps.sqlite

    Only the explicitly selected protocols are modified.
    Parent and child protocols remain read-only.
    """

    ABORT_MESSAGE = "Aborted by user."

    @staticmethod
    def _scalarValue(
            value,
            default=None,
    ):
        if value is None:
            return default

        getter = getattr(
            value,
            "get",
            None,
        )

        if callable(getter):
            try:
                return getter()

            except TypeError:
                try:
                    return getter(default)

                except Exception:
                    return default

            except Exception:
                return default

        return value

    def _getProtocolStatus(
            self,
            protocol,
    ) -> str:
        try:
            value = protocol.getStatus()

        except Exception:
            value = self._scalarValue(
                getattr(
                    protocol,
                    "status",
                    None,
                )
            )

        return str(
            value or ""
        ).strip().lower()

    def _getProtocolPid(
            self,
            protocol,
    ):
        for attrName in (
                "_pid",
                "pid",
        ):
            value = self._scalarValue(
                getattr(
                    protocol,
                    attrName,
                    None,
                )
            )

            if value in (
                    None,
                    "",
                    0,
                    "0",
            ):
                continue

            try:
                return int(value)

            except Exception:
                return None

        try:
            value = protocol.getPid()

        except Exception:
            value = None

        if value in (
                None,
                "",
                0,
                "0",
        ):
            return None

        try:
            return int(value)

        except Exception:
            return None

    def _getProtocolJobIds(
            self,
            protocol,
    ) -> List[str]:
        rawJobIds = None

        try:
            rawJobIds = (
                protocol.getJobIds()
            )

        except Exception:
            rawJobIds = self._scalarValue(
                getattr(
                    protocol,
                    "_jobId",
                    None,
                )
            )

        if rawJobIds is None:
            return []

        if isinstance(
                rawJobIds,
                str,
        ):
            if not rawJobIds.strip():
                return []

            rawValues = (
                rawJobIds
                .replace(";", ",")
                .split(",")
            )

        else:
            try:
                rawValues = list(
                    rawJobIds
                )

            except TypeError:
                rawValues = [
                    rawJobIds,
                ]

        jobIds = []
        seen = set()

        for rawValue in rawValues:
            jobId = str(
                rawValue or ""
            ).strip()

            if (
                    not jobId
                    or jobId == "0"
                    or jobId in seen
            ):
                continue

            seen.add(
                jobId
            )

            jobIds.append(
                jobId
            )

        return jobIds

    @staticmethod
    def _safeBooleanCall(
            protocol,
            methodName: str,
    ) -> bool:
        method = getattr(
            protocol,
            methodName,
            None,
        )

        if not callable(method):
            return False

        try:
            return bool(
                method()
            )

        except Exception:
            return False

    @staticmethod
    def _isPidAlive(
            pid,
    ) -> bool:
        if not pid:
            return False

        try:
            os.kill(
                int(pid),
                0,
            )

            return True

        except ProcessLookupError:
            return False

        except PermissionError:
            return True

        except Exception:
            return False

    @staticmethod
    def _reapChildProcess(
            pid,
    ) -> bool:
        """
        Reap a terminated worker when the current API
        process is its direct parent.

        A terminated but unreaped worker remains visible
        as a zombie and os.killpg(pgid, 0) still reports
        that its process group exists.
        """
        if not pid:
            return False

        try:
            waitedPid, _ = os.waitpid(
                int(pid),
                os.WNOHANG,
            )

            return (
                waitedPid
                == int(pid)
            )

        except (
                ChildProcessError,
                ProcessLookupError,
        ):
            # The worker may have been launched by another
            # API process or may already have been reaped.
            return False

        except Exception:
            logger.debug(
                "Could not reap PostgreSQL protocol "
                "worker pid=%s.",
                pid,
                exc_info=True,
            )

            return False

    @staticmethod
    def _isProcessGroupAlive(
            processGroupId,
    ) -> bool:
        """
        Return True only when the process group contains
        at least one process that is still executing.

        Zombie/dead processes do not count as alive.
        """
        if not processGroupId:
            return False

        processGroupId = int(
            processGroupId
        )

        try:
            os.killpg(
                processGroupId,
                0,
            )

        except ProcessLookupError:
            return False

        except PermissionError:
            return True

        except Exception:
            return False

        terminalStatuses = {
            psutil.STATUS_ZOMBIE,
            psutil.STATUS_DEAD,
        }

        try:
            for process in psutil.process_iter([
                "pid",
                "status",
            ]):
                try:
                    if (
                            os.getpgid(
                                process.pid
                            )
                            != processGroupId
                    ):
                        continue

                    processStatus = (
                        process.info.get(
                            "status"
                        )
                    )

                    if (
                            processStatus
                            not in terminalStatuses
                    ):
                        return True

                except (
                        psutil.NoSuchProcess,
                        ProcessLookupError,
                ):
                    continue

                except (
                        psutil.AccessDenied,
                        PermissionError,
                ):
                    # We cannot prove that the process is
                    # stopped, so remain conservative.
                    return True

        except Exception:
            logger.debug(
                "Could not inspect PostgreSQL protocol "
                "process group %s.",
                processGroupId,
                exc_info=True,
            )

            # killpg(..., 0) confirmed that something
            # exists, but inspection failed.
            return True

        # The group disappeared during inspection or all
        # its remaining members are zombies/dead.
        return False

    @staticmethod
    def _getProcessCommandLine(
            pid: int,
    ) -> List[str]:
        commandLinePath = (
            "/proc/%s/cmdline"
            % int(pid)
        )

        try:
            with open(
                    commandLinePath,
                    "rb",
            ) as commandLineFile:
                rawCommandLine = (
                    commandLineFile.read()
                )

        except FileNotFoundError:
            return []

        except PermissionError as error:
            raise RuntimeError(
                "Cannot verify protocol worker pid=%s: %s"
                % (
                    pid,
                    error,
                )
            ) from error

        except Exception as error:
            raise RuntimeError(
                "Cannot inspect protocol worker pid=%s: %s"
                % (
                    pid,
                    error,
                )
            ) from error

        return [
            token.decode(
                errors="replace"
            )
            for token in rawCommandLine.split(
                b"\0"
            )
            if token
        ]

    def _assertProtocolWorkerPid(
            self,
            *,
            pid: int,
            projectId: int,
            protocolId: int,
    ) -> Dict[str, Any]:
        commandLine = (
            self._getProcessCommandLine(
                pid
            )
        )

        if not commandLine:
            return {
                "verified": False,
                "processMissing": True,
                "commandLine": [],
            }

        commandText = " ".join(
            commandLine
        )

        expectedModule = (
            "app.backend.runtime."
            "postgresql_protocol_worker"
        )

        expectedProjectId = str(
            projectId
        )

        expectedProtocolId = str(
            protocolId
        )

        moduleMatches = (
            expectedModule
            in commandText
        )

        projectMatches = False
        protocolMatches = False

        for index, token in enumerate(
                commandLine
        ):
            if (
                    token == "--project-id"
                    and index + 1
                    < len(commandLine)
            ):
                projectMatches = (
                    commandLine[index + 1]
                    == expectedProjectId
                )

            if (
                    token == "--protocol-id"
                    and index + 1
                    < len(commandLine)
            ):
                protocolMatches = (
                    commandLine[index + 1]
                    == expectedProtocolId
                )

        if not (
                moduleMatches
                and projectMatches
                and protocolMatches
        ):
            raise RuntimeError(
                "Refusing to terminate pid=%s because it "
                "does not belong to PostgreSQL protocol "
                "projectId=%s protocolId=%s. command=%s"
                % (
                    pid,
                    projectId,
                    protocolId,
                    commandText,
                )
            )

        return {
            "verified": True,
            "processMissing": False,
            "commandLine": commandLine,
        }

    def _killProcessGroup(
            self,
            *,
            pid: int,
            projectId: int,
            protocolId: int,
    ) -> Dict[str, Any]:
        if not self._isPidAlive(
                pid
        ):
            raise RuntimeError(
                "Cannot stop active PostgreSQL protocol "
                "projectId=%s protocolId=%s because its "
                "stored pid=%s is not alive. The protocol "
                "state will not be changed."
                % (
                    projectId,
                    protocolId,
                    pid,
                )
            )

        verification = (
            self._assertProtocolWorkerPid(
                pid=int(pid),
                projectId=int(projectId),
                protocolId=int(protocolId),
            )
        )

        if verification.get(
                "processMissing"
        ):
            raise RuntimeError(
                "Cannot stop PostgreSQL protocol "
                "projectId=%s protocolId=%s because "
                "pid=%s disappeared before a stop "
                "signal could be sent. The protocol "
                "state will not be changed."
                % (
                    projectId,
                    protocolId,
                    pid,
                )
            )

        try:
            processGroupId = os.getpgid(
                int(pid)
            )

        except ProcessLookupError as error:
            raise RuntimeError(
                "Cannot stop PostgreSQL protocol "
                "projectId=%s protocolId=%s because "
                "pid=%s disappeared before its process "
                "group could be resolved. The protocol "
                "state will not be changed."
                % (
                    projectId,
                    protocolId,
                    pid,
                )
            ) from error

        currentProcessGroupId = (
            os.getpgrp()
        )

        if (
                int(processGroupId)
                == int(currentProcessGroupId)
        ):
            raise RuntimeError(
                "Refusing to terminate PostgreSQL "
                "protocol process group %s because it "
                "matches the API process group."
                % processGroupId
            )

        try:
            os.killpg(
                processGroupId,
                signal.SIGTERM,
            )

        except ProcessLookupError as error:
            raise RuntimeError(
                "Cannot confirm the stop of PostgreSQL "
                "protocol projectId=%s protocolId=%s. "
                "Process group %s disappeared before "
                "SIGTERM could be delivered, so the "
                "protocol state will not be changed."
                % (
                    projectId,
                    protocolId,
                    processGroupId,
                )
            ) from error

        except Exception as error:
            raise RuntimeError(
                "Could not send SIGTERM to PostgreSQL "
                "protocol process group %s: %s"
                % (
                    processGroupId,
                    error,
                )
            ) from error

        for _ in range(15):
            self._reapChildProcess(
                pid
            )

            if not self._isProcessGroupAlive(
                    processGroupId
            ):
                return {
                    "pid": int(pid),
                    "processGroupId": (
                        int(processGroupId)
                    ),
                    "terminated": True,
                    "alreadyStopped": False,
                    "signal": "SIGTERM",
                    "verified": True,
                }

            time.sleep(
                0.2
            )

        try:
            os.killpg(
                processGroupId,
                signal.SIGKILL,
            )

        except ProcessLookupError:
            self._reapChildProcess(
                pid
            )
            return {
                "pid": int(pid),
                "processGroupId": (
                    int(processGroupId)
                ),
                "terminated": True,
                "alreadyStopped": False,
                "signal": "SIGKILL",
                "verified": True,
            }

        except Exception as error:
            raise RuntimeError(
                "Could not send SIGKILL to PostgreSQL "
                "protocol process group %s: %s"
                % (
                    processGroupId,
                    error,
                )
            ) from error

        for _ in range(10):
            self._reapChildProcess(
                pid
            )

            if not self._isProcessGroupAlive(
                    processGroupId
            ):
                return {
                    "pid": int(pid),
                    "processGroupId": (
                        int(processGroupId)
                    ),
                    "terminated": True,
                    "alreadyStopped": False,
                    "signal": "SIGKILL",
                    "verified": True,
                }

            time.sleep(
                0.1
            )

        raise RuntimeError(
            "PostgreSQL protocol process group %s "
            "is still alive after SIGKILL."
            % processGroupId
        )

    def _cancelQueueJobs(
            self,
            protocol,
    ) -> List[Dict[str, Any]]:
        jobIds = (
            self._getProtocolJobIds(
                protocol
            )
        )

        if not jobIds:
            return []

        try:
            hostConfig = (
                protocol.getHostConfig()
            )

            cancelCommandTemplate = (
                hostConfig.getCancelCommand()
            )

        except Exception as error:
            raise RuntimeError(
                "Could not load the queue cancel "
                "command: %s"
                % error
            ) from error

        if not cancelCommandTemplate:
            raise RuntimeError(
                "Queue cancellation command is not configured"
            )

        reports = []

        for jobId in jobIds:
            try:
                cancelCommand = (
                    cancelCommandTemplate
                    % {
                        "JOB_ID": jobId,
                    }
                )

            except Exception as error:
                raise RuntimeError(
                    "Could not build queue cancellation "
                    "command for job %s: %s"
                    % (
                        jobId,
                        error,
                    )
                ) from error

            completedProcess = subprocess.run(
                cancelCommand,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
            )

            report = {
                "jobId": str(jobId),
                "command": cancelCommand,
                "returnCode": int(
                    completedProcess.returncode
                ),
                "stdout": str(
                    completedProcess.stdout
                    or ""
                ).strip(),
                "stderr": str(
                    completedProcess.stderr
                    or ""
                ).strip(),
            }

            reports.append(
                report
            )

            if (
                    completedProcess.returncode
                    != 0
            ):
                raise RuntimeError(
                    "Queue cancellation failed for "
                    "job %s with return code %s: %s"
                    % (
                        jobId,
                        completedProcess.returncode,
                        report["stderr"]
                        or report["stdout"],
                    )
                )

        return reports

    @staticmethod
    def _setScalarAttribute(
            target,
            attributeName: str,
            value,
    ) -> bool:
        attribute = getattr(
            target,
            attributeName,
            None,
        )

        setter = getattr(
            attribute,
            "set",
            None,
        )

        if not callable(setter):
            return False

        setter(
            value
        )

        return True

    def _markProtocolAbortedInMemory(
            self,
            protocol,
    ) -> None:
        setStatus = getattr(
            protocol,
            "setStatus",
            None,
        )

        if callable(setStatus):
            setStatus(
                STATUS_ABORTED
            )

        else:
            self._setScalarAttribute(
                protocol,
                "status",
                STATUS_ABORTED,
            )

        self._setScalarAttribute(
            protocol,
            "endTime",
            datetime.datetime.now(),
        )

        self._setScalarAttribute(
            protocol,
            "_error",
            self.ABORT_MESSAGE,
        )

        self._setScalarAttribute(
            protocol,
            "_pid",
            0,
        )

        jobIdsAttribute = getattr(
            protocol,
            "_jobId",
            None,
        )

        clearJobIds = getattr(
            jobIdsAttribute,
            "clear",
            None,
        )

        if callable(clearJobIds):
            clearJobIds()

        else:
            setJobIds = getattr(
                jobIdsAttribute,
                "set",
                None,
            )

            if callable(setJobIds):
                setJobIds(
                    []
                )

    def _abortRunningProtocolSteps(
            self,
            *,
            mapper,
            projectId: int,
            protocolDbId: int,
    ) -> Dict[str, Any]:
        cursor = mapper.db.execute(
            """
            UPDATE protocol_steps
               SET status = %s,
                   "endTime" = COALESCE(
                       "endTime",
                       NOW()
                   ),
                   error = CASE
                       WHEN error IS NULL
                            OR BTRIM(error) = ''
                       THEN %s
                       ELSE error
                   END,
                   "updatedAt" = NOW()
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND LOWER(status) = 'running'
            """,
            (
                str(STATUS_ABORTED),
                self.ABORT_MESSAGE,
                int(projectId),
                int(protocolDbId),
            ),
        )

        return {
            "protocolDbId": int(
                protocolDbId
            ),
            "stepsAborted": int(
                getattr(
                    cursor,
                    "rowcount",
                    0,
                )
                or 0
            ),
        }

    def _closePostgresqlOutputSets(
            self,
            *,
            mapper,
            projectId: int,
            protocolDbId: int,
    ) -> Dict[str, Any]:
        storedSets = mapper.db.fetchAll(
            """
            SELECT id,
                   "outputName"
              FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
             ORDER BY "outputName"
            """,
            (
                int(projectId),
                int(protocolDbId),
            ),
        ) or []

        if not storedSets:
            return {
                "protocolDbId": int(
                    protocolDbId
                ),
                "setsClosed": 0,
                "outputs": [],
            }

        closedState = int(
            ScipionSet.STREAM_CLOSED
        )

        with mapper.db.transaction():
            mapper.db.execute(
                """
                UPDATE scipion_sets
                   SET properties = jsonb_set(
                           jsonb_set(
                               COALESCE(
                                   properties,
                                   '{}'::jsonb
                               ),
                               '{streamState}',
                               TO_JSONB(%s::integer),
                               TRUE
                           ),
                           '{_streamState}',
                           TO_JSONB(%s::integer),
                           TRUE
                       ),
                       "updatedAt" = NOW()
                 WHERE "projectId" = %s
                   AND "protocolDbId" = %s
                """,
                (
                    closedState,
                    closedState,
                    int(projectId),
                    int(protocolDbId),
                ),
                commit=False,
            )

            for propertyName in (
                    "streamState",
                    "_streamState",
            ):
                mapper.db.execute(
                    """
                    INSERT INTO scipion_set_properties (
                        "setId",
                        key,
                        value
                    )
                    SELECT id,
                           %s,
                           %s
                      FROM scipion_sets
                     WHERE "projectId" = %s
                       AND "protocolDbId" = %s
                    ON CONFLICT ON CONSTRAINT
                        ux_scipion_set_properties_set_key
                    DO UPDATE SET
                        value = EXCLUDED.value
                    """,
                    (
                        propertyName,
                        str(closedState),
                        int(projectId),
                        int(protocolDbId),
                    ),
                    commit=False,
                )

        return {
            "protocolDbId": int(
                protocolDbId
            ),
            "setsClosed": len(
                storedSets
            ),
            "outputs": [
                str(
                    row.get(
                        "outputName"
                    )
                    or ""
                )
                for row in storedSets
            ],
        }

    @staticmethod
    def _getPostgresqlRuntimeMapper(
            currentProject,
    ):
        getter = getattr(
            currentProject,
            "getPostgresqlRuntimeMapper",
            None,
        )

        if not callable(getter):
            raise RuntimeError(
                "Current project does not expose "
                "a PostgreSQL runtime mapper"
            )

        runtimeMapper = getter()

        if runtimeMapper is None:
            raise RuntimeError(
                "PostgreSQL runtime mapper is not available"
            )

        return runtimeMapper

    def _stopPostgresqlProtocols(
            self,
            *,
            mapper,
            projectId: int,
            resolvedProtocols,
            currentProject,
            buildProtocolMutationResultCallback: Callable,
    ) -> Dict[str, Any]:
        runtimeMapper = (
            self._getPostgresqlRuntimeMapper(
                currentProject
            )
        )

        statusService = (
            RuntimeProtocolStatusSyncService()
        )

        stopped = []
        skipped = []
        localStopped = []
        queueStopped = []
        stepReports = []
        outputReports = []
        statusReports = []
        elapsedReports = []

        for protocol in resolvedProtocols:
            protocolId = getattr(
                protocol,
                "getObjId",
                lambda: None,
            )()

            if protocolId in (
                    None,
                    "",
            ):
                raise RuntimeError(
                    "Cannot stop protocol without runtime id"
                )

            protocolId = int(
                protocolId
            )

            storedRow = (
                mapper
                .getProjectProtocolByProtocolId(
                    projectId=projectId,
                    protocolId=protocolId,
                )
            )

            if not storedRow:
                raise RuntimeError(
                    "Protocol %s was not found "
                    "in PostgreSQL"
                    % protocolId
                )

            protocolDbId = int(
                storedRow["id"]
            )

            protocolStatus = (
                self._getProtocolStatus(
                    protocol
                )
            )

            if (
                    protocolStatus
                    not in
                    RuntimeProtocolStatusSyncService
                    .ACTIVE_STATUS_TEXTS
            ):
                skipped.append({
                    "protocolId": str(
                        protocolId
                    ),
                    "protocolDbId": (
                        protocolDbId
                    ),
                    "status": (
                        protocolStatus
                    ),
                    "reason": (
                        "protocol_not_active"
                    ),
                })

                continue

            elapsedSnapshot = (
                statusService
                .captureProtocolElapsedState(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                )
            )

            stoppedAtEpochSeconds = (
                time.time()
            )

            pid = self._getProtocolPid(
                protocol
            )

            jobIds = (
                self._getProtocolJobIds(
                    protocol
                )
            )

            usesQueueForProtocol = (
                self._safeBooleanCall(
                    protocol,
                    "useQueueForProtocol",
                )
            )

            usesQueueForSteps = (
                self._safeBooleanCall(
                    protocol,
                    "useQueueForSteps",
                )
            )

            queueReports = []

            if jobIds:
                queueReports = (
                    self._cancelQueueJobs(
                        protocol
                    )
                )

                queueStopped.append({
                    "protocolId": str(
                        protocolId
                    ),
                    "protocolDbId": (
                        protocolDbId
                    ),
                    "jobIds": list(
                        jobIds
                    ),
                    "queueForProtocol": (
                        usesQueueForProtocol
                    ),
                    "queueForSteps": (
                        usesQueueForSteps
                    ),
                    "reports": (
                        queueReports
                    ),
                })

            processReport = None

            # Queue-for-steps still has a local PostgreSQL
            # worker coordinating the queue jobs.
            #
            # A scheduled protocol may also have a coordinator
            # PID before it submits the actual queue job.
            if pid:
                processReport = (
                    self._killProcessGroup(
                        pid=pid,
                        projectId=projectId,
                        protocolId=protocolId,
                    )
                )

                localStopped.append({
                    "protocolId": str(
                        protocolId
                    ),
                    "protocolDbId": (
                        protocolDbId
                    ),
                    **processReport,
                })

            processTerminationConfirmed = bool(
                processReport
                and processReport.get(
                    "terminated"
                )
            )

            queueTerminationConfirmed = bool(
                queueReports
            )

            if not (
                    processTerminationConfirmed
                    or queueTerminationConfirmed
            ):
                raise RuntimeError(
                    "Cannot mark PostgreSQL protocol %s "
                    "as aborted because no local process "
                    "or queue job termination was confirmed. "
                    "pid=%s jobIds=%s"
                    % (
                        protocolId,
                        pid,
                        jobIds,
                    )
                )

            self._markProtocolAbortedInMemory(
                protocol
            )

            runtimeMapper.store(
                protocol
            )

            runtimeMapper.commit()

            stepReport = (
                self._abortRunningProtocolSteps(
                    mapper=mapper,
                    projectId=projectId,
                    protocolDbId=protocolDbId,
                )
            )

            outputReport = (
                self._closePostgresqlOutputSets(
                    mapper=mapper,
                    projectId=projectId,
                    protocolDbId=protocolDbId,
                )
            )

            statusReport = (
                statusService
                .markProtocolAborted(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                )
            )

            elapsedReport = (
                statusService
                .finalizeProtocolElapsedTime(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                    elapsedSnapshot=elapsedSnapshot,
                    stoppedAtEpochSeconds=(
                        stoppedAtEpochSeconds
                    ),
                )
            )

            stepReports.append(
                stepReport
            )

            outputReports.append(
                outputReport
            )

            statusReports.append(
                statusReport
            )

            elapsedReports.append(
                elapsedReport
            )

            stopped.append({
                "protocolId": str(
                    protocolId
                ),
                "protocolDbId": (
                    protocolDbId
                ),
                "previousStatus": (
                    protocolStatus
                ),
                "status": str(
                    STATUS_ABORTED
                ),
                "pid": pid,
                "jobIds": list(
                    jobIds
                ),
                "process": (
                    processReport
                ),
                "queue": (
                    queueReports
                ),
                "steps": (
                    stepReport
                ),
                "outputs": (
                    outputReport
                ),
            })

        return (
            buildProtocolMutationResultCallback(
                "Protocol stopped successfully",
                protocolsCount=len(
                    stopped
                ),
                dependenciesCount=0,
                postgresqlRuntimeStop=True,
                postgresqlOnly=True,
                usesProjectSqlite=False,
                usesRunDb=False,
                usesStepsSqlite=False,
                stopped=stopped,
                skipped=skipped,
                localStopped=localStopped,
                queueStopped=queueStopped,
                postgresqlRuntimeStatus=(
                    statusReports
                ),
                postgresqlRuntimeElapsed=(
                    elapsedReports
                ),
                postgresqlRuntimeSteps=(
                    stepReports
                ),
                postgresqlRuntimeOutputs=(
                    outputReports
                ),
                postgresqlPointerRestore=None,
                postgresqlRuntimeSync=None,
                missingExecutionMirrors=[],
                degradedStop=False,
            )
        )

    def _stopLegacyProtocols(
            self,
            *,
            resolvedProtocols,
            currentProject,
            buildProtocolMutationResultCallback: Callable,
    ) -> Dict[str, Any]:
        stopped = []

        for protocol in resolvedProtocols:
            currentProject.stopProtocol(
                protocol
            )

            stopped.append(
                str(
                    protocol.getObjId()
                )
            )

        return (
            buildProtocolMutationResultCallback(
                "Protocol stopped successfully",
                protocolsCount=len(
                    stopped
                ),
                dependenciesCount=0,
                nativeStopped=stopped,
                postgresqlRuntimeStop=False,
            )
        )

    def stopProtocols(
            self,
            *,
            mapper,
            projectId: int,
            protocolIds,
            usingPostgresqlRuntime: bool,
            currentProject,
            getScipionProtocolForRuntimeCallback: Callable,
            buildProtocolMutationResultCallback: Callable,
    ) -> Dict[str, Any]:
        """
        Stop only the explicitly selected protocols.

        External parents, children and their outputs remain
        completely untouched.
        """
        resolvedProtocols = []
        seenProtocolIds = set()

        for rawProtocolId in (
                protocolIds or []
        ):
            protocol = (
                getScipionProtocolForRuntimeCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=rawProtocolId,
                )
            )

            protocolId = getattr(
                protocol,
                "getObjId",
                lambda: None,
            )()

            protocolIdText = str(
                protocolId
            )

            if protocolIdText in seenProtocolIds:
                continue

            seenProtocolIds.add(
                protocolIdText
            )

            resolvedProtocols.append(
                protocol
            )

        if not resolvedProtocols:
            raise HTTPException(
                status_code=(
                    status
                    .HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail=(
                    "No valid protocols to stop"
                ),
            )

        try:
            if usingPostgresqlRuntime:
                return (
                    self
                    ._stopPostgresqlProtocols(
                        mapper=mapper,
                        projectId=projectId,
                        resolvedProtocols=(
                            resolvedProtocols
                        ),
                        currentProject=(
                            currentProject
                        ),
                        buildProtocolMutationResultCallback=(
                            buildProtocolMutationResultCallback
                        ),
                    )
                )

            return (
                self
                ._stopLegacyProtocols(
                    resolvedProtocols=(
                        resolvedProtocols
                    ),
                    currentProject=(
                        currentProject
                    ),
                    buildProtocolMutationResultCallback=(
                        buildProtocolMutationResultCallback
                    ),
                )
            )

        except HTTPException:
            raise

        except Exception as error:
            logger.exception(
                "Failed to stop protocols. "
                "projectId=%s protocolIds=%s",
                projectId,
                protocolIds,
            )

            raise HTTPException(
                status_code=(
                    status
                    .HTTP_500_INTERNAL_SERVER_ERROR
                ),
                detail=(
                    "Failed to stop protocols: %s"
                    % error
                ),
            ) from error