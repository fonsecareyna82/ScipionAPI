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
    STATUS_ABORTED,
    STATUS_FAILED,
    STATUS_FINISHED,
    STATUS_INTERACTIVE,
    STATUS_LAUNCHED,
)
from pyworkflow.protocol.constants import UNKNOWN_JOBID
from pyworkflow.protocol.executor import (
    QueueStepExecutor,
    StepExecutor,
    ThreadStepExecutor,
)
from pyworkflow.protocol.launch import _submit
from pyworkflow.protocol.params import MultiPointerParam
from pyworkflow.protocol.protocol import anonimizeGPUs
from pyworkflow.utils import LoggingConfigurator
from pyworkflow.utils.log import setDefaultLoggingContext

from app.backend.database import getMapper
from app.backend.project import PostgresqlProject
from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
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


logger = logging.getLogger(__name__)

WORKER_MODULE = (
    "app.backend.runtime.postgresql_protocol_worker"
)

READY_PARENT_STATUSES = {
    STATUS_FINISHED,
    STATUS_INTERACTIVE,
    "finished",
    "interactive",
}

FAILED_PARENT_STATUSES = {
    STATUS_FAILED,
    STATUS_ABORTED,
    "failed",
    "aborted",
}


def buildPostgresqlWorkerCommand(
        projectId: int,
        protocolId: int,
        execute: bool = False,
) -> List[str]:
    command = [
        sys.executable,
        "-m",
        WORKER_MODULE,
        "--project-id",
        str(projectId),
        "--protocol-id",
        str(protocolId),
    ]

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
    ):
        self.mapper = mapper
        self.projectId = int(projectId)
        self.protocol = protocol
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

        self.protocolDbId = (
            identityResolver
            .resolvePostgresqlProtocolDbId(
                self.protocolId
            )
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

        def loadSteps(protocolSelf):
            return list(
                getattr(
                    protocolSelf,
                    "_steps",
                    [],
                )
                or []
            )

        def storeSteps(protocolSelf):
            adapter.replaceSteps()

        def updateStep(protocolSelf, step):
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
        stepIndex = getattr(
            step,
            "getIndex",
            lambda: None,
        )()

        if stepIndex is None:
            return

        stepIndex = int(stepIndex)

        snapshots = self.buildSnapshots()

        stepSnapshot = next(
            (
                snapshot
                for snapshot in snapshots
                if int(
                    snapshot.get("index")
                    or -1
                ) == stepIndex
            ),
            None,
        )

        if stepSnapshot is None:
            return

        self.mapper.upsertProtocolStep(
            projectId=self.projectId,
            protocolDbId=self.protocolDbId,
            protocolId=self.protocolId,
            step=stepSnapshot,
        )


class RuntimePostgresqlProtocolWorker:
    def __init__(
            self,
            projectId: int,
            protocolId: int,
    ):
        self.projectId = int(projectId)
        self.protocolId = int(protocolId)

        self.mapper = None
        self.project = None
        self.protocol = None
        self.runtimeMapper = None

    def load(self) -> None:
        self.mapper = getMapper()

        projectRow = self.mapper.db.fetchOne(
            """
            SELECT name
              FROM projects
             WHERE id = %s
             LIMIT 1
            """,
            (self.projectId,),
        )

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
            enableWriteFallback=False,
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

        self.protocol.makeWorkingDir()

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

    def close(self) -> None:
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

    def getProtocolDbId(self) -> int:
        resolver = ProtocolIdentityResolver(
            mapper=self.mapper,
            projectId=self.projectId,
        )

        protocolDbId = (
            resolver
            .resolvePostgresqlProtocolDbId(
                self.protocolId
            )
        )

        if protocolDbId is None:
            raise RuntimeError(
                "Protocol %s was not found "
                "in PostgreSQL"
                % self.protocolId
            )

        return int(protocolDbId)

    def loadParentStatuses(self) -> List[Dict[str, Any]]:
        protocolDbId = self.getProtocolDbId()

        rows = self.mapper.db.fetchAll(
            """
            SELECT
                parent.id AS "protocolDbId",
                parent."protocolId",
                parent.status
              FROM protocol_dependencies dependency
              JOIN protocols parent
                ON parent."projectId" =
                   dependency."projectId"
               AND parent.id =
                   dependency."parentProtocolDbId"
             WHERE dependency."projectId" = %s
               AND dependency."childProtocolDbId" = %s
             ORDER BY parent.id
            """,
            (
                self.projectId,
                protocolDbId,
            ),
        )

        return [
            dict(row)
            for row in rows or []
        ]

    def waitForDependencies(self) -> None:
        startedAt = time.monotonic()

        timeoutSeconds = float(
            os.environ.get(
                "SCIPION_POSTGRESQL_DEPENDENCY_TIMEOUT",
                "0",
            )
            or 0
        )

        lastReportedAt = 0.0

        while True:
            parentRows = self.loadParentStatuses()

            failedParents = []
            pendingParents = []

            for row in parentRows:
                parentStatus = str(
                    row.get("status")
                    or ""
                ).strip().lower()

                if (
                        parentStatus
                        in FAILED_PARENT_STATUSES
                ):
                    failedParents.append(row)
                    continue

                if (
                        parentStatus
                        not in READY_PARENT_STATUSES
                ):
                    pendingParents.append(row)

            if failedParents:
                raise RuntimeError(
                    "Cannot execute protocol %s because "
                    "parent protocol(s) failed or aborted: %s"
                    % (
                        self.protocolId,
                        ", ".join(
                            str(
                                row.get(
                                    "protocolId"
                                )
                            )
                            for row
                            in failedParents
                        ),
                    )
                )

            if not pendingParents:
                return

            elapsed = (
                time.monotonic()
                - startedAt
            )

            if (
                    timeoutSeconds > 0
                    and elapsed
                    >= timeoutSeconds
            ):
                raise TimeoutError(
                    "Timed out waiting for parent "
                    "protocols of %s: %s"
                    % (
                        self.protocolId,
                        ", ".join(
                            str(
                                row.get(
                                    "protocolId"
                                )
                            )
                            for row
                            in pendingParents
                        ),
                    )
                )

            if (
                    elapsed
                    - lastReportedAt
                    >= 30
            ):
                logger.info(
                    "Waiting for PostgreSQL parent "
                    "protocols. projectId=%s "
                    "protocolId=%s parents=%s",
                    self.projectId,
                    self.protocolId,
                    [
                        {
                            "protocolId": row.get(
                                "protocolId"
                            ),
                            "status": row.get(
                                "status"
                            ),
                        }
                        for row
                        in pendingParents
                    ],
                )

                lastReportedAt = elapsed

            time.sleep(2)

    def restoreExecutionInputs(self) -> Dict[str, Any]:
        protocolDbId = self.getProtocolDbId()

        graphRepository = (
            ProtocolGraphRepository()
        )

        refs = (
            graphRepository
            .loadInputRefsForProtocol(
                mapper=self.mapper,
                projectId=self.projectId,
                protocolDbId=protocolDbId,
            )
        )

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
                    or not parentOutputName
            ):
                errors.append({
                    **dict(ref),
                    "error": (
                        "Invalid PostgreSQL "
                        "input reference"
                    ),
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

            outputObject = (
                self.runtimeMapper
                .selectById(
                    int(runtimeObjectId)
                )
            )

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

            else:
                setattr(
                    self.protocol,
                    inputName,
                    pointer,
                )

            self.mapper.db.execute(
                """
                UPDATE protocol_input_refs
                   SET "objectId" = %s,
                       "objectClassName" = %s,
                       "updatedAt" = NOW()
                 WHERE "projectId" = %s
                   AND "protocolDbId" = %s
                   AND "inputName" = %s
                   AND "itemIndex" = %s
                """,
                (
                    str(runtimeObjectId),
                    outputInfo.get(
                        "className"
                    ),
                    self.projectId,
                    protocolDbId,
                    inputName,
                    int(
                        ref.get(
                            "itemIndex"
                        )
                        or 0
                    ),
                ),
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

    def buildStepsExecutor(self):
        protocol = self.protocol
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

    def markFailed(self, error) -> None:
        logger.exception(
            "PostgreSQL protocol execution failed. "
            "projectId=%s protocolId=%s",
            self.projectId,
            self.protocolId,
        )

        self.protocol.setFailed(
            str(error)
        )

        self.storeProtocol()

    def submitToQueue(self) -> int:
        command = buildPostgresqlWorkerCommand(
            projectId=self.projectId,
            protocolId=self.protocolId,
            execute=True,
        )

        hostConfig = (
            self.protocol
            .getHostConfig()
        )

        submitDict = dict(
            hostConfig.getQueuesDefault()
        )

        submitDict.update(
            self.protocol.getSubmitDict()
        )

        submitDict["JOB_COMMAND"] = (
            shlex.join(command)
        )

        jobId, error = _submit(
            hostConfig,
            submitDict,
            cwd=self.project.path,
            env=os.environ.copy(),
        )

        if (
                jobId is None
                or jobId == UNKNOWN_JOBID
        ):
            raise RuntimeError(
                "Could not submit PostgreSQL "
                "protocol to the queue: %s"
                % error
            )

        self.protocol.setJobId(
            jobId
        )

        self.protocol.setPid(0)

        self.protocol.setStatus(
            STATUS_LAUNCHED
        )

        self.storeProtocol()

        RuntimeProtocolStatusSyncService().markProtocolLaunched(
            mapper=self.mapper,
            projectId=self.projectId,
            protocolId=self.protocolId,
            resetElapsed=True,
        )

        return 0

    def execute(self) -> int:
        self.waitForDependencies()

        inputReport = (
            self.restoreExecutionInputs()
        )

        if inputReport.get("errors"):
            raise RuntimeError(
                "Could not restore PostgreSQL "
                "execution inputs: %s"
                % inputReport["errors"]
            )

        stepAdapter = (
            RuntimePostgresqlStepAdapter(
                mapper=self.mapper,
                projectId=self.projectId,
                protocol=self.protocol,
            )
        )

        stepAdapter.install()

        self.protocol.runMode.set(
            MODE_RESTART
        )

        self.protocol.setStatus(
            STATUS_LAUNCHED
        )

        if not self.protocol.useQueueForProtocol():
            self.protocol.setPid(
                os.getpid()
            )

        self.storeProtocol()

        RuntimeProtocolStatusSyncService().markProtocolLaunched(
            mapper=self.mapper,
            projectId=self.projectId,
            protocolId=self.protocolId,
            resetElapsed=True,
        )

        self.protocol.setStepsExecutor(
            self.buildStepsExecutor()
        )

        self.protocol.run()

        self.storeProtocol()

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

        self.mapper.db.execute(
            """
            UPDATE protocols
               SET "relationsSynchronized" = %s,
                   "updatedAt" = NOW()
             WHERE "projectId" = %s
               AND "protocolId" = %s
            """,
            (
                relationsSynchronized,
                self.projectId,
                str(self.protocolId),
            ),
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
            self.waitForDependencies()

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
            self.close()


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
        "--execute",
        action="store_true",
    )

    args = parser.parse_args()

    worker = RuntimePostgresqlProtocolWorker(
        projectId=args.project_id,
        protocolId=args.protocol_id,
    )

    return worker.run(
        execute=args.execute
    )


if __name__ == "__main__":
    raise SystemExit(main())