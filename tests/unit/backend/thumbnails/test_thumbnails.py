from concurrent.futures import Future

import pytest

from app.backend.thumbnails import catalog, scheduler, store
from app.backend.thumbnails import service as thumbnailService


class FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def fetchAll(self, query, params):
        return self.rows


class FakeMapper:
    def __init__(self, rows):
        self.db = FakeDb(rows)


PROTOCOL_ROWS = [
    {"id": 1, "protocolId": "10", "protocolClassName": "ProtImportMicrographs", "status": "finished",
     "params": {"_objLabel": "import mics"}},
    {"id": 2, "protocolId": "20", "protocolClassName": "ProtCTFFind", "status": "running", "params": {}},
    {"id": 3, "protocolId": "30", "protocolClassName": "ProtSomething", "status": "failed", "params": {}},
]

SUMMARIES = {
    "10": {"outputMicrographs": {"className": "SetOfMicrographs", "itemsCount": 20, "maxItemId": 20,
                                 "updatedAt": "2026-10-18T10:00:00"}},
    "20": {"outputCTF": {"className": "SetOfCTF", "itemsCount": 5, "maxItemId": 5, "updatedAt": "t1"},
           "outputTmp": {"className": "SetOfCTF", "itemsCount": 5, "updatedAt": "t1"}},
    "30": {"outputVolume": {"className": "Volume", "itemsCount": None, "updatedAt": "t2"}},
}


@pytest.fixture
def summaries(monkeypatch):
    from app.backend.runtime import protocol_output_persistence_service as persistence

    current = {key: {name: dict(value) for name, value in outputs.items()} for key, outputs in SUMMARIES.items()}
    monkeypatch.setattr(
        persistence.RuntimeProtocolOutputPersistenceService,
        "loadPersistedOutputSummariesByProtocolId",
        lambda self, mapper, projectId: current,
    )
    return current


def test_TheCatalogListsTheShownOutputsBestFirst(summaries):
    items = catalog.loadProjectThumbnailCatalog(FakeMapper(PROTOCOL_ROWS), 1)

    assert [(item.protocolId, item.outputName) for item in items] == [
        ("10", "outputMicrographs"), ("30", "outputVolume"), ("20", "outputCTF"),
    ]
    assert items[0].protocolLabel == "import mics" or items[0].protocolLabel
    assert {item.protocolStatus for item in items} == {"finished", "running", "failed"}


def test_TheSignatureFollowsTheOutputNotTheProtocol(summaries):
    first = catalog.loadProjectThumbnailCatalog(FakeMapper(PROTOCOL_ROWS), 1)[0].signature
    summaries["10"]["outputMicrographs"]["itemsCount"] = 21
    grown = catalog.loadProjectThumbnailCatalog(FakeMapper(PROTOCOL_ROWS), 1)[0].signature
    rows = [dict(row, status="running") for row in PROTOCOL_ROWS]
    sameOutput = catalog.loadProjectThumbnailCatalog(FakeMapper(rows), 1)[0].signature

    assert grown != first
    assert sameOutput == grown


def test_TheCardKeepsTheBestProtocolsAndLeavesOutFailedOnes(summaries):
    groups = catalog.selectProjectCardOutputs(catalog.loadProjectThumbnailCatalog(FakeMapper(PROTOCOL_ROWS), 1), 6, 1)

    assert [group[0].protocolId for group in groups] == ["10", "20"]
    assert all(len(group) == 1 for group in groups)


def test_TheStoreKeepsOneSignaturePerOutputAndSize(tmp_path):
    old = store.thumbnailPath(str(tmp_path), "10", "outputMicrographs", 256, "aaa")
    store.writeImage(old, b"old")
    otherSize = store.thumbnailPath(str(tmp_path), "10", "outputMicrographs", 512, "aaa")
    store.writeImage(otherSize, b"big")
    new = store.thumbnailPath(str(tmp_path), "10", "outputMicrographs", 256, "bbb")
    store.writeImage(new, b"new")

    assert store.isReady(new) and not old.exists() and store.isReady(otherSize)
    store.writeMissing(new, "Output not found")
    assert store.isMissing(new) and not new.exists() and store.readMissingReason(new) == "Output not found"
    assert store.snapSize(200) == 256 and store.snapSize(5000) == 1024 and store.snapSize(100) == 192


