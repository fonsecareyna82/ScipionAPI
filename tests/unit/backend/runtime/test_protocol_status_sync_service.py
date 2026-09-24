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
# * All comments concerning this program package may be sent to the
# * e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
from pyworkflow.protocol import STATUS_ABORTED

from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)


class FakeActiveRuntimeProtocol:
    def getPid(self):
        return 4321

    def getJobIds(self):
        return [
            "77",
            "78",
        ]

    def getElapsedTime(self):
        return None


class FakeRuntimeMetadataProtocol(FakeActiveRuntimeProtocol):
    def __init__(self):
        self._cpuTime = 7.5

    def getElapsedTime(self):
        return 18.25


class FakeMapper:
    def __init__(self):
        self.db = None
        self.row = {
            "id": 10,
            "status": "running",
            "params": {},
            "relationsSynchronized": False,
        }

    def getProjectProtocolByProtocolId(
            self,
            projectId,
            protocolId,
    ):
        return dict(self.row)

    def updateProtocol(self, values):
        if "status" in values:
            self.row["status"] = values["status"]

        if "params" in values:
            self.row["params"] = values["params"]

    def updateProtocolStatusIfCoordinatorRunId(self, protocolDbId, expectedRunId, status):
        assert protocolDbId == self.row["id"]
        params = RuntimeProtocolStatusSyncService().normalizeParams(self.row["params"])
        metadata = params.get(RuntimeProtocolStatusSyncService.RUNTIME_METADATA_KEY) or {}
        runId = metadata.get("coordinatorRunId") if isinstance(metadata, dict) else None
        if runId != expectedRunId:
            return False
        self.row["status"] = status
        return True

    def _storedCoordinatorRunId(self):
        params = RuntimeProtocolStatusSyncService().normalizeParams(self.row["params"])
        metadata = params.get(RuntimeProtocolStatusSyncService.RUNTIME_METADATA_KEY) or {}
        return metadata.get("coordinatorRunId") if isinstance(metadata, dict) else None

    def updateProtocolParamsIfCoordinatorRunId(self, protocolDbId, expectedRunId, params):
        assert protocolDbId == self.row["id"]
        if self._storedCoordinatorRunId() != expectedRunId:
            return False
        self.row["params"] = params
        return True

    def updateProtocolStatusAndParamsIfCoordinatorRunId(self, protocolDbId, expectedRunId, status, params):
        assert protocolDbId == self.row["id"]
        if self._storedCoordinatorRunId() != expectedRunId:
            return False
        self.row["status"] = status
        self.row["params"] = params
        return True


def test_PersistProtocolProcessIdentityPreservesRuntimeMetadata():
    mapper = FakeMapper()

    mapper.row["params"] = {
        (
            RuntimeProtocolStatusSyncService
            .RUNTIME_METADATA_KEY
        ): {
            "elapsedTimeSeconds": 18.5,
            "cpuTimeSeconds": 7.0,
            "pid": 1111,
            "jobIds": [
                "old-job",
            ],
        },
    }

    protocol = (
        FakeActiveRuntimeProtocol()
    )

    result = (
        RuntimeProtocolStatusSyncService()
        .persistProtocolProcessIdentity(
            mapper=mapper,
            projectId=1,
            protocolId=10,
            protocol=protocol,
        )
    )

    params = (
        RuntimeProtocolStatusSyncService()
        .normalizeParams(
            mapper.row["params"]
        )
    )

    metadata = params[
        (
            RuntimeProtocolStatusSyncService
            .RUNTIME_METADATA_KEY
        )
    ]

    assert metadata[
        "elapsedTimeSeconds"
    ] == 18.5

    assert metadata[
        "cpuTimeSeconds"
    ] == 7.0

    assert metadata["pid"] == 4321

    assert metadata["jobIds"] == [
        "77",
        "78",
    ]

    assert result == {
        "protocolId": "10",
        "pid": 4321,
        "jobIds": [
            "77",
            "78",
        ],
    }


def test_BuildRuntimeMetadataIncludesTimingAndProcessIdentity():
    metadata = RuntimeProtocolStatusSyncService().buildRuntimeMetadata(FakeRuntimeMetadataProtocol())

    assert metadata == {
        "cpuTimeSeconds": 7.5,
        "elapsedTimeSeconds": 18.25,
        "pid": 4321,
        "jobIds": ["77", "78"],
    }


