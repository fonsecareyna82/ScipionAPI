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
import inspect
from types import SimpleNamespace

import pytest

from pyworkflow.protocol import (
    MODE_RESUME,
    STATUS_SCHEDULED, STATUS_SAVED,
)

import app.backend.runtime.protocol_postgresql_continue_launcher_service as continueModule
import app.backend.runtime.protocol_postgresql_restart_launcher_service as restartModule

from app.backend.runtime.protocol_postgresql_continue_launcher_service import (
    CONTINUE_ACTION_RESTART,
    CONTINUE_ACTION_RESUME,
    CONTINUE_ACTION_SKIP,
    RuntimePostgresqlContinueLauncherService,
)
from app.backend.runtime.protocol_postgresql_restart_launcher_service import (
    RuntimePostgresqlRestartLauncherService,
)

class ScalarStub:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class ProtocolStub:
    def __init__(
            self,
            protocolId,
            *,
            status="finished",
            streaming=False,
            interactive=False,
    ):
        self.protocolId = int(
            protocolId
        )

        self.status = status
        self.streaming = streaming
        self.interactive = interactive

        self.runMode = ScalarStub()
        self._jobId = []
        self._steps = ["old-step"]
        self._stepsDone = ScalarStub(4)
        self._numberOfSteps = ScalarStub(4)
        self._cpuTime = ScalarStub(90)

        self.pid = 999
        self.makeWorkingDirCalls = 0
        self.cleanWorkingDirCalls = 0

    def getObjId(self):
        return self.protocolId

    def getStatus(self):
        return self.status

    def iterOutputAttributes(self):
        return []

    def getDefinition(self):
        return SimpleNamespace(iterParams=lambda: [])

    def setStatus(self, status):
        self.status = status

    def worksInStreaming(self):
        return self.streaming

    def isSaved(self):
        return self.status == "saved"

    def isScheduled(self):
        return self.status == "scheduled"

    def isInteractive(self):
        return self.interactive

    def setPid(self, pid):
        self.pid = pid

    def makeWorkingDir(self):
        self.makeWorkingDirCalls += 1

    def cleanWorkingDir(self):
        self.cleanWorkingDirCalls += 1


class IdentityResolverStub:
    def __init__(self, **kwargs):
        pass

    def resolvePostgresqlProtocolDbIdFromScipionProtocolId(
            self,
            protocolId,
    ):
        return 100 + int(
            protocolId
        )


class GraphRepositoryStub:
    def __init__(self):
        self.refsByProtocolDbId = {}
        self.relationSyncCalls = []
        self.relationSyncError = None

    def loadInputRefsForProtocol(
            self,
            *,
            protocolDbId,
            **kwargs,
    ):
        return list(
            self.refsByProtocolDbId.get(
                int(protocolDbId),
                [],
            )
        )

    def getPostgresqlRuntimeOutputInfo(
            self,
            **kwargs,
    ):
        return {
            "exists": True,
            "runtimeObjectId": 500,
        }

    def setProtocolRelationsSynchronized(
            self,
            **kwargs,
    ):
        self.relationSyncCalls.append(
            kwargs
        )

        if self.relationSyncError is not None:
            raise self.relationSyncError

        return True


class IdentityCollisionMapperStub:
    def __init__(self):
        self.scipionLookups = []
        self.dbLookups = []

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        self.scipionLookups.append({
            "projectId": projectId,
            "protocolId": protocolId,
        })
        return None

    def getProjectProtocolByDbId(self, projectId, protocolDbId):
        self.dbLookups.append({
            "projectId": projectId,
            "protocolDbId": protocolDbId,
        })

        return {
            "id": 31,
            "protocolId": "99",
        }


class MapperStub:
    def __init__(self):
        self.prepareContinueCalls = []
        self.prepareContinueError = None

    def prepareProtocolStepsForContinue(
            self,
            **kwargs,
    ):
        self.prepareContinueCalls.append(
            kwargs
        )

        if self.prepareContinueError is not None:
            raise self.prepareContinueError

        return 3


class RuntimeMapperStub:
    def __init__(self):
        self.storeCalls = []
        self.commitCalls = 0

    def store(self, protocol):
        self.storeCalls.append(
            protocol
        )

    def commit(self):
        self.commitCalls += 1


