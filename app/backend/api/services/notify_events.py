"""What tells the users of what happened: each event, who hears of it and what it says.

Each function is called where the event happens and never fails it: a notice that cannot be kept is only logged.
The notices go through ``Notifications.notify`` (each user's channel decides how they arrive).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.backend.mapper.notifications_mapper import NotificationsPostgresqlMapper

logger = logging.getLogger(__name__)

# A run that finishes after this long is told (to who chose to hear of it)
LONG_RUN_MINUTES = 30


def _notify(db, userIds: Iterable[Optional[int]], kind: str, title: str, body: str = "", link: str = "") -> List[int]:
    from app.backend.api.services.notifications import Notifications

    ids = sorted({int(userId) for userId in userIds if userId is not None})
    if not ids:
        return []
    try:
        return Notifications(db).notify(ids, kind, title, body, link)
    except Exception:
        logger.warning("Could not keep the %s notice", kind, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return []


def _name(person: Optional[Dict[str, Any]]) -> str:
    if not person:
        return "someone"
    full = "%s %s" % (person.get("firstName") or "", person.get("lastName") or "")
    return full.strip() or str(person.get("email") or "someone")


def _projectName(path: Any) -> str:
    return str(path or "").rstrip("/").split("/")[-1]


# Accounts ------------------------------------------------------------------------------------------------
def accountActivated(db, userId: int) -> List[int]:
    return _notify(db, [userId], "account.activated", "Your ScipionWeb account is active",
                   "An administrator activated your account: you can sign in now.", "/home")


# Projects ------------------------------------------------------------------------------------------------
def projectShared(db, sharer: Dict[str, Any], projectId: int, projectPath: Any, userIds: Iterable[int],
                  groupIds: Iterable[int], level: Optional[str]) -> List[int]:
    """Tell the users a project was shared with (and the members of the groups), but the one who shared it."""
    try:
        members = NotificationsPostgresqlMapper(db).groupMemberIds(list(groupIds or []))
    except Exception:
        logger.warning("Could not read the members of groups %s", groupIds, exc_info=True)
        members = []
    targets = (set(userIds or []) | set(members)) - {int(sharer["id"])}
    words = {"view": "to see", "work": "to work on", "manage": "to manage"}.get(str(level or ""), "")
    name = _projectName(projectPath)
    return _notify(db, targets, "project.shared", "%s shared the project %s with you" % (_name(sharer), name),
                   "%s shared the project %s with you%s." % (_name(sharer), name, " " + words if words else ""),
                   "/project/load/%d" % int(projectId))


def runEnded(db, runId: int, status: str) -> List[int]:
    """A protocol run ended: a failure is told to who launched it and the project's owner; a long run that
    finished, to who launched it."""
    try:
        run = NotificationsPostgresqlMapper(db).runOf(int(runId))
    except Exception:
        logger.warning("Could not read run %s", runId, exc_info=True)
        return []
    if not run:
        return []
    label = run.get("protocolLabel") or run.get("protocolClassName") or "A protocol"
    project = _projectName(run.get("projectPath"))
    link = "/project/load/%s?protocol=%s" % (run["projectId"], run["protocolId"]) if run.get("projectId") else ""
    status = str(status or "").lower()
    if status == "failed":
        return _notify(db, [run.get("userId"), run.get("ownerId")], "protocol.failed",
                       "%s failed in %s" % (label, project),
                       "The protocol %s (%s) failed in the project %s. Its log says why." % (
                           label, run.get("protocolClassName") or "", project), link)
    if status == "finished":
        started, ended = run.get("startedAt"), run.get("endedAt") or datetime.now(timezone.utc)
        minutes = (ended - started).total_seconds() / 60 if started else 0
        if minutes >= LONG_RUN_MINUTES:
            return _notify(db, [run.get("userId")], "protocol.finished", "%s finished in %s" % (label, project),
                           "The protocol %s finished in the project %s after %d minutes." % (
                               label, project, int(minutes)), link)
    return []


# The facility ---------------------------------------------------------------------------------------------
def _sessionPeople(db, session: Dict[str, Any]) -> List[int]:
    """A session's user and the PIs of its group."""
    from app.backend.mapper.facility_retention_mapper import FacilityRetentionPostgresqlMapper

    return FacilityRetentionPostgresqlMapper(db).noticeRecipients(session.get("userId"), session.get("groupId"))


def sessionChanged(db, before: Optional[Dict[str, Any]], session: Dict[str, Any]) -> List[int]:
    """A session started acquiring or finished: its user and the group's PIs hear of it."""
    previous = (before or {}).get("status")
    current = session.get("status")
    if previous == current or current not in ("acquiring", "finished"):
        return []
    try:
        people = _sessionPeople(db, session)
    except Exception:
        logger.warning("Could not read who session %s is for", session.get("id"), exc_info=True)
        return []
    where = session.get("microscopeName") or "the microscope"
    if current == "acquiring":
        title = "Your session %s started on %s" % (session["name"], where)
        body = "The acquisition of your session %s started on %s. Follow it in ScipionWeb, Facility, My sessions." % (
            session["name"], where)
    else:
        title = "Your session %s finished" % session["name"]
        body = ("The acquisition of your session %s on %s finished. Its data and how long they are kept are in "
                "ScipionWeb, Facility, My sessions." % (session["name"], where))
    return _notify(db, people, "facility.session", title, body, "/facility/mine")


def processingLaunched(db, row: Dict[str, Any], projectId: Optional[int]) -> List[int]:
    """A DATA's project was made and launched: its session's people can follow it."""
    try:
        people = _sessionPeople(db, row)
    except Exception:
        logger.warning("Could not read who session %s is for", row.get("sessionId"), exc_info=True)
        return []
    folder = row.get("folder") or "a DATA"
    return _notify(db, people, "facility.processing", "%s is being processed" % folder,
                   "The data of %s (session %s) are being processed: its monitor shows them as they come." % (
                       folder, row.get("sessionName") or ""),
                   "/project/%d/monitor" % int(projectId) if projectId else "/facility/mine")


def bookingRequested(db, booking: Dict[str, Any], when: str = "") -> List[int]:
    """A user asked for time: the staff who run sessions hear of it."""
    from app.backend.mapper.facility_alerts_mapper import FacilityAlertsPostgresqlMapper

    try:
        staff = [int(user["id"]) for user in FacilityAlertsPostgresqlMapper(db).usersWithPermission("facility.sessions")]
    except Exception:
        logger.warning("Could not read the facility's staff", exc_info=True)
        return []
    who = booking.get("ownerName") or booking.get("ownerEmail") or "A user"
    staff = [userId for userId in staff if userId != booking.get("ownerId")]
    return _notify(db, staff, "facility.bookingRequest",
                   "%s asks for %s" % (who, booking.get("resourceName") or "a resource"),
                   "%s asks for %s%s. It waits in the Facility's calendar." % (
                       who, booking.get("resourceName") or "a resource", ", " + when if when else ""),
                   "/facility/calendar")
