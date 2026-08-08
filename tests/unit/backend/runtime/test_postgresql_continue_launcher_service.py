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

    def prepareProtocolStepsForContinue(
            self,
            **kwargs,
    ):
        self.prepareContinueCalls.append(
            kwargs
        )

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



