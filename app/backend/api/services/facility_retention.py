"""How long a facility keeps a finished session's data, telling its users before they go.

A session's data are of two kinds: the raw movies (in the facility's storage, which ScipionWeb does not own) and
its projects (the processing ScipionWeb made). Each is kept until a date: the session's own when the staff gave
one, else the day it finished plus the facility's days (rawRetentionDays, processedRetentionDays; 0 says none).

Before each date its user and the PIs of its group are told, retentionNoticeDays before it (e.g. 30, 7 and 1 day),
through their notifications (the bell, and their mail: this kind is always mailed). A notice goes once per date:
one the staff move starts the notices again. The dates are also shown in "My sessions".

Nothing is deleted by itself. Past its date a session is listed for the staff, who delete its projects here (a
button) and record that the raw data were deleted (by hand, where they are). A session with both gone is archived.
"""
from __future__ import annotations

import datetime
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.api.services.facility_settings_service import FacilitySettingsService
from app.backend.mapper.facility_retention_mapper import FacilityRetentionPostgresqlMapper

logger = logging.getLogger(__name__)

KINDS = ("raw", "processed")
KIND_WORDS = {"raw": "raw movies", "processed": "processing projects"}
# How often the notices are looked for (the watcher's turns are much shorter)
NOTICE_EVERY_SECONDS = 3600.0
# Within these days of its date a session is "due" for the staff (unless the facility's notices start earlier)
DUE_DAYS = 30

_noticeLock = threading.Lock()
_lastNoticeAt = 0.0