def installPlanStubs(
        monkeypatch,
):
    graphRepository = (
        GraphRepositoryStub()
    )

    monkeypatch.setattr(
        continueModule,
        "ProtocolIdentityResolver",
        IdentityResolverStub,
    )

    monkeypatch.setattr(
        continueModule,
        "ProtocolGraphRepository",
        lambda: graphRepository,
    )

    return graphRepository


def installRestartValidationStubs(
        monkeypatch,
):
    graphRepository = GraphRepositoryStub()

    monkeypatch.setattr(
        restartModule,
        "ProtocolIdentityResolver",
        IdentityResolverStub,
    )

    monkeypatch.setattr(
        restartModule,
        "ProtocolGraphRepository",
        lambda: graphRepository,
    )

    return graphRepository


def test_ContinuePlanClassifiesMixedWorkflow(
        monkeypatch,
):
    installPlanStubs(
        monkeypatch
    )

    streamingFinished = ProtocolStub(
        1,
        status="finished",
        streaming=True,
    )

    nonStreamingFinished = ProtocolStub(
        2,
        status="finished",
        streaming=False,
    )

    streamingSaved = ProtocolStub(
        3,
        status="saved",
        streaming=True,
    )

    alreadyScheduled = ProtocolStub(
        4,
        status="scheduled",
        streaming=True,
    )

    interactive = ProtocolStub(
        5,
        status="interactive",
        streaming=True,
        interactive=True,
    )

    workflow = {
        "1": (
            streamingFinished,
            0,
        ),
        "2": (
            nonStreamingFinished,
            1,
        ),
        "3": (
            streamingSaved,
            1,
        ),
        "4": (
            alreadyScheduled,
            2,
        ),
        "5": (
            interactive,
            2,
        ),
    }

    plan = (
        RuntimePostgresqlContinueLauncherService()
        .buildContinuePlan(
            mapper=SimpleNamespace(),
            projectId=7,
            workflowProtocolMap=workflow,
            currentProject=SimpleNamespace(getPostgresqlRuntimeMapper=lambda: object()),
        )
    )

    assert plan["errors"] == []

    actions = {
        str(entry["protocolId"]): (
            entry["action"]
        )
        for entry in plan["entries"]
    }

    assert actions == {
        "1": CONTINUE_ACTION_RESUME,
        "2": CONTINUE_ACTION_RESTART,
        "3": CONTINUE_ACTION_RESTART,
        "4": CONTINUE_ACTION_SKIP,
        "5": CONTINUE_ACTION_SKIP,
    }

    assert plan["summary"][
        "resumeProtocolIds"
    ] == [
        "1",
    ]

    assert plan["summary"][
        "restartProtocolIds"
    ] == [
        "2",
        "3",
    ]


def test_ContinuePlanRejectsActiveProtocol(
        monkeypatch,
):
    installPlanStubs(
        monkeypatch
    )

    protocol = ProtocolStub(
        1,
        status="running",
        streaming=True,
    )

    plan = (
        RuntimePostgresqlContinueLauncherService()
        .buildContinuePlan(
            mapper=SimpleNamespace(),
            projectId=7,
            workflowProtocolMap={
                "1": (
                    protocol,
                    0,
                ),
            },
            currentProject=SimpleNamespace(getPostgresqlRuntimeMapper=lambda: object()),
        )
    )

    assert len(
        plan["errors"]
    ) == 1

    assert plan["errors"][0][
        "protocolId"
    ] == "1"

    assert plan["errors"][0][
        "status"
    ] == "running"


def test_ContinuePlanUsesStrictScipionProtocolIdentity():
    mapper = IdentityCollisionMapperStub()

    protocol = ProtocolStub(
        31,
        status="finished",
        streaming=False,
    )

    plan = RuntimePostgresqlContinueLauncherService().buildContinuePlan(
        mapper=mapper,
        projectId=7,
        workflowProtocolMap={
            "31": (
                protocol,
                0,
            ),
        },
        currentProject=SimpleNamespace(getPostgresqlRuntimeMapper=lambda: object()),
    )

    assert len(plan["entries"]) == 1

    entry = plan["entries"][0]

    assert entry["protocolId"] == 31
    assert entry["protocolDbId"] is None
    assert entry["action"] == "error"
    assert entry["reason"] == "protocol_not_found"

    assert plan["errors"] == [
        {
            "protocolId": "31",
            "error": "Protocol was not found in PostgreSQL",
        },
    ]

    assert mapper.scipionLookups == [
        {
            "projectId": 7,
            "protocolId": "31",
        },
    ]
    assert mapper.dbLookups == []


