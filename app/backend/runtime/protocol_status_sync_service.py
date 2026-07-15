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
import os
import time
from typing import Any, Callable, Dict, Optional

from pyworkflow.protocol import STATUS_NEW
from pyworkflow.protocol.protocol import getProtocolFromDb

logger = logging.getLogger(__name__)


class RuntimeProtocolStatusSyncService:
    """Synchronize PostgreSQL runtime protocol status from Scipion runtime state."""
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

    def buildRuntimeMetadata(
            self,
            protocol,
    ) -> Dict[str, Any]:
        cpuTimeValue = getattr(
            protocol,
            "_cpuTime",
            None,
        )

        if cpuTimeValue is None:
            cpuTimeValue = getattr(
                protocol,
                "cpuTime",
                None,
            )

        return {
            "cpuTimeSeconds": self.toSeconds(
                cpuTimeValue
            ),
            "elapsedTimeSeconds": self.toSeconds(
                self.safeCall(
                    protocol,
                    "getElapsedTime",
                    None,
                )
            ),
        }

    def mergeRuntimeMetadata(
            self,
            rawParams,
            protocol,
    ) -> Dict[str, Any]:
        params = rawParams or {}

        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {}

        if not isinstance(params, dict):
            params = {}

        params = dict(params)

        storedMetadata = params.get(
            self.RUNTIME_METADATA_KEY
        ) or {}

        if not isinstance(storedMetadata, dict):
            storedMetadata = {}

        runtimeMetadata = dict(storedMetadata)
        currentMetadata = self.buildRuntimeMetadata(
            protocol
        )

        cpuTimeSeconds = currentMetadata.get(
            "cpuTimeSeconds"
        )

        if cpuTimeSeconds is not None:
            runtimeMetadata[
                "cpuTimeSeconds"
            ] = cpuTimeSeconds

        # Scipion's native getElapsedTime() preserves the original
        # initTime in MODE_RESUME and therefore includes paused time.
        # Use it only to initialize old protocols that do not yet have
        # ScipionWeb-managed elapsed metadata.
        if (
                "elapsedTimeSeconds"
                not in runtimeMetadata
        ):
            nativeElapsedSeconds = (
                currentMetadata.get(
                    "elapsedTimeSeconds"
                )
            )

            if nativeElapsedSeconds is not None:
                runtimeMetadata[
                    "elapsedTimeSeconds"
                ] = nativeElapsedSeconds

        params[self.RUNTIME_METADATA_KEY] = (
            runtimeMetadata
        )

        return params

    def mergeRuntimeProtocolStatus(self, storedStatus, runtimeStatus):
        storedText = str(storedStatus or "").strip().lower()
        runtimeText = str(runtimeStatus or "").strip().lower()

        if not runtimeText:
            return storedStatus or STATUS_NEW

        # Do not downgrade a protocol that was already launched/running/scheduled
        # just because an early runtime read still reports "new".
        if runtimeText == "new" and storedText in {
            "launched",
            "running",
            "scheduled",
        }:
            return storedStatus

        # Do not overwrite terminal states with non-terminal stale reads.
        if storedText in {"finished", "failed", "aborted", "interactive"}:
            if runtimeText not in {"finished", "failed", "aborted", "interactive"}:
                return storedStatus

        return runtimeStatus

    def resolveRuntimeRunDbPath(
            self,
            projectPath: str,
            protocol,
    ) -> str:
        runDbPath = protocol.getDbPath()

        if not os.path.isabs(str(runDbPath)):
            workingDir = protocol.getWorkingDir()

            if not os.path.isabs(str(workingDir)):
                workingDir = os.path.join(str(projectPath), str(workingDir))

            runDbPath = os.path.join(str(workingDir), "logs", "run.db")

        return os.path.abspath(str(runDbPath))

    def loadRuntimeProtocolFromRunDb(
            self,
            projectPath: str,
            runDbPath: str,
            protocolId,
    ):
        return getProtocolFromDb(
            projectPath,
            runDbPath,
            int(protocolId),
            chdir=False,
        )

    def syncProtocolStatus(
            self,
            mapper,
            projectId: int,
            protocolId,
            protocol,
            buildProtocolContextCallback: Callable,
    ) -> Dict[str, Any]:
        statusValue = self.safeCall(protocol, "getStatus", None)

        if str(statusValue or "").strip().lower() in ("", "new"):
            existing = mapper.getProjectProtocolByProtocolId(
                projectId=projectId,
                protocolId=protocolId,
            )
            existingStatus = existing.get("status") if existing else None

            if str(existingStatus or "").strip().lower() in ("launched", "running", "scheduled"):
                statusValue = existingStatus

        protocolContext = buildProtocolContextCallback(
            projectId,
            protocol,
            mapper,
        )

        # Make the status preservation above effective when saving the context.
        protocolContext.setdefault("info", {})["status"] = statusValue

        mapper.saveProtocol(protocolContext)

        return {
            "protocolId": str(protocolId),
            "status": statusValue,
        }

    def syncProtocolStatusFromRunDb(
            self,
            mapper,
            projectId: int,
            protocolId,
            protocol,
            getCurrentProjectPathCallback: Callable,
            syncRuntimeProtocolCallback: Callable,
    ) -> Dict[str, Any]:
        projectPath = getCurrentProjectPathCallback()

        if not projectPath:
            raise RuntimeError(
                "Cannot resolve current project path for "
                "PostgreSQL runtime status sync"
            )

        runDbPath = self.resolveRuntimeRunDbPath(
            projectPath=projectPath,
            protocol=protocol,
        )

        runtimeProtocol = self.loadRuntimeProtocolFromRunDb(
            projectPath=projectPath,
            runDbPath=runDbPath,
            protocolId=protocolId,
        )

        runtimeStatus = runtimeProtocol.getStatus()

        row = mapper.getProjectProtocolByProtocolId(
            projectId=projectId,
            protocolId=protocolId,
        )

        if not row:
            raise RuntimeError(
                f"PostgreSQL protocol row not found. "
                f"projectId={projectId} "
                f"protocolId={protocolId}"
            )

        previousStatusText = str(
            row.get("status") or ""
        ).strip().lower()

        runtimeStatusText = str(
            runtimeStatus or ""
        ).strip().lower()

        persistedStatus = (
            self.mergeRuntimeProtocolStatus(
                storedStatus=row.get("status"),
                runtimeStatus=runtimeStatus,
            )
        )

        params = self.mergeRuntimeMetadata(
            row.get("params"),
            runtimeProtocol,
        )

        params = self.updateElapsedTimeMetadata(
            params=params,
            statusValue=persistedStatus,
        )

        runtimeMetadata = params.get(
            self.RUNTIME_METADATA_KEY
        ) or {}

        finalSyncPending = bool(
            runtimeMetadata.get(
                self.FINAL_SYNC_PENDING_KEY,
                False,
            )
        )

        transitionedToTerminal = (
                previousStatusText
                in self.ACTIVE_STATUS_TEXTS
                and runtimeStatusText
                in self.TERMINAL_STATUS_TEXTS
        )

        needsFinalSync = (
                transitionedToTerminal
                or (
                        runtimeStatusText
                        in self.TERMINAL_STATUS_TEXTS
                        and finalSyncPending
                )
        )

        outputSync = None

        if needsFinalSync:
            try:
                outputSync = syncRuntimeProtocolCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                    registerOutputs=True,
                    syncRelations=True,
                    protocol=runtimeProtocol,
                )

                syncedRow = mapper.getProjectProtocolByProtocolId(
                    projectId=projectId,
                    protocolId=protocolId,
                )

                if syncedRow:
                    syncedParams = self.mergeRuntimeMetadata(
                        syncedRow.get("params"),
                        runtimeProtocol,
                    )

                    syncedRuntimeMetadata = (
                            syncedParams.get(
                                self.RUNTIME_METADATA_KEY
                            )
                            or {}
                    )

                    if isinstance(
                            syncedRuntimeMetadata,
                            dict,
                    ):
                        syncedRuntimeMetadata.pop(
                            self.FINAL_SYNC_PENDING_KEY,
                            None,
                        )

                        syncedRuntimeMetadata[
                            "elapsedTimeSeconds"
                        ] = runtimeMetadata.get(
                            "elapsedTimeSeconds",
                            0.0,
                        )

                        if (
                                self.ELAPSED_UPDATED_AT_KEY
                                in runtimeMetadata
                        ):
                            syncedRuntimeMetadata[
                                self.ELAPSED_UPDATED_AT_KEY
                            ] = runtimeMetadata[
                                self.ELAPSED_UPDATED_AT_KEY
                            ]
                        else:
                            syncedRuntimeMetadata.pop(
                                self.ELAPSED_UPDATED_AT_KEY,
                                None,
                            )

                        syncedParams[
                            self.RUNTIME_METADATA_KEY
                        ] = syncedRuntimeMetadata

                    mapper.updateProtocol({
                        "id": syncedRow["id"],
                        "params": json.dumps(
                            syncedParams,
                            ensure_ascii=False,
                        ),
                    })

            except Exception:
                logger.exception(
                    "Failed to perform final PostgreSQL runtime sync. "
                    "Falling back to status and timing update. "
                    "projectId=%s protocolId=%s status=%s",
                    projectId,
                    protocolId,
                    runtimeStatus,
                )

                try:
                    mapper.db.conn.rollback()
                except Exception:
                    logger.exception(
                        "Failed to rollback PostgreSQL connection after final "
                        "runtime sync error. projectId=%s protocolId=%s",
                        projectId,
                        protocolId,
                    )

                runtimeMetadata[
                    self.FINAL_SYNC_PENDING_KEY
                ] = True

                params[
                    self.RUNTIME_METADATA_KEY
                ] = runtimeMetadata

                mapper.updateProtocol({
                    "id": row["id"],
                    "status": persistedStatus,
                    "params": json.dumps(
                        params,
                        ensure_ascii=False,
                    ),
                })

        else:
            # Fast path used by the periodic project refresh.
            #
            # A launched/running/scheduled protocol only needs its current
            # state and timing metadata updated. Steps and outputs are synced
            # when the protocol reaches a terminal state.
            mapper.updateProtocol({
                "id": row["id"],
                "status": persistedStatus,
                "params": json.dumps(
                    params,
                    ensure_ascii=False,
                ),
            })

        persistedRow = (
            mapper.getProjectProtocolByProtocolId(
                projectId=projectId,
                protocolId=protocolId,
            )
        )

        if persistedRow:
            persistedStatus = persistedRow.get(
                "status"
            )

            persistedParams = (
                    persistedRow.get("params") or {}
            )

            if isinstance(persistedParams, str):
                try:
                    persistedParams = json.loads(
                        persistedParams
                    )
                except Exception:
                    persistedParams = {}

            if isinstance(persistedParams, dict):
                runtimeMetadata = (
                        persistedParams.get(
                            self.RUNTIME_METADATA_KEY
                        )
                        or runtimeMetadata
                )

        return {
            "projectId": projectId,
            "protocolId": str(protocolId),
            "runDbPath": runDbPath,
            "status": persistedStatus,
            "runtimeMetadata": runtimeMetadata,
            "transitionedToTerminal": (
                transitionedToTerminal
            ),
            "outputSync": outputSync,
        }

    def syncActivePostgresqlRuntimeProtocolStatuses(
            self,
            mapper,
            projectId: int,
            syncRuntimeProtocolStatusFromRunDbCallback: Callable,
            syncRuntimeProtocolCallback: Callable,
    ) -> dict:
        """
        Refresh only active PostgreSQL runtime protocol statuses from logs/run.db.

        This is intentionally status-first:
          - active protocols are read from PostgreSQL
          - runtime status is resolved from run.db
          - terminal protocols may trigger a full runtime sync to register outputs
        """
        rows = mapper.db.fetchAll(
            """
            SELECT "protocolId", status
              FROM protocols
             WHERE "projectId" = %s
               AND (
                    LOWER(COALESCE(status, '')) IN (
                        'launched',
                        'running',
                        'scheduled'
                    )
                    OR (
                        LOWER(COALESCE(status, '')) IN (
                            'finished',
                            'failed',
                            'aborted',
                            'interactive'
                        )
                        AND (
                            (params::jsonb -> %s) IS NULL
                            OR (
                                params::jsonb
                                -> %s
                                ->> 'finalSyncPending'
                            ) = 'true'
                        )
                    )
               )
             ORDER BY "protocolId"
            """,
            (
                projectId,
                self.RUNTIME_METADATA_KEY,
                self.RUNTIME_METADATA_KEY,
            )
        )

        report = {
            "checked": len(rows or []),
            "updated": [],
            "unchanged": [],
            "errors": [],
        }

        for row in rows or []:
            protocolId = row.get("protocolId")
            previousStatus = row.get("status")

            try:
                result = syncRuntimeProtocolStatusFromRunDbCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                )

                newStatus = result.get("status")

                item = {
                    "protocolId": str(protocolId),
                    "previousStatus": previousStatus,
                    "status": newStatus,
                }

                item["runtimeMetadata"] = result.get(
                    "runtimeMetadata"
                )

                runtimeSync = result.get("outputSync")

                if isinstance(runtimeSync, dict):
                    item["runtimeSync"] = runtimeSync
                    item["outputsRegistered"] = runtimeSync.get(
                        "outputs",
                        0,
                    )
                    item["outputsDeclared"] = runtimeSync.get(
                        "outputsDeclared",
                        0,
                    )
                    item["outputErrors"] = runtimeSync.get(
                        "outputErrors",
                        [],
                    )

                if str(previousStatus or "").strip().lower() != str(newStatus or "").strip().lower():
                    report["updated"].append(item)
                else:
                    report["unchanged"].append(item)

            except Exception as e:
                try:
                    mapper.db.conn.rollback()
                except Exception:
                    logger.exception(
                        "Failed to rollback PostgreSQL connection after runtime "
                        "protocol refresh error. projectId=%s protocolId=%s",
                        projectId,
                        protocolId,
                    )
                logger.debug(
                    "Could not refresh PostgreSQL runtime protocol status. projectId=%s protocolId=%s",
                    projectId,
                    protocolId,
                    exc_info=True,
                )
                report["errors"].append({
                    "protocolId": str(protocolId),
                    "error": str(e),
                })

        return report