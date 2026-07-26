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
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pyworkflow.object import CsvList
from pyworkflow.protocol import STATUS_ABORTED

import app.backend.runtime.protocol_stop_service as stopModule
from app.backend.runtime.protocol_stop_service import (
    RuntimeProtocolStopService,
)


class FakeScalar:
    def __init__(self, value=None):
        self.value = value

    def get(self, default=None):
        if self.value is None:
            return default

        return self.value

    def set(self, value):
        self.value = value


class FakeListScalar(list):
    def get(self):
        return list(self)

    def set(self, values):
        self.clear()
        self.extend(
            values or []
        )


class FakeHostConfig:
    def getCancelCommand(self):
        return "cancel-job %(JOB_ID)s"


class FakeProtocol:
    def __init__(
            self,
            protocolId=10,
            protocolStatus="running",
            pid=1234,
            jobIds=None,
            queueForProtocol=False,
            queueForSteps=False,
    ):
        self.protocolId = protocolId
        self.status = FakeScalar(
            protocolStatus
        )

        self.endTime = FakeScalar()
        self._error = FakeScalar()
        self._pid = FakeScalar(pid)
        self._jobId = FakeListScalar(
            jobIds or []
        )

        self.queueForProtocol = (
            queueForProtocol
        )

        self.queueForSteps = (
            queueForSteps
        )

    def getObjId(self):
        return self.protocolId

    def getStatus(self):
        return self.status.get()

    def setStatus(self, value):
        self.status.set(
            value
        )

    def getPid(self):
        return self._pid.get()

    def getJobIds(self):
        return list(
            self._jobId
        )

    def useQueueForProtocol(self):
        return self.queueForProtocol

    def useQueueForSteps(self):
        return self.queueForSteps

    def getHostConfig(self):
        return FakeHostConfig()


class FakeCursor:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount


class FakeDb:
    def __init__(self):
        self.executeCalls = []
        self.fetchAllCalls = []

    @contextmanager
    def transaction(self):
        yield

    def execute(
            self,
            query,
            params=None,
            commit=True,
    ):
        self.executeCalls.append({
            "query": query,
            "params": params,
            "commit": commit,
        })

        return FakeCursor(
            rowcount=1
        )

    def fetchAll(
            self,
            query,
            params=None,
    ):
        self.fetchAllCalls.append({
            "query": query,
            "params": params,
        })

        if "FROM scipion_sets" in query:
            return [
                {
                    "id": 100,
                    "outputName": (
                        "outputParticles"
                    ),
                },
            ]

        return []


class FakeMapper:
    def __init__(self):
        self.db = FakeDb()

    def getProjectProtocolByProtocolId(
            self,
            projectId,
            protocolId,
    ):
        return {
            "id": 50,
            "projectId": projectId,
            "protocolId": str(
                protocolId
            ),
            "status": "running",
            "params": {},
        }


class FakeRuntimeMapper:
    def __init__(self):
        self.stored = []
        self.commits = 0

    def store(self, protocol):
        self.stored.append(
            protocol
        )

    def commit(self):
        self.commits += 1


class FakeCurrentProject:
    def __init__(self):
        self.runtimeMapper = (
            FakeRuntimeMapper()
        )

        self.legacyStopped = []

    def getPostgresqlRuntimeMapper(self):
        return self.runtimeMapper

    def stopProtocol(self, protocol):
        self.legacyStopped.append(
            protocol
        )


class FakeStatusService:
    ACTIVE_STATUS_TEXTS = {
        "launched",
        "running",
        "scheduled",
    }

    def captureProtocolElapsedState(
            self,
            **kwargs,
    ):
        return {
            "elapsedTimeSeconds": 5.0,
            "elapsedUpdatedAtEpochSeconds": 10.0,
        }

    def markProtocolAborted(
            self,
            protocolId,
            **kwargs,
    ):
        return {
            "protocolId": str(
                protocolId
            ),
            "status": STATUS_ABORTED,
        }

    def finalizeProtocolElapsedTime(
            self,
            protocolId,
            **kwargs,
    ):
        return {
            "protocolId": str(
                protocolId
            ),
            "elapsedTimeSeconds": 8.0,
        }