def test_ContinuePlanRejectsMissingRuntimeMapper():
    protocol = ProtocolStub(
        1,
        status="finished",
        streaming=False,
    )

    plan = RuntimePostgresqlContinueLauncherService().buildContinuePlan(
        mapper=SimpleNamespace(),
        projectId=7,
        workflowProtocolMap={
            "1": (
                protocol,
                0,
            ),
        },
        currentProject=SimpleNamespace(getPostgresqlRuntimeMapper=lambda: None),
    )

    assert plan == {
        "entries": [],
        "errors": [{
            "error": "PostgreSQL runtime mapper is not available",
        }],
        "summary": {
            "protocolsCount": 0,
            "actionableCount": 0,
            "restartProtocolIds": [],
            "resumeProtocolIds": [],
            "skipped": [],
            "parentProtocolsModified": False,
        },
    }


def test_ContinuePlanRejectsRestartOutputEnumerationFailure(
        monkeypatch,
):
    class FailingOutputProtocol(ProtocolStub):
        def iterOutputAttributes(self):
            raise RuntimeError("output enumeration failed")

    installPlanStubs(
        monkeypatch
    )

    protocol = FailingOutputProtocol(
        10,
        status="finished",
        streaming=False,
    )

    plan = RuntimePostgresqlContinueLauncherService().buildContinuePlan(
        mapper=SimpleNamespace(),
        projectId=7,
        workflowProtocolMap={
            "10": (
                protocol,
                0,
            ),
        },
        currentProject=SimpleNamespace(getPostgresqlRuntimeMapper=lambda: object()),
    )

    assert plan["entries"][0]["action"] == CONTINUE_ACTION_RESTART

    assert plan["errors"] == [{
        "protocolId": "10",
        "error": "Could not enumerate protocol runtime outputs: output enumeration failed",
    }]

    assert "runtimeStructure" not in plan["entries"][0]


def test_ContinuePlanRejectsRestartInputEnumerationFailure(
        monkeypatch,
):
    class FailingDefinition:
        def iterParams(self):
            raise RuntimeError("input enumeration failed")

    class FailingInputProtocol(ProtocolStub):
        def getDefinition(self):
            return FailingDefinition()

    installPlanStubs(
        monkeypatch
    )

    protocol = FailingInputProtocol(
        10,
        status="finished",
        streaming=False,
    )

    plan = RuntimePostgresqlContinueLauncherService().buildContinuePlan(
        mapper=SimpleNamespace(),
        projectId=7,
        workflowProtocolMap={
            "10": (
                protocol,
                0,
            ),
        },
        currentProject=SimpleNamespace(getPostgresqlRuntimeMapper=lambda: object()),
    )

    assert plan["entries"][0]["action"] == CONTINUE_ACTION_RESTART

    assert plan["errors"] == [{
        "protocolId": "10",
        "error": "Could not enumerate protocol runtime input parameters: input enumeration failed",
    }]

    assert "runtimeStructure" not in plan["entries"][0]


def test_ContinuePlanDoesNotRequireRestartStructureForResume(
        monkeypatch,
):
    class ResumeProtocol(ProtocolStub):
        def iterOutputAttributes(self):
            raise AssertionError("resume outputs must not be enumerated")

        def getDefinition(self):
            raise AssertionError("resume definition must not be enumerated")

    installPlanStubs(
        monkeypatch
    )

    protocol = ResumeProtocol(
        10,
        status="finished",
        streaming=True,
    )

    plan = RuntimePostgresqlContinueLauncherService().buildContinuePlan(
        mapper=SimpleNamespace(),
        projectId=7,
        workflowProtocolMap={
            "10": (
                protocol,
                0,
            ),
        },
        currentProject=SimpleNamespace(getPostgresqlRuntimeMapper=lambda: object()),
    )

    assert plan["errors"] == []
    assert plan["entries"][0]["action"] == CONTINUE_ACTION_RESUME
    assert "runtimeStructure" not in plan["entries"][0]


