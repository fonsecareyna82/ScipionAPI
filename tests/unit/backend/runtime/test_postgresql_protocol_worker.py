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
import threading
import inspect
from types import SimpleNamespace

import app.backend.runtime.postgresql_protocol_worker as postgresqlProtocolWorkerModule

from pyworkflow.object import (
    Object,
    Set,
)

from app.backend.runtime.postgresql_protocol_worker import (
    POSTGRESQL_RUN_MODE_RESUME,
    RuntimePostgresqlProtocolWorker,
    RuntimePostgresqlStepAdapter,
)


class ProtocolStub:
    def __init__(
            self,
            streaming=False,
            prerequisites=None,
            inputConditions=None,
    ):
        self.streaming = streaming
        self.prerequisites = [] if prerequisites is None else prerequisites
        self.inputConditions = dict(inputConditions or {})

    def worksInStreaming(self):
        return self.streaming

    def getPrerequisites(self):
        return self.prerequisites

    def getParam(self, paramName):
        return SimpleNamespace()

    def evalParamCondition(self, paramName):
        return self.inputConditions.get(paramName, True)


def buildWorker(
        streaming,
        parentStatus="running",
        outputExists=True,
        prerequisites=None,
        prerequisiteStatuses=None,
        validationErrors=None,
        inputRestoreErrors=None,
        inputCondition=True,
):
    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    worker.protocol = ProtocolStub(
        streaming=streaming,
        prerequisites=prerequisites,
        inputConditions={
            "inputSet": inputCondition,
        },
    )

    worker.loadParentStatuses = lambda: [
        {
            "protocolDbId": 20,
            "protocolId": 2,
            "status": parentStatus,
        },
    ]

    worker.loadInputRefs = lambda: [
        {
            "inputName": "inputSet",
            "itemIndex": 0,
            "parentProtocolDbId": 20,
            "parentProtocolId": 2,
            "parentOutputName": "outputSet",
        },
    ]

    worker.getRuntimeOutputInfo = (
        lambda inputRef: {
            "exists": outputExists,
            "runtimeObjectId": (
                200
                if outputExists
                else None
            ),
        }
    )

    prerequisiteStatuses = (
        prerequisiteStatuses
        or {}
    )

    def loadPrerequisiteStatuses(
            protocolIds,
    ):
        result = {}

        for protocolId in protocolIds:
            if (
                    protocolId
                    not in prerequisiteStatuses
            ):
                continue

            result[protocolId] = {
                "protocolDbId": (
                    100 + protocolId
                ),
                "protocolId": protocolId,
                "status": (
                    prerequisiteStatuses[
                        protocolId
                    ]
                ),
            }

        return result

    worker.loadPrerequisiteStatuses = (
        loadPrerequisiteStatuses
    )

    worker.validateAvailableInputs = (
        lambda inputRefs=None: {
            "inputRestoreErrors": list(
                inputRestoreErrors
                or []
            ),
            "validationErrors": list(
                validationErrors
                or []
            ),
        }
    )

    return worker


def test_WorkerDoesNotExecuteDirectPostgresqlQueries():
    source = inspect.getsource(RuntimePostgresqlProtocolWorker)

    assert "self.mapper.db.fetchOne(" not in source
    assert "self.mapper.db.fetchAll(" not in source
    assert "self.mapper.db.execute(" not in source