def buildResult(
        message,
        **extra,
):
    return {
        "status": 0,
        "errors": [],
        "message": message,
        **extra,
    }


def test_GetProtocolJobIdsSupportsScipionCsvList():
    protocol = FakeProtocol(
        protocolId=10,
        protocolStatus="running",
        pid=1234,
    )

    protocol._jobId = CsvList()
    protocol._jobId.append(
        "77"
    )
    protocol._jobId.append(
        "78"
    )

    # Scipion's Protocol.getJobIds() returns
    # the CsvList object itself.
    protocol.getJobIds = (
        lambda: protocol._jobId
    )

    service = (
        RuntimeProtocolStopService()
    )

    assert (
        service._getProtocolJobIds(
            protocol
        )
        == [
            "77",
            "78",
        ]
    )


def test_GetProtocolJobIdsSupportsEmptyScipionCsvList():
    protocol = FakeProtocol(
        protocolId=10,
        protocolStatus="running",
        pid=1234,
    )

    protocol._jobId = CsvList()

    protocol.getJobIds = (
        lambda: protocol._jobId
    )

    service = (
        RuntimeProtocolStopService()
    )

    assert (
        service._getProtocolJobIds(
            protocol
        )
        == []
    )


def test_PostgresqlStopKillsWorkerAndPersistsAbort(
        monkeypatch,
):
    monkeypatch.setattr(
        stopModule,
        "RuntimeProtocolStatusSyncService",
        FakeStatusService,
    )

    mapper = FakeMapper()

    currentProject = (
        FakeCurrentProject()
    )

    protocol = FakeProtocol(
        protocolId=10,
        protocolStatus="running",
        pid=1234,
    )

    service = (
        RuntimeProtocolStopService()
    )

    killCalls = []

    monkeypatch.setattr(
        service,
        "_killProcessGroup",
        lambda **kwargs: (
            killCalls.append(
                kwargs
            )
            or {
                "pid": 1234,
                "processGroupId": 1234,
                "terminated": True,
                "alreadyStopped": False,
                "signal": "SIGTERM",
                "verified": True,
            }
        ),
    )

    result = service.stopProtocols(
        mapper=mapper,
        projectId=1,
        protocolIds=["10"],
        usingPostgresqlRuntime=True,
        currentProject=currentProject,
        getScipionProtocolForRuntimeCallback=(
            lambda **kwargs: protocol
        ),
        buildProtocolMutationResultCallback=(
            buildResult
        ),
    )

    assert result["status"] == 0
    assert result["postgresqlOnly"] is True
    assert result["usesProjectSqlite"] is False
    assert result["usesRunDb"] is False
    assert result["usesStepsSqlite"] is False

    assert killCalls == [
        {
            "pid": 1234,
            "projectId": 1,
            "protocolId": 10,
        },
    ]

    assert protocol.getStatus() == (
        STATUS_ABORTED
    )

    assert protocol.getPid() == 0
    assert protocol.getJobIds() == []

    assert (
        currentProject
        .runtimeMapper
        .stored
        == [
            protocol,
        ]
    )

    assert (
        currentProject
        .runtimeMapper
        .commits
        == 1
    )

    executedSql = "\n".join(
        call["query"]
        for call
        in mapper.db.executeCalls
    )

    assert "UPDATE protocol_steps" in (
        executedSql
    )

    assert "UPDATE scipion_sets" in (
        executedSql
    )

    assert "streamState" in executedSql


