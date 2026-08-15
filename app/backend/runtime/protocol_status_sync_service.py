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
import json
import logging
import time
from typing import Any, Dict, Optional

from pyworkflow.protocol import STATUS_NEW, STATUS_ABORTED
from app.backend.runtime.postgresql_runtime_event_service import (
    PostgresqlRuntimeEventPublisher,
)

logger = logging.getLogger(__name__)


class RuntimeProtocolStatusSyncService:
    """Manage PostgreSQL runtime protocol status, timing and process metadata."""
    RUNTIME_METADATA_KEY = "_scipionWebRuntime"

    ACTIVE_STATUS_TEXTS = {
        "launched",
        "running",
        "scheduled",
    }

    TERMINAL_STATUS_TEXTS = {
        "finished",
        "failed",
        "aborted",
        "interactive",
    }

    FINAL_SYNC_PENDING_KEY = "finalSyncPending"
    ELAPSED_UPDATED_AT_KEY = (
        "elapsedUpdatedAtEpochSeconds"
    )

    ELAPSED_ACTIVE_STATUS_TEXTS = {
        "launched",
        "running",
    }

    @staticmethod
    def safeCall(obj: Any, methodName: str, default: Any = None) -> Any:
        try:
            method = getattr(obj, methodName, None)
            if method is None:
                return default
            return method()
        except Exception:
            return default

    @staticmethod
    def scalarValue(value: Any) -> Any:
        if value is None:
            return None

        getter = getattr(value, "get", None)

        if callable(getter):
            try:
                return getter()
            except TypeError:
                try:
                    return getter(None)
                except Exception:
                    return None
            except Exception:
                return None

        return value

    def getProtocolPid(
            self,
            protocol,
    ) -> Optional[int]:
        pid = self.safeCall(
            protocol,
            "getPid",
            None,
        )

        if pid is None:
            pid = self.scalarValue(
                getattr(
                    protocol,
                    "_pid",
                    None,
                )
            )

        try:
            pid = int(
                pid
            )

        except (
                TypeError,
                ValueError,
        ):
            return None

        return (
            pid
            if pid > 0
            else None
        )

    def getProtocolJobIds(
            self,
            protocol,
    ):
        rawJobIds = self.safeCall(
            protocol,
            "getJobIds",
            None,
        )

        if rawJobIds is None:
            rawJobIds = self.scalarValue(
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

    def buildRuntimeMetadata(self, protocol) -> Dict[str, Any]:
        cpuTimeValue = getattr(protocol, "_cpuTime", None)

        if cpuTimeValue is None:
            cpuTimeValue = getattr(protocol, "cpuTime", None)

        return {
            "cpuTimeSeconds": self.toSeconds(cpuTimeValue),
            "elapsedTimeSeconds": self.toSeconds(self.safeCall(protocol, "getElapsedTime", None)),
            "pid": self.getProtocolPid(protocol),
            "jobIds": self.getProtocolJobIds(protocol),
        }

    def persistProtocolProcessIdentity(
            self,
            mapper,
            projectId: int,
            protocolId,
            protocol,
    ) -> Dict[str, Any]:
        """
        Persist only the active process and queue identity.

        This is used by QueueStepExecutor whenever a step job
        is submitted to or removed from the queue.
        """
        row = (
            mapper
            .getProjectProtocolByProtocolId(
                projectId=projectId,
                protocolId=protocolId,
            )
        )

        if not row:
            raise RuntimeError(
                "Cannot persist protocol process identity: "
                "protocol row was not found. "
                "projectId=%s protocolId=%s"
                % (
                    projectId,
                    protocolId,
                )
            )

        params = self.normalizeParams(
            row.get(
                "params"
            )
        )

        runtimeMetadata = params.get(
            self.RUNTIME_METADATA_KEY
        ) or {}

        if not isinstance(
                runtimeMetadata,
                dict,
        ):
            runtimeMetadata = {}

        runtimeMetadata = dict(
            runtimeMetadata
        )

        pid = self.getProtocolPid(
            protocol
        )

        jobIds = self.getProtocolJobIds(
            protocol
        )

        runtimeMetadata["pid"] = pid
        runtimeMetadata["jobIds"] = list(
            jobIds
        )

        params[
            self.RUNTIME_METADATA_KEY
        ] = runtimeMetadata

        mapper.updateProtocol({
            "id": row["id"],
            "params": json.dumps(
                params,
                ensure_ascii=False,
            ),
        })

        return {
            "protocolId": str(
                protocolId
            ),
            "pid": pid,
            "jobIds": list(
                jobIds
            ),
        }

    def resetProtocolRuntimeMetadata(
            self,
            mapper,
            projectId: int,
            protocolId,
    ) -> Dict[str, Any]:
        """
        Clear execution-specific PostgreSQL metadata after
        resetting a protocol to SAVED.

        Reset-from does not launch a new worker, so elapsed
        metadata cannot be deferred to markProtocolLaunched().
        """
        row = (
            mapper
            .getProjectProtocolByProtocolId(
                projectId=projectId,
                protocolId=protocolId,
            )
        )

        if not row:
            raise RuntimeError(
                "Cannot reset protocol runtime metadata: "
                "protocol row was not found. "
                "projectId=%s protocolId=%s"
                % (
                    projectId,
                    protocolId,
                )
            )

        params = self.normalizeParams(
            row.get(
                "params"
            )
        )

        runtimeMetadata = params.get(
            self.RUNTIME_METADATA_KEY
        ) or {}

        if not isinstance(
                runtimeMetadata,
                dict,
        ):
            runtimeMetadata = {}

        runtimeMetadata = dict(
            runtimeMetadata
        )

        runtimeMetadata[
            "cpuTimeSeconds"
        ] = 0.0

        runtimeMetadata[
            "elapsedTimeSeconds"
        ] = 0.0

        runtimeMetadata[
            "pid"
        ] = None

        runtimeMetadata[
            "jobIds"
        ] = []

        runtimeMetadata.pop(
            self.ELAPSED_UPDATED_AT_KEY,
            None,
        )

        runtimeMetadata.pop(
            self.FINAL_SYNC_PENDING_KEY,
            None,
        )

        params[
            self.RUNTIME_METADATA_KEY
        ] = runtimeMetadata

        mapper.updateProtocol({
            "id": row["id"],
            "params": json.dumps(
                params,
                ensure_ascii=False,
            ),
        })

        return {
            "protocolId": str(
                protocolId
            ),
            "cpuTimeSeconds": 0.0,
            "elapsedTimeSeconds": 0.0,
            "pid": None,
            "jobIds": [],
        }

    def toSeconds(self, value: Any) -> Optional[float]:
        value = self.scalarValue(value)

        if value is None:
            return None

        totalSeconds = getattr(
            value,
            "total_seconds",
            None,
        )

        if callable(totalSeconds):
            try:
                value = totalSeconds()
            except Exception:
                return None

        try:
            return float(value)
        except Exception:
            return None

    def normalizeParams(
            self,
            rawParams,
    ) -> Dict[str, Any]:
        params = rawParams or {}

        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {}

        if not isinstance(params, dict):
            params = {}

        return dict(params)

    def persistProtocolExecutionUser(
            self,
            mapper,
            projectId: int,
            protocolId,
            userId: int,
    ) -> Dict[str, Any]:
        row = (
            mapper
            .getProjectProtocolByProtocolId(
                projectId=projectId,
                protocolId=protocolId,
            )
        )

        if not row:
            raise RuntimeError(
                "Cannot persist protocol execution user: "
                "protocol row was not found. "
                "projectId=%s protocolId=%s"
                % (
                    projectId,
                    protocolId,
                )
            )

        params = self.normalizeParams(
            row.get(
                "params"
            )
        )

        runtimeMetadata = params.get(
            self.RUNTIME_METADATA_KEY
        ) or {}

        if not isinstance(
                runtimeMetadata,
                dict,
        ):
            runtimeMetadata = {}

        runtimeMetadata = dict(
            runtimeMetadata
        )

        runtimeMetadata[
            "launchedByUserId"
        ] = int(userId)

        params[
            self.RUNTIME_METADATA_KEY
        ] = runtimeMetadata

        mapper.updateProtocol({
            "id": row["id"],
            "params": json.dumps(
                params,
                ensure_ascii=False,
            ),
        })

        return {
            "projectId": int(projectId),
            "protocolId": str(protocolId),
            "launchedByUserId": int(userId),
        }

    def mergeRuntimeProtocolStatus(self, storedStatus, runtimeStatus):
        storedText = str(storedStatus or "").strip().lower()
        runtimeText = str(runtimeStatus or "").strip().lower()

        if not runtimeText:
            return storedStatus or STATUS_NEW

        if runtimeText == "new" and storedText in self.ACTIVE_STATUS_TEXTS:
            return storedStatus

        if storedText in self.TERMINAL_STATUS_TEXTS and runtimeText not in self.TERMINAL_STATUS_TEXTS:
            return storedStatus

        return runtimeStatus

    def getEffectiveElapsedTimeSeconds(self, runtimeMetadata: Any, statusValue, nowEpochSeconds: Optional[float] = None, fallbackElapsedSeconds: Any = None) -> float:
        fallbackSeconds = max(0.0, float(self.toSeconds(fallbackElapsedSeconds) or 0.0))

        if not isinstance(runtimeMetadata, dict):
            return fallbackSeconds

        elapsedSeconds = max(0.0, float(self.toSeconds(runtimeMetadata.get("elapsedTimeSeconds")) or 0.0))
        statusText = str(statusValue or "").strip().lower()

        if statusText not in self.ELAPSED_ACTIVE_STATUS_TEXTS:
            return max(elapsedSeconds, fallbackSeconds)

        previousUpdate = self.toSeconds(runtimeMetadata.get(self.ELAPSED_UPDATED_AT_KEY))

        if previousUpdate is None:
            return max(elapsedSeconds, fallbackSeconds)

        nowEpochSeconds = float(nowEpochSeconds if nowEpochSeconds is not None else time.time())

        if nowEpochSeconds < float(previousUpdate):
            return max(elapsedSeconds, fallbackSeconds)

        projectedElapsedSeconds = elapsedSeconds + nowEpochSeconds - float(previousUpdate)
        return max(projectedElapsedSeconds, fallbackSeconds)

    def getStoredElapsedTimeSeconds(
            self,
            mapper,
            projectId: int,
            protocolId,
    ) -> float:
        row = mapper.getProjectProtocolByProtocolId(
            projectId=projectId,
            protocolId=protocolId,
        )

        if not row:
            return 0.0

        params = self.normalizeParams(
            row.get("params")
        )

        runtimeMetadata = params.get(
            self.RUNTIME_METADATA_KEY
        ) or {}

        if not isinstance(runtimeMetadata, dict):
            return 0.0

        elapsedSeconds = self.toSeconds(
            runtimeMetadata.get(
                "elapsedTimeSeconds"
            )
        )

        return max(
            0.0,
            float(elapsedSeconds or 0.0),
        )

    def markProtocolAborted(
            self,
            mapper,
            projectId: int,
            protocolId,
    ) -> Dict[str, Any]:
        row = mapper.getProjectProtocolByProtocolId(
            projectId=projectId,
            protocolId=protocolId,
        )

        if not row:
            raise RuntimeError(
                "Cannot mark runtime protocol as aborted: "
                "protocol row not found. "
                f"projectId={projectId} "
                f"protocolId={protocolId}"
            )

        mapper.updateProtocol({
            "id": row["id"],
            "status": STATUS_ABORTED,
        })

        PostgresqlRuntimeEventPublisher.publish(
            db=mapper.db,
            projectId=projectId,
            eventType=(
                "protocol_changed"
            ),
            protocolId=protocolId,
            protocolDbId=row["id"],
            status=str(
                STATUS_ABORTED
            ),
        )

        return {
            "protocolId": str(protocolId),
            "status": STATUS_ABORTED,
        }

    def markProtocolLaunched(
            self,
            mapper,
            projectId: int,
            protocolId,
            baseElapsedTimeSeconds: float = 0.0,
            resetElapsed: bool = False,
    ) -> Dict[str, Any]:
        row = mapper.getProjectProtocolByProtocolId(
            projectId=projectId,
            protocolId=protocolId,
        )

        if not row:
            raise RuntimeError(
                "Cannot initialize runtime elapsed time: "
                "protocol row not found. "
                f"projectId={projectId} "
                f"protocolId={protocolId}"
            )

        params = self.normalizeParams(
            row.get("params")
        )

        runtimeMetadata = params.get(
            self.RUNTIME_METADATA_KEY
        ) or {}

        if not isinstance(runtimeMetadata, dict):
            runtimeMetadata = {}

        runtimeMetadata = dict(runtimeMetadata)

        elapsedSeconds = (
            0.0
            if resetElapsed
            else max(
                0.0,
                float(
                    baseElapsedTimeSeconds
                    or 0.0
                ),
            )
        )

        runtimeMetadata[
            "elapsedTimeSeconds"
        ] = elapsedSeconds

        runtimeMetadata[
            self.ELAPSED_UPDATED_AT_KEY
        ] = time.time()

        params[
            self.RUNTIME_METADATA_KEY
        ] = runtimeMetadata

        mapper.updateProtocol({
            "id": row["id"],
            "params": json.dumps(
                params,
                ensure_ascii=False,
            ),
        })

        return {
            "protocolId": str(protocolId),
            "elapsedTimeSeconds": elapsedSeconds,
            "resetElapsed": bool(resetElapsed),
        }

    def updateElapsedTimeMetadata(
            self,
            params: Dict[str, Any],
            statusValue,
            nowEpochSeconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        params = self.normalizeParams(params)

        runtimeMetadata = params.get(
            self.RUNTIME_METADATA_KEY
        ) or {}

        if not isinstance(runtimeMetadata, dict):
            runtimeMetadata = {}

        runtimeMetadata = dict(runtimeMetadata)

        elapsedSeconds = self.toSeconds(
            runtimeMetadata.get(
                "elapsedTimeSeconds"
            )
        )

        elapsedSeconds = max(
            0.0,
            float(elapsedSeconds or 0.0),
        )

        previousUpdate = self.toSeconds(
            runtimeMetadata.get(
                self.ELAPSED_UPDATED_AT_KEY
            )
        )

        nowEpochSeconds = float(
            nowEpochSeconds
            if nowEpochSeconds is not None
            else time.time()
        )

        if (
                previousUpdate is not None
                and nowEpochSeconds
                >= float(previousUpdate)
        ):
            elapsedSeconds += (
                    nowEpochSeconds
                    - float(previousUpdate)
            )

        statusText = str(
            statusValue or ""
        ).strip().lower()

        if (
                statusText
                in self.ELAPSED_ACTIVE_STATUS_TEXTS
        ):
            runtimeMetadata[
                self.ELAPSED_UPDATED_AT_KEY
            ] = nowEpochSeconds

        else:
            runtimeMetadata.pop(
                self.ELAPSED_UPDATED_AT_KEY,
                None,
            )

        runtimeMetadata[
            "elapsedTimeSeconds"
        ] = elapsedSeconds

        params[
            self.RUNTIME_METADATA_KEY
        ] = runtimeMetadata

        return params

    def captureProtocolElapsedState(
            self,
            mapper,
            projectId: int,
            protocolId,
    ) -> Dict[str, Any]:
        row = mapper.getProjectProtocolByProtocolId(
            projectId=projectId,
            protocolId=protocolId,
        )

        if not row:
            return {
                "elapsedTimeSeconds": 0.0,
                self.ELAPSED_UPDATED_AT_KEY: None,
            }

        params = self.normalizeParams(
            row.get("params")
        )

        runtimeMetadata = params.get(
            self.RUNTIME_METADATA_KEY
        ) or {}

        if not isinstance(runtimeMetadata, dict):
            runtimeMetadata = {}

        return {
            "elapsedTimeSeconds": max(
                0.0,
                float(
                    self.toSeconds(
                        runtimeMetadata.get(
                            "elapsedTimeSeconds"
                        )
                    )
                    or 0.0
                ),
            ),
            self.ELAPSED_UPDATED_AT_KEY: (
                self.toSeconds(
                    runtimeMetadata.get(
                        self.ELAPSED_UPDATED_AT_KEY
                    )
                )
            ),
        }

    def finalizeProtocolElapsedTime(
            self,
            mapper,
            projectId: int,
            protocolId,
            elapsedSnapshot: Dict[str, Any],
            stoppedAtEpochSeconds: float,
    ) -> Dict[str, Any]:
        row = mapper.getProjectProtocolByProtocolId(
            projectId=projectId,
            protocolId=protocolId,
        )

        if not row:
            raise RuntimeError(
                "Cannot finalize runtime elapsed time: "
                "protocol row not found. "
                f"projectId={projectId} "
                f"protocolId={protocolId}"
            )

        params = self.normalizeParams(
            row.get("params")
        )

        runtimeMetadata = params.get(
            self.RUNTIME_METADATA_KEY
        ) or {}

        if not isinstance(runtimeMetadata, dict):
            runtimeMetadata = {}

        runtimeMetadata = dict(runtimeMetadata)

        elapsedSeconds = max(
            0.0,
            float(
                elapsedSnapshot.get(
                    "elapsedTimeSeconds",
                    0.0,
                )
                or 0.0
            ),
        )

        previousUpdate = self.toSeconds(
            elapsedSnapshot.get(
                self.ELAPSED_UPDATED_AT_KEY
            )
        )

        stoppedAtEpochSeconds = float(
            stoppedAtEpochSeconds
        )

        if (
                previousUpdate is not None
                and stoppedAtEpochSeconds
                >= float(previousUpdate)
        ):
            elapsedSeconds += (
                    stoppedAtEpochSeconds
                    - float(previousUpdate)
            )

        runtimeMetadata[
            "elapsedTimeSeconds"
        ] = elapsedSeconds

        runtimeMetadata.pop(
            self.ELAPSED_UPDATED_AT_KEY,
            None,
        )

        params[
            self.RUNTIME_METADATA_KEY
        ] = runtimeMetadata

        mapper.updateProtocol({
            "id": row["id"],
            "params": json.dumps(
                params,
                ensure_ascii=False,
            ),
        })

        return {
            "protocolId": str(protocolId),
            "elapsedTimeSeconds": elapsedSeconds,
        }