def test_ResetProtocolRuntimeMetadataClearsExecutionState():
    mapper = FakeMapper()

    mapper.row["params"] = {
        (
            RuntimeProtocolStatusSyncService
            .RUNTIME_METADATA_KEY
        ): {
            "cpuTimeSeconds": 21.0,
            "elapsedTimeSeconds": 92.5,
            "elapsedUpdatedAtEpochSeconds": 12345.0,
            "finalSyncPending": True,
            "pid": 4321,
            "jobIds": [
                "77",
                "78",
            ],
        },
    }

    result = (
        RuntimeProtocolStatusSyncService()
        .resetProtocolRuntimeMetadata(
            mapper=mapper,
            projectId=1,
            protocolId=10,
        )
    )

    params = (
        RuntimeProtocolStatusSyncService()
        .normalizeParams(
            mapper.row["params"]
        )
    )

    metadata = params[
        (
            RuntimeProtocolStatusSyncService
            .RUNTIME_METADATA_KEY
        )
    ]

    assert metadata[
        "cpuTimeSeconds"
    ] == 0.0

    assert metadata[
        "elapsedTimeSeconds"
    ] == 0.0

    assert metadata[
        "pid"
    ] is None

    assert metadata[
        "jobIds"
    ] == []

    assert (
        "elapsedUpdatedAtEpochSeconds"
        not in metadata
    )

    assert (
        "finalSyncPending"
        not in metadata
    )

    assert result == {
        "protocolId": "10",
        "cpuTimeSeconds": 0.0,
        "elapsedTimeSeconds": 0.0,
        "elapsedSessionId": None,
        "pid": None,
        "jobIds": [],
    }

def test_GetEffectiveElapsedTimeProjectsActiveCheckpoint():
    service = (
        RuntimeProtocolStatusSyncService()
    )

    result = (
        service
        .getEffectiveElapsedTimeSeconds(
            runtimeMetadata={
                "elapsedTimeSeconds": 25.0,
                (
                    service
                    .ELAPSED_UPDATED_AT_KEY
                ): 100.0,
            },
            statusValue="running",
            nowEpochSeconds=115.0,
        )
    )

    assert result == 40.0


def test_GetEffectiveElapsedTimeDoesNotProjectTerminalProtocol():
    service = (
        RuntimeProtocolStatusSyncService()
    )

    result = (
        service
        .getEffectiveElapsedTimeSeconds(
            runtimeMetadata={
                "elapsedTimeSeconds": 25.0,
                (
                    service
                    .ELAPSED_UPDATED_AT_KEY
                ): 100.0,
            },
            statusValue="finished",
            nowEpochSeconds=115.0,
        )
    )

    assert result == 25.0


def test_GetEffectiveElapsedTimeIgnoresFutureCheckpoint():
    service = (
        RuntimeProtocolStatusSyncService()
    )

    result = (
        service
        .getEffectiveElapsedTimeSeconds(
            runtimeMetadata={
                "elapsedTimeSeconds": 25.0,
                (
                    service
                    .ELAPSED_UPDATED_AT_KEY
                ): 120.0,
            },
            statusValue="running",
            nowEpochSeconds=115.0,
        )
    )

    assert result == 25.0


def test_GetEffectiveElapsedTimeUsesStepFallbackWhenMetadataIsZero():
    service = RuntimeProtocolStatusSyncService()

    result = service.getEffectiveElapsedTimeSeconds(
        {
            "elapsedTimeSeconds": 0.0,
            service.ELAPSED_UPDATED_AT_KEY: 100.0,
        },
        "running",
        nowEpochSeconds=100.0,
        fallbackElapsedSeconds=137.0,
    )

    assert result == 137.0


def test_GetEffectiveElapsedTimeKeepsProjectedMetadataWhenGreaterThanSteps():
    service = RuntimeProtocolStatusSyncService()

    result = service.getEffectiveElapsedTimeSeconds(
        {
            "elapsedTimeSeconds": 25.0,
            service.ELAPSED_UPDATED_AT_KEY: 100.0,
        },
        "running",
        nowEpochSeconds=115.0,
        fallbackElapsedSeconds=30.0,
    )

    assert result == 40.0


def test_PersistProtocolExecutionUserStoresExecutionId():
    mapper = FakeMapper()

    result = (
        RuntimeProtocolStatusSyncService()
        .persistProtocolExecutionUser(
            mapper=mapper,
            projectId=1,
            protocolId=10,
            userId=7,
            executionId="execution-123",
        )
    )

    params = (
        RuntimeProtocolStatusSyncService()
        .normalizeParams(
            mapper.row["params"]
        )
    )

    metadata = params[
        (
            RuntimeProtocolStatusSyncService
            .RUNTIME_METADATA_KEY
        )
    ]

    assert (
        metadata["launchedByUserId"]
        == 7
    )

    assert (
        metadata["executionId"]
        == "execution-123"
    )

    assert result == {
        "projectId": 1,
        "protocolId": "10",
        "launchedByUserId": 7,
        "executionId": "execution-123",
    }

