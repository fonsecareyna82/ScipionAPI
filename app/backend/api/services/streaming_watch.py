"""The assistant watching a project that processes in streaming, for a user who asked for it in the help chat.

The monitor tells what goes past the project's limits while someone looks at it; a watch looks on its own, every
few minutes, and leaves a notice when something gets worse than it was when the watch began (the CTF resolution,
the drift, the particles per micrograph, the share past the limits), when the acquisition pauses or stops, when a
stage stops giving anything, or when a protocol fails. Each problem is told once, and again only after it went
away and came back. A watch ends when its time is up, when the session is over (a last notice says so) or when
the user stops it. No model is asked: the texts and what to do are fixed rules.
"""
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from app.backend.mapper.assistant_mapper import AssistantPostgresqlMapper

logger = logging.getLogger(__name__)

CHECK_SECONDS = 120
DEFAULT_HOURS = 24
MAX_HOURS = 72
# Micrographs needed in the newest window before it is compared
MIN_ITEMS = 20
FAILED = ("failed", "aborted")

_thread: Optional[threading.Thread] = None
_startLock = threading.Lock()
_wakeUp = threading.Event()


def hoursOf(value: Any) -> int:
    try:
        hours = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_HOURS
    return min(MAX_HOURS, max(1, hours))


def _worse(reference: Dict[str, Any], current: Dict[str, Any], key: str, ratio: float, least: float) -> bool:
    before, now = reference.get(key), current.get(key)
    if before is None or now is None:
        return False
    if ratio >= 1:
        return now > before * ratio and now - before >= least
    return now < before * ratio and before - now >= least