def test_RestartValidationUsesStrictScipionProtocolIdentity():
    mapper = IdentityCollisionMapperStub()

    protocol = ProtocolStub(
        31,
        status="finished",
    )

    result = RuntimePostgresqlRestartLauncherService().validateRestartSubworkflow(
        mapper=mapper,
        projectId=7,
        workflowProtocolMap={
            "31": (
                protocol,
                0,
            ),
        },
        currentProject=SimpleNamespace(
            getPostgresqlRuntimeMapper=lambda: object()
        ),
    )

    assert result["protocolDbIds"] == []
    assert result["errors"] == [
        {
            "protocolId": "31",
            "error": "Protocol was not found in PostgreSQL",
        },
    ]

    assert mapper.scipionLookups == [
        {
            "projectId": 7,
            "protocolId": "31",
        },
        {
            "projectId": 7,
            "protocolId": "31",
        },
    ]
    assert mapper.dbLookups == []


def test_RestartValidationRejectsMissingRuntimeMapper():
    protocol = ProtocolStub(
        10,
        status="finished",
    )

    result = RuntimePostgresqlRestartLauncherService().validateRestartSubworkflow(
        mapper=SimpleNamespace(),
        projectId=7,
        workflowProtocolMap={
            "10": (
                protocol,
                0,
            ),
        },
        currentProject=SimpleNamespace(
            getPostgresqlRuntimeMapper=lambda: None
        ),
    )

    assert result == {
        "protocolsCount": 0,
        "protocolDbIds": [],
        "errors": [{
            "error": "PostgreSQL runtime mapper is not available",
        }],
        "parentProtocolsModified": False,
    }


def test_RestartValidationRejectsOutputEnumerationFailure(
        monkeypatch,
):
    class FailingOutputProtocol(ProtocolStub):
        def iterOutputAttributes(self):
            raise RuntimeError("output enumeration failed")

    installRestartValidationStubs(
        monkeypatch
    )

    protocol = FailingOutputProtocol(
        10,
        status="finished",
    )

    result = RuntimePostgresqlRestartLauncherService().validateRestartSubworkflow(
        mapper=SimpleNamespace(),
        projectId=7,
        workflowProtocolMap={
            "10": (
                protocol,
                0,
            ),
        },
        currentProject=SimpleNamespace(
            getPostgresqlRuntimeMapper=lambda: object()
        ),
    )

    assert result["errors"] == [{
        "protocolId": "10",
        "error": "Could not enumerate protocol runtime outputs: output enumeration failed",
    }]

    assert result["runtimeStructures"] == {}


def test_RestartValidationRejectsInputEnumerationFailure(
        monkeypatch,
):
    class FailingDefinition:
        def iterParams(self):
            raise RuntimeError("input enumeration failed")

    class FailingInputProtocol(ProtocolStub):
        def getDefinition(self):
            return FailingDefinition()

    installRestartValidationStubs(
        monkeypatch
    )

    protocol = FailingInputProtocol(
        10,
        status="finished",
    )

    result = RuntimePostgresqlRestartLauncherService().validateRestartSubworkflow(
        mapper=SimpleNamespace(),
        projectId=7,
        workflowProtocolMap={
            "10": (
                protocol,
                0,
            ),
        },
        currentProject=SimpleNamespace(
            getPostgresqlRuntimeMapper=lambda: object()
        ),
    )

    assert result["errors"] == [{
        "protocolId": "10",
        "error": "Could not enumerate protocol runtime input parameters: input enumeration failed",
    }]

    assert result["runtimeStructures"] == {}


def test_RestartPreparationUsesStrictScipionProtocolIdentity():
    mapper = IdentityCollisionMapperStub()

    protocol = ProtocolStub(
        31,
        status="finished",
    )

    with pytest.raises(
            RuntimeError,
            match="Protocol 31 was not found in PostgreSQL",
    ):
        RuntimePostgresqlRestartLauncherService()._prepareProtocol(
            mapper=mapper,
            projectId=7,
            protocol=protocol,
            level=0,
            runtimeMapper=object(),
        )

    assert mapper.scipionLookups == [
        {
            "projectId": 7,
            "protocolId": "31",
        },
    ]
    assert mapper.dbLookups == []