def test_MarkProtocolLaunchedDoesNotStartElapsedClockImmediately(
        monkeypatch,
):
    """
    The elapsed clock must reflect actual execution time, not queue
    wait, so a plain launch (no execution has started yet) must leave
    the checkpoint unset and the effective elapsed time frozen.
    """
    service = RuntimeProtocolStatusSyncService()
    mapper = FakeMapper()

    monkeypatch.setattr(
        "app.backend.runtime.protocol_status_sync_service.time.time",
        lambda: 100.0,
    )

    service.markProtocolLaunched(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        resetElapsed=True,
    )

    params = service.normalizeParams(
        mapper.row["params"]
    )

    metadata = params[
        service.RUNTIME_METADATA_KEY
    ]

    assert (
        service.ELAPSED_UPDATED_AT_KEY
        not in metadata
    )

    assert (
        service.getEffectiveElapsedTimeSeconds(
            runtimeMetadata=metadata,
            statusValue="launched",
            nowEpochSeconds=115.0,
        )
        == 0.0
    )

def test_MarkProtocolLaunchedRepeatedCallsStayFrozenWhileQueued(
        monkeypatch,
):
    """
    Both the initial queue submission and the later execute() re-affirm
    of the Launched status (once the queued job actually starts) call
    markProtocolLaunched(); while still queued/launched, neither call
    should make the effective elapsed time advance with wall-clock time.
    """
    service = RuntimeProtocolStatusSyncService()
    mapper = FakeMapper()

    currentTime = {
        "value": 100.0,
    }

    monkeypatch.setattr(
        "app.backend.runtime.protocol_status_sync_service.time.time",
        lambda: currentTime["value"],
    )

    service.markProtocolLaunched(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        resetElapsed=True,
    )

    currentTime["value"] = 130.0

    secondReport = service.markProtocolLaunched(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        resetElapsed=True,
    )

    params = service.normalizeParams(
        mapper.row["params"]
    )

    metadata = params[
        service.RUNTIME_METADATA_KEY
    ]

    assert (
        secondReport["elapsedSessionId"]
    )

    assert metadata[
        "elapsedTimeSeconds"
    ] == 0.0

    assert (
        service.ELAPSED_UPDATED_AT_KEY
        not in metadata
    )

    assert (
        service.getEffectiveElapsedTimeSeconds(
            runtimeMetadata=metadata,
            statusValue="launched",
            nowEpochSeconds=145.0,
        )
        == 0.0
    )

def test_MarkProtocolLaunchedRestartAfterTerminalCreatesNewElapsedSession(
        monkeypatch,
):
    service = RuntimeProtocolStatusSyncService()
    mapper = FakeMapper()

    mapper.row["params"] = {
        service.RUNTIME_METADATA_KEY: {
            "elapsedTimeSeconds": 40.0,
            service.ELAPSED_SESSION_ID_KEY: "old-session",
        },
    }

    monkeypatch.setattr(
        "app.backend.runtime.protocol_status_sync_service.time.time",
        lambda: 200.0,
    )

    report = service.markProtocolLaunched(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        baseElapsedTimeSeconds=40.0,
        resetElapsed=True,
    )

    params = service.normalizeParams(
        mapper.row["params"]
    )

    metadata = params[
        service.RUNTIME_METADATA_KEY
    ]

    assert (
        report["elapsedSessionId"]
        != "old-session"
    )

    assert metadata[
        "elapsedTimeSeconds"
    ] == 0.0

    assert (
        service.ELAPSED_UPDATED_AT_KEY
        not in metadata
    )

    assert (
        service.getEffectiveElapsedTimeSeconds(
            runtimeMetadata=metadata,
            statusValue="launched",
            nowEpochSeconds=215.0,
        )
        == 0.0
    )


def test_MarkProtocolLaunchedResumeAfterTerminalKeepsAccumulatedElapsed(
        monkeypatch,
):
    service = RuntimeProtocolStatusSyncService()
    mapper = FakeMapper()

    mapper.row["params"] = {
        service.RUNTIME_METADATA_KEY: {
            "elapsedTimeSeconds": 40.0,
            service.ELAPSED_SESSION_ID_KEY: "resume-session",
        },
    }

    monkeypatch.setattr(
        "app.backend.runtime.protocol_status_sync_service.time.time",
        lambda: 200.0,
    )

    report = service.markProtocolLaunched(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        baseElapsedTimeSeconds=40.0,
        resetElapsed=False,
    )

    params = service.normalizeParams(
        mapper.row["params"]
    )

    metadata = params[
        service.RUNTIME_METADATA_KEY
    ]

    assert (
        report["elapsedSessionId"]
        == "resume-session"
    )

    assert metadata[
        "elapsedTimeSeconds"
    ] == 40.0

    assert (
        service.ELAPSED_UPDATED_AT_KEY
        not in metadata
    )

    assert (
        service.getEffectiveElapsedTimeSeconds(
            runtimeMetadata=metadata,
            statusValue="launched",
            nowEpochSeconds=215.0,
        )
        == 40.0
    )