def test_WorkerLoadUsesMapperProjectRuntimeMetadata(
        authTestEnv,
        monkeypatch,
        tmp_path,
):
    projectPath = tmp_path / "runtime-project"
    import app.backend.database as databaseModule
    projectPath.mkdir()

    calls = {
        "runtimeMetadata": [],
    }

    class ForbiddenDbStub:
        def fetchOne(self, *args, **kwargs):
            raise AssertionError(
                "Worker load must not execute direct project SQL"
            )

    class MapperStub:
        def __init__(self):
            self.db = ForbiddenDbStub()

        def getProjectRuntimeMetadata(self, projectId):
            calls["runtimeMetadata"].append(projectId)

            return {
                "id": projectId,
                "name": str(projectPath),
            }

    runtimeMapper = object()

    class ProtocolStub:
        def makeWorkingDir(self):
            calls["workingDirCreated"] = True

    protocol = ProtocolStub()

    class ProjectStub:
        def __init__(
                self,
                domain,
                path,
                projectId,
                flatMapper,
        ):
            calls["projectInit"] = {
                "domain": domain,
                "path": path,
                "projectId": projectId,
                "flatMapper": flatMapper,
            }

        def load(self, chdir=False):
            calls["projectLoadChdir"] = chdir

        def getPostgresqlRuntimeMapper(self):
            return runtimeMapper

        def getProtocol(self, protocolId):
            calls["loadedProtocolId"] = protocolId
            return protocol

    mapper = MapperStub()

    monkeypatch.setattr(
        databaseModule,
        "getMapper",
        lambda: mapper,
    )

    monkeypatch.setattr(
        postgresqlProtocolWorkerModule,
        "PostgresqlProject",
        ProjectStub,
    )

    monkeypatch.setattr(
        postgresqlProtocolWorkerModule.Config,
        "getDomain",
        lambda: "test-domain",
    )

    worker = RuntimePostgresqlProtocolWorker(
        projectId=7,
        protocolId=31,
    )

    worker.configureSchedulingLogging = lambda: None
    worker.load()

    assert calls == {
        "runtimeMetadata": [7],
        "projectInit": {
            "domain": "test-domain",
            "path": str(projectPath),
            "projectId": 7,
            "flatMapper": mapper,
        },
        "projectLoadChdir": True,
        "loadedProtocolId": 31,
        "workingDirCreated": True,
    }

    assert worker.mapper is mapper
    assert worker.runtimeMapper is runtimeMapper
    assert worker.protocol is protocol


def test_WorkerAppliesTransientQueueOverrideInMemory():
    class QueueProtocolStub:
        def __init__(self):
            self.queueParams = None

        def useQueue(self):
            return True

        def setQueueParams(self, queueParams):
            self.queueParams = queueParams

    protocol = QueueProtocolStub()

    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
        queueName="gpu",
        queueParams={
            "JOB_TIME": "72",
        },
    )

    worker.protocol = protocol

    assert worker._applyQueueLaunchOverride() is True

    assert protocol.queueParams == [
        "gpu",
        {
            "JOB_TIME": "72",
        },
    ]


