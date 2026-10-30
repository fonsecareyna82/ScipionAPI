"""A protocol's summary (the desktop Summary tab): asked to a child, with the objects its lines link to."""
from contextlib import contextmanager

import pytest

from app.backend.api.services import protocol_summary_service as service
from app.backend.api.services import protocol_summary_worker as worker

USER = {"id": 3}


class Mapper:
    def __init__(self, visible=True, exists=True):
        self.visible, self.exists = visible, exists

    def getProject(self, projectId, userId):
        return {"id": projectId} if self.visible else None

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        if not self.exists:
            return None
        return {"id": 900 + protocolId, "projectId": projectId, "protocolId": protocolId, "status": "finished"}


class Worker:
    def __init__(self, reply):
        self.reply, self.requests = reply, []

    def __call__(self, request, timeout):
        self.requests.append(request)
        return self.reply


def test_the_summary_is_asked_to_a_child_and_its_reply_is_checked():
    child = Worker({"lines": ["*12* micrographs", 7], "hasWarnings": True,
                    "objects": {"41": {"protocolId": 2, "outputName": "outputMicrographs",
                                       "className": "SetOfMicrographs", "label": "outputMicrographs"},
                                "42": {"protocolId": "2", "outputName": "x"},
                                "43": {"protocolId": 2, "outputName": "not a name"},
                                "id": {"protocolId": 2, "outputName": "outputMovies"}}})

    summary = service.getProtocolSummary(mapper=Mapper(), current_user=USER, project_id=7, protocol_id=2,
                                         worker_runner=child)

    assert child.requests == [{"projectId": 7, "protocolId": 2, "protocolDbId": 902}]
    assert summary["lines"] == ["*12* micrographs", "7"]
    assert summary["hasWarnings"] is True
    assert list(summary["objects"]) == ["41"]


@pytest.mark.parametrize("mapper,code", [(Mapper(visible=False), "unauthorized"), (Mapper(exists=False), "not_found")])
def test_no_child_starts_for_a_protocol_out_of_reach(mapper, code):
    child = Worker({"lines": []})
    with pytest.raises(service.ProtocolSummaryError) as error:
        service.getProtocolSummary(mapper=mapper, current_user=USER, project_id=7, protocol_id=2,
                                   worker_runner=child)
    assert error.value.code == code
    assert child.requests == []


def test_a_reply_without_lines_is_refused():
    with pytest.raises(service.ProtocolSummaryError) as error:
        service.getProtocolSummary(mapper=Mapper(), current_user=USER, project_id=7, protocol_id=2,
                                   worker_runner=Worker({"objects": {}}))
    assert error.value.code == "invalid_reply"


# The child -----------------------------------------------------------------------------------------

class Obj:
    def __init__(self, objId, className, label=""):
        self.objId, self.className, self.label = objId, className, label

    def getObjId(self):
        return self.objId

    def getClassName(self):
        return self.className

    def getObjLabel(self):
        return self.label


class Pointer:
    def __init__(self, producer, extended, pointed):
        self.producer, self.extended, self.pointed = producer, extended, pointed

    def getObjValue(self):
        return self.producer

    def hasExtended(self):
        return bool(self.extended)

    def getExtended(self):
        return self.extended

    def get(self):
        return self.pointed


@pytest.fixture
def loaded(monkeypatch):
    """The child loading the given protocol, with its inputs and outputs already there."""
    holder = {}

    @contextmanager
    def load(request):
        yield None, None, holder["protocol"]

    monkeypatch.setattr(worker, "loadRuntimeProtocol", load)
    monkeypatch.setattr(worker, "restoreProtocolInputs", lambda *args: None)
    monkeypatch.setattr(worker, "attachStoredOutputs", lambda *args: [])
    return holder


REQUEST = {"projectId": 7, "protocolId": 5, "protocolDbId": 905}


def test_the_child_gives_the_desktop_summary_with_comment_error_and_warnings(loaded):
    from pyworkflow.protocol import Protocol

    class CountingProtocol(Protocol):
        def _summary(self):
            return ["*12* micrographs imported"]

    protocol = CountingProtocol()
    protocol.setObjComment("Second try")
    protocol.getError().set("Out of memory")
    protocol.addSummaryWarning("*Missing run data*")
    loaded["protocol"] = protocol

    reply = worker._run(REQUEST)

    assert reply["lines"] == ["*12* micrographs imported", "", "*COMMENTS:* ", "Second try",
                              "", "*ERROR:*", "Out of memory", "", "*WARNINGS:*", "*Missing run data*"]
    assert reply["hasWarnings"] is True


