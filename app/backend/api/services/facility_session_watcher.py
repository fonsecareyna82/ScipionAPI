"""Watching the folders of the sessions that acquire.

Every ``WATCH_SECONDS`` the watcher looks, for each DATA of a session acquiring, at its folder on the
microscope's offload (``<offloadPath>/<session>_DATA_NN``): the movies EPU writes in
``Images-Disc*/GridSquare_*/Data`` (SerialEM and tomography write them in the folder itself), how many and
how big, and when the first and the newest arrived. A folder of movies is read again only when its
modification time changed, and every one every ``FULL_SCAN_SECONDS`` (network mounts may not update it).
The first movie's metadata says what was acquired (``facility_acquisition_reader``); it is read once.

Only one server process watches at a time (an advisory lock); with facility mode off, nothing is watched.
"""
from __future__ import annotations

import datetime
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.backend.api.services.facility_acquisition_reader import metadataFileOf, readAcquisition
from app.backend.api.services.facility_service import facilityModeEnabled
from app.backend.mapper.facility_microscope_mapper import FacilityMicroscopePostgresqlMapper
from app.backend.mapper.facility_session_mapper import FacilitySessionPostgresqlMapper

logger = logging.getLogger(__name__)

WATCH_SECONDS = float(os.environ.get("SCIPIONWEB_FACILITY_WATCH_SECONDS") or 30)
FULL_SCAN_SECONDS = 600.0
# The names of movies: EPU's <image>_Fractions.<ext> and <image>_EER.eer, and the movie formats themselves
MOVIE_EXTENSIONS = (".eer", ".tif", ".tiff", ".mrcs")
FRACTIONS_MARK = "_fractions."
# Gain and dark references that share the movies' extensions
NOT_MOVIES = ("countref", "gain", "dark")

_wakeUp = threading.Event()
_startLock = threading.Lock()
_thread: Optional[threading.Thread] = None


def isMovie(name: str) -> bool:
    lower = name.lower()
    if lower.startswith(NOT_MOVIES) or lower.endswith((".xml", ".jpg", ".mdoc")):
        return False
    return FRACTIONS_MARK in lower or lower.endswith(MOVIE_EXTENSIONS)


def dataFolder(offloadPath: str, sessionName: str, number: int) -> Path:
    return Path(offloadPath) / ("%s_DATA_%02d" % (sessionName, int(number)))


def _movieFolders(root: Path) -> List[Path]:
    """Where movies are: the folder itself and EPU's Images-Disc*/GridSquare_*/Data."""
    folders = [root]
    for disc in sorted(root.glob("Images-Disc*")):
        folders.extend(sorted(path for path in disc.glob("GridSquare_*/Data") if path.is_dir()))
    return folders


def _readFolder(folder: Path) -> Dict[str, Any]:
    count, size, newest, oldest, first = 0, 0, None, None, None
    with os.scandir(folder) as entries:
        for entry in entries:
            if not isMovie(entry.name) or not entry.is_file():
                continue
            stat = entry.stat()
            count += 1
            size += stat.st_size
            newest = stat.st_mtime if newest is None else max(newest, stat.st_mtime)
            if oldest is None or (stat.st_mtime, entry.name) < (oldest, first):
                oldest, first = stat.st_mtime, entry.name
    return {"count": count, "bytes": size, "newest": newest, "oldest": oldest, "first": first}


def scanFolder(root: Path, state: Dict[str, Any], now: float, fullScanSeconds: float = FULL_SCAN_SECONDS) -> Dict[str, Any]:
    """Look at a DATA folder; answers its totals and the state for the next look.

    state is what the last look answered (``scanState``): the folders of movies whose modification time is
    the same are not read again, unless the last full look is older than fullScanSeconds.
    """
    if not root.is_dir():
        return {"exists": False, "count": 0, "bytes": 0, "newest": None, "oldest": None, "first": None,
                "state": {"exists": False}}
    full = now - float(state.get("fullScanAt") or 0) >= fullScanSeconds
    known = state.get("folders") or {}
    folders: Dict[str, Any] = {}
    for folder in _movieFolders(root):
        relative = str(folder.relative_to(root)) if folder != root else "."
        try:
            mtime = folder.stat().st_mtime
        except OSError:
            continue
        previous = known.get(relative)
        if not full and previous and previous.get("mtime") == mtime:
            folders[relative] = previous
            continue
        try:
            folders[relative] = dict(_readFolder(folder), mtime=mtime)
        except OSError:
            logger.warning("Could not read %s", folder, exc_info=True)
    totals = {"exists": True, "count": 0, "bytes": 0, "newest": None, "oldest": None, "first": None}
    for relative, found in folders.items():
        if not found.get("count"):
            continue
        totals["count"] += found["count"]
        totals["bytes"] += found["bytes"]
        totals["newest"] = max(filter(None, [totals["newest"], found["newest"]]))
        if totals["oldest"] is None or found["oldest"] < totals["oldest"]:
            totals["oldest"] = found["oldest"]
            totals["first"] = str(root / relative / found["first"]) if relative != "." else str(root / found["first"])
    totals["state"] = {"exists": True, "fullScanAt": now if full else state.get("fullScanAt"), "folders": folders}
    return totals


