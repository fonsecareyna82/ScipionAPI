"""The disk the projects use, and the folder each user's projects go into.

Each project is measured in the background, one at a time and paced, so a server with many large projects is
not kept busy: what its folder takes on the disk (the blocks it holds, as du counts), in all and in its Runs and
Uploads folders. Symbolic links are not followed (imported movies are usually links to the microscope's data,
which the project does not hold) and a file with several hard links is counted once. A linked project (a link
in the projects folder to a project elsewhere) is measured where it really is.

A project is measured again a day after its last measure, an hour after it when it changed since (its protocols
ran), and whenever someone asks. The measures are kept in the database, so the project list, the user's total
and the administrators' view of every user, group and project read them without walking any folder.

New projects go into a folder of their owner's, under the projects folder (like each user's ScipionUserData in
Scipion): named after their email, chosen with their first project and kept afterwards.
"""
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.backend.mapper.storage_mapper import StoragePostgresqlMapper
from app.backend.utils.background_delete import TRASH_FOLDER

logger = logging.getLogger(__name__)

MAX_AGE_SECONDS = 24 * 3600
ACTIVITY_SECONDS = 3600
# Between two projects, and when there is nothing to measure (a request wakes it up)
PAUSE_BETWEEN_SECONDS = 2.0
IDLE_SECONDS = 300.0
# Inside a project: a short pause every so many entries, so a large one does not hold the disk
PAUSE_EVERY_ENTRIES = 2000
PAUSE_SECONDS = 0.02

RUNS_FOLDER = "Runs"
UPLOADS_FOLDER = "Uploads"

_wakeUp = threading.Event()
_startLock = threading.Lock()
_thread: Optional[threading.Thread] = None


# Measuring a folder --------------------------------------------------------------------------------------------

def _diskBytes(stat: os.stat_result) -> int:
    blocks = getattr(stat, "st_blocks", None)
    return int(blocks) * 512 if blocks is not None else int(stat.st_size)


def measureFolder(root: Path, pauseEvery: int = PAUSE_EVERY_ENTRIES, pauseSeconds: float = PAUSE_SECONDS,
                  sleep: Callable[[float], None] = time.sleep) -> Dict[str, int]:
    """What a project folder takes on the disk: in all, in Runs and in Uploads, and its files.

    Links are not followed and hard links are counted once; the project's own trash (what is being removed) and
    what cannot be read are left out.
    """
    totals = {"runs": 0, "uploads": 0, "other": 0}
    files = 0
    seen = set()
    entries = 0
    stack = []
    for entry in list(os.scandir(root)):
        if entry.name == TRASH_FOLDER:
            continue
        bucket = "runs" if entry.name == RUNS_FOLDER else "uploads" if entry.name == UPLOADS_FOLDER else "other"
        stack.append((entry, bucket))
    while stack:
        entry, bucket = stack.pop()
        entries += 1
        if pauseEvery and entries % pauseEvery == 0:
            sleep(pauseSeconds)
        try:
            if entry.is_dir(follow_symlinks=False):
                try:
                    stack.extend((child, bucket) for child in os.scandir(entry.path))
                except OSError:
                    continue
            elif entry.is_file(follow_symlinks=False):
                stat = entry.stat(follow_symlinks=False)
                if stat.st_nlink > 1:
                    key = (stat.st_dev, stat.st_ino)
                    if key in seen:
                        continue
                    seen.add(key)
                totals[bucket] += _diskBytes(stat)
                files += 1
        except OSError:
            continue
    return {"totalBytes": sum(totals.values()), "runsBytes": totals["runs"], "uploadsBytes": totals["uploads"],
            "files": files}


def projectsRoot() -> Path:
    """The projects folder (PROJECTS_PATH)."""
    from app.backend.api.services.project_service import ProjectService

    return Path(ProjectService._resolveProjectsPath())


def locationOf(path: Path, root: Path) -> str:
    """managed: a folder in the projects folder; linked: a link there to one elsewhere; external: elsewhere."""
    entry = Path(os.path.abspath(os.path.expanduser(str(path))))
    rootPath = Path(os.path.abspath(str(root)))
    inside = entry == rootPath or rootPath in entry.parents
    if not inside:
        return "external"
    # A link anywhere between the projects folder and the project takes it elsewhere
    current = entry
    while current != rootPath:
        if current.is_symlink():
            return "linked"
        current = current.parent
    return "managed"


