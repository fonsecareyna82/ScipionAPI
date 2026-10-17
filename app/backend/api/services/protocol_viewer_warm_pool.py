"""API-side handle of the warm viewer worker (protocol_viewer_warm_worker).

One warm process per API process. Requests are forked from it; when it is
missing, broken or stale (plugins, environment or code changed) it is
restarted, and callers fall back to a one-shot worker process if it cannot
run the request at all.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import signal
import subprocess
import sys
import threading
import uuid
from typing import Dict, Optional

logger = logging.getLogger(__name__)

WARM_WORKER_MODULE = 'app.backend.api.services.protocol_viewer_warm_worker'
WARM_SWITCH = 'SCIPION_PROTOCOL_VIEWER_WARM_WORKER'
_START_TIMEOUT = 180
_FORK_TIMEOUT = 15
_KILL_GRACE = 5


class WarmWorkerTimeout(RuntimeError):
    """The forked worker did not finish in time and was killed."""


def warmWorkerEnabled() -> bool:
    return os.environ.get(WARM_SWITCH, '1').strip().lower() not in ('0', 'false', 'no', 'off')


def currentRevision() -> str:
    """Plugins and environment revisions; a change makes the warm process stale."""
    try:
        from app.backend.api.services.scipion_domain_refresh_service import (
            _readEnvironmentRevision, _readPluginsRevision,
        )
        return '%s:%s' % (_readPluginsRevision(), _readEnvironmentRevision())
    except Exception:
        return '0:0'


class _WarmProcess:
    def __init__(self, env: Dict[str, str], revision: str):
        self.revision = revision
        self.envKey = _envKey(env)
        self._writeLock = threading.Lock()
        self._pending: Dict[str, queue.Queue] = {}
        self._ready = threading.Event()
        self.alive = True
        env = dict(env, SCIPION_VIEWER_WARM_REVISION=revision)
        self.process = subprocess.Popen(
            [sys.executable, '-m', WARM_WORKER_MODULE],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, start_new_session=True, text=True, bufsize=1,
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get('ready'):
                self._ready.set()
                continue
            target = self._pending.get(message.get('id'))
            if target is not None:
                target.put(message)
        self.alive = False
        self._ready.set()
        for target in list(self._pending.values()):
            target.put({'dead': True})

    def waitReady(self) -> bool:
        self._ready.wait(_START_TIMEOUT)
        return self.alive and self._ready.is_set()

    def run(self, module: str, paths: Dict[str, str], timeout: float) -> Optional[int]:
        """Exit code of the forked worker, or None if this process cannot run it."""
        requestId = uuid.uuid4().hex
        replies: queue.Queue = queue.Queue()
        self._pending[requestId] = replies
        try:
            command = dict(paths, id=requestId, module=module, revision=self.revision)
            try:
                with self._writeLock:
                    self.process.stdin.write(json.dumps(command) + '\n')
                    self.process.stdin.flush()
            except (OSError, ValueError):
                self.alive = False
                return None
            try:
                started = replies.get(timeout=_FORK_TIMEOUT)
            except queue.Empty:
                return None
            if 'pid' not in started:
                if started.get('stale') or started.get('dead'):
                    self.alive = False
                return None
            pid = started['pid']
            try:
                finished = replies.get(timeout=timeout)
            except queue.Empty:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                try:
                    replies.get(timeout=_KILL_GRACE)
                except queue.Empty:
                    pass
                raise WarmWorkerTimeout()
            if finished.get('dead'):
                return None
            return int(finished.get('exit', 1))
        finally:
            self._pending.pop(requestId, None)

    def stop(self):
        self.alive = False
        try:
            self.process.stdin.close()
        except Exception:
            pass
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass


def _envKey(env: Dict[str, str]) -> str:
    return json.dumps(sorted(env.items()))


_lock = threading.Lock()
_warm: Optional[_WarmProcess] = None


def _getWarmProcess(env: Dict[str, str]) -> Optional[_WarmProcess]:
    global _warm
    revision = currentRevision()
    with _lock:
        if (_warm is not None and _warm.alive and _warm.revision == revision
                and _warm.envKey == _envKey(env)):
            return _warm
        if _warm is not None:
            _warm.stop()
        try:
            _warm = _WarmProcess(env, revision)
        except OSError:
            _warm = None
            return None
        warm = _warm
    return warm if warm.waitReady() else None


def runInWarmWorker(module: str, paths: Dict[str, str], env: Dict[str, str],
                    timeout: float) -> Optional[int]:
    """Run ``module`` forked from the warm process; None means "use a cold worker".

    A stale warm process is restarted once before giving up.
    """
    if not warmWorkerEnabled():
        return None
    for _attempt in range(2):
        warm = _getWarmProcess(env)
        if warm is None:
            return None
        code = warm.run(module, paths, timeout)
        if code is not None:
            return code
        if warm.alive:
            return None  # Not a staleness problem; let a cold worker try.
    return None


def prestartWarmWorker(env: Dict[str, str]) -> None:
    """Warm up in the background, e.g. while the user looks at the viewers."""
    if not warmWorkerEnabled():
        return
    threading.Thread(target=_getWarmProcess, args=(env,), daemon=True).start()


def stopWarmWorker():
    global _warm
    with _lock:
        if _warm is not None:
            _warm.stop()
            _warm = None
