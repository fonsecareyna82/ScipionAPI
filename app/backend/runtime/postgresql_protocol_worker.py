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
import argparse
import json
import logging
import os
import re
import shlex
import sys
import time
from types import MethodType
from typing import Any, Dict, List

from pyworkflow import Config
from pyworkflow.object import Pointer, PointerList
from pyworkflow.protocol import (
    LegacyProtocol,
    MODE_RESTART,
    MODE_RESUME,
    Set,
    STATUS_ABORTED,
    STATUS_FAILED,
    STATUS_FINISHED,
    STATUS_INTERACTIVE,
    STATUS_LAUNCHED,
    STATUS_RUNNING,
    STATUS_SAVED,
    STATUS_SCHEDULED,
)
from pyworkflow.protocol.constants import UNKNOWN_JOBID
from pyworkflow.protocol.executor import (
    QueueStepExecutor,
    StepExecutor,
    ThreadStepExecutor,
)
from pyworkflow.protocol.launch import _submit
from pyworkflow.protocol.params import (
    MultiPointerParam,
    PointerParam,
    RelationParam,
)
from pyworkflow.protocol.protocol import anonimizeGPUs
from pyworkflow.utils import LoggingConfigurator
from pyworkflow.utils.log import setDefaultLoggingContext

from app.backend.project import PostgresqlProject
from app.backend.api.services.settings_service import SettingsService
from app.backend.mapper.postgresql_scipion_item_hydrator import (
    setPostgresqlRuntimeParentReference,
)
from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)
from app.backend.runtime.postgresql_runtime_event_service import (
    DEFAULT_RUNTIME_EVENT_WAIT_SECONDS,
    FALLBACK_RUNTIME_POLL_SECONDS,
    PostgresqlRuntimeEventListener,
    PostgresqlRuntimeEventPublisher,
)
from app.backend.runtime.postgresql_scheduling_log_formatter import (
    PostgresqlSchedulingLogFormatter,
)
from app.backend.runtime.protocol_identity import (
    ProtocolIdentityResolver,
)
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)
from app.backend.runtime.protocol_step_persistence_service import (
    RuntimeProtocolStepPersistenceService,
)
from app.backend.runtime.postgresql_output_set_adapter import (
    RuntimePostgresqlOutputSetAdapter,
)
from app.backend.runtime.postgresql_runtime_set_sqlite_materializer import (
    PostgresqlRuntimeSetSqliteMaterializer,
)

logger = logging.getLogger(__name__)

WORKER_MODULE = (
    "app.backend.runtime.postgresql_protocol_worker"
)

POSTGRESQL_RUN_MODE_RESTART = (
    "restart"
)

POSTGRESQL_RUN_MODE_RESUME = (
    "resume"
)

POSTGRESQL_RUN_MODES = {
    POSTGRESQL_RUN_MODE_RESTART,
    POSTGRESQL_RUN_MODE_RESUME,
}


def normalizePostgresqlRunMode(
        runMode,
) -> str:
    normalizedRunMode = str(
        runMode
        or POSTGRESQL_RUN_MODE_RESTART
    ).strip().lower()

    if (
            normalizedRunMode
            not in POSTGRESQL_RUN_MODES
    ):
        raise ValueError(
            "Unsupported PostgreSQL "
            "protocol run mode: %s"
            % runMode
        )

    return normalizedRunMode

FINISHED_INPUT_PARENT_STATUSES = {
    str(STATUS_FINISHED).strip().lower(),
    "finished",
}

FAILED_INPUT_PARENT_STATUSES = {
    str(STATUS_FAILED).strip().lower(),
    str(STATUS_ABORTED).strip().lower(),
    "failed",
    "aborted",
}

TERMINAL_PREREQUISITE_STATUSES = {
    str(STATUS_FINISHED).strip().lower(),
    str(STATUS_FAILED).strip().lower(),
    str(STATUS_ABORTED).strip().lower(),
    "finished",
    "failed",
    "aborted",
}

STREAMING_PARENT_NOT_STARTED_STATUSES = {
    str(STATUS_SAVED).strip().lower(),
    str(STATUS_SCHEDULED).strip().lower(),
    "new",
    "saved",
    "scheduled",
}


def buildPostgresqlWorkerCommand(
        projectId: int,
        protocolId: int,
        execute: bool = False,
        runMode: str = POSTGRESQL_RUN_MODE_RESTART,
        queueName=None,
        queueParams=None,
) -> List[str]:
    normalizedRunMode = (
        normalizePostgresqlRunMode(
            runMode
        )
    )

    command = [
        sys.executable,
        "-m",
        WORKER_MODULE,
        "--project-id",
        str(projectId),
        "--protocol-id",
        str(protocolId),
    ]

    # Keep the existing restart command
    # unchanged for backward compatibility.
    if normalizedRunMode != POSTGRESQL_RUN_MODE_RESTART:
        command.extend([
            "--run-mode",
            normalizedRunMode,
        ])

    if queueParams is not None:
        if not isinstance(queueParams, dict):
            raise TypeError("PostgreSQL queue launch params must be a dictionary.")

        command.extend([
            "--queue-name",
            str(queueName or ""),
            "--queue-params-json",
            json.dumps(queueParams, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        ])

    if execute:
        command.append("--execute")

    return command


class RuntimePostgresqlStepAdapter:
    """
    Redirect Scipion's runtime step persistence to protocol_steps.

    The protocol keeps its normal in-memory Step objects and StepExecutor,
    but neither _storeSteps nor __updateStep creates steps.sqlite.
    """

    def __init__(
            self,
            mapper,
            projectId: int,
            protocol,
            runMode: str = (
                    POSTGRESQL_RUN_MODE_RESTART
            ),
    ):
        self.mapper = mapper
        self.projectId = int(projectId)
        self.protocol = protocol

        self.runMode = (
            normalizePostgresqlRunMode(
                runMode
            )
        )
        self.stepService = (
            RuntimeProtocolStepPersistenceService()
        )

        identityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        self.protocolId = int(
            protocol.getObjId()
        )

        self.protocolDbId = identityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
            self.protocolId
        )

        if self.protocolDbId is None:
            raise RuntimeError(
                "Protocol %s was not found in PostgreSQL"
                % self.protocolId
            )

        self.protocolDbId = int(
            self.protocolDbId
        )

    def install(self) -> None:
        adapter = self

        originalStore = (
            self.protocol._store
        )

        def loadSteps(protocolSelf):
            return (
                adapter
                .loadPreviousSteps()
            )

        def storeSteps(protocolSelf):
            adapter.replaceSteps()

        def updateStep(protocolSelf, step):
            adapter.installStepThreadResourceCleanup(step)
            adapter.upsertStep(step)

        def updateSteps(
                protocolSelf,
                updater,
                where="1",
        ):
            targetStatus = None

            match = re.search(
                r"status\s*=\s*'([^']+)'",
                str(where or ""),
                flags=re.IGNORECASE,
            )

            if match:
                targetStatus = (
                    match.group(1)
                    .strip()
                    .lower()
                )

            for step in (
                    getattr(
                        protocolSelf,
                        "_steps",
                        [],
                    )
                    or []
            ):
                stepStatus = str(
                    step.getStatus()
                    or ""
                ).strip().lower()

                if (
                        targetStatus
                        and stepStatus
                        != targetStatus
                ):
                    continue

                updater(step)
                adapter.upsertStep(step)

        def store(
                protocolSelf,
                *objects,
        ):
            jobIdsObject = getattr(
                protocolSelf,
                "_jobId",
                None,
            )

            if (
                    len(objects) == 1
                    and objects[0]
                    is jobIdsObject
            ):
                # Protocol._store normally provides this lock.
                # Preserve the same synchronization because
                # QueueStepExecutor may run several step threads.
                with protocolSelf._lock:
                    adapter.persistProtocolProcessIdentity()

                return

            return originalStore(
                *objects
            )

        self.protocol.loadSteps = MethodType(
            loadSteps,
            self.protocol,
        )

        self.protocol._storeSteps = MethodType(
            storeSteps,
            self.protocol,
        )

        self.protocol._Protocol__updateStep = (
            MethodType(
                updateStep,
                self.protocol,
            )
        )

        self.protocol._updateSteps = MethodType(
            updateSteps,
            self.protocol,
        )

        self.protocol._store = (
            MethodType(
                store,
                self.protocol,
            )
        )

    def installStepThreadResourceCleanup(self, step) -> None:
        runStep = getattr(step, "_run", None)

        if not callable(runStep):
            return

        wrappedStepIds = getattr(self, "_postgresqlResourceCleanupStepIds", None)

        if wrappedStepIds is None:
            wrappedStepIds = set()
            self._postgresqlResourceCleanupStepIds = wrappedStepIds

        stepIdentity = id(step)

        if stepIdentity in wrappedStepIds:
            return

        adapter = self

        def runWithPostgresqlCleanup(stepSelf):
            try:
                return runStep()

            finally:
                adapter.closeCurrentThreadPostgresqlResources()

        step._run = MethodType(
            runWithPostgresqlCleanup,
            step,
        )

        wrappedStepIds.add(stepIdentity)

    def closeCurrentThreadPostgresqlResources(self) -> None:
        db = getattr(self.mapper, "db", None)

        if db is None:
            return

        closeCurrentThreadResources = getattr(
            db,
            "closeCurrentThreadResources",
            None,
        )

        if not callable(closeCurrentThreadResources):
            return

        try:
            closeCurrentThreadResources()

        except Exception:
            logger.warning(
                "Could not release PostgreSQL step-thread resources. projectId=%s protocolId=%s",
                self.projectId,
                self.protocolId,
                exc_info=True,
            )

    def loadPreviousSteps(
            self,
    ) -> List[Any]:
        if (
                self.runMode
                != POSTGRESQL_RUN_MODE_RESUME
        ):
            return []

        snapshots = (
            self.mapper
            .listProtocolSteps(
                projectId=self.projectId,
                protocolId=self.protocolId,
            )
            or []
        )

        snapshotsByIndex = {}

        for snapshot in snapshots:
            try:
                stepIndex = int(
                    snapshot.get(
                        "index"
                    )
                )

            except (
                    TypeError,
                    ValueError,
            ):
                continue

            snapshotsByIndex[
                stepIndex
            ] = dict(
                snapshot
            )

        previousSteps = []

        currentSteps = list(
            getattr(
                self.protocol,
                "_steps",
                [],
            )
            or []
        )

        # Scipion compares previous and current
        # steps positionally. Stop at the first
        # missing previous step to preserve that
        # alignment.
        for currentStep in currentSteps:
            try:
                stepIndex = int(
                    currentStep.getIndex()
                )

            except (
                    TypeError,
                    ValueError,
            ):
                break

            snapshot = (
                snapshotsByIndex.get(
                    stepIndex
                )
            )

            if snapshot is None:
                break

            previousSteps.append(
                self.buildPreviousStep(
                    currentStep=currentStep,
                    snapshot=snapshot,
                )
            )

        return previousSteps

    def buildPreviousStep(
            self,
            *,
            currentStep,
            snapshot,
    ):
        previousStep = (
            currentStep.clone()
        )

        stepIndex = int(
            snapshot.get(
                "index"
            )
            or currentStep.getIndex()
        )

        previousStep.setIndex(
            stepIndex
        )

        prerequisites = []

        for prerequisite in (
                snapshot.get(
                    "prerequisites"
                )
                or []
        ):
            try:
                prerequisites.append(
                    int(prerequisite)
                )

            except (
                    TypeError,
                    ValueError,
            ):
                continue

        previousStep.setPrerequisites(
            *prerequisites
        )

        storedName = snapshot.get(
            "name"
        )

        if (
                storedName is not None
                and hasattr(
                    previousStep,
                    "funcName",
                )
        ):
            previousStep.funcName.set(
                str(storedName)
            )

        storedArgs = snapshot.get(
            "args"
        )

        if (
                storedArgs is not None
                and hasattr(
                    previousStep,
                    "argsStr",
                )
        ):
            previousStep.argsStr.set(
                json.dumps(
                    storedArgs,
                    default=str,
                )
            )

        storedStatus = str(
            snapshot.get(
                "status"
            )
            or ""
        ).strip()

        if storedStatus:
            previousStep.setStatus(
                storedStatus
            )

        if hasattr(
                previousStep,
                "initTime",
        ):
            previousStep.initTime.set(
                snapshot.get(
                    "initTime"
                )
            )

        if hasattr(
                previousStep,
                "endTime",
        ):
            previousStep.endTime.set(
                snapshot.get(
                    "endTime"
                )
            )

        errorObject = getattr(
            previousStep,
            "_error",
            None,
        )

        if errorObject is not None:
            errorObject.set(
                snapshot.get(
                    "error"
                )
            )

        interactiveObject = getattr(
            previousStep,
            "interactive",
            None,
        )

        if interactiveObject is not None:
            interactiveObject.set(
                bool(
                    snapshot.get(
                        "interactive"
                    )
                )
            )

        needsGpuObject = getattr(
            previousStep,
            "_needsGPU",
            None,
        )

        if needsGpuObject is not None:
            needsGpuObject.set(
                bool(
                    snapshot.get(
                        "needsGpu",
                        True,
                    )
                )
            )

        return previousStep

    def buildSnapshots(self) -> List[Dict[str, Any]]:
        return (
            self.stepService
            .buildProtocolStepsForPostgresql(
                self.protocol
            )
        )

    def replaceSteps(self) -> None:
        snapshots = self.buildSnapshots()

        self.mapper.replaceProtocolSteps(
            projectId=self.projectId,
            protocolDbId=self.protocolDbId,
            protocolId=self.protocolId,
            steps=snapshots,
        )

    def upsertStep(self, step) -> None:
        stepIndex = getattr(step, "getIndex", lambda: None)()

        if stepIndex is None:
            return

        stepSnapshot = self.stepService.buildProtocolStepForPostgresql(step, event="step-updated")
        self.mapper.upsertProtocolStep(projectId=self.projectId,
                                       protocolDbId=self.protocolDbId,
                                       protocolId=self.protocolId,
                                       step=stepSnapshot)

    def persistProtocolProcessIdentity(
            self,
    ) -> Dict[str, Any]:
        return (
            RuntimeProtocolStatusSyncService()
            .persistProtocolProcessIdentity(
                mapper=self.mapper,
                projectId=self.projectId,
                protocolId=self.protocolId,
                protocol=self.protocol,
            )
        )


