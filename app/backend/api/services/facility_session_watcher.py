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
# A tomography DATA: SerialEM and Tomo5 may write the tilt movies as .mrc (EPU's .mrc are its integrated images)
TOMO_MOVIE_EXTENSIONS = MOVIE_EXTENSIONS + (".mrc",)
# How deep under a DATA folder movies are looked for (EPU: Images-Disc1/GridSquare_*/Data; tomography: <ts>/frames)
MAX_DEPTH = 4
# An ATLAS folder found is looked at again this often (EPU adds to it while it builds the atlas)
ATLAS_SCAN_SECONDS = 300.0
# Files counted at most in an ATLAS folder (one is a few hundred)
ATLAS_FILE_LIMIT = 100000

_wakeUp = threading.Event()
_startLock = threading.Lock()
_thread: Optional[threading.Thread] = None


def isMovie(name: str, technique: str = "spa") -> bool:
    lower = name.lower()
    if lower.startswith(NOT_MOVIES) or lower.endswith((".xml", ".jpg", ".mdoc")):
        return False
    return FRACTIONS_MARK in lower or lower.endswith(TOMO_MOVIE_EXTENSIONS if technique == "tomo" else MOVIE_EXTENSIONS)


def dataFolder(offloadPath: str, folder: str) -> Path:
    """Where a DATA is: its folder (named by its microscope's pattern) in the offload."""
    return Path(offloadPath) / folder


def _movieFolders(root: Path) -> List[Path]:
    """Where movies may be: the folder and its folders down to MAX_DEPTH (EPU's Images-Disc*/GridSquare_*/Data,
    a folder per tilt series)."""
    folders, level = [root], [root]
    for _ in range(MAX_DEPTH):
        below = []
        for folder in level:
            try:
                with os.scandir(folder) as entries:
                    below.extend(Path(entry.path) for entry in entries if entry.is_dir(follow_symlinks=False))
            except OSError:
                continue
        below.sort()
        folders.extend(below)
        level = below
    return folders


def _readFolder(folder: Path, technique: str = "spa") -> Dict[str, Any]:
    count, size, newest, oldest, first = 0, 0, None, None, None
    with os.scandir(folder) as entries:
        for entry in entries:
            if not isMovie(entry.name, technique) or not entry.is_file():
                continue
            stat = entry.stat()
            count += 1
            size += stat.st_size
            newest = stat.st_mtime if newest is None else max(newest, stat.st_mtime)
            if oldest is None or (stat.st_mtime, entry.name) < (oldest, first):
                oldest, first = stat.st_mtime, entry.name
    return {"count": count, "bytes": size, "newest": newest, "oldest": oldest, "first": first}


def scanFolder(root: Path, state: Dict[str, Any], now: float, fullScanSeconds: float = FULL_SCAN_SECONDS,
               technique: str = "spa") -> Dict[str, Any]:
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
            folders[relative] = dict(_readFolder(folder, technique), mtime=mtime)
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


def _tiltSeriesMdoc(movie: Path, root: Path) -> Optional[Path]:
    """A tilt series' mdoc describes its movies: the first one beside the movie, else up to the DATA folder."""
    folder = movie.parent
    while True:
        mdocs = sorted(folder.glob("*.mdoc"))
        if mdocs:
            return mdocs[0]
        if folder == root or root not in folder.parents:
            return None
        folder = folder.parent


def readFirstMovie(firstMovie: Path, root: Path, detectors: List[Dict[str, Any]],
                   detectorId: Optional[int], tolerance: float = 0.10) -> Optional[Dict[str, Any]]:
    """What the first movie's metadata says; None while EPU has not written it yet."""
    metadata = metadataFileOf(firstMovie) or _tiltSeriesMdoc(firstMovie, root)
    if metadata is None:
        return None
    try:
        acquisition = readAcquisition(metadata, detectors, detectorId, tolerance)
    except (ValueError, OSError) as error:
        return {"metadataFile": metadata.name, "error": str(error)}
    # Relative to the DATA folder: its project's Import Movies reads the movies with a pattern made from it
    acquisition["firstMovie"] = str(firstMovie.relative_to(root))
    acquisition["metadataPath"] = str(metadata.relative_to(root)) if root in metadata.parents else metadata.name
    acquisition["gainFile"] = _gainFile(root)
    return acquisition


def lastMovieAt(scan: Dict[str, Any], dataset: Dict[str, Any], now: float) -> Optional[datetime.datetime]:
    """When the last movie came: now when there are more than the last look saw, else what was known.

    Not the files' modification time alone: a movie copied keeping its time (or linked) would look old and
    its DATA stalled."""
    newest = _when(scan["newest"])
    if scan["count"] > int(dataset.get("movieCount") or 0):
        return max(filter(None, [newest, _when(now)]))
    return dataset.get("lastMovieAt") or newest