def test_RestoreExecutionInputsRefreshesDetachedSetWithoutMutatingParentOutput(
        monkeypatch,
):
    class InputSet(Set):
        def __init__(self, size):
            super().__init__()
            self._size.set(size)
            self.refreshCalls = 0
            self.cloneCalls = 0
            self.lastClone = None
            self.cloneKwargs = []

        def clone(self, **kwargs):
            self.cloneCalls += 1
            self.cloneKwargs.append(dict(kwargs))

            runtimeClone = InputSet(self.getSize())
            runtimeClone.setObjId(self.getObjId())

            self.lastClone = runtimeClone
            return runtimeClone

        def refreshPostgresqlRuntimeState(self):
            self.refreshCalls += 1
            self._size.set(5236)
            return self

    class RuntimeMapperStub:
        def __init__(self, outputSet):
            self.outputSet = outputSet
            self.selectCalls = []

        def selectRuntimeInputObjectById(self, runtimeObjectId):
            self.selectCalls.append(runtimeObjectId)
            return self.outputSet

    class GraphRepositoryStub:
        def getPostgresqlRuntimeOutputInfo(self, **kwargs):
            assert kwargs["projectId"] == 1
            assert kwargs["parentProtocolDbId"] == 20
            assert kwargs["outputName"] == "outputParticles"

            return {
                "exists": True,
                "runtimeObjectId": 44,
                "className": "SetOfParticles",
            }

    class InputProtocolStub:
        def getParam(self, paramName):
            assert paramName == "inputParticles"
            return SimpleNamespace()

    parentOutputSet = InputSet(2236)
    parentOutputSet.setObjId(44)

    runtimeMapper = RuntimeMapperStub(parentOutputSet)

    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    worker.mapper = object()
    worker.runtimeMapper = runtimeMapper
    worker.protocol = InputProtocolStub()
    worker.getProtocolDbId = lambda: 30

    monkeypatch.setattr(
        postgresqlProtocolWorkerModule,
        "ProtocolGraphRepository",
        GraphRepositoryStub,
    )

    inputRefs = [{
        "inputName": "inputParticles",
        "itemIndex": 0,
        "parentProtocolDbId": 20,
        "parentProtocolId": 2,
        "parentOutputName": "outputParticles",
    }]

    firstReport = worker.restoreExecutionInputs(
        persistResolvedRefs=False,
        inputRefs=inputRefs,
    )

    assert firstReport["errors"] == []
    assert firstReport["restored"] == 1

    runtimeInputSet = parentOutputSet.lastClone

    assert runtimeInputSet is not None
    assert runtimeInputSet is not parentOutputSet
    assert parentOutputSet.cloneCalls == 1
    assert parentOutputSet.cloneKwargs == [
        {
            "_postgresqlDetachedConsumer": True,
        }
    ]
    assert parentOutputSet.refreshCalls == 0
    assert parentOutputSet.getSize() == 2236

    assert runtimeInputSet.refreshCalls == 1
    assert runtimeInputSet.getSize() == 5236
    assert worker.protocol.inputParticles.get() is runtimeInputSet
    assert firstReport["items"][0]["parentProtocolModified"] is False

    secondReport = worker.restoreExecutionInputs(
        persistResolvedRefs=False,
        inputRefs=inputRefs,
    )

    assert secondReport["errors"] == []
    assert parentOutputSet.cloneCalls == 1
    assert parentOutputSet.refreshCalls == 0
    assert parentOutputSet.getSize() == 2236

    assert runtimeInputSet.refreshCalls == 2
    assert runtimeInputSet.getSize() == 5236
    assert worker.protocol.inputParticles.get() is runtimeInputSet

    assert runtimeMapper.selectCalls == [
        44,
    ]


def test_CloseClosesDetachedExecutionInputSets():
    class RuntimeInputSet:
        def __init__(self):
            self.closeCalls = 0

        def close(self):
            self.closeCalls += 1

    runtimeInputSet = RuntimeInputSet()

    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    worker._executionInputSetsByRuntimeObjectId = {
        44: runtimeInputSet,
    }

    worker.close()

    assert runtimeInputSet.closeCalls == 1
    assert worker._executionInputSetsByRuntimeObjectId == {}