def _badRequest(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _asDate(value: Any) -> Optional[datetime.date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        raise _badRequest("Dates are written YYYY-MM-DD: %s" % value)


def localDate(moment: Optional[datetime.datetime], timezone: str) -> Optional[datetime.date]:
    """The day a moment is in the facility (its time zone; UTC when unknown)."""
    if moment is None:
        return None
    from dateutil import tz

    zone = tz.gettz(timezone) or tz.UTC
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz.UTC)
    return moment.astimezone(zone).date()


def today(timezone: str) -> datetime.date:
    return localDate(datetime.datetime.now(datetime.timezone.utc), timezone)


def keptUntil(session: Dict[str, Any], kind: str, settings: Dict[str, Any]) -> Optional[datetime.date]:
    """Until when a session's data of a kind are kept: its own date, else the day it finished plus the
    facility's days; None when neither says."""
    own = _asDate(session.get(kind + "KeepUntil"))
    if own is not None:
        return own
    days = int(settings.get(kind + "RetentionDays") or 0)
    finishedOn = session.get("finishedOn") or localDate(session.get("finishedAt"), settings.get("timezone") or "UTC")
    if finishedOn is None or not days:
        return None
    return _asDate(finishedOn) + datetime.timedelta(days=days)


def _hasProjects(session: Dict[str, Any]) -> bool:
    if "projects" in session:
        return bool(session["projects"])
    return any(dataset.get("projectId") for dataset in session.get("datasets") or [])


def retentionState(session: Dict[str, Any], kind: str, settings: Dict[str, Any],
                   on: datetime.date) -> Dict[str, Any]:
    """Where a session's data of a kind are on a day.

    state: deleted (recorded), none (no projects to keep), open (not finished), kept (no date, or far from it),
    due (within the notices or DUE_DAYS of its date) or expired (past it: to delete)."""
    deletedAt = session.get(kind + "DeletedAt")
    until = keptUntil(session, kind, settings)
    answer = {"until": until.isoformat() if until else None, "daysLeft": None,
              "own": session.get(kind + "KeepUntil") is not None,
              "deletedAt": deletedAt.isoformat() if isinstance(deletedAt, datetime.datetime) else deletedAt,
              "deletedBy": session.get(kind + "DeletedByName") or session.get(kind + "DeletedByEmail") or None}
    if deletedAt:
        return dict(answer, state="deleted")
    if kind == "processed" and not _hasProjects(session):
        return dict(answer, state="none")
    if not session.get("finishedAt"):
        return dict(answer, state="open")
    if until is None:
        return dict(answer, state="kept")
    daysLeft = (until - on).days
    notices = settings.get("retentionNoticeDays") or []
    within = max([DUE_DAYS] + [int(day) for day in notices])
    state = "expired" if daysLeft < 0 else ("due" if daysLeft <= within else "kept")
    return dict(answer, daysLeft=daysLeft, state=state)


def noticesDue(session: Dict[str, Any], settings: Dict[str, Any], on: datetime.date) -> Dict[str, Any]:
    """The notices a session's user is owed on a day: {kind: (until, daysLeft, days)} for the kinds with one due,
    where days are the notice days it covers (a late look sends one notice, not each one missed)."""
    owed = {}
    # An archived session is history (its data gone, or imported from another system): nobody is told of it
    if session.get("status") == "archived":
        return owed
    notices = session.get("retentionNotices") or {}
    for kind in KINDS:
        state = retentionState(session, kind, settings, on)
        if state["state"] not in ("kept", "due") or state["daysLeft"] is None:
            continue
        sent = notices.get(kind) or {}
        already = set(sent.get("sent") or []) if sent.get("until") == state["until"] else set()
        days = [int(day) for day in settings.get("retentionNoticeDays") or []
                if state["daysLeft"] <= int(day) and int(day) not in already]
        if days:
            owed[kind] = (state["until"], state["daysLeft"], days)
    return owed


def noticeText(session: Dict[str, Any], owed: Dict[str, Any], downloadInstructions: str = "") -> Dict[str, str]:
    """The notice mail of a session: what of its data goes, and when."""
    lines = []
    for kind in KINDS:
        if kind not in owed:
            continue
        until, daysLeft, _ = owed[kind]
        left = "today" if daysLeft == 0 else ("tomorrow" if daysLeft == 1 else "in %d days" % daysLeft)
        lines.append("- Its %s are kept until %s (%s)." % (KIND_WORDS[kind], until, left))
    soonest = min(owed[kind][1] for kind in owed)
    body = ["The facility keeps the data of your session %s (%s) for a limited time:" % (
        session["name"], session.get("microscopeName") or "")]
    body.append("\n".join(lines))
    body.append("After that date they may be deleted. Take home what you need before then.")
    if downloadInstructions.strip():
        body.append("How to take your data home:\n%s" % downloadInstructions.strip())
    body.append("If you need them for longer, ask the facility. You can see your sessions in ScipionWeb, "
                "Facility, My sessions.")
    when = "today" if soonest == 0 else ("tomorrow" if soonest == 1 else "in %d days" % soonest)
    return {"subject": "Session %s: its data may be deleted %s" % (session["name"], when),
            "body": "\n\n".join(body) + "\n"}


class FacilityRetention:
    def __init__(self, db):
        self.db = db
        self.mapper = FacilityRetentionPostgresqlMapper(db)

    def _settings(self) -> Dict[str, Any]:
        return FacilitySettingsService(self.db).values()

    def _withState(self, session: Dict[str, Any], settings: Dict[str, Any], on: datetime.date) -> Dict[str, Any]:
        session = dict(session)
        notices = session.pop("retentionNotices", None) or {}
        for kind in KINDS:
            session[kind] = retentionState(session, kind, settings, on)
            given = notices.get(kind) or {}
            session[kind]["noticesSent"] = (given.get("sent") or []) if given.get("until") == session[kind]["until"] \
                else []
        for key in ("rawKeepUntil", "processedKeepUntil", "rawDeletedAt", "processedDeletedAt", "rawDeletedByName",
                    "rawDeletedByEmail", "processedDeletedByName", "processedDeletedByEmail"):
            session.pop(key, None)
        for project in session.get("projects") or []:
            # The project's name, not its folder's path
            project["name"] = str(project.get("name") or "").rstrip("/").split("/")[-1]
        return session

    def listRetention(self) -> Dict[str, Any]:
        """The finished sessions with until when each kind of their data is kept, the soonest first."""
        settings = self._settings()
        on = today(settings["timezone"])
        sessions = [self._withState(row, settings, on) for row in self.mapper.listFinished(settings["timezone"])]

        def soonest(session):
            days = [session[kind]["daysLeft"] for kind in KINDS if session[kind]["state"] in ("due", "expired", "kept")
                    and session[kind]["daysLeft"] is not None]
            return (min(days) if days else 10 ** 6, session["id"])

        sessions.sort(key=soonest)
        return {"sessions": sessions, "today": on.isoformat(),
                "rawRetentionDays": settings["rawRetentionDays"],
                "processedRetentionDays": settings["processedRetentionDays"],
                "retentionNoticeDays": settings["retentionNoticeDays"]}

    def getRetention(self, sessionId: int) -> Dict[str, Any]:
        settings = self._settings()
        rows = self.mapper.listFinished(settings["timezone"], sessionId)
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="No finished session with that id (only those have their data kept a time)")
        return self._withState(rows[0], settings, today(settings["timezone"]))

    def _raw(self, sessionId: int) -> Dict[str, Any]:
        rows = self.mapper.listFinished(self._settings()["timezone"], sessionId)
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="No finished session with that id (only those have their data kept a time)")
        return rows[0]

    def setKeepUntil(self, sessionId: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Give a session its own dates (None: the facility's days); its user is told again before them."""
        session = self._raw(sessionId)
        dates = {}
        for kind in KINDS:
            key = kind + "KeepUntil"
            dates[kind] = _asDate(payload.get(key)) if key in payload else session.get(key)
            if dates[kind] is not None and _asDate(session.get("finishedOn")) and \
                    dates[kind] < _asDate(session["finishedOn"]):
                raise _badRequest("A date to keep the data until is after the session finished (%s)"
                                  % session["finishedOn"])
        self.mapper.saveKeepUntil(sessionId, dates["raw"], dates["processed"])
        return self.getRetention(sessionId)

    def _archiveIfGone(self, sessionId: int) -> None:
        session = self._raw(sessionId)
        if session.get("rawDeletedAt") and (session.get("processedDeletedAt") or not session.get("projects")):
            self.mapper.archive(sessionId)

    def markRawDeleted(self, sessionId: int, userId: Optional[int]) -> Dict[str, Any]:
        """Record that a session's raw data were deleted where the facility keeps them (ScipionWeb does not)."""
        session = self._raw(sessionId)
        if session.get("rawDeletedAt"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Its raw data are recorded as deleted")
        self.mapper.markDeleted(sessionId, "raw", userId)
        self._archiveIfGone(sessionId)
        return self.getRetention(sessionId)

    def unmarkRawDeleted(self, sessionId: int) -> Dict[str, Any]:
        """Undo a record of deleted raw data made by mistake (it only records: nothing comes back)."""
        self._raw(sessionId)
        self.mapper.unmarkRawDeleted(sessionId)
        return self.getRetention(sessionId)

    def deleteProjects(self, sessionId: int, currentUser: Dict[str, Any]) -> Dict[str, Any]:
        """Delete the projects of a session's DATA, as the user (who must be able to manage each one); the
        session records it once none is left. Answers the session and the projects that could not go."""
        from app.backend.api.services.project_service import ProjectService
        from app.backend.mapper.postgresql import PostgresqlFlatMapper

        session = self._raw(sessionId)
        projects = session.get("projects") or []
        if not projects:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This session has no project left")
        service, mapper = ProjectService(), PostgresqlFlatMapper(self.db)
        deleted, failed = [], []
        for project in projects:
            name = str(project.get("name") or "").rstrip("/").split("/")[-1]
            try:
                service.deleteProject(mapper, currentUser, int(project["id"]))
                deleted.append({"id": project["id"], "name": name})
            except HTTPException as error:
                failed.append({"id": project["id"], "name": name, "detail": str(error.detail)})
            except Exception as error:
                logger.exception("Could not delete project %s of session %s", project["id"], sessionId)
                failed.append({"id": project["id"], "name": name, "detail": str(error)})
        if not failed:
            self.mapper.markDeleted(sessionId, "processed", currentUser.get("id"))
            self._archiveIfGone(sessionId)
        return {"session": self.getRetention(sessionId), "deleted": deleted, "failed": failed}

    # Notices -------------------------------------------------------------------------------------------
    def sendNotices(self, on: Optional[datetime.date] = None) -> List[Dict[str, Any]]:
        """Tell each session's user (and its group's PIs) the notices they are owed; answers what was told.

        A notice goes through the users' notifications: in the web, and mailed (it is mandatory: instantly or in
        the digest; it waits there while there is no mail server)."""
        from app.backend.api.services.notifications import Notifications

        settings = self._settings()
        on = on or today(settings["timezone"])
        notifications = Notifications(self.db)
        told = []
        for session in self.mapper.listFinished(settings["timezone"]):
            owed = noticesDue(session, settings, on)
            if not owed:
                continue
            userIds = self.mapper.noticeRecipients(session.get("userId"), session.get("groupId"))
            if userIds:
                text = noticeText(session, owed, settings.get("downloadInstructions") or "")
                notifications.notify(userIds, "facility.retention", text["subject"], text["body"], "/facility/mine")
                told.append({"sessionId": session["id"], "userIds": userIds, "kinds": sorted(owed)})
            # With nobody to tell (no user, no PI) the notice is taken as given: it would be owed for ever
            notices = dict(session.get("retentionNotices") or {})
            for kind, (until, _, days) in owed.items():
                previous = notices.get(kind) or {}
                already = (previous.get("sent") or []) if previous.get("until") == until else []
                notices[kind] = {"until": until, "sent": sorted(set(already) | set(days), reverse=True),
                                 "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
            self.mapper.saveNotices(session["id"], notices)
        return told


def sendNoticesNow(db, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """The watcher's turn: send the owed notices at most every NOTICE_EVERY_SECONDS (never fails)."""
    global _lastNoticeAt
    now = time.time() if now is None else now
    with _noticeLock:
        if now - _lastNoticeAt < NOTICE_EVERY_SECONDS:
            return []
        _lastNoticeAt = now
    try:
        return FacilityRetention(db).sendNotices()
    except Exception:
        logger.warning("Could not send the facility's retention notices", exc_info=True)
        return []