def _when(timestamp: Optional[float]) -> Optional[datetime.datetime]:
    return datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc) if timestamp else None


def _gainFile(root: Path) -> Optional[str]:
    """The gain reference EPU leaves in the DATA folder (``*.gain``), if any."""
    gains = sorted(root.glob("*.gain"))
    return str(gains[0]) if gains else None


def _acquisition(firstMovie: Path, root: Path, detectors: List[Dict[str, Any]],
                 detectorId: Optional[int]) -> Optional[Dict[str, Any]]:
    """What the first movie's metadata says; None while EPU has not written it yet."""
    metadata = metadataFileOf(firstMovie)
    if metadata is None:
        return None
    try:
        acquisition = readAcquisition(metadata, detectors, detectorId)
    except (ValueError, OSError) as error:
        return {"metadataFile": metadata.name, "error": str(error)}
    # Relative to the DATA folder: its project's Import Movies reads the movies with a pattern made from it
    acquisition["firstMovie"] = str(firstMovie.relative_to(root))
    acquisition["gainFile"] = _gainFile(root)
    return acquisition


def watchSessions(db, now: Optional[float] = None) -> int:
    """Look once at the DATA folders of the sessions acquiring; answers how many were looked at.

    Does nothing while another process watches."""
    sessions = FacilitySessionPostgresqlMapper(db)
    if not sessions.tryWatchLock():
        return 0
    microscopes = FacilityMicroscopePostgresqlMapper(db)
    detectorsOf: Dict[int, List[Dict[str, Any]]] = {}
    now = time.time() if now is None else now
    looked = 0
    try:
        for dataset in sessions.listWatchedDatasets():
            if not dataset["offloadPath"]:
                continue
            root = dataFolder(dataset["offloadPath"], dataset["sessionName"], dataset["number"])
            scan = scanFolder(root, dataset["scanState"] or {}, now)
            acquisition = None
            if scan["count"] and not dataset["acquisitionRead"]:
                microscopeId = int(dataset["microscopeId"])
                if microscopeId not in detectorsOf:
                    detectorsOf[microscopeId] = (microscopes.getMicroscope(microscopeId) or {}).get("detectors") or []
                acquisition = _acquisition(Path(scan["first"]), root, detectorsOf[microscopeId], dataset["detectorId"])
            sessions.saveScan(dataset["id"], scan["count"], scan["bytes"], _when(scan["oldest"]), _when(scan["newest"]),
                              scan["state"], acquisition)
            looked += 1
        _processPending(db)
    finally:
        sessions.unlockWatch()
    return looked


def _processPending(db) -> None:
    """Make and launch the projects of the DATA whose first movie was just read (one failing does not stop the rest)."""
    from app.backend.api.services.facility_session_processing import FacilitySessionProcessor
    from app.backend.mapper.postgresql import PostgresqlFlatMapper

    try:
        FacilitySessionProcessor(PostgresqlFlatMapper(db)).processPending()
    except Exception:
        logger.warning("Could not process the sessions' new DATA", exc_info=True)


def requestWatch() -> None:
    """Look now instead of at the next turn (a no-op where the watcher was not started)."""
    _wakeUp.set()


def startSessionWatcher(openDb: Callable[[], object]) -> None:
    """Start the watcher thread of this process, once; openDb gives it a connection of its own."""
    global _thread
    with _startLock:
        if _thread is not None:
            return
        _thread = threading.Thread(target=_run, args=(openDb,), name="facility-session-watcher", daemon=True)
        _thread.start()


def _run(openDb: Callable[[], object]) -> None:
    db = None
    while True:
        _wakeUp.clear()
        if facilityModeEnabled():
            try:
                if db is None:
                    db = openDb()
                watchSessions(db)
            except Exception:
                logger.warning("Could not look at the sessions' folders; trying again later", exc_info=True)
                try:
                    db.close()
                except Exception:
                    pass
                db = None
        _wakeUp.wait(WATCH_SECONDS)