def test_NonStreamingProtocolWaitsForRunningParent():
    worker = buildWorker(
        streaming=False,
        parentStatus="running",
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == [
        {
            "protocolDbId": 20,
            "protocolId": 2,
            "status": "running",
            "reason": (
                "input_parent_not_finished"
            ),
        },
    ]


def test_NonStreamingProtocolWaitsForInteractiveParent():
    worker = buildWorker(
        streaming=False,
        parentStatus="interactive",
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == [
        {
            "protocolDbId": 20,
            "protocolId": 2,
            "status": "interactive",
            "reason": (
                "input_parent_not_finished"
            ),
        },
    ]


def test_NonStreamingProtocolStartsAfterParentFinished():
    worker = buildWorker(
        streaming=False,
        parentStatus="finished",
        outputExists=True,
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "failedParents"
    ] == []

    assert readiness[
        "pendingParents"
    ] == []

    assert readiness[
        "missingInputs"
    ] == []

    assert readiness[
        "validationErrors"
    ] == []


def test_StreamingProtocolStartsWhenInputsValidate():
    worker = buildWorker(
        streaming=True,
        parentStatus="running",
        outputExists=True,
        validationErrors=[],
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == []

    assert readiness[
        "missingInputs"
    ] == []

    assert readiness[
        "validationErrors"
    ] == []


def test_StreamingInputParentPrerequisiteDoesNotWaitForTerminalStatus():
    worker = buildWorker(
        streaming=True,
        parentStatus="running",
        outputExists=True,
        prerequisites="2",
        prerequisiteStatuses={
            2: "running",
        },
        validationErrors=[],
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == []

    assert readiness[
        "failedParents"
    ] == []

    assert readiness[
        "missingInputs"
    ] == []

    assert readiness[
        "missingPrerequisites"
    ] == []

    assert readiness[
        "inputRestoreErrors"
    ] == []

    assert readiness[
        "validationErrors"
    ] == []


def test_StreamingProtocolWaitsUntilParentOutputExists():
    worker = buildWorker(
        streaming=True,
        parentStatus="running",
        outputExists=False,
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == []

    assert readiness[
        "missingInputs"
    ] == [
        {
            "inputName": "inputSet",
            "itemIndex": 0,
            "parentProtocolDbId": 20,
            "parentProtocolId": 2,
            "parentOutputName": "outputSet",
            "reason": (
                "parent_output_not_available"
            ),
        },
    ]


def test_StreamingProtocolIgnoresInputDisabledByCondition():
    validatedInputRefs = []

    worker = buildWorker(
        streaming=True,
        parentStatus="scheduled",
        outputExists=False,
        inputCondition=False,
        validationErrors=[],
    )

    def validateAvailableInputs(inputRefs=None):
        validatedInputRefs.append(list(inputRefs or []))

        return {
            "inputRestoreErrors": [],
            "validationErrors": [],
        }

    worker.validateAvailableInputs = validateAvailableInputs

    readiness = worker.getReadinessState()

    assert readiness["failedParents"] == []
    assert readiness["pendingParents"] == []
    assert readiness["missingInputs"] == []
    assert readiness["missingPrerequisites"] == []
    assert readiness["inputRestoreErrors"] == []
    assert readiness["validationErrors"] == []
    assert validatedInputRefs == [[]]


def test_StreamingProtocolWaitsWhileValidationFails():
    worker = buildWorker(
        streaming=True,
        parentStatus="running",
        outputExists=True,
        validationErrors=[
            "Input set does not contain enough items",
        ],
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == []

    assert readiness[
        "missingInputs"
    ] == []

    assert readiness[
        "validationErrors"
    ] == [
        "Input set does not contain enough items",
    ]


def test_CommaSeparatedPrerequisitesAreParsed():
    worker = buildWorker(
        streaming=True,
        parentStatus="finished",
        prerequisites="5, 8; 13",
    )

    assert (
        worker
        .getPrerequisiteProtocolIds()
        == {
            5,
            8,
            13,
        }
    )


def test_PrerequisiteIsCheckedWhenNotInputParent():
    worker = buildWorker(
        streaming=True,
        parentStatus="finished",
        outputExists=True,
        prerequisites="9",
        prerequisiteStatuses={
            9: "running",
        },
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == [
        {
            "protocolDbId": 109,
            "protocolId": 9,
            "status": "running",
            "reason": (
                "prerequisite_not_terminal"
            ),
        },
    ]


def test_FailedPrerequisiteDoesNotBlockProtocol():
    worker = buildWorker(
        streaming=True,
        parentStatus="finished",
        outputExists=True,
        prerequisites="9",
        prerequisiteStatuses={
            9: "failed",
        },
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "failedParents"
    ] == []

    assert readiness[
        "pendingParents"
    ] == []

    assert readiness[
        "missingPrerequisites"
    ] == []


def test_MissingPrerequisiteIsReported():
    worker = buildWorker(
        streaming=True,
        parentStatus="finished",
        outputExists=True,
        prerequisites="9",
        prerequisiteStatuses={},
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "missingPrerequisites"
    ] == [
        {
            "protocolId": 9,
            "reason": (
                "prerequisite_not_found"
            ),
        },
    ]


class DependencyEventListenerStub:
    def __init__(
            self,
            event=None,
    ):
        self.event = event
        self.waitCalls = []

    def wait(
            self,
            timeoutSeconds,
    ):
        self.waitCalls.append(
            timeoutSeconds
        )

        return self.event


def test_WaitForDependencyChangeUsesEventListener():
    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    listener = (
        DependencyEventListenerStub(
            event={
                "eventType": (
                    "protocol_changed"
                ),
                "projectId": 1,
                "protocolId": 2,
            }
        )
    )

    worker.dependencyEventListener = (
        listener
    )

    event = worker.waitForDependencyChange(
        90
    )

    assert event == {
        "eventType": (
            "protocol_changed"
        ),
        "projectId": 1,
        "protocolId": 2,
    }

    assert listener.waitCalls == [
        90,
    ]


def test_StreamingProtocolWaitsForScheduledParent():
    worker = buildWorker(
        streaming=True,
        parentStatus="scheduled",
        outputExists=True,
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == [
        {
            "protocolDbId": 20,
            "protocolId": 2,
            "status": "scheduled",
            "reason": (
                "streaming_input_parent_not_started"
            ),
        },
    ]

    assert readiness[
        "missingInputs"
    ] == []



class ProtocolJobStoreStub:
    def __init__(self):
        self._jobId = []
        self._lock = threading.RLock()
        self.originalStoreCalls = []

    def _store(
            self,
            *objects,
    ):
        self.originalStoreCalls.append(
            objects
        )


def test_StepAdapterPersistsQueueJobIdsInsteadOfChildObject():
    protocol = (
        ProtocolJobStoreStub()
    )

    adapter = object.__new__(
        RuntimePostgresqlStepAdapter
    )

    adapter.protocol = protocol

    persistedJobIds = []

    adapter.persistProtocolProcessIdentity = (
        lambda: persistedJobIds.append(
            list(
                protocol._jobId
            )
        )
    )

    adapter.install()

    protocol._jobId.append(
        "77"
    )

    protocol._store(
        protocol._jobId
    )

    assert persistedJobIds == [
        [
            "77",
        ],
    ]

    assert (
        protocol.originalStoreCalls
        == []
    )

    otherObject = object()

    protocol._store(
        otherObject
    )

    assert (
        protocol.originalStoreCalls
        == [
            (
                otherObject,
            ),
        ]
    )


class UpdatedRuntimeStepStub:
    def getIndex(self):
        return 4


class DirectStepPersistenceServiceStub:
    def __init__(self):
        self.calls = []

    def buildProtocolStepForPostgresql(self, step, event="snapshot"):
        self.calls.append((step, event))
        return {"index": 4, "name": "finalStep", "status": "finished", "elapsedSeconds": 10.0}

    def buildProtocolStepsForPostgresql(self, protocol):
        raise AssertionError("upsertStep must serialize the updated step directly")


class ProtocolStepMapperStub:
    def __init__(self):
        self.calls = []

    def upsertProtocolStep(self, **kwargs):
        self.calls.append(kwargs)


def test_StepAdapterPersistsExactUpdatedStepSnapshot():
    step = UpdatedRuntimeStepStub()
    mapper = ProtocolStepMapperStub()
    stepService = DirectStepPersistenceServiceStub()
    adapter = object.__new__(RuntimePostgresqlStepAdapter)
    adapter.mapper = mapper
    adapter.projectId = 1
    adapter.protocolDbId = 20
    adapter.protocolId = 30
    adapter.protocol = SimpleNamespace(_steps=[object()])
    adapter.stepService = stepService

    adapter.upsertStep(step)

    assert stepService.calls == [(step, "step-updated")]
    assert mapper.calls[0]["step"]["status"] == "finished"
    assert mapper.calls[0]["step"]["elapsedSeconds"] == 10.0


class ResumeItemStub(Object):
    pass


class ResumeSetStub(Set):
    ITEM_TYPE = ResumeItemStub

    def __init__(self):
        super().__init__()

        self.enablePostgresqlWriteCalls = 0

    def supportsPostgresqlNativeWrite(self):
        return True

    def enablePostgresqlWrite(self):
        self.enablePostgresqlWriteCalls += 1
        return self


class ForbiddenSqliteMaterializer:
    def __getattr__(self, attributeName):
        raise AssertionError("SQLite materializer must not be used. attributeName=%s" % attributeName)


class ResumeObjectMapperStub:
    def listProtocolStoredObjects(
            self,
            projectId,
            protocolDbId,
    ):
        return [
            {
                "path": "outputParticles",
                "name": "outputParticles",
                "parentObjectId": None,
                "scipionObjId": 44,
            },
        ]


class ResumeRuntimeMapperStub:
    def __init__(
            self,
            outputSet,
    ):
        self.outputSet = outputSet

        self.objectMapper = (
            ResumeObjectMapperStub()
        )

    def selectRuntimeInputObjectById(
            self,
            runtimeObjectId,
    ):
        assert runtimeObjectId == 44
        return self.outputSet


class ResumeProtocolStub:
    def __init__(self):
        self._outputs = []

        self._useOutputList = (
            SimpleNamespace(
                set=lambda value: None
            )
        )


def test_ResumeUsesNativePostgresqlWritableSet():
    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
        runMode=(
            POSTGRESQL_RUN_MODE_RESUME
        ),
    )

    outputSet = ResumeSetStub()
    outputSet.setObjId(44)

    # The test must fail if the SQLite compatibility materializer is accessed.
    outputSet._postgresqlSqliteMaterializer = ForbiddenSqliteMaterializer()

    worker.protocol = (
        ResumeProtocolStub()
    )

    worker.runtimeMapper = (
        ResumeRuntimeMapperStub(
            outputSet
        )
    )

    worker.getProtocolDbId = (
        lambda: 20
    )

    report = (
        worker.restoreResumeOutputs()
    )

    assert report["errors"] == []
    assert report["restored"] == 1

    assert (
        outputSet
        .enablePostgresqlWriteCalls
        == 1
    )

    assert (
        worker.protocol.outputParticles
        is outputSet
    )

    assert (
        report["items"][0][
            "writablePostgresql"
        ]
        is True
    )

    assert (
        outputSet.getStreamState()
        == Set.STREAM_OPEN
    )


def test_MarkFailedRollsBackBeforeStoringProtocol():
    events = []

    class FailedProtocolStub:
        def setFailed(
                self,
                message,
        ):
            events.append(
                (
                    "failed",
                    message,
                )
            )

    database = SimpleNamespace(
        rollback=lambda: events.append(
            "rollback"
        )
    )

    worker = (
        RuntimePostgresqlProtocolWorker(
            projectId=344,
            protocolId=24,
        )
    )

    worker.mapper = SimpleNamespace(
        db=database
    )

    worker.protocol = (
        FailedProtocolStub()
    )

    worker.storeProtocol = (
        lambda: events.append(
            "store"
        )
    )

    worker.markFailed(
        RuntimeError(
            "database failure"
        )
    )

    assert events == [
        "rollback",
        (
            "failed",
            "database failure",
        ),
        "store",
    ]


def test_RunClosesWorkerBeforeCleaningCompatibilitySqliteSnapshots():
    events = []

    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    worker.load = lambda: events.append("load")
    worker.waitUntilReady = lambda: events.append("wait")
    worker.execute = lambda: events.append("execute") or 0
    worker.close = lambda: events.append("close")
    worker.cleanupCompatibilitySqliteSnapshots = lambda: events.append("cleanup")

    assert worker.run(
        execute=True
    ) == 0

    assert events == [
        "load",
        "wait",
        "execute",
        "close",
        "cleanup",
    ]


def test_RunCleansCompatibilitySqliteSnapshotsAfterFailure():
    events = []

    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    worker.load = lambda: events.append("load")
    worker.waitUntilReady = lambda: events.append("wait")

    def failExecution():
        events.append("execute")
        raise RuntimeError("protocol failure")

    worker.execute = failExecution

    worker.markFailed = lambda error: events.append(
        (
            "failed",
            str(error),
        )
    )

    worker.close = lambda: events.append("close")
    worker.cleanupCompatibilitySqliteSnapshots = lambda: events.append("cleanup")

    assert worker.run(
        execute=True
    ) == 1

    assert events == [
        "load",
        "wait",
        "execute",
        (
            "failed",
            "protocol failure",
        ),
        "close",
        "cleanup",
    ]


def test_CompatibilitySqliteCleanupFailureIsBestEffort(
        monkeypatch,
):
    def failCleanup(cls):
        raise RuntimeError(
            "cleanup failure"
        )

    monkeypatch.setattr(
        postgresqlProtocolWorkerModule.PostgresqlRuntimeSetSqliteMaterializer,
        "cleanupCurrentWorkerDirectory",
        classmethod(failCleanup),
    )

    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    report = worker.cleanupCompatibilitySqliteSnapshots()

    assert report["removed"] is False
    assert report["deletedCount"] == 0
    assert report["registryEntriesRemoved"] == 0
    assert report["error"] == "cleanup failure"


def test_EffectiveQueueLaunchParamsUsesRuntimeApiSettings(monkeypatch):
    class SettingsServiceStub:
        def getRuntimeInstanceSettings(self, mapper, currentUser):
            return {
                "defaultQueueName": "gpu",
            }

        def getRuntimeHostSettings(self, mapper, currentUser):
            return {
                "queues": [
                    {
                        "name": "cpu",
                        "params": [
                            {
                                "variableName": "JOB_TIME",
                                "value": "24",
                            },
                        ],
                    },
                    {
                        "name": "gpu",
                        "params": [
                            {
                                "variableName": "JOB_TIME",
                                "value": "72",
                            },
                            {
                                "variableName": "JOB_MEMORY",
                                "value": "64000",
                            },
                            {
                                "variableName": "GPU_COUNT",
                                "value": "1",
                            },
                        ],
                    },
                ],
            }

    monkeypatch.setattr(
        postgresqlProtocolWorkerModule,
        "SettingsService",
        SettingsServiceStub,
    )

    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    worker.mapper = object()

    queueName, queueParams = worker._getEffectiveQueueLaunchParams()

    assert queueName == "gpu"
    assert queueParams == {
        "JOB_TIME": "72",
        "JOB_MEMORY": "64000",
        "GPU_COUNT": "1",
    }


def test_EffectiveQueueLaunchParamsFallsBackToFirstConfiguredQueue(monkeypatch):
    class SettingsServiceStub:
        def getRuntimeInstanceSettings(self, mapper, currentUser):
            return {
                "defaultQueueName": "missing",
            }

        def getRuntimeHostSettings(self, mapper, currentUser):
            return {
                "queues": [
                    {
                        "name": "gpu",
                        "params": [
                            {
                                "variableName": "JOB_TIME",
                                "value": "72",
                            },
                        ],
                    },
                ],
            }

    monkeypatch.setattr(
        postgresqlProtocolWorkerModule,
        "SettingsService",
        SettingsServiceStub,
    )

    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    worker.mapper = object()

    queueName, queueParams = worker._getEffectiveQueueLaunchParams()

    assert queueName == "gpu"
    assert queueParams == {
        "JOB_TIME": "72",
    }


def test_EnsureQueueLaunchParamsUsesEffectiveSettingsWhenOverrideIsMissing():
    class QueueProtocolStub:
        def __init__(self):
            self.queueParams = None

        def hasQueueParams(self):
            return self.queueParams is not None

        def getQueueParams(self):
            return self.queueParams

        def setQueueParams(self, queueParams):
            self.queueParams = queueParams

    protocol = QueueProtocolStub()

    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    worker.protocol = protocol

    worker._getEffectiveQueueLaunchParams = lambda: (
        "gpu",
        {
            "JOB_TIME": "72",
            "JOB_MEMORY": "64000",
        },
    )

    queueName, queueParams = (
        worker._ensureQueueLaunchParams()
    )

    assert queueName == "gpu"

    assert queueParams == {
        "JOB_TIME": "72",
        "JOB_MEMORY": "64000",
    }

    assert protocol.queueParams == [
        "gpu",
        {
            "JOB_TIME": "72",
            "JOB_MEMORY": "64000",
        },
    ]


def test_BuildStepsExecutorUsesEffectiveQueueParams(
        monkeypatch,
):
    calls = {}

    class QueueStepsProtocolStub:
        def __init__(self):
            self.queueParams = None
            self.numberOfThreads = SimpleNamespace(
                get=lambda: 1
            )

        def getHostConfig(self):
            return "host"

        def getGpuList(self):
            return []

        def useQueue(self):
            return True

        def useQueueForSteps(self):
            return True

        def modeParallel(self):
            return False

        def hasQueueParams(self):
            return self.queueParams is not None

        def getQueueParams(self):
            return self.queueParams

        def setQueueParams(self, queueParams):
            self.queueParams = queueParams

        def getSubmitDict(self):
            queueName, queueParams = self.queueParams

            submitDict = {
                "JOB_QUEUE": queueName,
            }

            submitDict.update(
                queueParams
            )

            return submitDict

    def buildQueueStepExecutor(
            hostConfig,
            submitDict,
            numberOfThreads,
            gpuList=None,
    ):
        calls["hostConfig"] = hostConfig
        calls["submitDict"] = dict(
            submitDict
        )
        calls["numberOfThreads"] = (
            numberOfThreads
        )
        calls["gpuList"] = gpuList

        return "queue-executor"

    monkeypatch.setattr(
        postgresqlProtocolWorkerModule,
        "QueueStepExecutor",
        buildQueueStepExecutor,
    )

    monkeypatch.setattr(
        postgresqlProtocolWorkerModule,
        "anonimizeGPUs",
        lambda gpuList: gpuList,
    )

    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    worker.protocol = (
        QueueStepsProtocolStub()
    )

    worker._getEffectiveQueueLaunchParams = lambda: (
        "gpu",
        {
            "JOB_TIME": "72",
            "JOB_MEMORY": "64000",
        },
    )

    executor = worker.buildStepsExecutor()

    assert executor == "queue-executor"

    assert calls["submitDict"] == {
        "JOB_QUEUE": "gpu",
        "JOB_TIME": "72",
        "JOB_MEMORY": "64000",
    }


def test_SubmitToQueueForwardsEffectiveParamsToExecuteWorker(
        monkeypatch,
):
    calls = {}

    class QueueProtocolStub:
        def __init__(self):
            self.queueParams = None
            self.jobId = None
            self.pid = None
            self.status = None

        def hasQueueParams(self):
            return self.queueParams is not None

        def getQueueParams(self):
            return self.queueParams

        def setQueueParams(self, queueParams):
            self.queueParams = queueParams

        def getHostConfig(self):
            return "host"

        def getSubmitDict(self):
            queueName, queueParams = self.queueParams

            submitDict = {
                "JOB_QUEUE": queueName,
            }

            submitDict.update(
                queueParams
            )

            return submitDict

        def setJobId(self, jobId):
            self.jobId = jobId

        def setPid(self, pid):
            self.pid = pid

        def setStatus(self, status):
            self.status = status

    def buildWorkerCommand(**kwargs):
        calls["commandArgs"] = kwargs
        return ["worker-command"]

    def submit(
            hostConfig,
            submitDict,
            cwd,
            env,
    ):
        calls["hostConfig"] = hostConfig
        calls["submitDict"] = dict(
            submitDict
        )
        calls["cwd"] = cwd

        return "12345", None

    monkeypatch.setattr(
        postgresqlProtocolWorkerModule,
        "buildPostgresqlWorkerCommand",
        buildWorkerCommand,
    )

    monkeypatch.setattr(
        postgresqlProtocolWorkerModule,
        "_submit",
        submit,
    )

    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    worker.protocol = QueueProtocolStub()

    worker.project = SimpleNamespace(
        path="/tmp/project"
    )

    worker._getEffectiveQueueLaunchParams = lambda: (
        "gpu",
        {
            "JOB_TIME": "72",
            "JOB_MEMORY": "64000",
        },
    )

    worker.storeProtocol = lambda: None
    worker.markProtocolExecutionLaunched = lambda: None

    assert worker.submitToQueue() == 0

    assert calls["commandArgs"] == {
        "projectId": 1,
        "protocolId": 30,
        "execute": True,
        "runMode": "restart",
        "queueName": "gpu",
        "queueParams": {
            "JOB_TIME": "72",
            "JOB_MEMORY": "64000",
        },
    }

    assert calls["submitDict"]["JOB_QUEUE"] == "gpu"
    assert calls["submitDict"]["JOB_TIME"] == "72"
    assert calls["submitDict"]["JOB_MEMORY"] == "64000"