def test_RestartLaunchDoesNotPrecleanLaterProtocolAfterPreparationFailure(
        monkeypatch,
):
    service = RuntimePostgresqlRestartLauncherService()

    firstProtocol = ProtocolStub(10)
    failingProtocol = ProtocolStub(11)
    laterProtocol = ProtocolStub(12)

    cleanupCalls = []
    refCleanupCalls = []

    def cleanupCallback(**kwargs):
        cleanupCalls.append(list(kwargs["protocols"]))

        return {
            "protocolsCount": len(kwargs["protocols"]),
            "setsDeleted": 0,
            "objectsDeleted": 0,
            "filesDeleted": 0,
            "fileErrors": [],
            "items": [],
        }

    def refCleanupCallback(**kwargs):
        refCleanupCalls.append(list(kwargs["protocols"]))

        return {
            "updated": 0,
            "parentProtocolDbIds": [],
        }

    def prepareProtocol(**kwargs):
        protocol = kwargs["protocol"]
        protocolId = protocol.getObjId()

        if protocolId == 11:
            raise RuntimeError("restart preparation failed")

        return {
            "protocolId": str(protocolId),
            "protocolDbId": 100 + protocolId,
            "level": int(kwargs["level"]),
            "interactive": False,
        }

    monkeypatch.setattr(
        service,
        "_prepareProtocol",
        prepareProtocol,
    )

    validationInfo = {
        "errors": [],
        "runtimeStructures": {
            "10": {
                "outputNames": [],
                "pointerParams": [],
            },
            "11": {
                "outputNames": [],
                "pointerParams": [],
            },
            "12": {
                "outputNames": [],
                "pointerParams": [],
            },
        },
    }

    with pytest.raises(
            RuntimeError,
            match="restart preparation failed",
    ):
        service.launchRestartSubworkflow(
            mapper=SimpleNamespace(),
            projectId=7,
            workflowProtocolMap={
                "10": (firstProtocol, 0),
                "11": (failingProtocol, 1),
                "12": (laterProtocol, 2),
            },
            currentProject=SimpleNamespace(
                getPostgresqlRuntimeMapper=lambda: object()
            ),
            validationInfo=validationInfo,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback=cleanupCallback,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=refCleanupCallback,
        )

    assert cleanupCalls == [
        [firstProtocol],
        [failingProtocol],
    ]

    assert refCleanupCalls == [
        [firstProtocol],
        [failingProtocol],
    ]


def test_ResumePreparationPreservesOutputsAndCpuTime(
        monkeypatch,
):
    graphRepository = installPlanStubs(
        monkeypatch
    )

    protocol = ProtocolStub(
        1,
        status="failed",
        streaming=True,
    )

    mapper = MapperStub()

    runtimeMapper = (
        RuntimeMapperStub()
    )

    entry = {
        "protocol": protocol,
        "protocolId": 1,
        "protocolDbId": 101,
        "level": 0,
        "action": (
            CONTINUE_ACTION_RESUME
        ),
    }

    service = (
        RuntimePostgresqlContinueLauncherService()
    )

    result = (
        service._prepareResumeProtocol(
            mapper=mapper,
            projectId=7,
            entry=entry,
            runtimeMapper=runtimeMapper,
        )
    )

    assert protocol.runMode.get() == (
        MODE_RESUME
    )

    assert protocol.status == (
        STATUS_SCHEDULED
    )

    assert protocol.pid == 0
    assert protocol._jobId == []
    assert protocol._steps == []

    assert protocol._stepsDone.get() == 0
    assert protocol._numberOfSteps.get() == 0

    # Resume must preserve accumulated CPU time.
    assert protocol._cpuTime.get() == 90

    assert protocol.makeWorkingDirCalls == 1
    assert protocol.cleanWorkingDirCalls == 0

    assert result["outputsPreserved"] is True
    assert result[
        "workingDirectoryPreserved"
    ] is True

    assert result["stepsPrepared"] == 3

    assert runtimeMapper.storeCalls == [
        protocol,
    ]

    assert runtimeMapper.commitCalls == 1

    assert mapper.prepareContinueCalls == [
        {
            "projectId": 7,
            "protocolId": 1,
            "statusValue": STATUS_SAVED,
            "event": "continue_resume",
        },
    ]

    assert graphRepository.relationSyncCalls == [
        {
            "mapper": mapper,
            "projectId": 7,
            "protocolId": 1,
            "synchronized": False,
        },
    ]