def test_StaleCoordinatorCannotWriteIdentityAfterConcurrentRelaunch():
    import pytest
    from app.backend.runtime.protocol_status_sync_service import StaleCoordinatorRunError

    service = RuntimeProtocolStatusSyncService()
    currentMetadata = {
        "coordinatorRunId": "new-run",
        "hostname": "node-new",
        "pid": 9900,
        "jobIds": [],
    }

    class RacingMapper(FakeMapper):
        def __init__(self):
            super().__init__()
            self.row["params"] = {
                service.RUNTIME_METADATA_KEY: {"coordinatorRunId": "old-run"},
            }
            self.relaunched = False

        def relaunch(self):
            if not self.relaunched:
                self.relaunched = True
                self.row["params"] = {
                    service.RUNTIME_METADATA_KEY: dict(currentMetadata),
                }

        def updateProtocol(self, values):
            self.relaunch()
            super().updateProtocol(values)

        def updateProtocolParamsIfCoordinatorRunId(self, protocolDbId, expectedRunId, params):
            assert protocolDbId == self.row["id"]
            self.relaunch()
            current = service.normalizeParams(self.row["params"])
            runId = current[service.RUNTIME_METADATA_KEY]["coordinatorRunId"]
            if runId != expectedRunId:
                return False
            self.row["params"] = params
            return True

    mapper = RacingMapper()
    with pytest.raises(StaleCoordinatorRunError):
        service.persistProtocolProcessIdentity(
            mapper=mapper, projectId=1, protocolId=10,
            protocol=FakeActiveRuntimeProtocol(),
            hostname="node-old", coordinatorRunId="old-run",
        )

    params = service.normalizeParams(mapper.row["params"])
    assert params[service.RUNTIME_METADATA_KEY] == currentMetadata


def test_MarkProtocolAbortedWritesAtomicallyWhenStillOwner():
    service = RuntimeProtocolStatusSyncService()
    mapper = FakeMapper()
    mapper.row["params"] = {
        service.RUNTIME_METADATA_KEY: {"coordinatorRunId": "run-1"},
    }

    report = service.markProtocolAborted(
        mapper=mapper, projectId=1, protocolId=10,
        expectedCoordinatorRunId="run-1",
    )

    assert report["status"] == STATUS_ABORTED
    assert mapper.row["status"] == STATUS_ABORTED


def test_MarkProtocolAbortedRaisesWhenCoordinatorWasSupersededBeforeWrite():
    # Regression test for the race the Stop flow used to have: it re-read
    # PID/hostname right after killing the remote process and compared
    # them in Python, but a relaunch landing between that check and the
    # actual status write would still get silently overwritten as
    # ABORTED. The write itself must now be conditional on ownership.
    import pytest
    from app.backend.runtime.protocol_status_sync_service import StaleCoordinatorRunError

    service = RuntimeProtocolStatusSyncService()

    class RacingMapper(FakeMapper):
        def __init__(self):
            super().__init__()
            self.row["params"] = {
                service.RUNTIME_METADATA_KEY: {"coordinatorRunId": "old-run"},
            }
            self.relaunched = False

        def updateProtocolStatusIfCoordinatorRunId(self, protocolDbId, expectedRunId, status):
            # A newer launch takes over the row right as the Stop tries
            # to write ABORTED for the old (already-killed) coordinator.
            if not self.relaunched:
                self.relaunched = True
                self.row["params"] = {
                    service.RUNTIME_METADATA_KEY: {"coordinatorRunId": "new-run"},
                }
            return super().updateProtocolStatusIfCoordinatorRunId(
                protocolDbId, expectedRunId, status,
            )

    mapper = RacingMapper()

    with pytest.raises(StaleCoordinatorRunError):
        service.markProtocolAborted(
            mapper=mapper, projectId=1, protocolId=10,
            expectedCoordinatorRunId="old-run",
        )

    # The superseded Stop must NOT have flipped the newer run's status.
    assert mapper.row["status"] == "running"