def problems(reference: Optional[Dict[str, Any]], snapshot: Dict[str, Any],
             failedBefore: List[str], protocols: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """What is wrong now, each with its key, a title, what is seen and what to do."""
    found: List[Dict[str, str]] = []

    def add(key: str, title: str, text: str, hint: str) -> None:
        found.append({"key": key, "title": title, "text": text, "hint": hint})

    quality = snapshot.get("quality") or {}
    before = (reference or {}).get("quality") or {}
    if quality.get("items", 0) >= MIN_ITEMS and before.get("items", 0) >= MIN_ITEMS:
        count = quality["items"]
        if _worse(before, quality, "resolution", 1.25, 0.5):
            add("resolution", "The CTF resolution got worse",
                "Over the last %d micrographs the median CTF resolution is %.1f Å; it was %.1f Å when I began." % (
                    count, quality["resolution"], before["resolution"]),
                "Thicker ice or more drift usually do this: look at the newest micrographs in the monitor and, if "
                "it is the ice, collect on other squares.")
        if _worse(before, quality, "totalDrift", 1.4, 3.0):
            add("drift", "The drift went up",
                "The median total drift of the last %d movies is %.1f Å; it was %.1f Å." % (
                    count, quality["totalDrift"], before["totalDrift"]),
                "The stage may not settle after each move, or the grid charges: a longer delay after moving, or "
                "other squares, usually help.")
        if _worse(before, quality, "particles", 0.65, 5.0):
            add("particles", "Fewer particles per micrograph",
                "The last %d micrographs have a median of %.0f particles picked; there were %.0f." % (
                    count, quality["particles"], before["particles"]),
                "The ice or the concentration changes across the grid: check where the microscope collects now.")
        outside, earlier = quality.get("outside"), before.get("outside") or 0.0
        if outside is not None and outside >= 0.3 and outside - earlier >= 0.15:
            add("outside", "Many micrographs past the project's limits",
                "%.0f %% of the last %d micrographs go past the limits set in the monitor (it was %.0f %%)." % (
                    100 * outside, count, 100 * earlier),
                "Open the monitor to see which limit they pass, and whether the limits suit this sample.")
    flow = snapshot.get("flow") or {}
    if flow.get("acquisition") == "paused":
        add("paused", "No new %s" % (flow.get("unit") or "movies"),
            "Nothing new for %.0f minutes." % (flow.get("idleMinutes") or 0),
            "Check the microscope and its acquisition software. If the session is over, nothing is needed: the "
            "import closes by itself after its timeout.")
    elif flow.get("acquisition") == "stopped":
        add("stopped", "The import does not run any more",
            "%s is not running, but the acquisition was still open." % (flow.get("label") or "The import"),
            "Look at its log; continue it to read the new movies.")
    for stalled in snapshot.get("stalled") or []:
        add("stalled:%s" % stalled.get("protocolId"), "%s stopped giving results" % (stalled.get("label") or
                                                                                     stalled.get("stage")),
            "Nothing new for %.0f minutes, with %s waiting." % (stalled.get("minutes") or 0, stalled.get("behind")),
            "Look at its log: it may wait for a queue or have hung. Stopping and continuing it often helps.")
    for protocol in protocols:
        if protocol.get("status") in FAILED and str(protocol["protocolId"]) not in failedBefore:
            add("failed:%s" % protocol["protocolId"], "#%s %s %s" % (protocol["protocolId"], protocol.get("label"),
                                                                    protocol.get("status")),
                "The protocol %s." % protocol.get("status"),
                "Ask me in the help chat why it failed and how to go on.")
    return found


def finishedText(snapshot: Dict[str, Any]) -> str:
    flow = snapshot.get("flow") or {}
    stages = snapshot.get("stages") or {}
    made = ", ".join("%s %s" % (count, stage) for stage, count in stages.items() if count)
    return "The acquisition finished (%s %s) and every step got to the end%s. I stop watching." % (
        flow.get("items") or 0, flow.get("unit") or "movies", (": " + made) if made else "")


def failedIds(protocols: List[Dict[str, Any]]) -> List[str]:
    return [str(protocol["protocolId"]) for protocol in protocols if protocol.get("status") in FAILED]


def startingState(snapshot: Dict[str, Any], protocols: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What a new watch keeps: the stream as it is (the reference, once there are enough micrographs) and the
    protocols that had failed already (not told)."""
    reference = snapshot if (snapshot.get("quality") or {}).get("items", 0) >= MIN_ITEMS else None
    return {"reference": reference, "state": {"failedBefore": failedIds(protocols), "told": []}}


def step(watch: Dict[str, Any], snapshot: Dict[str, Any],
         protocols: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One look at a watch: {reference, state, notices: [{title, body}], end: reason or None}."""
    reference = watch.get("reference")
    state = dict(watch.get("state") or {})
    state.setdefault("failedBefore", [])
    told = list(state.get("told") or [])
    if reference is None and (snapshot.get("quality") or {}).get("items", 0) >= MIN_ITEMS:
        reference = snapshot
    if (snapshot.get("flow") or {}).get("complete"):
        state["told"] = told
        return {"reference": reference, "state": state, "end": "finished",
                "notices": [{"title": "The session is over", "body": finishedText(snapshot)}]}
    found = problems(reference, snapshot, state["failedBefore"], protocols)
    notices = [{"title": problem["title"], "body": "%s\n\nWhat to do: %s" % (problem["text"], problem["hint"])}
               for problem in found if problem["key"] not in told]
    # A problem gone can be told again if it comes back
    state["told"] = [problem["key"] for problem in found]
    return {"reference": reference, "state": state, "notices": notices, "end": None}


def projectName(db, projectId: int) -> str:
    from app.backend.api.services.notify_events import _projectName

    row = db.fetchOne("SELECT name FROM projects WHERE id = %s", (int(projectId),)) or {}
    return _projectName(row.get("name")) or "#%s" % projectId


def watchOnce(db, snapshotOf: Optional[Callable[[int], Dict[str, Any]]] = None) -> int:
    """One turn over every active watch; answers how many notices it left."""
    from app.backend.api.services.notifications import Notifications
    from app.backend.mapper.help_chat_mapper import HelpChatPostgresqlMapper

    mapper = AssistantPostgresqlMapper(db)
    watches = mapper.activeWatches()
    if not watches or not mapper.tryWatcherLock():
        return 0
    if snapshotOf is None:
        from app.backend.api.services.streaming_monitor import watchSnapshot

        flat = _flatMapper(db)
        snapshotOf = lambda projectId: watchSnapshot(flat, projectId)  # noqa: E731
    left = 0
    snapshots: Dict[int, Dict[str, Any]] = {}
    try:
        notifications = Notifications(db)
        for watch in watches:
            projectId, userId = int(watch["projectId"]), int(watch["userId"])
            name = projectName(db, projectId)
            link = "/project/load/%d?monitor=1" % projectId
            try:
                if watch.get("expired"):
                    mapper.endWatch(watch["id"], "time")
                    notifications.notify([userId], "assistant.watch", "%s: I stopped watching" % name,
                                         "The time you gave me to watch it is over. Ask me again in the help chat "
                                         "to go on.", link)
                    left += 1
                    continue
                if projectId not in snapshots:
                    snapshots[projectId] = snapshotOf(projectId)
                protocols = HelpChatPostgresqlMapper(db).projectProtocols(projectId)
                result = step(watch, snapshots[projectId], protocols)
                for notice in result["notices"]:
                    notifications.notify([userId], "assistant.watch", "%s: %s" % (name, notice["title"]),
                                         notice["body"], link)
                    left += 1
                mapper.saveWatch(watch["id"], result["reference"], result["state"])
                if result["end"]:
                    mapper.endWatch(watch["id"], result["end"])
            except Exception:
                logger.warning("Could not look at the watch %s of project %s", watch.get("id"), projectId,
                               exc_info=True)
    finally:
        mapper.watcherUnlock()
    if left:
        from app.backend.api.services.notification_sender import requestSend

        requestSend()
    return left


def _flatMapper(db):
    """The monitor reads through a mapper's connection: here, this thread's."""
    from types import SimpleNamespace

    return SimpleNamespace(db=db)


def requestWatch() -> None:
    _wakeUp.set()


def startStreamingWatcher(openDb: Callable[[], object]) -> None:
    """Start this API process' watcher thread, once (it idles while nothing is watched)."""
    global _thread
    with _startLock:
        if _thread is not None:
            return
        _thread = threading.Thread(target=_run, args=(openDb,), name="streaming-watcher", daemon=True)
        _thread.start()


def _run(openDb: Callable[[], object]) -> None:
    db = None
    while True:
        _wakeUp.clear()
        try:
            if db is None:
                db = openDb()
            watchOnce(db)
        except Exception:
            logger.warning("Could not look at the watched streams; trying again later", exc_info=True)
            try:
                db.close()
            except Exception:
                pass
            db = None
        _wakeUp.wait(CHECK_SECONDS)


WATCHED = ("The CTF resolution, the drift and the particles per micrograph against how they are when I begin",
           "Micrographs past the limits set in the monitor",
           "A pause or stop of the acquisition, and a step that stops giving results",
           "Protocols that fail")


def watchCard(projectId: int, name: str, snapshot: Dict[str, Any], hours: Any, active: Optional[Dict[str, Any]],
              reason: str = "") -> Dict[str, Any]:
    """Watching a project: refused when nothing of it processes in streaming, or it is watched already."""
    from app.backend.api.services.assistant_actions import ProposalError

    if active is not None:
        raise ProposalError("I already watch %s for this user, until %s" % (name, active.get("until")))
    flow = snapshot.get("flow") or {}
    if not snapshot.get("streaming") or flow.get("complete"):
        raise ProposalError("Nothing of %s processes in streaming now: there is nothing to watch" % name)
    quality = snapshot.get("quality") or {}
    return {"kind": "action", "action": "watch", "projectId": int(projectId), "protocolId": "", "label": name,
            "hours": hoursOf(hours), "watched": list(WATCHED),
            "now": {"acquisition": flow.get("acquisition"), "items": flow.get("items"), "unit": flow.get("unit"),
                    "micrographs": quality.get("items"),
                    **{key: quality.get(key) for key in ("resolution", "totalDrift", "particles")}},
            "reason": str(reason or "")[:500]}


def unwatchCard(projectId: int, name: str, active: Optional[Dict[str, Any]], reason: str = "") -> Dict[str, Any]:
    from app.backend.api.services.assistant_actions import ProposalError

    if active is None:
        raise ProposalError("I am not watching %s for this user" % name)
    return {"kind": "action", "action": "unwatch", "projectId": int(projectId), "protocolId": "", "label": name,
            "until": str(active.get("until") or ""), "reason": str(reason or "")[:500]}