def test_PostgresqlStopCancelsQueueAndKillsCoordinator(
        monkeypatch,
):
    monkeypatch.setattr(
        stopModule,
        "RuntimeProtocolStatusSyncService",
        FakeStatusService,
    )

    mapper = FakeMapper()

    currentProject = (
        FakeCurrentProject()
    )

    protocol = FakeProtocol(
        protocolId=10,
        protocolStatus="running",
        pid=1234,
        jobIds=[
            "77",
            "78",
        ],
        queueForSteps=True,
    )

    service = (
        RuntimeProtocolStopService()
    )

    cancelCalls = []
    killCalls = []

    monkeypatch.setattr(
        service,
        "_cancelQueueJobs",
        lambda protocol: (
            cancelCalls.append(
                protocol
            )
            or [
                {
                    "jobId": "77",
                    "returnCode": 0,
                },
                {
                    "jobId": "78",
                    "returnCode": 0,
                },
            ]
        ),
    )

    monkeypatch.setattr(
        service,
        "_killProcessGroup",
        lambda **kwargs: (
            killCalls.append(
                kwargs
            )
            or {
                "terminated": True,
            }
        ),
    )

    result = service.stopProtocols(
        mapper=mapper,
        projectId=1,
        protocolIds=["10"],
        usingPostgresqlRuntime=True,
        currentProject=currentProject,
        getScipionProtocolForRuntimeCallback=(
            lambda **kwargs: protocol
        ),
        buildProtocolMutationResultCallback=(
            buildResult
        ),
    )

    assert result["status"] == 0

    assert cancelCalls == [
        protocol,
    ]

    assert killCalls == [
        {
            "pid": 1234,
            "projectId": 1,
            "protocolId": 10,
        },
    ]

    assert result["queueStopped"][0][
        "jobIds"
    ] == [
        "77",
        "78",
    ]


def test_PostgresqlStopSkipsFinishedProtocol(
        monkeypatch,
):
    monkeypatch.setattr(
        stopModule,
        "RuntimeProtocolStatusSyncService",
        FakeStatusService,
    )

    mapper = FakeMapper()

    currentProject = (
        FakeCurrentProject()
    )

    protocol = FakeProtocol(
        protocolId=10,
        protocolStatus="finished",
        pid=0,
    )

    service = (
        RuntimeProtocolStopService()
    )

    result = service.stopProtocols(
        mapper=mapper,
        projectId=1,
        protocolIds=["10"],
        usingPostgresqlRuntime=True,
        currentProject=currentProject,
        getScipionProtocolForRuntimeCallback=(
            lambda **kwargs: protocol
        ),
        buildProtocolMutationResultCallback=(
            buildResult
        ),
    )

    assert result["protocolsCount"] == 0

    assert result["skipped"] == [
        {
            "protocolId": "10",
            "protocolDbId": 50,
            "status": "finished",
            "reason": (
                "protocol_not_active"
            ),
        },
    ]

    assert (
        currentProject
        .runtimeMapper
        .stored
        == []
    )


def test_PostgresqlStopDeduplicatesProtocolIds(
        monkeypatch,
):
    monkeypatch.setattr(
        stopModule,
        "RuntimeProtocolStatusSyncService",
        FakeStatusService,
    )

    mapper = FakeMapper()

    currentProject = (
        FakeCurrentProject()
    )

    protocol = FakeProtocol(
        protocolId=10,
        protocolStatus="running",
        pid=1234,
    )

    resolvedCalls = []

    service = (
        RuntimeProtocolStopService()
    )

    monkeypatch.setattr(
        service,
        "_killProcessGroup",
        lambda **kwargs: {
            "terminated": True,
        },
    )

    service.stopProtocols(
        mapper=mapper,
        projectId=1,
        protocolIds=[
            "10",
            "10",
        ],
        usingPostgresqlRuntime=True,
        currentProject=currentProject,
        getScipionProtocolForRuntimeCallback=(
            lambda **kwargs: (
                resolvedCalls.append(
                    kwargs
                )
                or protocol
            )
        ),
        buildProtocolMutationResultCallback=(
            buildResult
        ),
    )

    assert len(
        currentProject
        .runtimeMapper
        .stored
    ) == 1