def test_ResumePreparationDoesNotScheduleProtocolWhenRelationInvalidationFails(
        monkeypatch,
):
    graphRepository = installPlanStubs(
        monkeypatch
    )

    graphRepository.relationSyncError = RuntimeError(
        "relation invalidation failed"
    )

    protocol = ProtocolStub(
        1,
        status="failed",
        streaming=True,
    )

    protocol._jobId = [77]

    mapper = MapperStub()
    runtimeMapper = RuntimeMapperStub()

    entry = {
        "protocol": protocol,
        "protocolId": 1,
        "protocolDbId": 101,
        "level": 0,
        "action": CONTINUE_ACTION_RESUME,
    }

    service = RuntimePostgresqlContinueLauncherService()

    with pytest.raises(
            RuntimeError,
            match="relation invalidation failed",
    ):
        service._prepareResumeProtocol(
            mapper=mapper,
            projectId=7,
            entry=entry,
            runtimeMapper=runtimeMapper,
        )

    assert protocol.runMode.get() is None
    assert protocol.status == "failed"
    assert protocol.pid == 999
    assert protocol._jobId == [77]
    assert protocol._steps == ["old-step"]
    assert protocol._stepsDone.get() == 4
    assert protocol._numberOfSteps.get() == 4
    assert protocol._cpuTime.get() == 90
    assert protocol.makeWorkingDirCalls == 0
    assert protocol.cleanWorkingDirCalls == 0

    assert mapper.prepareContinueCalls == []
    assert runtimeMapper.storeCalls == []
    assert runtimeMapper.commitCalls == 0

    assert graphRepository.relationSyncCalls == [{
        "mapper": mapper,
        "projectId": 7,
        "protocolId": 1,
        "synchronized": False,
    }]


def test_ResumePreparationDoesNotScheduleProtocolWhenStepPreparationFails(
        monkeypatch,
):
    graphRepository = installPlanStubs(
        monkeypatch
    )

    protocol = ProtocolStub(
        1,
        status="failed",
        streaming=True,
    )

    protocol._jobId = [77]

    mapper = MapperStub()
    mapper.prepareContinueError = RuntimeError(
        "step preparation failed"
    )

    runtimeMapper = RuntimeMapperStub()

    entry = {
        "protocol": protocol,
        "protocolId": 1,
        "protocolDbId": 101,
        "level": 0,
        "action": CONTINUE_ACTION_RESUME,
    }

    service = RuntimePostgresqlContinueLauncherService()

    with pytest.raises(
            RuntimeError,
            match="step preparation failed",
    ):
        service._prepareResumeProtocol(
            mapper=mapper,
            projectId=7,
            entry=entry,
            runtimeMapper=runtimeMapper,
        )

    assert protocol.runMode.get() is None
    assert protocol.status == "failed"
    assert protocol.pid == 999
    assert protocol._jobId == [77]
    assert protocol._steps == ["old-step"]
    assert protocol._stepsDone.get() == 4
    assert protocol._numberOfSteps.get() == 4
    assert protocol._cpuTime.get() == 90
    assert protocol.makeWorkingDirCalls == 0
    assert protocol.cleanWorkingDirCalls == 0

    assert runtimeMapper.storeCalls == []
    assert runtimeMapper.commitCalls == 0

    assert graphRepository.relationSyncCalls == [{
        "mapper": mapper,
        "projectId": 7,
        "protocolId": 1,
        "synchronized": False,
    }]

    assert mapper.prepareContinueCalls == [{
        "projectId": 7,
        "protocolId": 1,
        "statusValue": STATUS_SAVED,
        "event": "continue_resume",
    }]