def test_MarkProtocolAbortedWithoutExpectedRunIdWritesUnconditionally():
    # Callers (or protocols predating this feature) that never captured a
    # coordinatorRunId keep the original unconditional-write behavior.
    service = RuntimeProtocolStatusSyncService()
    mapper = FakeMapper()
    mapper.row["params"] = {}

    report = service.markProtocolAborted(
        mapper=mapper, projectId=1, protocolId=10,
    )

    assert report["status"] == STATUS_ABORTED
    assert mapper.row["status"] == STATUS_ABORTED


def test_WriteCoordinatorHeartbeatSucceedsWhileStillOwner():
    service = RuntimeProtocolStatusSyncService()
    mapper = FakeMapper()
    mapper.row["params"] = {
        service.RUNTIME_METADATA_KEY: {"coordinatorRunId": "run-1"},
    }

    updated = service.writeCoordinatorHeartbeat(
        mapper=mapper, projectId=1, protocolId=10, coordinatorRunId="run-1",
    )

    assert updated is True
    params = service.normalizeParams(mapper.row["params"])
    metadata = params[service.RUNTIME_METADATA_KEY]
    assert isinstance(metadata[service.COORDINATOR_HEARTBEAT_KEY], float)


def test_WriteCoordinatorHeartbeatFailsAfterSupersededRelaunch():
    service = RuntimeProtocolStatusSyncService()
    mapper = FakeMapper()
    mapper.row["params"] = {
        service.RUNTIME_METADATA_KEY: {"coordinatorRunId": "new-run"},
    }

    updated = service.writeCoordinatorHeartbeat(
        mapper=mapper, projectId=1, protocolId=10, coordinatorRunId="old-run",
    )

    assert updated is False
    # The stale coordinator's heartbeat must not have touched the row at
    # all -- the newer run's identity stays exactly as it was.
    params = service.normalizeParams(mapper.row["params"])
    assert service.COORDINATOR_HEARTBEAT_KEY not in params[service.RUNTIME_METADATA_KEY]


def test_IsCoordinatorHeartbeatStale():
    service = RuntimeProtocolStatusSyncService()
    now = 1_000_000.0

    # No heartbeat recorded at all -- not enough information to presume
    # anything, so this must NOT be reported as stale.
    assert service.isCoordinatorHeartbeatStale({}, now) is False
    assert service.isCoordinatorHeartbeatStale(
        {service.COORDINATOR_HEARTBEAT_KEY: None}, now,
    ) is False

    # A recent heartbeat is not stale.
    assert service.isCoordinatorHeartbeatStale(
        {service.COORDINATOR_HEARTBEAT_KEY: now - 10.0}, now,
    ) is False

    # An old heartbeat, past the threshold, is stale.
    assert service.isCoordinatorHeartbeatStale(
        {service.COORDINATOR_HEARTBEAT_KEY: now - 200.0}, now,
        staleAfterSeconds=180.0,
    ) is True

    # A custom threshold is respected.
    assert service.isCoordinatorHeartbeatStale(
        {service.COORDINATOR_HEARTBEAT_KEY: now - 50.0}, now,
        staleAfterSeconds=30.0,
    ) is True


def test_MarkProtocolPresumedFailedWritesStatusAndReasonAtomically():
    from pyworkflow.protocol import STATUS_FAILED

    service = RuntimeProtocolStatusSyncService()
    mapper = FakeMapper()
    mapper.row["params"] = {
        service.RUNTIME_METADATA_KEY: {"coordinatorRunId": "run-1"},
    }

    report = service.markProtocolPresumedFailed(
        mapper=mapper, projectId=1, protocolId=10,
        expectedCoordinatorRunId="run-1",
        reason="host unreachable",
    )

    assert report["status"] == STATUS_FAILED
    assert mapper.row["status"] == STATUS_FAILED
    params = service.normalizeParams(mapper.row["params"])
    assert params[service.RUNTIME_METADATA_KEY]["presumedFailedReason"] == "host unreachable"


def test_MarkProtocolPresumedFailedRaisesWhenCoordinatorWasSuperseded():
    import pytest
    from app.backend.runtime.protocol_status_sync_service import StaleCoordinatorRunError

    service = RuntimeProtocolStatusSyncService()
    mapper = FakeMapper()
    mapper.row["params"] = {
        service.RUNTIME_METADATA_KEY: {"coordinatorRunId": "new-run"},
    }

    with pytest.raises(StaleCoordinatorRunError):
        service.markProtocolPresumedFailed(
            mapper=mapper, projectId=1, protocolId=10,
            expectedCoordinatorRunId="old-run",
            reason="host unreachable",
        )

    # The newer run's status must be untouched.
    assert mapper.row["status"] == "running"