def measureProject(path: str, root: Path, sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    """The measure of one project, ready to be saved (an error says why it could not be made)."""
    started = time.monotonic()
    entry = Path(os.path.expanduser(str(path or "")))
    values: Dict[str, Any] = {"totalBytes": None, "files": None, "runsBytes": None, "uploadsBytes": None,
                              "location": None, "measuredPath": None, "error": None}
    try:
        values["location"] = locationOf(entry, root)
        real = entry.resolve(strict=True)
        values["measuredPath"] = str(real)
        if not real.is_dir():
            raise NotADirectoryError("Not a folder")
        values.update(measureFolder(real, sleep=sleep))
    except FileNotFoundError:
        values["error"] = "The project folder is not there"
    except OSError as error:
        values["error"] = "The project folder could not be read: %s" % (error.strerror or error)
    values["durationSeconds"] = round(time.monotonic() - started, 2)
    return values


# The measurer --------------------------------------------------------------------------------------------------

def measureNext(db, root: Path, sleep: Callable[[float], None] = time.sleep) -> Optional[int]:
    """Measure the project most in need of it; answers its id, or None when none needs it (or another process
    measures). Leaves no transaction open."""
    storage = StoragePostgresqlMapper(db)
    try:
        if not storage.lockMeasure():
            return None
        try:
            project = storage.nextToMeasure(MAX_AGE_SECONDS, ACTIVITY_SECONDS)
            if project is None:
                return None
            startedAt = datetime.now(timezone.utc)
            storage.startMeasure(int(project["id"]), startedAt)
            # Nothing stays open while the folder is walked, which may take minutes
            db.rollback()
            values = measureProject(project["path"], root, sleep=sleep)
            values["measuredAt"] = startedAt
            storage.saveMeasure(int(project["id"]), values)
            return int(project["id"])
        finally:
            storage.unlockMeasure()
    finally:
        db.rollback()


def startDiskUsageMeasurer(openDb: Callable[[], object], root: Callable[[], Path]) -> None:
    """Start the measurer thread of this process, once; openDb gives it a connection of its own."""
    global _thread
    with _startLock:
        if _thread is not None:
            return
        _thread = threading.Thread(target=_run, args=(openDb, root), name="project-disk-usage", daemon=True)
        _thread.start()


def _run(openDb: Callable[[], object], root: Callable[[], Path]) -> None:
    db = None
    while True:
        _wakeUp.clear()
        measured = None
        try:
            if db is None:
                db = openDb()
            measured = measureNext(db, root())
            # With the new measures, the quotas reaching 80 % or full are told
            from app.backend.api.services.storage_quotas import refreshNoticesNow

            refreshNoticesNow(db)
        except Exception:
            logger.warning("Could not measure the projects' disk usage; trying again later", exc_info=True)
            try:
                db.close()
            except Exception:
                pass
            db = None
        _wakeUp.wait(PAUSE_BETWEEN_SECONDS if measured is not None else IDLE_SECONDS)


def wakeMeasurer() -> None:
    """Measure now what needs it (a new project) instead of after the idle wait (a no-op where it was not started)."""
    _wakeUp.set()


def requestMeasure(db, projectIds: Optional[List[int]] = None) -> None:
    """Ask for new measures (of every project, without ids) and wake the measurer of this process up."""
    StoragePostgresqlMapper(db).requestMeasure(projectIds)
    _wakeUp.set()


# What they use -------------------------------------------------------------------------------------------------

def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _personName(first: Optional[str], last: Optional[str], email: Optional[str]) -> str:
    name = " ".join(part for part in (first, last) if part and str(part).strip()).strip()
    return name or (email or "")


def _projectOut(row: Dict[str, Any]) -> Dict[str, Any]:
    path = str(row.get("path") or "")
    return {
        "id": int(row["id"]),
        "name": Path(path).name or path,
        "path": path,
        "ownerId": row["ownerId"],
        "ownerName": _personName(row.get("ownerFirstName"), row.get("ownerLastName"), row.get("ownerEmail")),
        "ownerEmail": row.get("ownerEmail"),
        "totalBytes": row.get("totalBytes"),
        "runsBytes": row.get("runsBytes"),
        "uploadsBytes": row.get("uploadsBytes"),
        "files": row.get("files"),
        "location": row.get("location"),
        "measuredAt": _iso(row.get("measuredAt")),
        "durationSeconds": row.get("durationSeconds"),
        "error": row.get("error"),
        "measuring": row.get("startedAt") is not None,
        "requested": row.get("requestedAt") is not None and (
            row.get("measuredAt") is None or row["requestedAt"] > row["measuredAt"]),
        "lastActivity": _iso(row.get("lastActivity")),
    }


def _sum(projects: List[Dict[str, Any]]) -> Dict[str, Any]:
    measured = [project for project in projects if project["totalBytes"] is not None]
    times = [project["measuredAt"] for project in measured if project["measuredAt"]]
    activity = [project["lastActivity"] for project in projects if project["lastActivity"]]
    return {"projects": len(projects), "measured": len(measured),
            "totalBytes": sum(int(project["totalBytes"]) for project in measured),
            "runsBytes": sum(int(project["runsBytes"] or 0) for project in measured),
            "uploadsBytes": sum(int(project["uploadsBytes"] or 0) for project in measured),
            "oldestMeasure": min(times) if times else None,
            "lastActivity": max(activity) if activity else None}


def diskOf(path: Path) -> Optional[Dict[str, Any]]:
    try:
        usage = shutil.disk_usage(str(path))
    except OSError:
        return None
    return {"path": str(path), "totalBytes": usage.total, "usedBytes": usage.used, "freeBytes": usage.free}


def usageReport(db, root: Path) -> Dict[str, Any]:
    """Every project's measure, summed by owner and by group (a user in two groups counts in both), and the
    projects' disk."""
    storage = StoragePostgresqlMapper(db)
    projects = [_projectOut(row) for row in storage.listProjectUsage()]

    byOwner: Dict[int, List[Dict[str, Any]]] = {}
    for project in projects:
        byOwner.setdefault(int(project["ownerId"]), []).append(project)
    users = []
    for ownerId, owned in byOwner.items():
        users.append(dict(_sum(owned), userId=ownerId, name=owned[0]["ownerName"], email=owned[0]["ownerEmail"]))
    users.sort(key=lambda user: (-user["totalBytes"], user["name"].lower()))

    groups: Dict[int, Dict[str, Any]] = {}
    for row in storage.listGroupMembers():
        group = groups.setdefault(int(row["id"]), {"groupId": int(row["id"]), "name": row["name"],
                                                    "members": [], "pis": []})
        if row.get("userId") is not None:
            group["members"].append(int(row["userId"]))
            if row.get("groupRole") == "pi":
                group["pis"].append(int(row["userId"]))
    groupList = []
    for group in groups.values():
        owned = [project for member in group["members"] for project in byOwner.get(member, [])]
        groupList.append(dict(_sum(owned), groupId=group["groupId"], name=group["name"],
                              members=len(group["members"]),
                              membersWithProjects=sum(1 for member in group["members"] if member in byOwner)))
    groupList.sort(key=lambda group: (-group["totalBytes"], group["name"].lower()))

    return {"disk": diskOf(root), "total": _sum(projects), "users": users, "groups": groupList,
            "projects": projects,
            "pending": sum(1 for project in projects if project["requested"] or project["measuredAt"] is None),
            "measuring": [project["id"] for project in projects if project["measuring"]]}


def formatSize(totalBytes: Optional[int]) -> Optional[str]:
    """The size as the project list shows it (in GB)."""
    if totalBytes is None:
        return None
    return "%.2f GB" % (int(totalBytes) / (1024 ** 3))


# The users' projects folders -----------------------------------------------------------------------------------

FOLDER_NAME = re.compile(r"[^a-z0-9._-]+")
# Never a name the projects folder already uses for something else
RESERVED_FOLDERS = {TRASH_FOLDER}


def folderNameOf(email: Optional[str], userId: int) -> str:
    """The folder named after the user's email (scipion@cnb.csic.es: scipion)."""
    local = str(email or "").split("@", 1)[0].strip().lower()
    name = FOLDER_NAME.sub("_", local).strip("._-")
    return name or "user%d" % int(userId)


def userProjectsFolder(db, user: Dict[str, Any], root: Path) -> Path:
    """The folder of the user's new projects, made if needed: theirs if they have one, else a new one named after
    their email (with _2, _3… when the name is taken by another user or by something in the projects folder)."""
    storage = StoragePostgresqlMapper(db)
    userId = int(user["id"])
    folder = storage.projectsFolderOf(userId)
    if not folder:
        base = folderNameOf(user.get("email"), userId)
        taken = set(storage.foldersLike(base))
        for number in range(1, 1000):
            candidate = base if number == 1 else "%s_%d" % (base, number)
            if candidate in taken or candidate in RESERVED_FOLDERS or os.path.lexists(root / candidate):
                continue
            folder = storage.claimProjectsFolder(userId, candidate)
            if folder is None:
                # Another request gave them one meanwhile, or took this name
                folder = storage.projectsFolderOf(userId)
            if folder:
                break
        if not folder:
            raise RuntimeError("No folder could be chosen for the projects of user %s" % userId)
    path = Path(root) / folder
    path.mkdir(parents=True, exist_ok=True)
    return path
