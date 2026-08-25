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
import socket
import ast
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)
from scipionapi_cli.runtime import (
    getWorkerProcessState,
)

PROTOCOL_TASK_NAME = "app.tasks.executeProtocolTask"

PROTOCOL_ACTIVE_STATUSES = {
    "scheduled",
    "launched",
    "running",
}


class JobMonitoringService:
    def __init__(
            self,
            celeryAppInstance=None,
            inspectTimeout: float = 1.0,
    ):
        self.statusSyncService = (
            RuntimeProtocolStatusSyncService()
        )
        self.inspectTimeout = max(
            0.1,
            float(inspectTimeout),
        )

        if celeryAppInstance is not None:
            self.celeryApp = celeryAppInstance
            self.celeryImportError = None
            return

        try:
            from app.workers.task_queue import celeryApp
            self.celeryApp = celeryApp
            self.celeryImportError = None

        except Exception as error:
            self.celeryApp = None
            self.celeryImportError = str(error)

    @staticmethod
    def _optionalInt(value) -> Optional[int]:
        try:
            value = int(value)
        except (
                TypeError,
                ValueError,
        ):
            return None

        return (
            value
            if value > 0
            else None
        )

    @staticmethod
    def _optionalFloat(value) -> Optional[float]:
        try:
            return float(value)
        except (
                TypeError,
                ValueError,
        ):
            return None

    @staticmethod
    def _normalizeParams(rawParams) -> Dict[str, Any]:
        params = rawParams or {}

        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {}

        return (
            dict(params)
            if isinstance(params, dict)
            else {}
        )

    @staticmethod
    def _normalizeJobIds(rawJobIds) -> List[str]:
        if rawJobIds is None:
            return []

        if isinstance(rawJobIds, str):
            rawValues = (
                rawJobIds
                .replace(";", ",")
                .split(",")
            )
        else:
            try:
                rawValues = list(rawJobIds)
            except TypeError:
                rawValues = [rawJobIds]

        result = []
        seen = set()

        for rawValue in rawValues:
            value = str(
                rawValue or ""
            ).strip()

            if (
                    not value
                    or value == "0"
                    or value in seen
            ):
                continue

            seen.add(value)
            result.append(value)

        return result

    @staticmethod
    def _normalizeTaskArgs(rawArgs) -> List[Any]:
        if isinstance(
                rawArgs,
                (
                    list,
                    tuple,
                ),
        ):
            return list(rawArgs)

        if isinstance(rawArgs, str):
            try:
                parsed = ast.literal_eval(rawArgs)
            except Exception:
                return []

            if isinstance(
                    parsed,
                    (
                        list,
                        tuple,
                    ),
            ):
                return list(parsed)

        return []

    @staticmethod
    def _datetimeFromEpoch(value) -> Optional[datetime]:
        try:
            return datetime.fromtimestamp(
                float(value),
                tz=timezone.utc,
            )
        except (
                TypeError,
                ValueError,
                OSError,
        ):
            return None

    @staticmethod
    def _runtimeMetadata(row) -> Dict[str, Any]:
        if not isinstance(row, dict):
            return {}

        runtimeMetadata = row.get(
            "runtimeMetadata"
        )

        if isinstance(runtimeMetadata, dict):
            return dict(runtimeMetadata)

        params = JobMonitoringService._normalizeParams(
            row.get("params")
        )

        runtimeMetadata = params.get(
            "_scipionWebRuntime"
        ) or {}

        return (
            dict(runtimeMetadata)
            if isinstance(runtimeMetadata, dict)
            else {}
        )

    def _inspectCall(
            self,
            inspector,
            methodName: str,
            errors: List[str],
    ) -> Dict[str, Any]:
        try:
            method = getattr(
                inspector,
                methodName,
            )

            result = method()

            if isinstance(result, dict):
                return result

            errors.append(
                "%s: no response"
                % methodName
            )

            return {}

        except Exception as error:
            errors.append(
                "%s: %s"
                % (
                    methodName,
                    error,
                )
            )

            return {}

    def _getCelerySnapshot(self) -> Dict[str, Any]:
        if self.celeryApp is None:
            return {
                "available": False,
                "error": (
                    self.celeryImportError
                    or "Celery is not available."
                ),
                "stats": {},
                "active": {},
                "reserved": {},
            }

        errors = []

        try:
            inspector = self.celeryApp.control.inspect(
                timeout=self.inspectTimeout
            )
        except Exception as error:
            return {
                "available": False,
                "error": str(error),
                "stats": {},
                "active": {},
                "reserved": {},
            }

        stats = self._inspectCall(
            inspector,
            "stats",
            errors,
        )

        active = self._inspectCall(
            inspector,
            "active",
            errors,
        )

        reserved = self._inspectCall(
            inspector,
            "reserved",
            errors,
        )

        workerNames = (
            set(stats)
            | set(active)
            | set(reserved)
        )

        available = bool(
            workerNames
        )

        error = (
            "; ".join(errors)
            if errors
            else None
        )

        if (
                not available
                and error is None
        ):
            error = (
                "No Celery workers responded."
            )

        return {
            "available": available,
            "error": error,
            "stats": stats,
            "active": active,
            "reserved": reserved,
        }

    @staticmethod
    def _inferWorkerQueues(
            workerName: str,
            tasks,
    ) -> List[str]:
        queues = []

        for task in tasks or []:
            deliveryInfo = (
                task.get(
                    "delivery_info"
                )
                or {}
            )

            queueName = str(
                deliveryInfo.get(
                    "routing_key"
                )
                or ""
            ).strip()

            if (
                    queueName
                    and queueName not in queues
            ):
                queues.append(
                    queueName
                )

        if queues:
            return queues

        loweredName = str(
            workerName or ""
        ).lower()

        if loweredName.startswith(
                "protocols@"
        ):
            return [
                "protocols",
            ]

        if loweredName.startswith(
                "plugins@"
        ):
            return [
                "plugins",
            ]

        return []

    @staticmethod
    def _workerKind(
            workerName: str,
    ) -> Optional[str]:
        name = str(
            workerName or ""
        ).lower()

        if name.startswith(
                "protocols@"
        ):
            return "protocols"

        if name.startswith(
                "plugins@"
        ):
            return "plugins"

        return None

    def _buildWorkers(
            self,
            snapshot,
    ) -> List[Dict[str, Any]]:
        stats = snapshot["stats"]
        active = snapshot["active"]
        reserved = snapshot["reserved"]

        workerNames = (
            set(stats)
            | set(active)
            | set(reserved)
        )

        workers = []

        for workerName in workerNames:
            workerStats = (
                stats.get(
                    workerName
                )
                or {}
            )

            celeryPid = self._optionalInt(
                workerStats.get("pid")
            )

            poolStats = (
                workerStats.get(
                    "pool"
                )
                or {}
            )

            concurrency = self._optionalInt(
                poolStats.get(
                    "max-concurrency"
                )
            )

            if concurrency is None:
                processes = (
                    poolStats.get(
                        "processes"
                    )
                    or []
                )

                concurrency = len(
                    processes
                )

            workerActive = list(
                active.get(
                    workerName
                )
                or []
            )

            workerReserved = list(
                reserved.get(
                    workerName
                )
                or []
            )

            workers.append({
                "name": workerName,
                "queues": self._inferWorkerQueues(
                    workerName,
                    workerActive + workerReserved,
                ),
                "online": True,
                "concurrency": int(
                    concurrency or 0
                ),
                "active": len(
                    workerActive
                ),
                "reserved": len(
                    workerReserved
                ),
                "kind": self._workerKind(
                    workerName
                ),
                "state": "online",
                "pid": celeryPid,
            })

        expectedWorkers = (
            ("protocols", "protocols"),
            ("plugins", "plugins"),
        )

        existingKinds = {
            worker.get("kind")
            for worker in workers
        }

        for (
            workerKind,
            queueName,
        ) in expectedWorkers:
            processState = (
                getWorkerProcessState(
                    workerKind
                )
            )

            matchingWorker = next(
                (
                    worker
                    for worker in workers
                    if worker.get("kind")
                    == workerKind
                ),
                None,
            )

            if matchingWorker is not None:
                matchingWorker["pid"] = (
                        processState.get("pid")
                        or matchingWorker.get("pid")
                )
                continue

            processRunning = (
                processState.get("state")
                == "running"
            )

            workers.append({
                "name": (
                    f"{workerKind}@"
                    f"{socket.gethostname()}"
                ),
                "kind": workerKind,
                "queues": [
                    queueName,
                ],
                "online": False,
                "state": (
                    "unresponsive"
                    if processRunning
                    else "offline"
                ),
                "pid": (
                    processState.get(
                        "pid"
                    )
                ),
                "concurrency": 0,
                "active": 0,
                "reserved": 0,
            })

        workers.sort(
            key=lambda worker: (
                0
                if str(worker["name"]).startswith(
                    "protocols@"
                )
                else 1
                if str(worker["name"]).startswith(
                    "plugins@"
                )
                else 2,
                str(worker["name"]),
            )
        )

        return workers

    def _getCeleryTaskState(
            self,
            taskId: str,
    ):
        state = "STARTED"
        step = None

        if (
                self.celeryApp is None
                or not taskId
        ):
            return state, step

        try:
            taskResult = (
                self.celeryApp
                .AsyncResult(
                    taskId
                )
            )

            taskState = str(
                taskResult.state
                or ""
            ).strip().upper()

            if (
                    taskState
                    and taskState != "PENDING"
            ):
                state = taskState

            taskInfo = (
                taskResult.info
            )

            if isinstance(
                    taskInfo,
                    dict,
            ):
                rawStep = (
                    taskInfo.get(
                        "step"
                    )
                )

                if rawStep:
                    step = str(
                        rawStep
                    )

        except Exception:
            pass

        return state, step

    def _buildRecentJobs(
            self,
            rows,
    ) -> List[Dict[str, Any]]:
        jobs = []

        for row in rows or []:
            runtimeMetadata = (
                self
                ._runtimeMetadata(
                    row
                )
            )

            jobs.append({
                "projectId": int(
                    row["projectId"]
                ),
                "projectName": str(
                    row.get(
                        "projectName"
                    )
                    or ""
                ),
                "protocolId": str(
                    row.get(
                        "protocolId"
                    )
                    or ""
                ),
                "protocolClassName": str(
                    row.get(
                        "protocolClassName"
                    )
                    or ""
                ),
                "status": str(
                    row.get(
                        "status"
                    )
                    or ""
                ).strip().lower(),
                "runtimePid": self._optionalInt(
                    runtimeMetadata.get(
                        "pid"
                    )
                ),
                "jobIds": self._normalizeJobIds(
                    runtimeMetadata.get(
                        "jobIds"
                    )
                ),
                "elapsedTimeSeconds": self._optionalFloat(
                    runtimeMetadata.get(
                        "elapsedTimeSeconds"
                    )
                ),
                "createdAt": row.get(
                    "createdAt"
                ),
                "updatedAt": row.get(
                    "updatedAt"
                ),
            })

        return jobs

    def _buildActiveJobs(
            self,
            mapper,
            snapshot,
            activeRows,
            nowEpochSeconds: float,
    ) -> List[Dict[str, Any]]:
        activeJobs = []
        observedProtocolKeys = set()

        activeByProtocol = {
            (
                int(row["projectId"]),
                str(row["protocolId"]),
            ): row
            for row in activeRows or []
        }

        for workerName, tasks in (
                snapshot["active"]
                        .items()
        ):
            for task in tasks or []:
                if (
                        str(
                            task.get(
                                "name"
                            )
                            or ""
                        )
                        != PROTOCOL_TASK_NAME
                ):
                    continue

                args = self._normalizeTaskArgs(
                    task.get(
                        "args"
                    )
                )

                if len(args) < 2:
                    continue

                try:
                    projectId = int(
                        args[0]
                    )
                    protocolId = int(
                        args[1]
                    )
                except (
                        TypeError,
                        ValueError,
                ):
                    continue

                protocolKey = (
                    projectId,
                    str(protocolId),
                )

                observedProtocolKeys.add(
                    protocolKey
                )

                runMode = str(
                    args[2]
                    if len(args) > 2
                    else "resume"
                )

                protocolRow = (
                        mapper
                        .getProtocolByProtocolId(
                            protocolId=protocolId,
                            projectId=projectId,
                        )
                        or {}
                )

                activeRow = (
                        activeByProtocol.get(
                            protocolKey
                        )
                        or {}
                )

                runtimeMetadata = (
                    self
                    ._runtimeMetadata(
                        protocolRow
                    )
                )

                taskId = str(
                    task.get(
                        "id"
                    )
                    or ""
                )

                celeryState, step = (
                    self
                    ._getCeleryTaskState(
                        taskId
                    )
                )

                timeStart = self._optionalFloat(
                    task.get(
                        "time_start"
                    )
                )

                elapsedSeconds = (
                    max(
                        0.0,
                        nowEpochSeconds
                        - timeStart,
                    )
                    if timeStart is not None
                    else None
                )

                deliveryInfo = (
                        task.get(
                            "delivery_info"
                        )
                        or {}
                )

                activeJobs.append({
                    "taskId": taskId,
                    "projectId": projectId,
                    "projectName": activeRow.get(
                        "projectName"
                    ),
                    "protocolId": str(
                        protocolId
                    ),
                    "protocolClassName": (
                            protocolRow.get(
                                "protocolClassName"
                            )
                            or activeRow.get(
                        "protocolClassName"
                    )
                    ),
                    "runMode": runMode,
                    "celeryState": celeryState,
                    "step": step,
                    "protocolStatus": str(
                        protocolRow.get(
                            "status"
                        )
                        or activeRow.get(
                            "status"
                        )
                        or ""
                    ).strip().lower(),
                    "worker": workerName,
                    "queue": deliveryInfo.get(
                        "routing_key"
                    ),
                    "workerPid": self._optionalInt(
                        task.get(
                            "worker_pid"
                        )
                    ),
                    "protocolPid": self._optionalInt(
                        runtimeMetadata.get(
                            "pid"
                        )
                    ),
                    "jobIds": self._normalizeJobIds(
                        runtimeMetadata.get(
                            "jobIds"
                        )
                    ),
                    "startedAt": self._datetimeFromEpoch(
                        timeStart
                    ),
                    "elapsedSeconds": elapsedSeconds,
                })

        for row in activeRows or []:
            projectId = int(
                row["projectId"]
            )

            protocolId = str(
                row["protocolId"]
            )

            protocolStatus = str(
                row.get(
                    "status"
                )
                or ""
            ).strip().lower()

            if (
                    protocolStatus
                    not in PROTOCOL_ACTIVE_STATUSES
            ):
                continue

            protocolKey = (
                projectId,
                protocolId,
            )

            if protocolKey in observedProtocolKeys:
                continue

            runtimeMetadata = (
                self
                ._runtimeMetadata(
                    row
                )
            )

            activeJobs.append({
                "taskId": (
                        "postgresql:%s:%s"
                        % (
                            projectId,
                            protocolId,
                        )
                ),
                "projectId": projectId,
                "projectName": row.get(
                    "projectName"
                ),
                "protocolId": protocolId,
                "protocolClassName": row.get(
                    "protocolClassName"
                ),
                "runMode": "unknown",
                "celeryState": None,
                "step": None,
                "protocolStatus": protocolStatus,
                "worker": None,
                "queue": None,
                "workerPid": None,
                "protocolPid": self._optionalInt(
                    runtimeMetadata.get(
                        "pid"
                    )
                ),
                "jobIds": self._normalizeJobIds(
                    runtimeMetadata.get(
                        "jobIds"
                    )
                ),
                "startedAt": row.get(
                    "updatedAt"
                ),
                "elapsedSeconds": (
                    self
                    .statusSyncService
                    .getEffectiveElapsedTimeSeconds(
                        runtimeMetadata=runtimeMetadata,
                        statusValue=protocolStatus,
                        nowEpochSeconds=(
                            nowEpochSeconds
                        ),
                    )
                ),
            })

        activeJobs.sort(
            key=lambda job: (
                    job["startedAt"]
                    or datetime.min.replace(
                tzinfo=timezone.utc
            )
            ),
            reverse=True,
        )

        return activeJobs

    def getOverview(
            self,
            mapper,
            recentLimit: int = 25,
    ) -> Dict[str, Any]:
        nowEpochSeconds = (
            time.time()
        )

        activeRows = (
            mapper
            .listActiveProtocolExecutions()
        )

        recentRows = (
            mapper
            .listRecentProtocolExecutions(
                limit=recentLimit
            )
        )

        snapshot = (
            self
            ._getCelerySnapshot()
        )

        return {
            "celeryAvailable": bool(
                snapshot["available"]
            ),
            "celeryError": snapshot[
                "error"
            ],
            "workers": self._buildWorkers(
                snapshot
            ),
            "activeJobs": self._buildActiveJobs(
                mapper=mapper,
                snapshot=snapshot,
                activeRows=activeRows,
                nowEpochSeconds=nowEpochSeconds,
            ),
            "recentJobs": self._buildRecentJobs(
                recentRows
            ),
            "refreshedAt": datetime.fromtimestamp(
                nowEpochSeconds,
                tz=timezone.utc,
            ),
        }