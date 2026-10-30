"""A protocol's summary (the desktop Summary tab), computed in a child process and kept while it holds.

The request is authorized here, before any plugin code runs; the child loads the project and the
protocol, runs ``summary()`` and answers its lines and the objects they link to. Loading the project is
most of the cost, so the answer is kept with a fingerprint of what the summary reads (the protocol, its
objects, its sets and its parents' sets: ``ProtocolSummaryMapper``). A read whose fingerprint has not
changed answers the kept summary with one query: a finished protocol is computed once, and polling a
running one computes again only when its data change.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Mapping, Optional, Tuple

from app.backend.api.services.protocol_viewer_dynamic_form_service import (
    DynamicProtocolViewerFormError, _run_worker,
)
from app.backend.mapper.protocol_summary_mapper import ProtocolSummaryMapper

_WORKER_MODULE = 'app.backend.api.services.protocol_summary_worker'
_REPLY_MARKER = b'__SCIPION_SUMMARY_JSON__:'
_MAX_REQUEST = 4096
_MAX_REPLY = 262144
_TIMEOUT = 60
_MAX_LINES = 400
_MAX_LINE = 4000
# Kept summaries: the most recent ones; one is computed again after a while anyway (a run folder that
# went missing, an updated plugin)
_CACHE_SIZE = 512
_CACHE_SECONDS = 3600


class _SummaryCache:
    """{(projectId, protocolId): (fingerprint, keptAt, summary)}, with one computation at a time per key."""

    def __init__(self, size: int = _CACHE_SIZE, seconds: float = _CACHE_SECONDS):
        self.size, self.seconds = size, seconds
        self._entries: "OrderedDict[Tuple[int, int], Tuple[str, float, dict]]" = OrderedDict()
        self._lock = threading.Lock()
        self._keyLocks: Dict[Tuple[int, int], threading.Lock] = {}

    def get(self, key, fingerprint: str) -> Optional[dict]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry[0] != fingerprint or time.monotonic() - entry[1] > self.seconds:
                return None
            self._entries.move_to_end(key)
            return entry[2]

    def put(self, key, fingerprint: str, summary: dict) -> None:
        with self._lock:
            self._entries[key] = (fingerprint, time.monotonic(), summary)
            self._entries.move_to_end(key)
            while len(self._entries) > self.size:
                oldest, _ = self._entries.popitem(last=False)
                self._keyLocks.pop(oldest, None)

    def keyLock(self, key) -> threading.Lock:
        with self._lock:
            return self._keyLocks.setdefault(key, threading.Lock())

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._keyLocks.clear()


_cache = _SummaryCache()


class ProtocolSummaryError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _int_id(value) -> bool:
    return type(value) is int and 0 < value <= 2147483647


def _objects(value) -> dict:
    """The linked objects of the reply, each with an int protocolId and a valid output name."""
    if not isinstance(value, dict):
        return {}
    objects = {}
    for objId, item in value.items():
        if not (isinstance(objId, str) and objId.isdigit() and isinstance(item, dict)):
            continue
        name = item.get('outputName')
        if not (_int_id(item.get('protocolId')) and isinstance(name, str) and name.isidentifier()):
            continue
        objects[objId] = {'protocolId': item['protocolId'], 'outputName': name,
                          'className': str(item.get('className') or ''), 'label': str(item.get('label') or name)}
    return objects


def getProtocolSummary(*, mapper: Any, current_user: Mapping[str, Any], project_id: int, protocol_id: int,
                       worker_runner=None) -> dict:
    """{lines, objects, hasWarnings} of the protocol, for a user who may see its project."""
    if not (_int_id(project_id) and _int_id(protocol_id)):
        raise ProtocolSummaryError('invalid_identity')
    if (not isinstance(current_user, Mapping) or not _int_id(current_user.get('id'))
            or mapper is None or not mapper.getProject(projectId=project_id, userId=current_user['id'])):
        raise ProtocolSummaryError('unauthorized')
    row = mapper.getProjectProtocolByProtocolId(projectId=project_id, protocolId=protocol_id)
    if not isinstance(row, dict):
        raise ProtocolSummaryError('not_found')
    key = (project_id, protocol_id)
    fingerprint = _fingerprint(mapper, project_id, protocol_id)
    if fingerprint is not None:
        kept = _cache.get(key, fingerprint)
        if kept is not None:
            return kept
    # Two readers of the same protocol (two tabs polling) compute it once
    with _cache.keyLock(key):
        if fingerprint is not None:
            kept = _cache.get(key, fingerprint)
            if kept is not None:
                return kept
        summary = _compute(row, project_id, protocol_id, worker_runner)
        if fingerprint is not None:
            _cache.put(key, fingerprint, summary)
        return summary


def _fingerprint(mapper: Any, project_id: int, protocol_id: int) -> Optional[str]:
    """None when it cannot be read: the summary is then computed and not kept."""
    try:
        return ProtocolSummaryMapper(mapper.db).getFingerprint(project_id, protocol_id)
    except Exception:
        return None


def _compute(row: dict, project_id: int, protocol_id: int, worker_runner) -> dict:
    request = {'projectId': project_id, 'protocolId': protocol_id, 'protocolDbId': int(row['id'])}
    try:
        if worker_runner is not None:
            reply = worker_runner(request, _TIMEOUT)
        else:
            reply = _run_worker(request, _TIMEOUT, module=_WORKER_MODULE, marker=_REPLY_MARKER,
                                max_request=_MAX_REQUEST, max_reply=_MAX_REPLY)
    except DynamicProtocolViewerFormError as exc:
        raise ProtocolSummaryError(exc.code) from exc
    lines = reply.get('lines') if isinstance(reply, dict) else None
    if not isinstance(lines, list):
        raise ProtocolSummaryError('invalid_reply')
    return {
        'lines': [str(line)[:_MAX_LINE] for line in lines][:_MAX_LINES],
        'objects': _objects(reply.get('objects')),
        'hasWarnings': bool(reply.get('hasWarnings')),
    }