def test_the_child_tells_which_protocol_output_each_linked_object_is(loaded):
    producer = Obj(2, "ProtImportMovies")
    movies = Obj(17, "SetOfMovies", "Movies of grid 3")
    micrographs = Obj(41, "SetOfMicrographs")

    class Protocol:
        def getObjId(self):
            return 5

        def iterOutputAttributes(self):
            return iter([("outputMicrographs", micrographs)])

        def iterInputAttributes(self):
            # An item of a set (outputCoordinates.12) is no output of its own
            return iter([("inputMovies", Pointer(producer, "outputMovies", movies)),
                         ("inputItem", Pointer(producer, "outputCoordinates.12", Obj(99, "Coordinate")))])

        def checkSummaryWarnings(self):
            pass

        def summary(self):
            return ["From [[sci-open:17][outputMovies]]"]

        def hasSummaryWarnings(self):
            return False

    loaded["protocol"] = Protocol()

    assert worker._run(REQUEST)["objects"] == {
        "41": {"protocolId": 5, "outputName": "outputMicrographs", "className": "SetOfMicrographs",
               "label": "outputMicrographs"},
        "17": {"protocolId": 2, "outputName": "outputMovies", "className": "SetOfMovies",
               "label": "Movies of grid 3"},
    }


def test_the_child_refuses_an_unexpected_request():
    assert worker._valid_request(REQUEST)
    assert not worker._valid_request(dict(REQUEST, action="x"))
    assert not worker._valid_request(dict(REQUEST, projectId="7"))


# Kept summaries ------------------------------------------------------------------------------------

class FingerprintDb:
    """The database as the fingerprint query sees it: one text per protocol."""

    def __init__(self):
        self.fingerprints = {}

    def fetchOne(self, query, params):
        value = self.fingerprints.get((params["projectId"], params["protocolId"]))
        return {"fingerprint": value} if value is not None else None


class KeepingMapper(Mapper):
    def __init__(self):
        super().__init__()
        self.db = FingerprintDb()


@pytest.fixture
def keeping():
    service._cache.clear()
    mapper = KeepingMapper()
    mapper.db.fingerprints[(7, "2")] = "running|10:00|a"
    yield mapper
    service._cache.clear()


def test_an_unchanged_protocol_answers_its_kept_summary_without_a_child(keeping):
    child = Worker({"lines": ["*40* movies"]})
    ask = lambda: service.getProtocolSummary(mapper=keeping, current_user=USER, project_id=7, protocol_id=2,
                                             worker_runner=child)

    assert ask()["lines"] == ["*40* movies"]
    assert ask()["lines"] == ["*40* movies"]
    assert len(child.requests) == 1

    # New items, a new status, a new comment: a new fingerprint, computed again
    keeping.db.fingerprints[(7, "2")] = "running|10:05|b"
    child.reply = {"lines": ["*52* movies"]}
    assert ask()["lines"] == ["*52* movies"]
    assert len(child.requests) == 2


def test_a_summary_is_computed_again_after_a_while(keeping, monkeypatch):
    child = Worker({"lines": ["Done"]})
    ask = lambda: service.getProtocolSummary(mapper=keeping, current_user=USER, project_id=7, protocol_id=2,
                                             worker_runner=child)
    now = [1000.0]
    monkeypatch.setattr(service.time, "monotonic", lambda: now[0])

    ask()
    now[0] += service._CACHE_SECONDS + 1
    ask()

    assert len(child.requests) == 2


def test_without_a_fingerprint_nothing_is_kept(keeping):
    keeping.db.fingerprints.clear()
    child = Worker({"lines": ["Done"]})
    for _ in range(2):
        service.getProtocolSummary(mapper=keeping, current_user=USER, project_id=7, protocol_id=2,
                                   worker_runner=child)
    assert len(child.requests) == 2


def test_two_readers_of_the_same_protocol_start_one_child(keeping):
    import threading

    started, release = threading.Event(), threading.Event()
    calls = []

    def slowChild(request, timeout):
        calls.append(request)
        started.set()
        release.wait(5)
        return {"lines": ["Done"]}

    answers = []
    readers = [threading.Thread(target=lambda: answers.append(service.getProtocolSummary(
        mapper=keeping, current_user=USER, project_id=7, protocol_id=2, worker_runner=slowChild)))
        for _ in range(2)]
    readers[0].start()
    started.wait(5)
    readers[1].start()
    release.set()
    for reader in readers:
        reader.join(5)

    assert len(calls) == 1
    assert [answer["lines"] for answer in answers] == [["Done"], ["Done"]]


def test_the_cache_keeps_the_most_recent_summaries():
    cache = service._SummaryCache(size=2)
    for protocolId in (1, 2, 3):
        cache.put((7, protocolId), "f", {"lines": [str(protocolId)]})
    assert cache.get((7, 1), "f") is None
    assert cache.get((7, 3), "f") == {"lines": ["3"]}
    assert cache.get((7, 3), "other") is None
