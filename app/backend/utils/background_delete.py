"""Deleting large folders without making the user wait.

A folder is first renamed into a trash folder next to it (instant on the same
filesystem, so it disappears for everything else at once) and then removed by
a background thread. Whatever a crash leaves in a trash folder is removed the
next time something is moved there, or by purgeTrash at start-up.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional, Union

logger = logging.getLogger(__name__)

TRASH_FOLDER = ".scipion-trash"

# One thread: removing trees is disk bound, several at once only compete.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="background-delete")
_purgedTrash = set()
_purgedLock = threading.Lock()


def _remove(path: Path) -> None:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        logger.exception("Could not remove %s", path)


def _trashOf(path: Path) -> Path:
    return path.parent / TRASH_FOLDER


def moveToTrash(path: Union[str, Path], trashIn: Optional[Union[str, Path]] = None) -> Optional[Path]:
    """Rename the folder into a trash folder (next to it, or in trashIn); None when it cannot be moved."""
    path = Path(path)
    if not os.path.lexists(path):
        return None
    trash = Path(trashIn) / TRASH_FOLDER if trashIn is not None else _trashOf(path)
    try:
        trash.mkdir(exist_ok=True)
        target = trash / f"{path.name}.{uuid.uuid4().hex[:12]}"
        os.rename(path, target)
        return target
    except OSError:
        logger.warning("Could not move %s to the trash; it is removed in place", path, exc_info=True)
        return None


def removeInBackground(path: Union[str, Path], then: Optional[Callable[[], None]] = None) -> Future:
    """Remove the path in the background thread, then call ``then`` (in that thread)."""
    path = Path(path)

    def run():
        _remove(path)
        if then is not None:
            then()

    return _executor.submit(run)


def deleteInBackground(path: Union[str, Path], trashIn: Optional[Union[str, Path]] = None) -> Optional[Future]:
    """Make the folder disappear now and remove its contents in the background.

    When it cannot be renamed (e.g. another filesystem), it is removed in place
    in the background instead.
    """
    path = Path(path)
    if not os.path.lexists(path):
        return None
    moved = moveToTrash(path, trashIn)
    if moved is None:
        return removeInBackground(path)
    _purgeOnce(moved.parent, keep=moved)
    return removeInBackground(moved)


def purgeTrash(trash: Union[str, Path], keep: Optional[Path] = None) -> None:
    """Remove whatever an earlier run left in a trash folder (in the background)."""
    trash = Path(trash)
    try:
        leftovers = [entry for entry in trash.iterdir() if entry != keep]
    except OSError:
        return
    for entry in leftovers:
        removeInBackground(entry)


def _purgeOnce(trash: Path, keep: Path) -> None:
    with _purgedLock:
        if trash in _purgedTrash:
            return
        _purgedTrash.add(trash)
    purgeTrash(trash, keep=keep)


def waitForBackgroundDeletes(timeout: Optional[float] = None) -> None:
    """For tests: wait until every queued delete is done."""
    _executor.submit(lambda: None).result(timeout=timeout)