def test_TheSchedulerQueuesEachOutputOnce(monkeypatch):
    submitted = []

    def submit(job):
        submitted.append(job)
        return Future()

    monkeypatch.setattr(scheduler, "_submit", submit)
    monkeypatch.setattr(scheduler, "_pending", {})
    items = [{"protocolId": "10", "outputName": f"o{index}", "size": 256, "path": f"/tmp/x{index}"}
             for index in range(10)]

    first = scheduler.schedule(1, 7, items)
    again = scheduler.schedule(1, 7, items[:3])

    assert [len(job["items"]) for job in submitted] == [8, 2]
    assert submitted[0]["operation"] == "render-thumbnails" and submitted[0]["userId"] == 7
    assert set(again) == {"/tmp/x0", "/tmp/x1", "/tmp/x2"}
    assert again["/tmp/x0"] is first["/tmp/x0"]
    first["/tmp/x0"].set_result([])
    assert "/tmp/x0" not in scheduler._pending


def test_TheListShowsWhatIsReadyAndQueuesTheRest(summaries, monkeypatch, tmp_path):
    scheduled = []
    monkeypatch.setattr(scheduler, "schedule", lambda projectId, userId, items: scheduled.extend(items) or {})
    mapper = FakeMapper(PROTOCOL_ROWS)
    micrographs = catalog.loadProjectThumbnailCatalog(mapper, 1)[0]
    store.writeImage(store.thumbnailPath(str(tmp_path), "10", "outputMicrographs", 256, micrographs.signature), b"x")

    payload = thumbnailService.listProjectThumbnails(mapper, 1, str(tmp_path), 7, scope="card", size=200)

    assert payload["size"] == 256
    states = {output["outputName"]: output["state"] for group in payload["groups"] for output in group["outputs"]}
    assert states == {"outputMicrographs": "ready", "outputCTF": "pending"}
    assert [item["outputName"] for item in scheduled] == ["outputCTF"]
    url = payload["groups"][0]["outputs"][0]["url"]
    assert url == f"/projects/1/protocols/10/outputs/outputMicrographs/thumbnail-image?size=256&sig={micrographs.signature}"


def test_TheImageIsServedFromDiskOrDrawnFirst(summaries, monkeypatch, tmp_path):
    mapper = FakeMapper(PROTOCOL_ROWS)
    current = catalog.loadProjectThumbnailCatalog(mapper, 1)[0]
    path = store.thumbnailPath(str(tmp_path), "10", "outputMicrographs", 256, current.signature)

    def drawNow(projectId, userId, items):
        store.writeImage(path, b"RIFF....WEBP")
        done = Future()
        done.set_result([])
        return {str(path): done}

    monkeypatch.setattr(scheduler, "schedule", drawNow)
    drawn = thumbnailService.outputThumbnailImage(mapper, 1, str(tmp_path), 7, "10", "outputMicrographs", 256,
                                                  current.signature)
    assert drawn.headers["cache-control"] == thumbnailService.IMMUTABLE

    stale = thumbnailService.outputThumbnailImage(mapper, 1, str(tmp_path), 7, "10", "outputMicrographs", 256, "old")
    assert stale.headers["cache-control"] == "private, no-cache"


def test_TheImageIsPendingOrUnavailable(summaries, monkeypatch, tmp_path):
    mapper = FakeMapper(PROTOCOL_ROWS)
    monkeypatch.setattr(scheduler, "schedule", lambda *args: {})

    pending = thumbnailService.outputThumbnailImage(mapper, 1, str(tmp_path), 7, "20", "outputCTF", 256, None,
                                                    waitSeconds=0)
    assert pending.status_code == 202

    ctf = next(item for item in catalog.loadProjectThumbnailCatalog(mapper, 1) if item.outputName == "outputCTF")
    store.writeMissing(store.thumbnailPath(str(tmp_path), "20", "outputCTF", 256, ctf.signature), "Thumbnail not available")
    with pytest.raises(Exception) as error:
        thumbnailService.outputThumbnailImage(mapper, 1, str(tmp_path), 7, "20", "outputCTF", 256, None, waitSeconds=0)
    assert getattr(error.value, "status_code", None) == 404


def test_TheWorkerDrawsEachOutputOrMarksIt(monkeypatch, tmp_path):
    from app.backend.runtime import preview_process_executor as executor

    class FakeThumbnails:
        def renderProtocolOutputThumbnailBytes(self, protocolId, outputName, size):
            return (b"webp", None) if outputName == "good" else (None, "Output not found")

    monkeypatch.setattr(executor, "_thumbnailServiceForProject", lambda *args: FakeThumbnails())
    good = tmp_path / "good.webp"
    bad = tmp_path / "bad.webp"

    results = executor._runRenderThumbnailsJob(None, None, {
        "projectId": 1, "userId": 7,
        "items": [{"protocolId": "10", "outputName": "good", "size": 256, "path": str(good)},
                  {"protocolId": "10", "outputName": "bad", "size": 256, "path": str(bad)}],
    })

    assert [result["ready"] for result in results] == [True, False]
    assert good.read_bytes() == b"webp"
    assert store.isMissing(bad)
