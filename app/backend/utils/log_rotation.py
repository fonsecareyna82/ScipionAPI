"""Keep the service log files (app.log, celery.log, celery-protocols.log) from growing without end.

The CLI starts each service with its stdout and stderr appended to one log file, and names that file in
SCIPIONAPI_LOG_FILE. The service itself then looks at the file every few minutes: once it is bigger than
LOG_MAX_MB, its content is copied to <file>.1 (the older copies move to .2, .3 ...; LOG_BACKUPS are kept)
and the file is emptied in place. The file is not renamed, because the process keeps writing to the same
open file; it was opened for appending, so it goes on writing at the start of the emptied file.
"""

import fcntl
import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LOG_FILE_ENV = "SCIPIONAPI_LOG_FILE"
DEFAULT_MAX_MB = 100
DEFAULT_BACKUPS = 3
CHECK_EVERY_SECONDS = 300

_thread: Optional[threading.Thread] = None
_startLock = threading.Lock()


def _envInt(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def maxBytes() -> int:
    return _envInt("LOG_MAX_MB", DEFAULT_MAX_MB, 1) * 1024 * 1024


def backups() -> int:
    return _envInt("LOG_BACKUPS", DEFAULT_BACKUPS, 1)


def rotateIfBig(path, limit: Optional[int] = None, keep: Optional[int] = None) -> bool:
    """Copy the log to <path>.1 and empty it when it is bigger than the limit. True when it rotated."""
    path = Path(path)
    limit = maxBytes() if limit is None else limit
    keep = backups() if keep is None else keep
    try:
        if not path.is_file() or path.stat().st_size <= limit:
            return False
        with open(path, "r+b") as handle:
            # Several processes may share the file (the API's workers): only one rotates it at a time
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return False
            try:
                if os.fstat(handle.fileno()).st_size <= limit:
                    return False
                for index in range(keep - 1, 0, -1):
                    older = path.with_name("%s.%d" % (path.name, index))
                    if older.exists():
                        os.replace(older, path.with_name("%s.%d" % (path.name, index + 1)))
                with open(path.with_name(path.name + ".1"), "wb") as copy:
                    shutil.copyfileobj(handle, copy, 1024 * 1024)
                handle.truncate(0)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
        return True
    except OSError:
        logger.warning("Could not rotate the log %s", path, exc_info=True)
        return False


def startLogRotation() -> None:
    """Start, once per process, the thread that keeps this service's own log file small."""
    global _thread
    path = (os.environ.get(LOG_FILE_ENV) or "").strip()
    if not path:
        return
    with _startLock:
        if _thread is not None:
            return
        _thread = threading.Thread(target=_run, args=(path,), name="log-rotation", daemon=True)
        _thread.start()


def _run(path: str) -> None:
    stop = threading.Event()
    while True:
        rotateIfBig(path)
        stop.wait(CHECK_EVERY_SECONDS)
