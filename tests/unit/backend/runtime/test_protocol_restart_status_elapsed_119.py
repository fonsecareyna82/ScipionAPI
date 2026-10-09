"""#119 RED: a newly accepted restart must own a fresh elapsed session.

The regression was observed while scheduled, before the worker called
markProtocolLaunched(). This test does not execute or alter real protocols.
"""
import json

from app.backend.runtime.protocol_status_sync_service import RuntimeProtocolStatusSyncService


class _RestartMapper119:
    def __init__(self):
        self.row = {
            "id": 42,
            "status": "scheduled",
            "params": {
                "_scipionWebRuntime": {
                    "elapsedSessionId": "previous-finished-run",
                    "elapsedTimeSeconds": 15.0,
                    "elapsedUpdatedAtEpochSeconds": 1234.0,
                    "cpuTimeSeconds": 14.5,
                },
            },
        }

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        assert (projectId, protocolId) == (1, 25)
        return dict(self.row)

    def updateProtocol(self, values):
        assert values["id"] == 42
        self.row["params"] = values["params"]


def test_119_RestartResetsElapsedSessionAtDispatchBeforeWorkerLaunch():
    mapper = _RestartMapper119()
    service = RuntimeProtocolStatusSyncService()

    service.startCoordinatorRun(mapper=mapper, projectId=1, protocolId=25, resetElapsed=True)

    params = service.normalizeParams(mapper.row["params"])
    runtime = params[service.RUNTIME_METADATA_KEY]
    assert mapper.row["status"] == "scheduled"
    assert runtime["elapsedTimeSeconds"] == 0.0
    assert runtime["cpuTimeSeconds"] == 0.0
    assert runtime["elapsedSessionId"] not in (None, "", "previous-finished-run")
    assert service.ELAPSED_UPDATED_AT_KEY not in runtime
    assert runtime["coordinatorRunId"]


def test_119_ResumeKeepsPriorElapsedSessionWhenDispatching():
    mapper = _RestartMapper119()
    service = RuntimeProtocolStatusSyncService()

    service.startCoordinatorRun(mapper=mapper, projectId=1, protocolId=25, resetElapsed=False)

    params = service.normalizeParams(mapper.row["params"])
    runtime = params[service.RUNTIME_METADATA_KEY]
    assert runtime["elapsedTimeSeconds"] == 15.0
    assert runtime["elapsedSessionId"] == "previous-finished-run"
