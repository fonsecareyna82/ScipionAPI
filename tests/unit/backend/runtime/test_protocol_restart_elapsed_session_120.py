"""#120: dispatched Restart session survives worker launch; Continue keeps elapsed."""
from app.backend.runtime.protocol_status_sync_service import RuntimeProtocolStatusSyncService


class Mapper120:
    def __init__(self, elapsed=15.0, session="previous-session"):
        self.row = {
            "id": 11, "status": "scheduled", "params": {
                "_scipionWebRuntime": {
                    "elapsedSessionId": session,
                    "elapsedTimeSeconds": elapsed,
                    "elapsedUpdatedAtEpochSeconds": 1000.0,
                    "cpuTimeSeconds": 12.0,
                    "customMetadata": "keep-me",
                }
            }
        }

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        assert (projectId, protocolId) == (1, 25)
        return dict(self.row)

    def updateProtocol(self, values):
        assert values["id"] == 11
        if "params" in values:
            self.row["params"] = values["params"]


def metadata(mapper):
    service = RuntimeProtocolStatusSyncService()
    return service.normalizeParams(mapper.row["params"])[service.RUNTIME_METADATA_KEY]


def test_120_RestartZeroBeforeLaunchAndSameSessionAfterWorkerStart():
    service = RuntimeProtocolStatusSyncService()
    mapper = Mapper120()
    run_id = service.startCoordinatorRun(mapper=mapper, projectId=1, protocolId=25, resetElapsed=True)
    before = metadata(mapper)
    assert before["coordinatorRunId"] == run_id
    assert before["elapsedSessionId"] == run_id
    assert before["elapsedTimeSeconds"] == 0.0
    assert "elapsedUpdatedAtEpochSeconds" not in before
    assert service.getEffectiveElapsedTimeSeconds(before, "scheduled", fallbackElapsedSeconds=15.0) == 0.0
    assert before["customMetadata"] == "keep-me"

    result = service.markProtocolLaunched(mapper=mapper, projectId=1, protocolId=25,
                                          baseElapsedTimeSeconds=15.0, resetElapsed=True)
    after = metadata(mapper)
    assert result["elapsedSessionId"] == run_id
    assert after["elapsedSessionId"] == run_id
    assert after["elapsedTimeSeconds"] == 0.0
    assert "elapsedUpdatedAtEpochSeconds" not in after


def test_120_ContinueRetainsPriorElapsedAndSessionOnDispatch():
    service = RuntimeProtocolStatusSyncService()
    mapper = Mapper120()
    run_id = service.startCoordinatorRun(mapper=mapper, projectId=1, protocolId=25, resetElapsed=False)
    during = metadata(mapper)
    assert during["coordinatorRunId"] == run_id
    assert during["elapsedSessionId"] == "previous-session"
    assert during["elapsedTimeSeconds"] == 15.0
    assert during["cpuTimeSeconds"] == 12.0
