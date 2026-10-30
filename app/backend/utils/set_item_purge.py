"""Removing the items of deleted Sets in the background.

Deleting a Set removes its row and its tables at once; its items, possibly
millions, are queued and removed here in small batches, so a Reset, a Restart
or a delete does not wait for them and no long transaction holds the tables.
Whatever a stopped server left queued is removed after the next start.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from app.backend.mapper.set_item_purge_mapper import SetItemPurgePostgresqlMapper

logger = logging.getLogger(__name__)

BATCH_SIZE = 20000
# The background purge rests between batches: millions of deletions in a row write the change log
# faster than checkpoints recycle it, and on a nearly full disk the database stopped for lack of space
BACKGROUND_BATCH_SIZE = 5000
BACKGROUND_PAUSE_SECONDS = 0.2
PURGES_PER_READ = 100
# Sets deleted by other processes (protocol workers) are noticed within this time
POLL_SECONDS = 60.0

_wakeUp = threading.Event()
_startLock = threading.Lock()
_thread: Optional[threading.Thread] = None


def purgePendingSetItems(db, batchSize: int = BATCH_SIZE, pauseSeconds: float = 0.0) -> int:
    """Remove every queued item; returns how many. Does nothing while another process purges.

    pauseSeconds is waited after every full batch, to spread the writes of a large purge."""
    mapper = SetItemPurgePostgresqlMapper(db)
    if not mapper.tryLock():
        return 0
    removed = 0
    try:
        while True:
            purges = mapper.listPurges(PURGES_PER_READ)
            if not purges:
                return removed
            for purge in purges:
                while True:
                    count = mapper.deleteItemsBatch(purge, batchSize)
                    removed += count
                    if count < batchSize:
                        break
                    if pauseSeconds > 0:
                        time.sleep(pauseSeconds)
                mapper.finishPurge(purge["id"])
    finally:
        mapper.unlock()


def requestSetItemPurge() -> None:
    """Purge now instead of at the next poll (a no-op where the purge thread was not started)."""
    _wakeUp.set()


def startSetItemPurge(openDb: Callable[[], object]) -> None:
    """Start the purge thread of this process, once; openDb gives it a connection of its own."""
    global _thread
    with _startLock:
        if _thread is not None:
            return
        _thread = threading.Thread(target=_run, args=(openDb,), name="set-item-purge", daemon=True)
        _thread.start()


def _run(openDb: Callable[[], object]) -> None:
    db = None
    while True:
        # Cleared before purging, so a request arriving meanwhile purges again
        _wakeUp.clear()
        try:
            if db is None:
                db = openDb()
            removed = purgePendingSetItems(db, BACKGROUND_BATCH_SIZE, BACKGROUND_PAUSE_SECONDS)
            if removed:
                logger.info("Removed %s items of deleted Sets", removed)
        except Exception:
            logger.warning("Could not remove the items of deleted Sets; trying again later", exc_info=True)
            try:
                db.close()
            except Exception:
                pass
            db = None
        _wakeUp.wait(POLL_SECONDS)
