"""Renders missing thumbnails in worker processes, never in the request.

Requests only check files (thumbnails.store). The outputs without a thumbnail
are grouped per project into jobs of a few outputs (each job loads the
project once) and run by several worker processes at a time. An output
already queued is not queued again; a request may wait a little for it.
"""
from __future__ import annotations

import logging
import multiprocessing
import os
import threading
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures import wait as waitFutures
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Outputs drawn per job: one project load serves them all.
JOB_SIZE = 8

_executor: Optional[ProcessPoolExecutor] = None
_executorLock = threading.Lock()
_pending: Dict[str, Future] = {}
_pendingLock = threading.Lock()


def workerCount() -> int:
    configured = os.environ.get("SCIPION_THUMBNAIL_WORKERS")
    if configured:
        try:
            return max(1, int(configured))
        except ValueError:
            pass
    return max(2, min(4, (os.cpu_count() or 2) // 2))


def _getExecutor() -> ProcessPoolExecutor:
    global _executor
    if _executor is None:
        with _executorLock:
            if _executor is None:
                _executor = ProcessPoolExecutor(
                    max_workers=workerCount(),
                    mp_context=multiprocessing.get_context("spawn"),
                )
    return _executor


def _submit(job: dict) -> Future:
    from app.backend.runtime.preview_process_executor import _runPreviewJob

    return _getExecutor().submit(_runPreviewJob, job)


def schedule(projectId: int, userId: int, items: List[dict]) -> Dict[str, Future]:
    """Queue the items (protocolId, outputName, size, path) that are not queued yet.

    Returns the future of every item, queued now or before.
    """
    futures: Dict[str, Future] = {}
    fresh: List[dict] = []
    with _pendingLock:
        for item in items:
            path = str(item["path"])
            existing = _pending.get(path)
            if existing is not None and not existing.done():
                futures[path] = existing
            elif path not in futures:
                fresh.append(item)
                futures[path] = None  # filled below
        for start in range(0, len(fresh), JOB_SIZE):
            chunk = fresh[start:start + JOB_SIZE]
            try:
                future = _submit({
                    "operation": "render-thumbnails",
                    "projectId": int(projectId),
                    "userId": int(userId),
                    "items": chunk,
                })
            except Exception:
                logger.exception("Could not queue thumbnails. projectId=%s", projectId)
                for item in chunk:
                    futures.pop(str(item["path"]), None)
                continue
            for item in chunk:
                path = str(item["path"])
                _pending[path] = future
                futures[path] = future
                future.add_done_callback(lambda done, path=path: _forget(path, done))
    return {path: future for path, future in futures.items() if future is not None}


def _forget(path: str, future: Future) -> None:
    with _pendingLock:
        if _pending.get(path) is future:
            _pending.pop(path, None)
    error = future.exception() if not future.cancelled() else None
    if error is not None:
        logger.warning("Thumbnail job failed for %s: %s", path, error)
    elif not future.cancelled():
        result = future.result()
        if isinstance(result, dict) and not result.get("ok", True):
            logger.warning("Thumbnail job failed for %s: %s", path, result.get("detail"))


def waitFor(futures: List[Future], timeout: float) -> bool:
    """Wait up to timeout seconds for the futures; True when all are done."""
    if not futures:
        return True
    _, notDone = waitFutures(futures, timeout=max(0.0, timeout))
    return not notDone