class RuntimePostgresqlProtocolWorker:
    def __init__(
            self,
            projectId: int,
            protocolId: int,
            runMode: str = POSTGRESQL_RUN_MODE_RESTART,
            queueName=None,
            queueParams=None,
    ):
        self.projectId = int(projectId)
        self.protocolId = int(protocolId)

        self.runMode = normalizePostgresqlRunMode(runMode)

        if queueParams is not None and not isinstance(queueParams, dict):
            raise TypeError("PostgreSQL queue launch params must be a dictionary.")

        self._queueLaunchOverride = None if queueParams is None else (str(queueName or ""), dict(queueParams))

        self.mapper = None
        self.project = None
        self.protocol = None
        self.runtimeMapper = None
        self.dependencyEventListener = None
        self._executionInputSetsByRuntimeObjectId = {}
        self._executionInputObjectsByRuntimeObjectId = {}
        self._executionInputObjectIdsResolving = set()

    @staticmethod
    def _allowsScalarPointers(param) -> bool:
        return (
                bool(getattr(param, "allowsPointers", False))
                and not isinstance(
            param,
            (
                PointerParam,
                MultiPointerParam,
                RelationParam,
            ),
        )
        )

    def _applyQueueLaunchOverride(self) -> bool:
        if self._queueLaunchOverride is None or self.protocol is None:
            return False

        if not self.protocol.useQueue():
            return False

        queueName, queueParams = self._queueLaunchOverride
        self.protocol.setQueueParams([queueName, dict(queueParams)])

        return True

    def load(self, configureLogging: bool = True,) -> None:
        from app.backend.database import getMapper
        self.mapper = getMapper()

        projectRow = self.mapper.getProjectRuntimeMetadata(self.projectId)

        if not projectRow:
            raise RuntimeError(
                "Project %s was not found"
                % self.projectId
            )

        projectPath = str(
            projectRow.get("name")
            or ""
        ).strip()

        if not projectPath:
            raise RuntimeError(
                "Project %s has no filesystem path"
                % self.projectId
            )

        self.project = PostgresqlProject(
            domain=Config.getDomain(),
            path=projectPath,
            projectId=self.projectId,
            flatMapper=self.mapper,
        )

        self.project.load(
            chdir=True
        )

        self.runtimeMapper = (
            self.project
            .getPostgresqlRuntimeMapper()
        )

        if self.runtimeMapper is None:
            raise RuntimeError(
                "PostgreSQL runtime mapper "
                "is not available"
            )

        self.protocol = self.project.getProtocol(
            self.protocolId
        )

        if isinstance(
                self.protocol,
                LegacyProtocol,
        ):
            raise RuntimeError(
                "Protocol %s could not be loaded "
                "with its real class"
                % self.protocolId
            )

        self._applyQueueLaunchOverride()
        self.protocol.makeWorkingDir()

        if configureLogging:
            self.configureSchedulingLogging()

    def configureSchedulingLogging(
            self,
    ) -> None:
        schedulePath = os.path.abspath(
            self.protocol.getScheduleLog()
        )

        LoggingConfigurator.setUpProtocolSchedulingLog(
            schedulePath
        )

        setDefaultLoggingContext(
            self.protocolId,
            self.project.getShortName(),
        )

    def configureRunLogging(
            self,
    ) -> None:
        stdoutPath = os.path.abspath(
            self.protocol.getStdoutLog()
        )

        stderrPath = os.path.abspath(
            self.protocol.getStderrLog()
        )

        LoggingConfigurator.setUpProtocolRunLogging(
            stdoutPath,
            stderrPath,
        )

        setDefaultLoggingContext(
            self.protocolId,
            self.project.getShortName(),
        )

    def getSchedulingProtocolLabel(
            self,
    ) -> str:
        try:
            label = str(
                self.protocol.getObjLabel()
                or ""
            ).strip()

        except Exception:
            label = ""

        if label:
            return label

        return "Protocol %s" % (
            self.protocolId
        )

    def _closeExecutionInputSets(self) -> None:
        runtimeInputSets = list(self._executionInputSetsByRuntimeObjectId.values())
        runtimeInputObjects = list(self._executionInputObjectsByRuntimeObjectId.values())

        for runtimeInputObject in runtimeInputObjects:
            runtimeInputObjectDict = getattr(runtimeInputObject, "__dict__", None)

            if isinstance(runtimeInputObjectDict, dict):
                runtimeInputObjectDict.pop("_postgresqlRuntimeObjectResolver", None)

        self._executionInputSetsByRuntimeObjectId.clear()
        self._executionInputObjectsByRuntimeObjectId.clear()
        self._executionInputObjectIdsResolving.clear()

        releasedInputSetIds = set()

        for runtimeInputSet in runtimeInputSets:
            runtimeInputSetId = id(runtimeInputSet)

            if runtimeInputSetId in releasedInputSetIds:
                continue

            releasedInputSetIds.add(
                runtimeInputSetId
            )

            releaseDetachedConsumer = getattr(
                runtimeInputSet,
                "releasePostgresqlDetachedConsumer",
                None,
            )

            if callable(releaseDetachedConsumer):
                try:
                    releaseDetachedConsumer()
                except Exception:
                    logger.debug(
                        "Could not release detached PostgreSQL execution input Set. "
                        "projectId=%s protocolId=%s",
                        self.projectId,
                        self.protocolId,
                        exc_info=True,
                    )

                continue

            close = getattr(
                runtimeInputSet,
                "close",
                None,
            )

            if not callable(close):
                continue

            try:
                close()
            except Exception:
                logger.debug(
                    "Could not close detached PostgreSQL execution input Set. "
                    "projectId=%s protocolId=%s",
                    self.projectId,
                    self.protocolId,
                    exc_info=True,
                )

    def close(self) -> None:
        if (
                self.dependencyEventListener
                is not None
        ):
            try:
                self.dependencyEventListener.close()

            except Exception:
                logger.debug(
                    "Could not close PostgreSQL "
                    "runtime event listener.",
                    exc_info=True,
                )

            self.dependencyEventListener = None
        self._closeExecutionInputSets()

        if self.project is not None:
            try:
                self.project.closeMapper()
            except Exception:
                logger.debug(
                    "Could not close PostgreSQL project mapper.",
                    exc_info=True,
                )

        if self.mapper is not None:
            try:
                self.mapper.db.close()
            except Exception:
                logger.debug(
                    "Could not close PostgreSQL connection.",
                    exc_info=True,
                )

    def cleanupCompatibilitySqliteSnapshots(self) -> Dict[str, Any]:
        try:
            report = PostgresqlRuntimeSetSqliteMaterializer.cleanupCurrentWorkerDirectory()
        except Exception as error:
            logger.warning(
                "Could not clean PostgreSQL SQLite compatibility snapshots. "
                "projectId=%s protocolId=%s error=%s",
                self.projectId,
                self.protocolId,
                error,
                exc_info=True,
            )

            return {
                "workerDirectory": None,
                "removed": False,
                "deleted": [],
                "deletedCount": 0,
                "registryEntriesRemoved": 0,
                "error": str(error),
            }

        if (
                report.get("removed")
                or report.get("registryEntriesRemoved")
        ):
            logger.debug(
                "Cleaned PostgreSQL SQLite compatibility snapshots. "
                "projectId=%s protocolId=%s workerDirectory=%s "
                "deletedCount=%s registryEntriesRemoved=%s",
                self.projectId,
                self.protocolId,
                report.get("workerDirectory"),
                report.get("deletedCount"),
                report.get("registryEntriesRemoved"),
            )

        return report

    def getProtocolDbId(self) -> int:
        resolver = ProtocolIdentityResolver(
            mapper=self.mapper,
            projectId=self.projectId,
        )

        protocolDbId = resolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
            self.protocolId
        )

        if protocolDbId is None:
            raise RuntimeError(
                "Protocol %s was not found "
                "in PostgreSQL"
                % self.protocolId
            )

        return int(protocolDbId)

    def loadParentStatuses(self) -> List[Dict[str, Any]]:
        return ProtocolGraphRepository().loadParentProtocolStatuses(
            mapper=self.mapper,
            projectId=self.projectId,
            childProtocolDbId=self.getProtocolDbId(),
        )

    def loadInputRefs(
            self,
    ) -> List[Dict[str, Any]]:
        return (
            ProtocolGraphRepository()
            .loadInputRefsForProtocol(
                mapper=self.mapper,
                projectId=self.projectId,
                protocolDbId=(
                    self.getProtocolDbId()
                ),
            )
        )

    def getRuntimeOutputInfo(
            self,
            inputRef,
    ) -> Dict[str, Any]:
        outputName = str(
            inputRef.get(
                "parentOutputName"
            )
            or ""
        ).strip()

        rootOutputName = (
            outputName.split(".", 1)[0]
            if outputName
            else ""
        )

        if not rootOutputName:
            return {
                "exists": False,
                "runtimeObjectId": None,
            }

        return (
            ProtocolGraphRepository()
            .getPostgresqlRuntimeOutputInfo(
                mapper=self.mapper,
                projectId=self.projectId,
                parentProtocolDbId=int(
                    inputRef[
                        "parentProtocolDbId"
                    ]
                ),
                outputName=rootOutputName,
            )
        )

    def getPrerequisiteProtocolIds(
            self,
    ):
        rawPrerequisites = (
            self.protocol
            .getPrerequisites()
            or []
        )

        if isinstance(
                rawPrerequisites,
                str,
        ):
            rawValues = [
                rawPrerequisites,
            ]

        else:
            try:
                rawValues = list(
                    rawPrerequisites
                )

            except TypeError:
                rawValues = [
                    rawPrerequisites,
                ]

        result = set()

        for rawValue in rawValues:
            tokens = re.split(
                r"[\s,;]+",
                str(
                    rawValue
                    or ""
                ).strip(),
            )

            for token in tokens:
                if not token:
                    continue

                try:
                    result.add(
                        int(token)
                    )

                except (
                        TypeError,
                        ValueError,
                ):
                    logger.warning(
                        "Ignoring invalid prerequisite "
                        "protocol id. projectId=%s "
                        "protocolId=%s value=%s",
                        self.projectId,
                        self.protocolId,
                        token,
                    )

        return result

    def loadPrerequisiteStatuses(
            self,
            prerequisiteIds,
    ) -> Dict[int, Dict[str, Any]]:
        normalizedIds = sorted({
            int(protocolId)
            for protocolId
            in prerequisiteIds or []
        })

        if not normalizedIds:
            return {}

        rows = ProtocolGraphRepository().loadProtocolStatusesByProtocolIds(
            mapper=self.mapper,
            projectId=self.projectId,
            protocolIds=normalizedIds,
        )

        result = {}

        for row in rows or []:
            try:
                protocolId = int(
                    row["protocolId"]
                )

            except Exception:
                continue

            result[protocolId] = dict(
                row
            )

        return result

    def openDependencyEventListener(
            self,
    ):
        if (
                self.dependencyEventListener
                is not None
        ):
            return (
                self.dependencyEventListener
            )

        listener = (
            PostgresqlRuntimeEventListener(
                projectId=self.projectId
            )
        )

        try:
            # Subscribe before reading dependencies.
            # This avoids losing an event between the
            # initial readiness check and LISTEN.
            listener.open()

            parentRows = (
                self.loadParentStatuses()
            )

            prerequisiteIds = (
                self
                .getPrerequisiteProtocolIds()
            )

            prerequisiteRows = (
                self
                .loadPrerequisiteStatuses(
                    prerequisiteIds
                )
            )

            watchedProtocolIds = set(
                prerequisiteIds
            )

            watchedProtocolDbIds = set()

            for row in parentRows:
                protocolId = row.get(
                    "protocolId"
                )

                protocolDbId = row.get(
                    "protocolDbId"
                )

                try:
                    watchedProtocolIds.add(
                        int(protocolId)
                    )
                except Exception:
                    pass

                try:
                    watchedProtocolDbIds.add(
                        int(protocolDbId)
                    )
                except Exception:
                    pass

            for row in (
                    prerequisiteRows.values()
            ):
                protocolDbId = row.get(
                    "protocolDbId"
                )

                try:
                    watchedProtocolDbIds.add(
                        int(protocolDbId)
                    )
                except Exception:
                    pass

            listener.setWatchedProtocols(
                protocolIds=(
                    watchedProtocolIds
                ),
                protocolDbIds=(
                    watchedProtocolDbIds
                ),
            )

            self.dependencyEventListener = (
                listener
            )

            logger.debug(
                "Listening for PostgreSQL "
                "dependency events. "
                "projectId=%s protocolId=%s "
                "watchedProtocolIds=%s "
                "watchedProtocolDbIds=%s",
                self.projectId,
                self.protocolId,
                sorted(
                    watchedProtocolIds
                ),
                sorted(
                    watchedProtocolDbIds
                ),
            )

            return listener

        except Exception:
            listener.close()

            logger.warning(
                "PostgreSQL runtime event "
                "listener is unavailable. "
                "The scheduler will use its "
                "periodic fallback. "
                "projectId=%s protocolId=%s",
                self.projectId,
                self.protocolId,
                exc_info=True,
            )

            return None

    def waitForDependencyChange(
            self,
            timeoutSeconds: float,
    ):
        listener = (
            self.openDependencyEventListener()
        )

        if listener is None:
            time.sleep(
                min(
                    float(timeoutSeconds),
                    FALLBACK_RUNTIME_POLL_SECONDS,
                )
            )

            return None

        try:
            return listener.wait(
                timeoutSeconds
            )

        except Exception:
            logger.warning(
                "PostgreSQL dependency event "
                "wait failed. Falling back to "
                "periodic checking. "
                "projectId=%s protocolId=%s",
                self.projectId,
                self.protocolId,
                exc_info=True,
            )

            listener.close()
            self.dependencyEventListener = None

            time.sleep(
                min(
                    float(timeoutSeconds),
                    FALLBACK_RUNTIME_POLL_SECONDS,
                )
            )

            return None

    def isInputRefActive(self, inputRef) -> bool:
        inputName = str(inputRef.get("inputName") or "").strip()

        if not inputName:
            return True

        try:
            param = self.protocol.getParam(inputName)
        except Exception:
            param = None

        if param is None:
            return True

        try:
            return bool(self.protocol.evalParamCondition(inputName))
        except Exception:
            logger.warning(
                "Could not evaluate protocol input condition. projectId=%s protocolId=%s inputName=%s",
                self.projectId,
                self.protocolId,
                inputName,
                exc_info=True,
            )
            return True

    def partitionInputRefsByCondition(self, inputRefs):
        activeInputRefs = []
        inactiveInputRefs = []

        for inputRef in inputRefs or []:
            if self.isInputRefActive(inputRef):
                activeInputRefs.append(dict(inputRef))
            else:
                inactiveInputRefs.append(dict(inputRef))

        return activeInputRefs, inactiveInputRefs

    def validateProtocolInputs(
            self,
    ) -> List[str]:
        try:
            validationErrors = (
                self.protocol.validate()
                or []
            )

        except Exception as error:
            return [
                "Protocol input validation failed: %s"
                % error
            ]

        return [
            str(error)
            for error
            in validationErrors
            if str(
                error
                or ""
            ).strip()
        ]

    def validateAvailableInputs(
            self,
            inputRefs=None,
    ) -> Dict[str, Any]:
        inputReport = self.restoreExecutionInputs(persistResolvedRefs=False, inputRefs=inputRefs)

        inputRestoreErrors = list(
            inputReport.get(
                "errors"
            )
            or []
        )

        validationErrors = []

        if not inputRestoreErrors:
            validationErrors = (
                self.validateProtocolInputs()
            )

        return {
            "inputRestoreErrors": (
                inputRestoreErrors
            ),
            "validationErrors": (
                validationErrors
            ),
        }

    def getReadinessState(
            self,
    ) -> Dict[str, Any]:
        parentRows = (
            self.loadParentStatuses()
        )

        inputRefs = (
            self.loadInputRefs()
        )

        activeInputRefs, inactiveInputRefs = self.partitionInputRefsByCondition(inputRefs)

        streaming = bool(
            self.protocol
            .worksInStreaming()
        )

        prerequisiteIds = (
            self
            .getPrerequisiteProtocolIds()
        )

        prerequisiteRowsById = (
            self.loadPrerequisiteStatuses(
                prerequisiteIds
            )
        )

        parentRowsByDbId = {}

        for row in parentRows:
            try:
                parentRowsByDbId[
                    int(row["protocolDbId"])
                ] = row

            except Exception:
                continue

        failedParents = []
        pendingParents = []
        missingInputs = []
        missingPrerequisites = []
        inputRestoreErrors = []
        validationErrors = []

        pendingKeys = set()
        failedKeys = set()

        inputParentDbIds = set()

        for inputRef in inputRefs:
            try:
                inputParentDbIds.add(int(inputRef["parentProtocolDbId"]))
            except (KeyError, TypeError, ValueError):
                continue

        def addPending(
                row,
                reason,
        ):
            protocolDbId = row.get(
                "protocolDbId"
            )

            key = (
                str(protocolDbId),
                str(reason),
            )

            if key in pendingKeys:
                return

            pendingKeys.add(
                key
            )

            pendingParents.append({
                "protocolDbId": (
                    protocolDbId
                ),
                "protocolId": row.get(
                    "protocolId"
                ),
                "status": row.get(
                    "status"
                ),
                "reason": reason,
            })

        def addFailed(
                row,
        ):
            protocolDbId = row.get(
                "protocolDbId"
            )

            key = str(
                protocolDbId
            )

            if key in failedKeys:
                return

            failedKeys.add(
                key
            )

            failedParents.append(
                dict(row)
            )

        # Prerequisites are independent from input dependencies.
        # They may reference any protocol in the project.
        for prerequisiteId in sorted(
                prerequisiteIds
        ):
            prerequisiteRow = (
                prerequisiteRowsById.get(
                    prerequisiteId
                )
            )

            if prerequisiteRow is None:
                missingPrerequisites.append({
                    "protocolId": (
                        prerequisiteId
                    ),
                    "reason": (
                        "prerequisite_not_found"
                    ),
                })

                continue

            prerequisiteStatus = str(
                prerequisiteRow.get(
                    "status"
                )
                or ""
            ).strip().lower()

            if (
                    prerequisiteStatus
                    not in
                    TERMINAL_PREREQUISITE_STATUSES
            ):
                addPending(
                    prerequisiteRow,
                    "prerequisite_not_terminal",
                )

        # Check every parent required by an input pointer.
        for inputRef in activeInputRefs:
            try:
                parentProtocolDbId = int(
                    inputRef[
                        "parentProtocolDbId"
                    ]
                )

            except Exception:
                missingInputs.append({
                    **dict(inputRef),
                    "reason": (
                        "missing_parent_protocol"
                    ),
                })

                continue

            parentRow = (
                parentRowsByDbId.get(
                    parentProtocolDbId
                )
            )

            if parentRow is None:
                missingInputs.append({
                    **dict(inputRef),
                    "reason": (
                        "parent_protocol_not_found"
                    ),
                })

                continue

            parentStatus = str(
                parentRow.get(
                    "status"
                )
                or ""
            ).strip().lower()

            parentOutputName = str(inputRef.get("parentOutputName") or "").strip()
            directProtocolPointer = not parentOutputName
            parentFailed = parentStatus in FAILED_INPUT_PARENT_STATUSES

            if directProtocolPointer:
                if parentFailed:
                    addFailed(parentRow)
                    continue

                if parentStatus not in FINISHED_INPUT_PARENT_STATUSES:
                    addPending(
                        parentRow,
                        "input_parent_not_finished",
                    )
                    continue

                continue

            # A resumed streaming child must not consume an
            # output left by a previous execution while its
            # parent is still only scheduled or saved.
            #
            # Once the parent reaches launched/running, normal
            # streaming concurrency is allowed again.
            if (
                    streaming
                    and parentStatus
                    in STREAMING_PARENT_NOT_STARTED_STATUSES
            ):
                addPending(
                    parentRow,
                    "streaming_input_parent_not_started",
                )

                continue

            # A non-streaming consumer normally waits until its
            # input parent finishes. A failed/aborted parent is
            # handled differently: if the concrete output exists,
            # it may still be consumed and validated.
            if (
                    not streaming
                    and not parentFailed
                    and parentStatus
                    not in FINISHED_INPUT_PARENT_STATUSES
            ):
                addPending(
                    parentRow,
                    "input_parent_not_finished",
                )

                continue

            # For concrete output pointers, output availability is
            # authoritative once the scheduling constraints above
            # have been satisfied. A failed/aborted parent is still
            # usable if the requested output already exists.

            outputInfo = (
                self.getRuntimeOutputInfo(
                    inputRef
                )
            )

            if (
                    not outputInfo.get(
                        "exists"
                    )
                    or outputInfo.get(
                        "runtimeObjectId"
                    )
                    in (
                        None,
                        "",
                    )
            ):
                if parentFailed:
                    addFailed(parentRow)
                    continue
                missingInputs.append({
                    "inputName": (
                        inputRef.get(
                            "inputName"
                        )
                    ),
                    "itemIndex": int(
                        inputRef.get(
                            "itemIndex"
                        )
                        or 0
                    ),
                    "parentProtocolDbId": (
                        parentProtocolDbId
                    ),
                    "parentProtocolId": (
                        inputRef.get(
                            "parentProtocolId"
                        )
                    ),
                    "parentOutputName": (
                        inputRef.get(
                            "parentOutputName"
                        )
                    ),
                    "reason": (
                        "parent_output_not_available"
                    ),
                })

            if (
                    streaming
                    and parentStatus
                    not in TERMINAL_PREREQUISITE_STATUSES
                    and str(
                        outputInfo.get(
                            "kind"
                        )
                        or ""
                    ).strip().lower()
                    == "set"
                    and outputInfo.get(
                        "itemsCount"
                    )
                    == 0
            ):
                missingInputs.append({
                    "inputName": (
                        inputRef.get(
                            "inputName"
                        )
                    ),
                    "itemIndex": int(
                        inputRef.get(
                            "itemIndex"
                        )
                        or 0
                    ),
                    "parentProtocolDbId": (
                        parentProtocolDbId
                    ),
                    "parentProtocolId": (
                        inputRef.get(
                            "parentProtocolId"
                        )
                    ),
                    "parentOutputName": (
                        inputRef.get(
                            "parentOutputName"
                        )
                    ),
                    "reason": (
                        "parent_output_empty"
                    ),
                })

                continue

        # Preserve any dependency that is not represented by
        # an input pointer or by the explicit prerequisites field.
        for row in parentRows:
            try:
                parentProtocolDbId = int(
                    row["protocolDbId"]
                )

                parentProtocolId = int(
                    row["protocolId"]
                )

            except Exception:
                continue

            if (
                    parentProtocolDbId
                    in inputParentDbIds
                    or parentProtocolId
                    in prerequisiteIds
            ):
                continue

            parentStatus = str(
                row.get(
                    "status"
                )
                or ""
            ).strip().lower()

            if (
                    parentStatus
                    in FAILED_INPUT_PARENT_STATUSES
            ):
                addFailed(
                    row
                )

            elif (
                    parentStatus
                    not in
                    FINISHED_INPUT_PARENT_STATUSES
            ):
                addPending(
                    row,
                    "dependency_not_finished",
                )

        # Once outputs exist and dependencies are satisfied,
        # reconstruct the actual inputs and run Scipion validation.
        if (
                not failedParents
                and not pendingParents
                and not missingInputs
                and not missingPrerequisites
        ):
            validationReport = self.validateAvailableInputs(inputRefs=activeInputRefs)

            inputRestoreErrors = list(
                validationReport.get(
                    "inputRestoreErrors"
                )
                or []
            )

            validationErrors = list(
                validationReport.get(
                    "validationErrors"
                )
                or []
            )

        return {
            "streaming": streaming,
            "failedParents": (
                failedParents
            ),
            "pendingParents": (
                pendingParents
            ),
            "missingInputs": (
                missingInputs
            ),
            "missingPrerequisites": (
                missingPrerequisites
            ),
            "inputRestoreErrors": (
                inputRestoreErrors
            ),
            "validationErrors": (
                validationErrors
            ),
        }

    def waitUntilReady(
            self,
    ) -> None:
        startedAt = time.monotonic()

        timeoutSeconds = max(
            0.0,
            float(
                os.environ.get(
                    "SCIPION_POSTGRESQL_DEPENDENCY_TIMEOUT",
                    "0",
                )
                or 0
            ),
        )

        eventWaitSeconds = max(
            1.0,
            float(
                os.environ.get(
                    "SCIPION_POSTGRESQL_EVENT_WAIT_SECONDS",
                    str(
                        DEFAULT_RUNTIME_EVENT_WAIT_SECONDS
                    ),
                )
                or DEFAULT_RUNTIME_EVENT_WAIT_SECONDS
            ),
        )

        heartbeatSeconds = max(
            30.0,
            float(
                os.environ.get(
                    "SCIPION_POSTGRESQL_SCHEDULE_HEARTBEAT_SECONDS",
                    "300",
                )
                or 300
            ),
        )

        formatter = (
            PostgresqlSchedulingLogFormatter()
        )

        protocolLabel = (
            self.getSchedulingProtocolLabel()
        )

        lastWaitFingerprint = None
        lastWaitLogAt = None

        logger.info(
            "Checking whether protocol "
            "\"%s\" (id %s) can start.",
            protocolLabel,
            self.protocolId,
        )

        self.openDependencyEventListener()

        while True:
            readiness = (
                self.getReadinessState()
            )

            failedParents = readiness[
                "failedParents"
            ]

            if failedParents:
                failedProtocolIds = ", ".join(
                    str(
                        row.get(
                            "protocolId"
                        )
                    )
                    for row
                    in failedParents
                )

                raise RuntimeError(
                    "Protocol \"%s\" cannot start "
                    "because input protocol(s) %s "
                    "failed or were aborted."
                    % (
                        protocolLabel,
                        failedProtocolIds,
                    )
                )

            missingPrerequisites = readiness[
                "missingPrerequisites"
            ]

            if missingPrerequisites:
                missingProtocolIds = ", ".join(
                    str(
                        item.get(
                            "protocolId"
                        )
                    )
                    for item
                    in missingPrerequisites
                )

                raise RuntimeError(
                    "Protocol \"%s\" cannot start "
                    "because prerequisite "
                    "protocol(s) %s do not exist. "
                    "Check the Prerequisites field."
                    % (
                        protocolLabel,
                        missingProtocolIds,
                    )
                )

            pendingParents = readiness[
                "pendingParents"
            ]

            missingInputs = readiness[
                "missingInputs"
            ]

            inputRestoreErrors = readiness[
                "inputRestoreErrors"
            ]

            validationErrors = readiness[
                "validationErrors"
            ]

            if (
                    not pendingParents
                    and not missingInputs
                    and not inputRestoreErrors
                    and not validationErrors
            ):
                logger.info(
                    "All dependencies and inputs "
                    "are ready. Starting protocol "
                    "\"%s\" (id %s).",
                    protocolLabel,
                    self.protocolId,
                )

                return

            now = time.monotonic()

            elapsed = (
                now
                - startedAt
            )

            waitFingerprint = (
                formatter.buildFingerprint(
                    readiness
                )
            )

            waitStateChanged = (
                waitFingerprint
                != lastWaitFingerprint
            )

            heartbeatDue = (
                lastWaitLogAt is None
                or (
                    now
                    - lastWaitLogAt
                    >= heartbeatSeconds
                )
            )

            if (
                    waitStateChanged
                    or heartbeatDue
            ):
                logger.info(
                    "%s",
                    formatter.buildWaitingMessage(
                        readiness,
                        heartbeat=(
                            not waitStateChanged
                            and lastWaitFingerprint
                            is not None
                        ),
                    ),
                )

                lastWaitFingerprint = (
                    waitFingerprint
                )

                lastWaitLogAt = now

            if (
                    timeoutSeconds > 0
                    and elapsed
                    >= timeoutSeconds
            ):
                raise TimeoutError(
                    "Protocol \"%s\" could not "
                    "start after %.0f seconds.\n%s"
                    % (
                        protocolLabel,
                        elapsed,
                        formatter
                        .buildWaitingMessage(
                            readiness,
                            heartbeat=True,
                        ),
                    )
                )

            waitSeconds = (
                eventWaitSeconds
            )

            if timeoutSeconds > 0:
                remainingTimeout = max(
                    0.0,
                    timeoutSeconds
                    - elapsed,
                )

                waitSeconds = min(
                    waitSeconds,
                    remainingTimeout,
                )

            if waitSeconds <= 0:
                continue

            dependencyEvent = (
                self.waitForDependencyChange(
                    waitSeconds
                )
            )

            if dependencyEvent is not None:
                logger.debug(
                    "Received PostgreSQL "
                    "dependency event. "
                    "projectId=%s protocolId=%s "
                    "event=%s",
                    self.projectId,
                    self.protocolId,
                    dependencyEvent,
                )

    def _getExecutionInputObject(
            self,
            runtimeObjectId: int,
    ):
        runtimeObjectId = int(runtimeObjectId)

        cachedInputObject = self._executionInputObjectsByRuntimeObjectId.get(
            runtimeObjectId
        )

        if cachedInputObject is not None:
            return cachedInputObject

        if runtimeObjectId in self._executionInputObjectIdsResolving:
            return None

        self._executionInputObjectIdsResolving.add(
            runtimeObjectId
        )

        try:
            sourceOutputObject = self.runtimeMapper.selectRuntimeInputObjectById(
                runtimeObjectId,
                runtimeObjectResolver=self._getExecutionInputObject,
            )

            if sourceOutputObject is None:
                return None

            if not isinstance(sourceOutputObject, Set):
                self._executionInputObjectsByRuntimeObjectId[runtimeObjectId] = sourceOutputObject
                return sourceOutputObject

            cloneRuntimeSet = getattr(
                sourceOutputObject,
                "clone",
                None,
            )

            if not callable(cloneRuntimeSet):
                raise RuntimeError(
                    "PostgreSQL input Set does not support detached cloning. "
                    "runtimeObjectId=%s className=%s"
                    % (
                        runtimeObjectId,
                        sourceOutputObject.__class__.__name__,
                    )
                )

            runtimeInputSet = cloneRuntimeSet(
                _postgresqlDetachedConsumer=True
            )

            if runtimeInputSet is None:
                raise RuntimeError(
                    "PostgreSQL input Set clone returned None. "
                    "runtimeObjectId=%s className=%s"
                    % (
                        runtimeObjectId,
                        sourceOutputObject.__class__.__name__,
                    )
                )

            if runtimeInputSet is sourceOutputObject:
                raise RuntimeError(
                    "PostgreSQL input Set clone reused the parent output object. "
                    "runtimeObjectId=%s className=%s"
                    % (
                        runtimeObjectId,
                        sourceOutputObject.__class__.__name__,
                    )
                )

            self._executionInputSetsByRuntimeObjectId[runtimeObjectId] = runtimeInputSet
            self._executionInputObjectsByRuntimeObjectId[runtimeObjectId] = runtimeInputSet

            return runtimeInputSet

        finally:
            self._executionInputObjectIdsResolving.discard(
                runtimeObjectId
            )

    def restoreExecutionInputs(
            self,
            persistResolvedRefs: bool = True,
            inputRefs=None,
    ) -> Dict[str, Any]:
        protocolDbId = self.getProtocolDbId()

        graphRepository = (
            ProtocolGraphRepository()
        )

        if inputRefs is None:
            refs = graphRepository.loadInputRefsForProtocol(mapper=self.mapper, projectId=self.projectId,
                                                            protocolDbId=protocolDbId)
        else:
            refs = [dict(inputRef) for inputRef in inputRefs or []]

        restored = []
        errors = []
        multiPointerLists = {}

        for ref in refs or []:
            inputName = str(
                ref.get("inputName")
                or ""
            ).strip()

            parentProtocolDbId = ref.get(
                "parentProtocolDbId"
            )

            parentOutputName = str(
                ref.get("parentOutputName")
                or ""
            ).strip()

            if (
                    not inputName
                    or parentProtocolDbId
                    in (None, "")
            ):
                errors.append({
                    **dict(ref),
                    "error": (
                        "Invalid PostgreSQL "
                        "input reference"
                    ),
                })
                continue

            if not parentOutputName:
                parentProtocolId = ref.get(
                    "parentProtocolId"
                )

                if parentProtocolId in (
                        None,
                        "",
                ):
                    errors.append({
                        **dict(ref),
                        "error": (
                            "Direct PostgreSQL protocol input "
                            "does not expose parentProtocolId"
                        ),
                    })
                    continue

                try:
                    parentProtocol = (
                        self.project.getProtocol(
                            int(parentProtocolId)
                        )
                    )
                except Exception as error:
                    errors.append({
                        **dict(ref),
                        "error": (
                                "Could not reconstruct PostgreSQL "
                                "parent protocol %s: %s"
                                % (
                                    parentProtocolId,
                                    error,
                                )
                        ),
                    })
                    continue

                if parentProtocol is None:
                    errors.append({
                        **dict(ref),
                        "error": (
                                "PostgreSQL parent protocol %s "
                                "was not found"
                                % parentProtocolId
                        ),
                    })
                    continue

                pointer = Pointer(
                    parentProtocol
                )

                param = self.protocol.getParam(
                    inputName
                )

                if isinstance(
                        param,
                        MultiPointerParam,
                ):
                    pointerList = (
                        multiPointerLists.get(
                            inputName
                        )
                    )

                    if pointerList is None:
                        pointerList = PointerList()

                        multiPointerLists[
                            inputName
                        ] = pointerList

                        setattr(
                            self.protocol,
                            inputName,
                            pointerList,
                        )

                    pointerList.append(
                        pointer
                    )

                elif self._allowsScalarPointers(
                        param
                ):
                    protVar = getattr(
                        self.protocol,
                        inputName,
                        None,
                    )
                    setValue = getattr(
                        protVar,
                        "set",
                        None,
                    )
                    setPointer = getattr(
                        protVar,
                        "setPointer",
                        None,
                    )
                    if (
                            not callable(setValue)
                            or not callable(setPointer)
                    ):
                        errors.append({
                            **dict(ref),
                            "error": (
                                    "Scalar input %s does not "
                                    "support pointer restoration"
                                    % inputName
                            ),
                        })
                        continue

                    pointedValue = pointer.get()

                    if pointedValue is None:
                        errors.append({
                            **dict(ref),
                            "error": (
                                    "Scalar input %s resolved "
                                    "to None"
                                    % inputName
                            ),
                        })
                        continue

                    valueGetter = getattr(
                        pointedValue,
                        "get",
                        None,
                    )
                    scalarValue = (
                        valueGetter()
                        if callable(valueGetter)
                        else pointedValue
                    )
                    setValue(
                        scalarValue
                    )
                    setPointer(
                        pointer
                    )
                else:
                    setattr(
                        self.protocol,
                        inputName,
                        pointer,
                    )

                restored.append({
                    "inputName": inputName,
                    "itemIndex": int(
                        ref.get("itemIndex")
                        or 0
                    ),
                    "parentProtocolDbId": int(
                        parentProtocolDbId
                    ),
                    "parentProtocolId": str(
                        parentProtocolId
                    ),
                    "parentOutputName": None,
                    "runtimeObjectId": None,
                    "directProtocolPointer": True,
                    "parentProtocolModified": False,
                })

                continue

            outputParts = [
                part
                for part
                in parentOutputName.split(".")
                if part
            ]

            rootOutputName = (
                outputParts[0]
                if outputParts
                else parentOutputName
            )

            outputInfo = (
                graphRepository
                .getPostgresqlRuntimeOutputInfo(
                    mapper=self.mapper,
                    projectId=self.projectId,
                    parentProtocolDbId=int(
                        parentProtocolDbId
                    ),
                    outputName=rootOutputName,
                )
            )

            if not outputInfo.get("exists"):
                errors.append({
                    **dict(ref),
                    "error": (
                        "Parent output %s was "
                        "not found in PostgreSQL"
                        % parentOutputName
                    ),
                })
                continue

            runtimeObjectId = outputInfo.get(
                "runtimeObjectId"
            )

            if runtimeObjectId in (None, ""):
                errors.append({
                    **dict(ref),
                    "error": (
                        "Parent output %s has no "
                        "Scipion runtime object id"
                        % parentOutputName
                    ),
                })
                continue

            try:
                outputObject = self._getExecutionInputObject(int(runtimeObjectId))
            except Exception as error:
                errors.append({
                    **dict(ref),
                    "error": (
                            "Could not build detached PostgreSQL input %s: %s"
                            % (
                                parentOutputName,
                                error,
                            )
                    ),
                })
                continue

            if outputObject is None:
                errors.append({
                    **dict(ref),
                    "error": (
                            "Could not reconstruct "
                            "PostgreSQL output %s"
                            % parentOutputName
                    ),
                })
                continue

            if isinstance(outputObject, Set):
                refreshRuntimeState = getattr(outputObject, "refreshPostgresqlRuntimeState", None)

                if not callable(refreshRuntimeState):
                    errors.append({
                        **dict(ref),
                        "error": (
                                "PostgreSQL input Set %s does not expose "
                                "runtime refresh support"
                                % parentOutputName
                        ),
                    })
                    continue

                try:
                    refreshedOutputObject = refreshRuntimeState()
                except Exception as error:
                    errors.append({
                        **dict(ref),
                        "error": (
                                "Could not refresh PostgreSQL input Set %s: %s"
                                % (
                                    parentOutputName,
                                    error,
                                )
                        ),
                    })
                    continue

                if refreshedOutputObject is not outputObject:
                    errors.append({
                        **dict(ref),
                        "error": (
                                "PostgreSQL input Set refresh replaced runtime "
                                "object identity. outputName=%s"
                                % parentOutputName
                        ),
                    })
                    continue

            pointer = Pointer(
                outputObject
            )

            if len(outputParts) > 1:
                pointer.setExtendedParts(
                    outputParts[1:]
                )

            param = self.protocol.getParam(
                inputName
            )

            if isinstance(
                    param,
                    MultiPointerParam,
            ):
                pointerList = (
                    multiPointerLists.get(
                        inputName
                    )
                )

                if pointerList is None:
                    pointerList = PointerList()

                    multiPointerLists[
                        inputName
                    ] = pointerList

                    setattr(
                        self.protocol,
                        inputName,
                        pointerList,
                    )

                pointerList.append(pointer)

            elif bool(
                    getattr(
                        param,
                        "allowsPointers",
                        False,
                    )
            ):
                protVar = getattr(
                    self.protocol,
                    inputName,
                    None,
                )
                setPointer = getattr(
                    protVar,
                    "setPointer",
                    None,
                )

                if not callable(setPointer):
                    errors.append({
                        **dict(ref),
                        "error": (
                                "Scalar input %s does not "
                                "support pointer restoration"
                                % inputName
                        ),
                    })
                    continue
                setPointer(
                    pointer
                )
            else:
                setattr(
                    self.protocol,
                    inputName,
                    pointer,
                )

            if persistResolvedRefs:
                graphRepository.updateResolvedInputRef(
                    mapper=self.mapper,
                    projectId=self.projectId,
                    protocolDbId=protocolDbId,
                    inputName=inputName,
                    itemIndex=int(ref.get("itemIndex") or 0),
                    runtimeObjectId=runtimeObjectId,
                    objectClassName=outputInfo.get("className"),
                )

            restored.append({
                "inputName": inputName,
                "itemIndex": int(
                    ref.get("itemIndex")
                    or 0
                ),
                "parentProtocolDbId": int(
                    parentProtocolDbId
                ),
                "parentOutputName": (
                    parentOutputName
                ),
                "runtimeObjectId": int(
                    runtimeObjectId
                ),
                "directOutputPointer": True,
                "parentProtocolModified": False,
            })

        return {
            "restored": len(restored),
            "items": restored,
            "errors": errors,
            "parentProtocolsReadOnly": True,
        }

    def restoreResumeOutputs(
            self,
    ) -> Dict[str, Any]:
        if (
                self.runMode
                != POSTGRESQL_RUN_MODE_RESUME
        ):
            return {
                "restored": 0,
                "items": [],
                "errors": [],
                "skipped": True,
                "reason": "protocol_not_resuming",
                "selfProtocolOnly": True,
                "parentProtocolsModified": False,
            }

        objectMapper = getattr(
            self.runtimeMapper,
            "objectMapper",
            None,
        )

        outputReader = getattr(
            objectMapper,
            "listProtocolStoredObjects",
            None,
        )

        if not callable(outputReader):
            return {
                "restored": 0,
                "items": [],
                "errors": [{
                    "error": (
                        "PostgreSQL runtime object "
                        "mapper cannot load protocol outputs"
                    ),
                }],
                "skipped": False,
                "selfProtocolOnly": True,
                "parentProtocolsModified": False,
            }

        protocolDbId = (
            self.getProtocolDbId()
        )

        rows = outputReader(
            projectId=self.projectId,
            protocolDbId=protocolDbId,
        ) or []

        rootRows = [
            dict(row)
            for row in rows
            if row.get(
                "parentObjectId"
            ) in (
                None,
                "",
            )
        ]

        restored = []
        errors = []
        restoredOutputNames = set()

        for row in rootRows:
            outputName = str(
                row.get("path")
                or row.get("name")
                or ""
            ).strip()

            runtimeObjectId = row.get(
                "scipionObjId"
            )

            if not outputName:
                errors.append({
                    **row,
                    "error": (
                        "Stored PostgreSQL output "
                        "does not have an output name"
                    ),
                })
                continue

            if outputName in restoredOutputNames:
                continue

            if runtimeObjectId in (
                    None,
                    "",
            ):
                errors.append({
                    **row,
                    "outputName": outputName,
                    "error": (
                        "Stored PostgreSQL output "
                        "does not have a Scipion "
                        "runtime object id"
                    ),
                })
                continue

            sourceOutputObject = (
                self.runtimeMapper
                .selectRuntimeInputObjectById(
                    int(runtimeObjectId)
                )
            )

            if sourceOutputObject is None:
                errors.append({
                    **row,
                    "outputName": outputName,
                    "runtimeObjectId": (
                        runtimeObjectId
                    ),
                    "error": (
                        "Could not reconstruct "
                        "PostgreSQL protocol output"
                    ),
                })
                continue

            outputObject = (
                sourceOutputObject
            )

            writablePostgresql = False

            if isinstance(sourceOutputObject, Set):
                supportsNativeWrite = getattr(
                    sourceOutputObject,
                    "supportsPostgresqlNativeWrite",
                    None,
                )

                nativeWriteSupported = bool(supportsNativeWrite()) if callable(supportsNativeWrite) else False

                if not nativeWriteSupported:
                    errors.append({
                        **row,
                        "outputName": outputName,
                        "runtimeObjectId": runtimeObjectId,
                        "error": (
                            "PostgreSQL Set output cannot be resumed because "
                            "native PostgreSQL writing is not supported."
                        ),
                    })
                    continue

                enablePostgresqlWrite = getattr(
                    sourceOutputObject,
                    "enablePostgresqlWrite",
                    None,
                )

                if not callable(enablePostgresqlWrite):
                    errors.append({
                        **row,
                        "outputName": outputName,
                        "runtimeObjectId": runtimeObjectId,
                        "error": (
                            "PostgreSQL Set output declares native-write "
                            "support but does not provide "
                            "enablePostgresqlWrite()."
                        ),
                    })
                    continue

                try:
                    outputObject = enablePostgresqlWrite()

                except Exception as error:
                    errors.append({
                        **row,
                        "outputName": outputName,
                        "runtimeObjectId": runtimeObjectId,
                        "error": (
                            "Could not enable native PostgreSQL "
                            "Set writing: %s"
                            % error
                        ),
                    })
                    continue

                writablePostgresql = True

            # This is the protocol being resumed.
            # No external parent protocol or parent
            # output is attached or modified here.
            setOutputName = getattr(
                outputObject,
                "setName",
                None,
            )

            if callable(
                    setOutputName
            ):
                setOutputName(
                    outputName
                )

            # Keep the owning protocol available at runtime without
            # adding it to the persistent Scipion Object graph.
            #
            # A strong reference here creates:
            #
            # protocol -> output Set -> protocol
            #
            # and Set.write() enters infinite recursion while
            # serializing the Set properties.
            setPostgresqlRuntimeParentReference(
                runtimeObject=outputObject,
                parent=self.protocol,
            )

            parentIdSetter = getattr(
                outputObject,
                "setObjParentId",
                None,
            )

            if callable(parentIdSetter):
                parentIdSetter(
                    self.protocolId
                )
            else:
                outputObject._objParentId = (
                    self.protocolId
                )

            setattr(
                self.protocol,
                outputName,
                outputObject,
            )

            protocolOutputs = getattr(
                self.protocol,
                "_outputs",
                None,
            )

            if (
                    protocolOutputs is not None
                    and outputName
                    not in protocolOutputs
            ):
                protocolOutputs.append(
                    outputName
                )

            useOutputList = getattr(
                self.protocol,
                "_useOutputList",
                None,
            )

            useOutputListSetter = getattr(
                useOutputList,
                "set",
                None,
            )

            if callable(useOutputListSetter):
                useOutputListSetter(
                    True
                )

            reopened = False

            if isinstance(outputObject, Set):
                outputObject.setStreamState(Set.STREAM_OPEN)
                outputObject.write()
                reopened = True

            restoredOutputNames.add(
                outputName
            )

            restored.append({
                "outputName": outputName,
                "runtimeObjectId": int(
                    runtimeObjectId
                ),
                "className": (
                    outputObject
                    .__class__
                    .__name__
                ),
                "streamReopened": reopened,
                "writablePostgresql": (
                    writablePostgresql
                ),
                "ownerProtocolId": (
                    self.protocolId
                ),
                "ownerProtocolModified": True,
                "parentProtocolsModified": False,
            })

        return {
            "restored": len(restored),
            "items": restored,
            "errors": errors,
            "skipped": False,
            "selfProtocolOnly": True,
            "parentProtocolsModified": False,
        }

    def buildStepsExecutor(self):
        protocol = self.protocol

        if protocol.useQueueForSteps():
            self._ensureQueueLaunchParams()

        hostConfig = protocol.getHostConfig()
        gpuList = protocol.getGpuList()

        if protocol.useQueue():
            gpuList = anonimizeGPUs(
                gpuList
            )

        executor = None

        numberOfThreads = max(
            protocol.numberOfThreads.get(),
            1,
        )

        if (
                protocol.modeParallel()
                and numberOfThreads > 1
        ):
            if protocol.useQueueForSteps():
                executor = QueueStepExecutor(
                    hostConfig,
                    protocol.getSubmitDict(),
                    numberOfThreads - 1,
                    gpuList=gpuList,
                )
            else:
                executor = ThreadStepExecutor(
                    hostConfig,
                    numberOfThreads - 1,
                    gpuList=gpuList,
                )

        if (
                executor is None
                and protocol.useQueueForSteps()
        ):
            executor = QueueStepExecutor(
                hostConfig,
                protocol.getSubmitDict(),
                1,
                gpuList=gpuList,
            )

        if executor is None:
            executor = StepExecutor(
                hostConfig,
                gpuList=gpuList,
            )

        return executor

    def storeProtocol(self) -> None:
        self.runtimeMapper.store(
            self.protocol
        )

        self.runtimeMapper.commit()

        PostgresqlRuntimeEventPublisher.publish(
            db=self.mapper.db,
            projectId=self.projectId,
            eventType=(
                "protocol_changed"
            ),
            protocolId=self.protocolId,
            protocolDbId=(
                self.getProtocolDbId()
            ),
            status=str(
                self.protocol.getStatus()
                or ""
            ),
        )

    def markProtocolExecutionLaunched(
            self,
    ) -> Dict[str, Any]:
        statusService = (
            RuntimeProtocolStatusSyncService()
        )

        baseElapsedTimeSeconds = (
            statusService
            .getStoredElapsedTimeSeconds(
                mapper=self.mapper,
                projectId=self.projectId,
                protocolId=self.protocolId,
            )
        )

        return (
            statusService
            .markProtocolLaunched(
                mapper=self.mapper,
                projectId=self.projectId,
                protocolId=self.protocolId,
                baseElapsedTimeSeconds=(
                    baseElapsedTimeSeconds
                ),
                resetElapsed=(
                    self.runMode
                    == POSTGRESQL_RUN_MODE_RESTART
                ),
            )
        )

    def getProtocolExecutionUserId(
            self,
    ):
        row = (
            self.mapper
            .getProjectProtocolByProtocolId(
                projectId=self.projectId,
                protocolId=self.protocolId,
            )
            or {}
        )

        statusService = (
            RuntimeProtocolStatusSyncService()
        )

        params = statusService.normalizeParams(
            row.get("params")
        )

        runtimeMetadata = params.get(
            statusService.RUNTIME_METADATA_KEY
        ) or {}

        if not isinstance(
                runtimeMetadata,
                dict,
        ):
            return None

        userId = runtimeMetadata.get(
            "launchedByUserId"
        )

        try:
            return int(userId)

        except (
                TypeError,
                ValueError,
        ):
            return None

    def getMaxConcurrentRunsPerUser(
            self,
    ) -> int:
        instanceSettings = (
            SettingsService()
            .getRuntimeInstanceSettings(
                mapper=self.mapper,
                currentUser=None,
            )
        )

        try:
            maxConcurrentRuns = int(
                instanceSettings.get(
                    "maxConcurrentRunsPerUser"
                )
                or 4
            )

        except (
                TypeError,
                ValueError,
        ):
            maxConcurrentRuns = 4

        return max(
            1,
            min(
                64,
                maxConcurrentRuns,
            ),
        )

    def waitForUserExecutionSlot(
            self,
    ) -> bool:
        userId = (
            self.getProtocolExecutionUserId()
        )

        if userId is None:
            return True

        pollSeconds = max(
            0.1,
            float(
                os.environ.get(
                    "SCIPION_POSTGRESQL_EXECUTION_SLOT_POLL_SECONDS",
                    "5",
                )
                or 5
            ),
        )

        heartbeatSeconds = max(
            pollSeconds,
            float(
                os.environ.get(
                    "SCIPION_POSTGRESQL_EXECUTION_SLOT_HEARTBEAT_SECONDS",
                    "60",
                )
                or 60
            ),
        )

        lastWaitLogAt = None

        while True:
            with self.mapper.protocolExecutionUserLock(
                    userId
            ):
                storedStatus = (
                    self.getStoredProtocolStatus()
                )

                if storedStatus == "running":
                    self.protocol.setStatus(
                        STATUS_RUNNING
                    )

                    return True

                if storedStatus in {
                    "finished",
                    "failed",
                    "aborted",
                    "interactive",
                }:
                    logger.info(
                        "Protocol execution slot is no longer "
                        "required because the protocol became "
                        "terminal. projectId=%s protocolId=%s "
                        "status=%s",
                        self.projectId,
                        self.protocolId,
                        storedStatus,
                    )

                    return False

                if storedStatus not in {
                    "scheduled",
                    "launched",
                }:
                    raise RuntimeError(
                        "Cannot acquire protocol execution slot "
                        "from status '%s'. "
                        "projectId=%s protocolId=%s"
                        % (
                            storedStatus,
                            self.projectId,
                            self.protocolId,
                        )
                    )

                maxConcurrentRuns = (
                    self.getMaxConcurrentRunsPerUser()
                )

                runningProtocols = (
                    self.mapper
                    .countRunningProtocolsForUser(
                        userId
                    )
                )

                if (
                        runningProtocols
                        < maxConcurrentRuns
                ):
                    self.protocol.setStatus(
                        STATUS_RUNNING
                    )

                    self.storeProtocol()

                    logger.info(
                        "Acquired protocol execution slot. "
                        "userId=%s running=%s limit=%s "
                        "projectId=%s protocolId=%s",
                        userId,
                        runningProtocols + 1,
                        maxConcurrentRuns,
                        self.projectId,
                        self.protocolId,
                    )

                    return True

            now = time.monotonic()

            if (
                    lastWaitLogAt is None
                    or (
                        now
                        - lastWaitLogAt
                        >= heartbeatSeconds
                    )
            ):
                logger.info(
                    "Waiting for protocol execution slot. "
                    "userId=%s running=%s limit=%s "
                    "projectId=%s protocolId=%s",
                    userId,
                    runningProtocols,
                    maxConcurrentRuns,
                    self.projectId,
                    self.protocolId,
                )

                lastWaitLogAt = now

            time.sleep(
                pollSeconds
            )

    def getStoredProtocolStatus(self) -> str:
        row = self.mapper.getProjectProtocolByProtocolId(
            projectId=self.projectId,
            protocolId=self.protocolId,
        )

        return str((row or {}).get("status") or "").strip().lower()

    def registerCoordinatorProcess(self) -> None:
        """
        Register the real PostgreSQL worker before waiting
        for dependencies.

        Only process identity is persisted here. The protocol
        is already scheduled, so this must never overwrite a
        concurrent terminal status such as aborted.
        """
        self.protocol.setPid(os.getpid())

        RuntimeProtocolStatusSyncService().persistProtocolProcessIdentity(
            mapper=self.mapper,
            projectId=self.projectId,
            protocolId=self.protocolId,
            protocol=self.protocol,
        )

    def rollbackPostgresqlTransaction(
            self,
    ) -> None:
        db = getattr(
            self.mapper,
            "db",
            None,
        )

        if db is None:
            return

        rollback = getattr(
            db,
            "rollback",
            None,
        )

        if callable(
                rollback
        ):
            rollback()
            return

        connection = getattr(
            db,
            "conn",
            None,
        )

        if connection is not None:
            connection.rollback()

    def markFailed(
            self,
            error,
    ) -> None:
        logger.exception(
            "PostgreSQL protocol execution failed. "
            "projectId=%s protocolId=%s",
            self.projectId,
            self.protocolId,
        )

        # A PostgreSQL error leaves the connection in an
        # aborted transaction. Clear it before trying to
        # persist the terminal protocol state.
        self.rollbackPostgresqlTransaction()

        self.protocol.setFailed(
            str(error)
        )

        try:
            self.storeProtocol()

        except Exception:
            logger.exception(
                "Could not persist the complete failed "
                "protocol state. Falling back to a direct "
                "status update. projectId=%s protocolId=%s",
                self.projectId,
                self.protocolId,
            )

            self.rollbackPostgresqlTransaction()

            # Last-resort protection against protocols
            # remaining permanently Running/Launched.
            self.mapper.updateProjectProtocolStatus(
                projectId=self.projectId,
                protocolId=self.protocolId,
                statusValue=STATUS_FAILED,
            )

    def _getEffectiveQueueLaunchParams(self):
        settingsService = SettingsService()

        instanceSettings = settingsService.getRuntimeInstanceSettings(
            mapper=self.mapper,
            currentUser=None,
        )

        hostSettings = settingsService.getRuntimeHostSettings(
            mapper=self.mapper,
            currentUser=None,
        )

        queues = list(hostSettings.get("queues") or [])

        if not queues:
            raise RuntimeError(
                "Protocol requires queue execution but no queues are configured in the effective host settings."
            )

        defaultQueueName = str(instanceSettings.get("defaultQueueName") or "").strip()

        selectedQueue = next(
            (
                queue
                for queue in queues
                if str(queue.get("name") or "").strip() == defaultQueueName
            ),
            None,
        )

        if selectedQueue is None:
            selectedQueue = queues[0]

        queueName = str(selectedQueue.get("name") or "").strip()

        if not queueName:
            raise RuntimeError(
                "Effective queue configuration does not define a queue name."
            )

        queueParams = {}

        for queueParam in selectedQueue.get("params") or []:
            variableName = str(queueParam.get("variableName") or "").strip()

            if not variableName:
                continue

            queueParams[variableName] = str(queueParam.get("value") or "")

        return queueName, queueParams

    def _ensureQueueLaunchParams(self):
        if self.protocol.hasQueueParams():
            queueName, queueParams = self.protocol.getQueueParams()

            if not isinstance(queueParams, dict):
                raise RuntimeError(
                    "Protocol queue launch params must be a dictionary."
                )

            return str(queueName or ""), dict(queueParams)

        queueName, queueParams = self._getEffectiveQueueLaunchParams()

        self.protocol.setQueueParams([
            queueName,
            queueParams,
        ])

        return queueName, dict(queueParams)

    def submitToQueue(self) -> int:
        queueName, queueParams = self._ensureQueueLaunchParams()

        command = buildPostgresqlWorkerCommand(
            projectId=self.projectId,
            protocolId=self.protocolId,
            execute=True,
            runMode=self.runMode,
            queueName=queueName,
            queueParams=queueParams,
        )

        hostConfig = self.protocol.getHostConfig()
        submitDict = self.protocol.getSubmitDict()
        submitDict["JOB_COMMAND"] = shlex.join(command)

        queueEnv = os.environ.copy()

        bindingsPath = Config.getBindingsFolder()
        pythonPath = queueEnv.get("PYTHONPATH", "")

        queueEnv["PYTHONPATH"] = os.pathsep.join(
            path
            for path in [
                bindingsPath,
                pythonPath,
            ]
            if path
        )

        jobId, error = _submit(
            hostConfig,
            submitDict,
            cwd=self.project.path,
            env=queueEnv,
        )

        if jobId is None or jobId == UNKNOWN_JOBID:
            raise RuntimeError(
                "Could not submit PostgreSQL protocol to the queue: %s"
                % error
            )

        self.protocol.setJobId(jobId)
        self.protocol.setPid(0)
        self.protocol.setStatus(STATUS_LAUNCHED)

        self.storeProtocol()
        self.markProtocolExecutionLaunched()

        return 0

    def execute(self) -> int:

        inputRefs = self.loadInputRefs()
        activeInputRefs, _ = self.partitionInputRefsByCondition(inputRefs)
        inputReport = self.restoreExecutionInputs(inputRefs=activeInputRefs)

        if inputReport.get("errors"):
            raise RuntimeError(
                "Could not restore PostgreSQL "
                "execution inputs: %s"
                % inputReport["errors"]
            )

        resumeOutputReport = (
            self.restoreResumeOutputs()
        )

        if resumeOutputReport.get(
                "errors"
        ):
            raise RuntimeError(
                "Could not restore PostgreSQL "
                "outputs for protocol resume: %s"
                % resumeOutputReport[
                    "errors"
                ]
            )

        validationErrors = (
            self.validateProtocolInputs()
        )

        if validationErrors:
            raise RuntimeError(
                "Protocol inputs are not ready: %s"
                % validationErrors
            )

        self.configureRunLogging()
        stepAdapter = (
            RuntimePostgresqlStepAdapter(
                mapper=self.mapper,
                projectId=self.projectId,
                protocol=self.protocol,
                runMode=self.runMode,
            )
        )

        stepAdapter.install()

        scipionRunMode = (
            MODE_RESUME
            if (
                    self.runMode
                    == POSTGRESQL_RUN_MODE_RESUME
            )
            else MODE_RESTART
        )

        self.protocol.runMode.set(
            scipionRunMode
        )

        self.protocol.setStatus(
            STATUS_LAUNCHED
        )

        if not self.protocol.useQueueForProtocol():
            self.protocol.setPid(
                os.getpid()
            )

        self.storeProtocol()

        self.markProtocolExecutionLaunched()

        if not self.waitForUserExecutionSlot():
            return 0

        self.protocol.setStepsExecutor(
            self.buildStepsExecutor()
        )

        outputSetAdapter = (
            RuntimePostgresqlOutputSetAdapter(
                runtimeMapper=(
                    self.runtimeMapper
                ),
                projectId=self.projectId,
                protocol=self.protocol,
            )
        )

        outputSetAdapter.install()

        try:
            self.protocol.run()

            self.storeProtocol()

        finally:
            outputSetAdapter.uninstall()

        protocolStatus = str(
            self.protocol.getStatus()
            or ""
        ).strip().lower()

        relationsSynchronized = (
            protocolStatus
            in {
                str(
                    STATUS_FINISHED
                ).lower(),
                str(
                    STATUS_INTERACTIVE
                ).lower(),
                "finished",
                "interactive",
            }
        )

        ProtocolGraphRepository().setProtocolRelationsSynchronized(
            mapper=self.mapper,
            projectId=self.projectId,
            protocolId=self.protocolId,
            synchronized=relationsSynchronized,
        )

        return (
            0
            if relationsSynchronized
            else 1
        )

    def run(
            self,
            execute: bool = False,
    ) -> int:
        self.load()

        try:
            if not execute:
                if self.getStoredProtocolStatus() != str(STATUS_SCHEDULED).strip().lower():
                    logger.info(
                        "Skipping PostgreSQL protocol coordinator because protocol is no longer scheduled. "
                        "projectId=%s protocolId=%s status=%s",
                        self.projectId,
                        self.protocolId,
                        self.getStoredProtocolStatus(),
                    )
                    return 0

                self.registerCoordinatorProcess()

                if self.getStoredProtocolStatus() != str(STATUS_SCHEDULED).strip().lower():
                    logger.info(
                        "Stopping PostgreSQL protocol coordinator because protocol changed state during dispatch. "
                        "projectId=%s protocolId=%s status=%s",
                        self.projectId,
                        self.protocolId,
                        self.getStoredProtocolStatus(),
                    )
                    return 0

            self.waitUntilReady()

            if (
                    not execute
                    and self.protocol
                    .useQueueForProtocol()
            ):
                return self.submitToQueue()

            return self.execute()

        except Exception as error:
            self.markFailed(error)
            return 1
        finally:
            try:
                self.close()
            finally:
                self.cleanupCompatibilitySqliteSnapshots()


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--project-id",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--protocol-id",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--run-mode",
        choices=sorted(
            POSTGRESQL_RUN_MODES
        ),
        default=(
            POSTGRESQL_RUN_MODE_RESTART
        ),
    )

    parser.add_argument(
        "--queue-name",
        default=None,
    )

    parser.add_argument(
        "--queue-params-json",
        default=None,
    )

    parser.add_argument(
        "--execute",
        action="store_true",
    )

    args = parser.parse_args()

    queueParams = None

    if args.queue_params_json is not None:
        try:
            queueParams = json.loads(args.queue_params_json)
        except json.JSONDecodeError as error:
            parser.error(
                "Invalid PostgreSQL queue params JSON: %s"
                % error
            )

        if not isinstance(queueParams, dict):
            parser.error(
                "PostgreSQL queue params must decode to a dictionary."
            )

    if args.queue_name is not None and queueParams is None:
        parser.error(
            "--queue-name requires --queue-params-json."
        )

    worker = RuntimePostgresqlProtocolWorker(
        projectId=args.project_id,
        protocolId=args.protocol_id,
        runMode=args.run_mode,
        queueName=args.queue_name,
        queueParams=queueParams,
    )

    return worker.run(
        execute=args.execute
    )


if __name__ == "__main__":
    raise SystemExit(main())