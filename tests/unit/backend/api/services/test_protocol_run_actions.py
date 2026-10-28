"""The actions a protocol offers while it runs (STOP STREAMING, APPROVE CHECKPOINT), listed and run."""
from contextlib import contextmanager

import pytest

from app.backend.api.services import protocol_run_actions_service as service
from app.backend.api.services import protocol_run_actions_worker as worker

USER = {"id": 3}


class Mapper:
    def __init__(self, status="running", visible=True):
        self.status, self.visible = status, visible

    def getProject(self, projectId, userId):
        return {"id": projectId} if self.visible else None

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        return {"id": 900 + protocolId, "projectId": projectId, "protocolId": protocolId, "status": self.status}


class Worker:
    """Answers as the child would, and keeps what it was asked."""

    def __init__(self, reply):
        self.reply, self.requests = reply, []

    def __call__(self, request, timeout):
        self.requests.append(request)
        return self.reply


def test_only_a_running_protocol_asks_its_actions_to_a_child():
    idle = Worker({"actions": ["STOP STREAMING"]})
    assert service.listProtocolRunActions(mapper=Mapper("finished"), current_user=USER, project_id=7,
                                          protocol_id=2, worker_runner=idle) == []
    assert idle.requests == []

    running = Worker({"actions": ["STOP STREAMING", "", 3, "x" * 200]})
    assert service.listProtocolRunActions(mapper=Mapper(), current_user=USER, project_id=7, protocol_id=2,
                                          worker_runner=running) == ["STOP STREAMING"]
    assert running.requests == [{"projectId": 7, "protocolId": 2, "protocolDbId": 902, "action": None}]


def test_a_project_the_user_cannot_see_has_no_actions():
    with pytest.raises(service.ProtocolRunActionError) as error:
        service.listProtocolRunActions(mapper=Mapper(visible=False), current_user=USER, project_id=7,
                                       protocol_id=2, worker_runner=Worker({}))
    assert error.value.code == "unauthorized"


def test_an_action_runs_only_while_the_protocol_runs_and_offers_it():
    ran = Worker({"ran": "STOP STREAMING"})
    assert service.runProtocolRunAction(mapper=Mapper(), current_user=USER, project_id=7, protocol_id=2,
                                        action="STOP STREAMING", worker_runner=ran) == {"ran": "STOP STREAMING"}
    assert ran.requests[0]["action"] == "STOP STREAMING"

    for mapper, reply, code in ((Mapper("finished"), {"ran": "STOP STREAMING"}, "not_running"),
                                (Mapper(), {"error": "unknown_action"}, "unknown_action")):
        with pytest.raises(service.ProtocolRunActionError) as error:
            service.runProtocolRunAction(mapper=mapper, current_user=USER, project_id=7, protocol_id=2,
                                         action="STOP STREAMING", worker_runner=Worker(reply))
        assert error.value.code == code


@pytest.fixture
def loaded(monkeypatch):
    """The child loading the given protocol instead of one from the database."""
    holder = {}

    @contextmanager
    def load(request):
        yield None, None, holder["protocol"]

    monkeypatch.setattr(worker, "loadRuntimeProtocol", load)
    return holder


REQUEST = {"projectId": 7, "protocolId": 2, "protocolDbId": 902}


def test_a_streaming_import_running_offers_stop_streaming_and_leaves_the_file_it_looks_for(loaded, tmp_path):
    from pwem.protocols import ProtImportMovies

    protocol = ProtImportMovies()
    protocol.setWorkingDir(str(tmp_path))
    (tmp_path / "extra").mkdir()
    protocol.dataStreaming.set(True)
    protocol.setStatus("running")
    loaded["protocol"] = protocol

    assert worker._run(dict(REQUEST, action=None)) == {"actions": ["STOP STREAMING"]}
    assert worker._run(dict(REQUEST, action="STOP STREAMING")) == {"ran": "STOP STREAMING"}
    assert protocol.stopStreamingFileExists()

    protocol.setStatus("finished")
    assert worker._run(dict(REQUEST, action=None)) == {"actions": []}
    assert worker._run(dict(REQUEST, action="STOP STREAMING")) == {"error": "unknown_action"}


def test_callbacks_with_and_without_the_menu_event_are_both_called(loaded):
    called = []

    class Protocol:
        def getActions(self):
            return [("WITH EVENT", lambda event: called.append(("event", event))),
                    ("WITHOUT", lambda: called.append(("none",)))]

    loaded["protocol"] = Protocol()
    worker._run(dict(REQUEST, action="WITH EVENT"))
    worker._run(dict(REQUEST, action="WITHOUT"))

    assert called == [("event", None), ("none",)]


def test_a_plugin_failing_to_tell_its_actions_offers_none(loaded):
    class Protocol:
        def getActions(self):
            raise RuntimeError("broken plugin")

    loaded["protocol"] = Protocol()
    assert worker._run(dict(REQUEST, action=None)) == {"actions": []}


@pytest.mark.parametrize("request_", [
    dict(REQUEST, action=None), dict(REQUEST, action="STOP STREAMING"),
])
def test_valid_requests(request_):
    assert worker._valid_request(request_)


@pytest.mark.parametrize("request_", [
    REQUEST, dict(REQUEST, action=""), dict(REQUEST, action="x" * 200), dict(REQUEST, action=None, extra=1),
    dict(REQUEST, projectId="7", action=None), dict(REQUEST, protocolId=0, action=None),
])
def test_invalid_requests(request_):
    assert not worker._valid_request(request_)