def watchSessions(db, now: Optional[float] = None) -> int:
    """Look once at the DATA folders of the sessions acquiring; answers how many were looked at.

    Does nothing while another process watches."""
    sessions = FacilitySessionPostgresqlMapper(db)
    if not sessions.tryWatchLock():
        return 0
    microscopes = FacilityMicroscopePostgresqlMapper(db)
    from app.backend.api.services.facility_settings_service import FacilitySettingsService

    tolerance = float(FacilitySettingsService(db).values()["calibrationTolerancePercent"]) / 100
    detectorsOf: Dict[int, List[Dict[str, Any]]] = {}
    now = time.time() if now is None else now
    looked = 0
    try:
        for dataset in sessions.listWatchedDatasets():
            if not dataset["offloadPath"]:
                continue
            root = dataFolder(dataset["offloadPath"], dataset["folder"])
            scan = scanFolder(root, dataset["scanState"] or {}, now, technique=dataset.get("technique") or "spa")
            acquisition = None
            if scan["count"] and not dataset["acquisitionRead"]:
                microscopeId = int(dataset["microscopeId"])
                if microscopeId not in detectorsOf:
                    detectorsOf[microscopeId] = (microscopes.getMicroscope(microscopeId) or {}).get("detectors") or []
                acquisition = readFirstMovie(Path(scan["first"]), root, detectorsOf[microscopeId],
                                             dataset["detectorId"], tolerance)
            sessions.saveScan(dataset["id"], scan["count"], scan["bytes"], _when(scan["oldest"]),
                              lastMovieAt(scan, dataset, now), scan["state"], acquisition)
            looked += 1
        _watchAtlases(sessions, now)
        _markGrids(sessions)
        _processPending(db)
        _refreshAlerts(db)
        _sendRetentionNotices(db)
    finally:
        sessions.unlockWatch()
    return looked


def scanAtlas(root: Path, state: Dict[str, Any], now: float, everySeconds: float = ATLAS_SCAN_SECONDS) -> Optional[Dict[str, Any]]:
    """What an ATLAS folder holds: its files, their size and the newest's time, down to MAX_DEPTH (EPU writes
    Sample*/Atlas/ in it). None when it is not time to look again (found already, looked at recently)."""
    if state.get("files") and now - float(state.get("scannedAt") or 0) < everySeconds:
        return None
    if not root.is_dir():
        return {"exists": False, "scannedAt": now}
    files, size, newest = 0, 0, None
    for folder in _movieFolders(root):
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False):
                        stat = entry.stat(follow_symlinks=False)
                        files += 1
                        size += stat.st_size
                        newest = stat.st_mtime if newest is None else max(newest, stat.st_mtime)
        except OSError:
            continue
        if files >= ATLAS_FILE_LIMIT:
            break
    return {"exists": True, "scannedAt": now, "files": files, "bytes": size,
            "newestAt": _when(newest).isoformat() if newest else None}


def _watchAtlases(sessions, now: float) -> None:
    """Look at the ATLAS folders of the sessions acquiring (a failure here stops nothing else)."""
    try:
        for atlas in sessions.listWatchedAtlases():
            if not atlas["offloadPath"] or not atlas["folder"]:
                continue
            found = scanAtlas(dataFolder(atlas["offloadPath"], atlas["folder"]), atlas["scanState"] or {}, now)
            if found is not None:
                sessions.saveAtlasScan(atlas["id"], found)
    except Exception:
        logger.warning("Could not look at the sessions' ATLAS folders", exc_info=True)


def _markGrids(sessions) -> None:
    """The grids of the sessions acquiring: loaded, and used once a movie of theirs came."""
    try:
        sessions.markGrids()
    except Exception:
        logger.warning("Could not update the grids' status", exc_info=True)


def _sendRetentionNotices(db) -> None:
    """Tell the users of finished sessions before their data go (at most hourly; a failure stops nothing)."""
    from app.backend.api.services.facility_retention import sendNoticesNow

    sendNoticesNow(db)


def _processPending(db) -> None:
    """Make and launch the projects of the DATA whose first movie was just read (one failing does not stop the rest)."""
    from app.backend.api.services.facility_session_processing import FacilitySessionProcessor
    from app.backend.mapper.postgresql import PostgresqlFlatMapper

    try:
        FacilitySessionProcessor(PostgresqlFlatMapper(db)).processPending()
    except Exception:
        logger.warning("Could not process the sessions' new DATA", exc_info=True)


def _refreshAlerts(db) -> None:
    """Open and resolve the facility's alerts, and mail the new ones (a failure here stops nothing else)."""
    from app.backend.api.services.facility_alerts import FacilityAlerts

    try:
        alerts = FacilityAlerts(db)
        alerts.refresh()
        alerts.mailNew()
    except Exception:
        logger.warning("Could not refresh the facility's alerts", exc_info=True)


def watchOnce(db) -> int:
    """One turn of the watcher, leaving no transaction open.

    Its writes are committed as they are made, but its reads open a transaction that a long-lived connection
    would keep: idle in transaction for hours, it held the facility tables and a migration altering them waited.
    """
    try:
        return watchSessions(db)
    finally:
        db.rollback()


def _watchSeconds(db) -> float:
    """How long until the next turn: the facility's setting, else WATCH_SECONDS."""
    if db is None or not facilityModeEnabled():
        return WATCH_SECONDS
    from app.backend.api.services.facility_settings_service import FacilitySettingsService

    try:
        return float(FacilitySettingsService(db).values()["watchSeconds"])
    except Exception:
        return WATCH_SECONDS
    finally:
        try:
            db.rollback()
        except Exception:
            pass


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
                watchOnce(db)
            except Exception:
                logger.warning("Could not look at the sessions' folders; trying again later", exc_info=True)
                try:
                    db.close()
                except Exception:
                    pass
                db = None
        _wakeUp.wait(_watchSeconds(db))
