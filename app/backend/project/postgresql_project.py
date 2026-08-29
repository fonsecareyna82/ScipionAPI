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
import subprocess
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import pyworkflow as pw
from pyworkflow.project import Project as ScipionProject
from pyworkflow.project.project import REGEX_NUMBER_ENDING
from pyworkflow.protocol.constants import (
    MODE_RESTART,
    STATUS_SAVED,
    STATUS_SCHEDULED,
)
from pyworkflow.protocol.protocol import Protocol

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.postgresql_runtime_mapper import PostgresqlRuntimeMapper

logger = logging.getLogger(__name__)


class PostgresqlProject(ScipionProject):
    """
    PostgreSQL-aware Scipion Project.

    This class keeps Scipion's normal project paths,
    hosts and protocol setup logic, while replacing
    Project.mapper with PostgresqlRuntimeMapper.

    Project data and effective runtime settings are
    PostgreSQL-backed. Project-local project.sqlite
    and settings.sqlite databases are not required.
    """

    def __init__(self, domain, path: str, projectId: int, flatMapper: PostgresqlFlatMapper):
        super().__init__(domain, path)

        if projectId is None:
            raise ValueError("projectId is required")
        if flatMapper is None:
            raise ValueError("flatMapper is required")

        self.postgresqlProjectId = int(projectId)
        self.postgresqlFlatMapper = flatMapper
        self._postgresqlRuntimeMapper: Optional[PostgresqlRuntimeMapper] = None

    def _loadDb(self, dbPath=None):
        """Load PostgreSQL as the only project runtime mapper."""
        self.mapper = self.createMapper(None)

    def createMapper(self, sqliteFn):
        """Create the PostgreSQL runtime mapper regardless of sqliteFn."""
        runtimeMapper = PostgresqlRuntimeMapper(
            flatMapper=self.postgresqlFlatMapper,
            projectId=self.postgresqlProjectId,
            project=self,
        )

        self._postgresqlRuntimeMapper = runtimeMapper
        return runtimeMapper

    def getPostgresqlRuntimeMapper(self) -> Optional[PostgresqlRuntimeMapper]:
        return self._postgresqlRuntimeMapper

    def _updateProtocol(
            self,
            protocol: Protocol,
            tries=0,
            checkPid=False,
    ):
        """
        Refresh a PostgreSQL runtime protocol from PostgreSQL only.

        Scipion's native implementation reads logs/run.db and checks the
        protocol PID or queue job. Those sources do not belong to protocols
        executed by the PostgreSQL worker and must never change their status.

        Reading or refreshing a project must therefore remain read-only with
        respect to protocol execution state.
        """
        if protocol is None:
            return pw.NOT_UPDATED_UNNECESSARY

        previousStatus = str(
            protocol.getStatus()
            or ""
        ).strip().lower()

        try:
            self.mapper.updateFrom(
                protocol
            )
        except Exception:
            logger.exception(
                "Could not refresh PostgreSQL runtime protocol. "
                "projectId=%s protocolId=%s",
                self.postgresqlProjectId,
                getattr(
                    protocol,
                    "getObjId",
                    lambda: None,
                )(),
            )

            return pw.NOT_UPDATED_ERROR

        currentStatus = str(
            protocol.getStatus()
            or ""
        ).strip().lower()

        if currentStatus != previousStatus:
            return pw.PROTOCOL_UPDATED

        return pw.NOT_UPDATED_UNNECESSARY

    def closeMapper(self):
        """Close the PostgreSQL runtime mapper."""
        runtimeMapper = self._postgresqlRuntimeMapper

        try:
            if runtimeMapper is not None:
                runtimeMapper.close()
        finally:
            self.mapper = None
            self._postgresqlRuntimeMapper = None

    # ---------------------------------------------------
    #               PROTOCOLS
    # --------------------------------------------------
    def _setPostgresqlProtocolLabel(self, protocol):
        defaultLabel = protocol.getClassLabel()
        maxSuffix = 0

        for otherLabel in self.mapper.getPostgresqlProtocolLabels():
            match = REGEX_NUMBER_ENDING.match(otherLabel)

            if (
                    match
                    and match.group("prefix").strip() == defaultLabel
            ):
                suffix = match.group("number").strip("()")

                try:
                    maxSuffix = max(
                        int(suffix),
                        maxSuffix,
                    )
                except (TypeError, ValueError):
                    logger.error(
                        "Could not calculate protocol label suffix: %s",
                        suffix,
                    )

            elif otherLabel == defaultLabel:
                maxSuffix = max(1, maxSuffix)

        if maxSuffix:
            label = "%s (%d)" % (
                defaultLabel,
                maxSuffix + 1,
            )
        else:
            label = defaultLabel

        protocol.setObjLabel(label)

    def newProtocol(self, protocolClass, **kwargs):
        protocol = protocolClass(
            project=self,
            **kwargs,
        )

        if not protocol.getObjLabel():
            self._setPostgresqlProtocolLabel(protocol)

        protocol.setMapper(self.mapper)
        protocol.setProject(self)

        return protocol

    def _getProtocolsDependencies(
            self,
            protocols,
    ) -> str:
        """
        Check blocking protocol dependants using PostgreSQL instead of
        rebuilding Scipion's complete runs graph.

        This preserves the native Project semantics: a dependant protocol
        blocks relaunch unless it is saved, scheduled, or included in the
        same mutation group.
        """
        selectedProtocolIds = {
            str(protocolId)
            for protocolId in (
                getattr(
                    protocol,
                    "getObjId",
                    lambda: None,
                )()
                for protocol in protocols or []
            )
            if protocolId not in (None, "")
        }

        if not selectedProtocolIds:
            return ""

        adjacency = (
            self.postgresqlFlatMapper
            .getProjectProtocolAdjacencyMap(
                self.postgresqlProjectId
            )
        )

        protocolRows = (
            self.postgresqlFlatMapper
            .getProtocols(
                self.postgresqlProjectId
            )
            or []
        )

        rowsByProtocolId = {
            str(row.get("protocolId")): row
            for row in protocolRows
            if row.get("protocolId")
            not in (None, "")
        }

        nonBlockingStatuses = {
            str(STATUS_SAVED)
            .strip()
            .lower(),

            str(STATUS_SCHEDULED)
            .strip()
            .lower(),
        }

        errorParts = []

        for protocol in protocols or []:
            protocolId = getattr(
                protocol,
                "getObjId",
                lambda: None,
            )()

            if protocolId in (None, ""):
                continue

            protocolIdText = str(
                protocolId
            )

            childProtocolIds = (
                adjacency
                .get(
                    protocolIdText,
                    {},
                )
                .get(
                    "children",
                    [],
                )
                or []
            )

            blockingChildren = []

            for childProtocolId in childProtocolIds:
                childProtocolIdText = str(
                    childProtocolId
                )

                if (
                        childProtocolIdText
                        in selectedProtocolIds
                ):
                    continue

                childRow = rowsByProtocolId.get(
                    childProtocolIdText
                )

                if not childRow:
                    continue

                childStatus = str(
                    childRow.get("status")
                    or ""
                ).strip().lower()

                if (
                        childStatus
                        in nonBlockingStatuses
                ):
                    continue

                blockingChildren.append(
                    self._getPostgresqlProtocolLabel(
                        childRow
                    )
                )

            if not blockingChildren:
                continue

            try:
                protocolLabel = (
                    protocol.getRunName()
                )
            except Exception:
                protocolLabel = (
                    protocolIdText
                )

            errorParts.append(
                "\n *%s* is referenced from:\n   - %s"
                % (
                    protocolLabel,
                    "\n   - ".join(
                        blockingChildren
                    ),
                )
            )

        return "".join(errorParts)

    @staticmethod
    def _getPostgresqlProtocolLabel(
            protocolRow: Dict[str, Any],
    ) -> str:
        params = protocolRow.get(
            "params"
        ) or {}

        if isinstance(params, str):
            try:
                params = json.loads(
                    params
                )
            except Exception:
                params = {}

        if not isinstance(params, dict):
            params = {}

        for key in (
                "runName",
                "_runName",
                "title",
                "_title",
        ):
            value = params.get(key)

            if isinstance(value, dict):
                for valueKey in (
                        "value",
                        "editableValue",
                        "default",
                        "objValue",
                        "_value",
                ):
                    if valueKey in value:
                        value = value.get(
                            valueKey
                        )
                        break

            valueText = str(
                value or ""
            ).strip()

            if valueText:
                return valueText

        className = str(
            protocolRow.get(
                "protocolClassName"
            )
            or "Protocol"
        )

        protocolId = str(
            protocolRow.get(
                "protocolId"
            )
            or ""
        )

        return "%s (%s)" % (
            className,
            protocolId,
        )

    def _startPostgresqlProtocolWorker(self, protocol, runMode: str, wait: bool = False):
        from app.backend.runtime.postgresql_protocol_worker import buildPostgresqlWorkerCommand
        from app.backend.runtime.protocol_status_sync_service import (
            RuntimeProtocolStatusSyncService,
        )
        protocolId = getattr(protocol, "getObjId", lambda: None)()
        if protocolId in (None, ""):
            raise RuntimeError("Cannot start PostgreSQL protocol worker without protocol id")
        rawScheduleLogPath = str(getattr(protocol, "getScheduleLog", lambda: "")() or "").strip()
        if not rawScheduleLogPath:
            raise RuntimeError("Cannot start PostgreSQL protocol worker without schedule log path")
        scheduleLogPath = rawScheduleLogPath if os.path.isabs(rawScheduleLogPath) else os.path.join(self.path, rawScheduleLogPath)
        scheduleLogPath = os.path.abspath(scheduleLogPath)
        os.makedirs(os.path.dirname(scheduleLogPath), exist_ok=True)
        moduleRoot = str(Path(__file__).resolve().parents[3])
        bindingsPath = pw.Config.getBindingsFolder()

        workerEnv = os.environ.copy()

        pythonPathEntries = [
            entry
            for entry in str(
                workerEnv.get("PYTHONPATH") or ""
            ).split(os.pathsep)
            if entry
        ]

        pythonPathEntries = [
                                moduleRoot,
                                bindingsPath,
                            ] + [
                                entry
                                for entry in pythonPathEntries
                                if entry not in {
                moduleRoot,
                bindingsPath,
            }
                            ]

        workerEnv["PYTHONPATH"] = os.pathsep.join(
            pythonPathEntries
        )
        commandArgs = {
            "projectId": self.postgresqlProjectId,
            "protocolId": int(protocolId),
            "runMode": runMode,
        }

        if protocol.useQueue() and protocol.hasQueueParams():
            queueName, queueParams = protocol.getQueueParams()
            commandArgs["queueName"] = queueName
            commandArgs["queueParams"] = queueParams

        command = buildPostgresqlWorkerCommand(**commandArgs)
        with open(scheduleLogPath, "a", encoding="utf-8") as scheduleLog:
            process = subprocess.Popen(command, cwd=moduleRoot, env=workerEnv, stdin=subprocess.DEVNULL, stdout=scheduleLog, stderr=scheduleLog, start_new_session=True)
        protocol.setPid(
            process.pid
        )

        (
            RuntimeProtocolStatusSyncService()
            .persistProtocolProcessIdentity(
                mapper=self.postgresqlFlatMapper,
                projectId=self.postgresqlProjectId,
                protocolId=protocolId,
                protocol=protocol,
            )
        )
        logger.info("Started PostgreSQL protocol worker. projectId=%s protocolId=%s runMode=%s pid=%s", self.postgresqlProjectId, protocolId, runMode, process.pid)
        return process.wait() if wait else process.pid

    def _enqueuePostgresqlProtocolTask(
            self,
            protocol,
            runMode: str,
            wait: bool = False,
    ):
        from app.workers.task_queue import executeProtocolTask

        protocolId = getattr(
            protocol,
            "getObjId",
            lambda: None,
        )()

        if protocolId in (None, ""):
            raise RuntimeError(
                "Cannot enqueue PostgreSQL protocol without protocol id"
            )

        taskResult = executeProtocolTask.apply_async(
            args=[
                self.postgresqlProjectId,
                int(protocolId),
                runMode,
            ]
        )

        logger.info(
            "Queued PostgreSQL protocol task. "
            "projectId=%s protocolId=%s runMode=%s taskId=%s",
            self.postgresqlProjectId,
            protocolId,
            runMode,
            taskResult.id,
        )

        if not wait:
            return str(taskResult.id)

        result = taskResult.get()

        if isinstance(result, dict):
            return int(
                result.get(
                    "coordinatorReturnCode",
                    0,
                )
            )

        return result

    def launchProtocol(
            self,
            protocol: Protocol,
            wait=False,
            scheduled=False,
            force=False,
    ):
        if (
                protocol.getPrerequisites()
                and not scheduled
        ):
            return self.scheduleProtocol(
                protocol
            )

        isRestart = (
                protocol.getRunMode()
                == MODE_RESTART
        )

        if not force:
            if (
                    (
                            not protocol.isInteractive()
                            and not protocol.isInStreaming()
                    )
                    or isRestart
            ):
                self._checkModificationAllowed(
                    [protocol],
                    "Cannot RE-LAUNCH protocol",
                )

        previousStatus = (
                protocol.getStatus()
                or STATUS_SAVED
        )

        self._setupProtocol(
            protocol
        )

        if not scheduled:
            protocol.makePathsAndClean()

        if isRestart:
            self.mapper.deleteRelations(
                protocol
            )

        protocol.cleanExecutionAttributes()

        protocol.setStatus(
            STATUS_SCHEDULED
        )

        self.mapper.store(
            protocol
        )

        self.mapper.commit()

        runMode = (
            "restart"
            if isRestart
            else "resume"
        )

        try:
            return (
                self
                ._enqueuePostgresqlProtocolTask(
                    protocol=protocol,
                    runMode=runMode,
                    wait=wait,
                )
            )

        except Exception:
            protocol.setStatus(
                previousStatus
            )

            protocol.setPid(
                0
            )

            self.mapper.store(
                protocol
            )

            self.mapper.commit()

            raise

    def scheduleProtocol(
            self,
            protocol,
            prerequisites=None,
            initialSleepTime=0,
    ):
        prerequisites = (
                prerequisites or []
        )

        isRestart = (
                protocol.getRunMode()
                == MODE_RESTART
        )

        protocol.addPrerequisites(
            *prerequisites
        )

        self._setupProtocol(
            protocol
        )

        protocol.makePathsAndClean()

        if isRestart:
            self.mapper.deleteRelations(
                protocol
            )

        protocol.cleanExecutionAttributes()

        protocol.setStatus(
            STATUS_SCHEDULED
        )

        self.mapper.store(
            protocol
        )

        self.mapper.commit()

        runMode = (
            "restart"
            if isRestart
            else "resume"
        )

        try:
            return (
                self
                ._enqueuePostgresqlProtocolTask(
                    protocol=protocol,
                    runMode=runMode,
                    wait=False,
                )
            )

        except Exception:
            protocol.setStatus(
                STATUS_SAVED
            )

            protocol.setPid(
                0
            )

            self.mapper.store(
                protocol
            )

            self.mapper.commit()

            raise

    def _storeProtocol(self, protocol):
        """
        Store protocol through the PostgreSQL runtime mapper and make sure the
        Scipion filesystem layout exists.

        Scipion's Project._setupProtocol stores first to allocate an id, then
        assigns the workingDir and stores again. By hooking here, the first
        store does nothing filesystem-related, and the second store creates the
        logical run folder once workingDir is available.
        """
        super()._storeProtocol(protocol)
        self._ensureProtocolFilesystem(protocol)

    # ---------------------------------------------------
    #               HELPERS
    # --------------------------------------------------

    def _ensureProtocolFilesystem(self, protocol) -> None:
        """
        Ensure Scipion's logical protocol folder exists.

        PostgreSQL can persist the protocol row, but protocol execution and
        outputs still need the filesystem layout:
            Runs/000123_ProtClass/
            Runs/000123_ProtClass/extra/
            Runs/000123_ProtClass/logs/
            Runs/000123_ProtClass/tmp or scratch
        """
        workingDir = self._getProtocolWorkingDir(protocol)
        if not workingDir:
            return

        logsDir = self._getProtocolSubPath(protocol, "_getLogsPath", "logs")
        extraDir = self._getProtocolSubPath(protocol, "_getExtraPath", "extra")

        if (
                os.path.isdir(workingDir)
                and os.path.isdir(logsDir)
                and os.path.isdir(extraDir)
        ):
            return

        makeWorkingDir = getattr(protocol, "makeWorkingDir", None)
        if not callable(makeWorkingDir):
            raise RuntimeError(
                "Cannot create Scipion protocol filesystem layout: "
                "protocol does not provide makeWorkingDir(). "
                "protocolId=%s protocolClass=%s workingDir=%s"
                % (
                    getattr(protocol, "getObjId", lambda: None)(),
                    getattr(protocol, "getClassName", lambda: protocol.__class__.__name__)(),
                    workingDir,
                )
            )

        try:
            makeWorkingDir()
        except Exception as exc:
            raise RuntimeError(
                "Could not create Scipion protocol filesystem layout. "
                "protocolId=%s protocolClass=%s workingDir=%s"
                % (
                    getattr(protocol, "getObjId", lambda: None)(),
                    getattr(protocol, "getClassName", lambda: protocol.__class__.__name__)(),
                    workingDir,
                )
            ) from exc

        logger.info(
            "Created Scipion protocol filesystem layout. protocolId=%s workingDir=%s",
            getattr(protocol, "getObjId", lambda: None)(),
            workingDir,
        )

    def _getProtocolWorkingDir(self, protocol) -> Optional[str]:
        getWorkingDir = getattr(protocol, "getWorkingDir", None)
        if callable(getWorkingDir):
            try:
                value = getWorkingDir()
                if value:
                    return str(value)
            except Exception:
                pass

        workingDir = getattr(protocol, "workingDir", None)
        getter = getattr(workingDir, "get", None)
        if callable(getter):
            try:
                value = getter()
                if value:
                    return str(value)
            except Exception:
                pass

        return None

    def _getProtocolSubPath(self, protocol, methodName: str, fallbackName: str) -> str:
        method = getattr(protocol, methodName, None)
        if callable(method):
            try:
                value = method()
                if value:
                    return str(value)
            except Exception:
                pass

        workingDir = self._getProtocolWorkingDir(protocol)
        if not workingDir:
            return fallbackName

        return os.path.join(workingDir, fallbackName)