def test_ContinueLaunchDoesNotPrecleanLaterRestartAfterPreparationFailure(
        monkeypatch,
):
    service = RuntimePostgresqlContinueLauncherService()

    firstRestart = ProtocolStub(
        10,
        status="finished",
        streaming=False,
    )

    failingResume = ProtocolStub(
        11,
        status="finished",
        streaming=True,
    )

    laterRestart = ProtocolStub(
        12,
        status="finished",
        streaming=False,
    )

    plan = {
        "errors": [],
        "entries": [
            {
                "protocol": firstRestart,
                "protocolId": 10,
                "protocolDbId": 110,
                "level": 0,
                "action": CONTINUE_ACTION_RESTART,
                "reason": "native_continue_requires_restart",
                "runtimeStructure": {
                    "outputNames": [],
                    "pointerParams": [],
                },
            },
            {
                "protocol": failingResume,
                "protocolId": 11,
                "protocolDbId": 111,
                "level": 1,
                "action": CONTINUE_ACTION_RESUME,
                "reason": "streaming_execution_exists",
            },
            {
                "protocol": laterRestart,
                "protocolId": 12,
                "protocolDbId": 112,
                "level": 2,
                "action": CONTINUE_ACTION_RESTART,
                "reason": "native_continue_requires_restart",
                "runtimeStructure": {
                    "outputNames": [],
                    "pointerParams": [],
                },
            },
        ],
    }

    cleanupCalls = []
    refCleanupCalls = []

    def cleanupCallback(**kwargs):
        cleanupCalls.append(list(kwargs["protocols"]))

        return {
            "protocolsCount": len(kwargs["protocols"]),
            "setsDeleted": 0,
            "objectsDeleted": 0,
            "filesDeleted": 0,
            "filesSkipped": [],
            "fileErrors": [],
            "items": [],
        }

    def refCleanupCallback(**kwargs):
        refCleanupCalls.append(list(kwargs["protocols"]))

        return {
            "updated": 0,
            "parentProtocolDbIds": [],
        }

    monkeypatch.setattr(
        service,
        "_prepareRestartProtocol",
        lambda **kwargs: {
            "protocolId": str(kwargs["entry"]["protocolId"]),
            "protocolDbId": kwargs["entry"]["protocolDbId"],
            "level": kwargs["entry"]["level"],
            "action": CONTINUE_ACTION_RESTART,
            "interactive": False,
        },
    )

    def failResume(**kwargs):
        raise RuntimeError("resume preparation failed")

    monkeypatch.setattr(
        service,
        "_prepareResumeProtocol",
        failResume,
    )

    with pytest.raises(
            RuntimeError,
            match="resume preparation failed",
    ):
        service.launchContinueSubworkflow(
            mapper=SimpleNamespace(),
            projectId=7,
            currentProject=SimpleNamespace(
                getPostgresqlRuntimeMapper=lambda: object()
            ),
            plan=plan,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback=cleanupCallback,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=refCleanupCallback,
        )

    assert cleanupCalls == [
        [firstRestart],
    ]

    assert refCleanupCalls == [
        [firstRestart],
    ]


def test_PostgresqlLaunchersDoNotExecuteDirectQueries():
    for launcherClass in (
            RuntimePostgresqlRestartLauncherService,
            RuntimePostgresqlContinueLauncherService,
    ):
        source = inspect.getsource(
            launcherClass
        )

        assert ".db.fetchOne(" not in source
        assert ".db.fetchAll(" not in source
        assert ".db.execute(" not in source


def test_PostgresqlLaunchersDoNotExposeLegacyStorageProvenance():
    launcherMethods = (
        (
            RuntimePostgresqlRestartLauncherService,
            "launchRestartSubworkflow",
        ),
        (
            RuntimePostgresqlContinueLauncherService,
            "launchContinueSubworkflow",
        ),
    )

    for launcherClass, methodName in launcherMethods:
        source = inspect.getsource(
            getattr(
                launcherClass,
                methodName,
            )
        )

        for legacyField in (
                "usesProjectSqlite",
                "usesRunDb",
                "usesStepsSqlite",
        ):
            assert legacyField not in source



