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
from typing import Any, Callable, Dict, Optional

from pyworkflow.protocol import STATUS_NEW
from pyworkflow.protocol.protocol import getProtocolFromDb

logger = logging.getLogger(__name__)


class RuntimeProtocolStatusSyncService:
    """Synchronize PostgreSQL runtime protocol status from Scipion runtime state."""

    @staticmethod
    def safeCall(obj: Any, methodName: str, default: Any = None) -> Any:
        try:
            method = getattr(obj, methodName, None)
            if method is None:
                return default
            return method()
        except Exception:
            return default

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
                "Cannot resolve current project path for PostgreSQL runtime status sync"
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
                f"PostgreSQL protocol row not found. projectId={projectId} protocolId={protocolId}"
            )

        outputSync = None

        try:
            outputSync = syncRuntimeProtocolCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
                registerOutputs=True,
            )
        except Exception:
            logger.exception(
                "Failed to sync PostgreSQL runtime protocol outputs from run.db. "
                "Falling back to status-only update. projectId=%s protocolId=%s status=%s",
                projectId,
                protocolId,
                runtimeStatus,
            )

            mapper.updateProtocol({
                "id": row["id"],
                "status": runtimeStatus,
            })

        return {
            "projectId": projectId,
            "protocolId": str(protocolId),
            "runDbPath": runDbPath,
            "status": runtimeStatus,
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
               AND LOWER(COALESCE(status, '')) IN ('launched', 'running', 'scheduled')
             ORDER BY "protocolId"
            """,
            (projectId,),
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

                normalizedNewStatus = str(newStatus or "").strip().lower()

                if normalizedNewStatus in ("finished", "interactive"):
                    try:
                        runtimeSync = syncRuntimeProtocolCallback(
                            mapper=mapper,
                            projectId=projectId,
                            protocolId=protocolId,
                            registerOutputs=True,
                        )

                        item["runtimeSync"] = runtimeSync
                        item["outputsRegistered"] = runtimeSync.get("outputs", 0)
                        item["outputsDeclared"] = runtimeSync.get("outputsDeclared", 0)
                        item["outputErrors"] = runtimeSync.get("outputErrors", [])

                    except Exception as e:
                        logger.exception(
                            "Failed to sync PostgreSQL runtime outputs after terminal status. "
                            "projectId=%s protocolId=%s status=%s",
                            projectId,
                            protocolId,
                            newStatus,
                        )

                        item["outputsRegistered"] = 0
                        item["outputSyncError"] = str(e)

                if str(previousStatus or "").strip().lower() != str(newStatus or "").strip().lower():
                    report["updated"].append(item)
                else:
                    report["unchanged"].append(item)

            except Exception as e:
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