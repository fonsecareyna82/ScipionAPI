"""Cleaning a machine's scratch: what protocols left on its fast local disk and nobody will use.

Scipion makes each protocol's temporary folder on the scratch (SCIPION_SCRATCH) as
``<project folder name>_<protocol id, 6 digits>_<protocol class>``. A protocol that finishes well removes it; one
that fails keeps it on purpose (to look into the failure); one killed, or whose project or protocol was deleted,
leaves it for ever. Every protocol worker cleans its own machine's scratch (only it sees that disk), every
CLEAN_EVERY_SECONDS and when asked (``requestClean``).

A folder is removed when its project is gone, its protocol is gone, or its protocol is not running and the folder
was not touched for GRACE_SECONDS (a recent failure stays to be looked into). Never removed: a running, launched
or scheduled protocol's folder; anything touched in the last RECENT_SECONDS (a protocol starting); anything that
is not named as Scipion names them (the disk may hold others' files). Two workers of a machine never clean at
once (a lock on the scratch).
"""
from __future__ import annotations

import fcntl
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

CLEAN_EVERY_SECONDS = 3600.0
GRACE_SECONDS = 24 * 3600.0
RECENT_SECONDS = 3600.0
LIVE_STATUSES = {"launched", "running", "scheduled"}
LOCK_NAME = ".scipionweb-clean.lock"
# <project folder name>_<protocol id>_<protocol class>: the project's name may hold "_"
FOLDER = re.compile(r"^(?P<project>.+)_(?P<id>\d{6,})_(?P<cls>[A-Za-z_][A-Za-z0-9_]*)$")

_wakeUp = threading.Event()
_startLock = threading.Lock()
_thread: Optional[threading.Thread] = None
_last: Dict[str, Any] = {}


def parseFolder(name: str) -> Optional[Tuple[str, int, str]]:
    match = FOLDER.match(name)
    if not match:
        return None
    return match.group("project"), int(match.group("id")), match.group("cls")


def plan(entries: Iterable[Dict[str, Any]], protocols: Iterable[Dict[str, Any]], now: float,
         grace: float = GRACE_SECONDS, recent: float = RECENT_SECONDS) -> List[Dict[str, Any]]:
    """Which scratch folders go, and why. entries: {name, mtime}; protocols: the protocols of the projects named
    by those folders ({shortName, protocolId, protocolClassName, status}; a project without protocols comes with
    protocolId None)."""
    projects = set()
    byKey: Dict[Tuple[str, int, str], List[str]] = {}
    for protocol in protocols:
        projects.add(protocol["shortName"])
        if protocol.get("protocolId") is None:
            continue
        try:
            key = (protocol["shortName"], int(protocol["protocolId"]), str(protocol.get("protocolClassName") or ""))
        except (TypeError, ValueError):
            continue
        byKey.setdefault(key, []).append(str(protocol.get("status") or ""))
    removed = []
    for entry in entries:
        parsed = parseFolder(entry["name"])
        if parsed is None or now - float(entry["mtime"]) < recent:
            continue
        project, protocolId, className = parsed
        statuses = byKey.get((project, protocolId, className))
        if project not in projects:
            reason = "its project is gone"
        elif statuses is None:
            reason = "its protocol is gone"
        elif LIVE_STATUSES & set(statuses):
            continue
        elif now - float(entry["mtime"]) >= grace:
            reason = "its protocol is not running"
        else:
            continue
        removed.append({"name": entry["name"], "reason": reason})
    return removed


def _size(path: Path) -> int:
    total = 0
    for folder, _, files in os.walk(str(path)):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                continue
    return total


def _newest(path: Path) -> float:
    """When anything in the folder last changed (a protocol writing deep inside counts)."""
    newest = path.stat().st_mtime
    for folder, folders, files in os.walk(str(path)):
        for name in folders + files:
            try:
                newest = max(newest, os.lstat(os.path.join(folder, name)).st_mtime)
            except OSError:
                continue
    return newest


def cleanScratch(db, scratch: str, now: Optional[float] = None,
                 protocolsOf: Optional[Callable[[List[str]], List[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """Clean a scratch once; answers what was removed, the space freed and what failed."""
    now = time.time() if now is None else now
    root = Path(scratch)
    report: Dict[str, Any] = {"at": datetime.fromtimestamp(now, timezone.utc).isoformat(), "removed": [],
                              "freedBytes": 0, "kept": 0, "errors": []}
    if not root.is_dir():
        report["errors"].append("The scratch folder does not exist")
        return report
    with open(root / LOCK_NAME, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            report["errors"].append("Another worker of this machine is cleaning it")
            return report
        entries = []
        for child in root.iterdir():
            if child.name == LOCK_NAME or child.is_symlink() or not child.is_dir() or parseFolder(child.name) is None:
                continue
            try:
                entries.append({"name": child.name, "mtime": _newest(child)})
            except OSError:
                continue
        names = sorted({parseFolder(entry["name"])[0] for entry in entries})
        if protocolsOf is None:
            from app.backend.mapper.scratch_mapper import ScratchPostgresqlMapper

            protocolsOf = ScratchPostgresqlMapper(db).protocolsOfProjects
        protocols = protocolsOf(names) if names else []
        doomed = plan(entries, protocols, now)
        for item in doomed:
            path = root / item["name"]
            try:
                size = _size(path)
                shutil.rmtree(path)
                report["removed"].append(dict(item, bytes=size))
                report["freedBytes"] += size
            except OSError as error:
                report["errors"].append("%s: %s" % (item["name"], error))
        report["kept"] = len(entries) - len(report["removed"])
    if report["removed"]:
        logger.info("Scratch %s cleaned: %d folder(s), %d bytes", scratch, len(report["removed"]), report["freedBytes"])
    return report


def lastReport() -> Dict[str, Any]:
    """What the last cleaning of this machine's scratch did (empty before the first)."""
    return dict(_last)


def requestClean() -> None:
    _wakeUp.set()


def startScratchCleaner(openDb: Callable[[], object]) -> None:
    """Start this worker's cleaner thread, once (it idles while the machine has no scratch)."""
    global _thread
    with _startLock:
        if _thread is not None:
            return
        _thread = threading.Thread(target=_run, args=(openDb,), name="scratch-cleaner", daemon=True)
        _thread.start()


def _run(openDb: Callable[[], object]) -> None:
    global _last
    while True:
        _wakeUp.clear()
        scratch = (os.environ.get("SCIPION_SCRATCH") or "").strip()
        if scratch:
            db = None
            try:
                db = openDb()
                _last = cleanScratch(db, scratch)
            except Exception as error:
                logger.warning("Could not clean the scratch %s", scratch, exc_info=True)
                _last = {"at": datetime.now(timezone.utc).isoformat(), "removed": [], "freedBytes": 0, "kept": 0,
                         "errors": [str(error)]}
            finally:
                if db is not None:
                    try:
                        db.rollback()
                        db.close()
                    except Exception:
                        pass
        _wakeUp.wait(CLEAN_EVERY_SECONDS)
