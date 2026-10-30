"""The background purge of deleted Sets' items rests between full batches."""
# Loaded the way the server loads it: the purge module on its own is part of an import cycle
import app.backend.mapper.postgresql  # noqa: F401
from app.backend.utils import set_item_purge


class _FakeMapper:
    """One queued Set with `items` items; records what is deleted."""

    def __init__(self, items: int):
        self.items = items
        self.purges = [{"id": 1, "setId": 5, "tableId": None}]
        self.batches = []

    def tryLock(self):
        return True

    def unlock(self):
        pass

    def listPurges(self, limit):
        return list(self.purges)

    def deleteItemsBatch(self, purge, batchSize):
        count = min(batchSize, self.items)
        self.items -= count
        self.batches.append(count)
        return count

    def finishPurge(self, purgeId):
        self.purges = []


def _purge(monkeypatch, items, **kwargs):
    mapper = _FakeMapper(items)
    sleeps = []
    monkeypatch.setattr(set_item_purge, "SetItemPurgePostgresqlMapper", lambda db: mapper)
    monkeypatch.setattr(set_item_purge.time, "sleep", sleeps.append)
    removed = set_item_purge.purgePendingSetItems(object(), **kwargs)
    return removed, mapper.batches, sleeps


def test_PausesAfterEveryFullBatchOnly(monkeypatch):
    removed, batches, sleeps = _purge(monkeypatch, 25, batchSize=10, pauseSeconds=0.2)

    assert removed == 25
    assert batches == [10, 10, 5]
    assert sleeps == [0.2, 0.2]


def test_DoesNotPauseByDefault(monkeypatch):
    removed, _, sleeps = _purge(monkeypatch, 25, batchSize=10)

    assert removed == 25
    assert sleeps == []


def test_TheBackgroundThreadUsesSmallPausedBatches(monkeypatch):
    calls = []
    monkeypatch.setattr(set_item_purge, "purgePendingSetItems",
                        lambda db, *args: calls.append(args) or 0)

    class _Stop(Exception):
        pass

    def stopWaiting(_seconds):
        raise _Stop

    monkeypatch.setattr(set_item_purge._wakeUp, "wait", stopWaiting)
    try:
        set_item_purge._run(lambda: object())
    except _Stop:
        pass

    assert calls == [(set_item_purge.BACKGROUND_BATCH_SIZE, set_item_purge.BACKGROUND_PAUSE_SECONDS)]
    assert set_item_purge.BACKGROUND_PAUSE_SECONDS > 0