def test_LegacyStopStillDelegatesToProject():
    mapper = FakeMapper()

    currentProject = (
        FakeCurrentProject()
    )

    protocol = FakeProtocol(
        protocolId=10,
        protocolStatus="running",
    )

    result = (
        RuntimeProtocolStopService()
        .stopProtocols(
            mapper=mapper,
            projectId=1,
            protocolIds=["10"],
            usingPostgresqlRuntime=False,
            currentProject=currentProject,
            getScipionProtocolForRuntimeCallback=(
                lambda **kwargs: protocol
            ),
            buildProtocolMutationResultCallback=(
                buildResult
            ),
        )
    )

    assert result["status"] == 0

    assert (
        currentProject
        .legacyStopped
        == [
            protocol,
        ]
    )


def test_StopRejectsEmptyProtocolList():
    with pytest.raises(
            HTTPException
    ) as error:
        (
            RuntimeProtocolStopService()
            .stopProtocols(
                mapper=FakeMapper(),
                projectId=1,
                protocolIds=[],
                usingPostgresqlRuntime=True,
                currentProject=(
                    FakeCurrentProject()
                ),
                getScipionProtocolForRuntimeCallback=(
                    lambda **kwargs: None
                ),
                buildProtocolMutationResultCallback=(
                    buildResult
                ),
            )
        )

    assert error.value.status_code == 422


def test_StopDoesNotAbortWhenStoredPidIsDead(
        monkeypatch,
):
    protocol = FakeProtocol(
        protocolId=10,
        protocolStatus="scheduled",
        pid=1234,
    )

    service = (
        RuntimeProtocolStopService()
    )

    monkeypatch.setattr(
        service,
        "_isPidAlive",
        lambda pid: False,
    )

    with pytest.raises(
            HTTPException
    ) as error:
        service.stopProtocols(
            mapper=FakeMapper(),
            projectId=1,
            protocolIds=["10"],
            usingPostgresqlRuntime=True,
            currentProject=(
                FakeCurrentProject()
            ),
            getScipionProtocolForRuntimeCallback=(
                lambda **kwargs: protocol
            ),
            buildProtocolMutationResultCallback=(
                buildResult
            ),
        )

    assert error.value.status_code == 500

    assert protocol.getStatus() == (
        "scheduled"
    )

def test_ProcessGroupWithOnlyZombieIsNotAlive(
        monkeypatch,
):
    service = (
        RuntimeProtocolStopService()
    )

    monkeypatch.setattr(
        stopModule.os,
        "killpg",
        lambda processGroupId, signalNumber: None,
    )

    monkeypatch.setattr(
        stopModule.os,
        "getpgid",
        lambda pid: 1234,
    )

    zombieProcess = SimpleNamespace(
        pid=1234,
        info={
            "status": (
                stopModule
                .psutil
                .STATUS_ZOMBIE
            ),
        },
    )

    monkeypatch.setattr(
        stopModule.psutil,
        "process_iter",
        lambda attributes: [
            zombieProcess,
        ],
    )

    assert (
        service
        ._isProcessGroupAlive(
            1234
        )
        is False
    )

def test_ProcessGroupWithRunningMemberIsAlive(
        monkeypatch,
):
    service = (
        RuntimeProtocolStopService()
    )

    monkeypatch.setattr(
        stopModule.os,
        "killpg",
        lambda processGroupId, signalNumber: None,
    )

    monkeypatch.setattr(
        stopModule.os,
        "getpgid",
        lambda pid: 1234,
    )

    runningProcess = SimpleNamespace(
        pid=1234,
        info={
            "status": (
                stopModule
                .psutil
                .STATUS_RUNNING
            ),
        },
    )

    monkeypatch.setattr(
        stopModule.psutil,
        "process_iter",
        lambda attributes: [
            runningProcess,
        ],
    )

    assert (
        service
        ._isProcessGroupAlive(
            1234
        )
        is True
    )


def test_ReapChildProcessIgnoresNonChild(
        monkeypatch,
):
    service = (
        RuntimeProtocolStopService()
    )

    def raiseNotChild(
            pid,
            options,
    ):
        raise ChildProcessError()

    monkeypatch.setattr(
        stopModule.os,
        "waitpid",
        raiseNotChild,
    )

    assert (
        service
        ._reapChildProcess(
            1234
        )
        is False
    )



