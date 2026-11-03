"""The screen of the microscopes' room: each microscope's state and session, readable from across the room.

It is opened with a link (``/room?token=``) the facility's managers make, so the screen needs no signed-in
user: whoever has the link sees it, and a new link (or none) stops the old one. It shows names and states only:
no paths, projects, notes nor mail addresses.

A microscope is acquiring (a session acquiring on it), preparing (one planned for today), idle, in
maintenance or out of service (its status). The sessions planned for the next days come after, while the
facility has no booking calendar.
"""
import datetime
import secrets
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.api.services.facility_alerts import FacilityAlerts
from app.backend.api.services.facility_session_service import FacilitySessionService
from app.backend.mapper.facility_microscope_mapper import FacilityMicroscopePostgresqlMapper
from app.backend.mapper.facility_settings_mapper import FacilitySettingsPostgresqlMapper

ROOM_KEY = "roomScreen"
UPCOMING_DAYS = 7


def _name(user: Optional[Dict[str, Any]]) -> Optional[str]:
    """A person on the screen: their name, never their address (the part before @ when they have no name)."""
    if not user:
        return None
    full = "%s %s" % (user.get("firstName") or "", user.get("lastName") or "")
    return full.strip() or str(user.get("email") or "").split("@")[0] or None


def _day(value: Any) -> Optional[datetime.date]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class FacilityRoom:
    def __init__(self, db):
        self.db = db
        self.settings = FacilitySettingsPostgresqlMapper(db)

    # The link ------------------------------------------------------------------------------------------
    def _token(self) -> str:
        return str((self.settings.getSettings().get(ROOM_KEY) or {}).get("token") or "")

    def link(self) -> Dict[str, Any]:
        """The screen's link, for the facility's managers (no token: the screen is off)."""
        stored = self.settings.getSettings().get(ROOM_KEY) or {}
        return {"enabled": bool(stored.get("token")), "token": stored.get("token") or None,
                "createdAt": stored.get("createdAt")}

    def newLink(self, userId: Optional[int]) -> Dict[str, Any]:
        """A new link; the old one stops working."""
        self.settings.saveSettings({ROOM_KEY: {"token": secrets.token_urlsafe(32),
                                               "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat()}},
                                   userId)
        return self.link()

    def turnOff(self, userId: Optional[int]) -> Dict[str, Any]:
        self.settings.saveSettings({ROOM_KEY: {}}, userId)
        return self.link()

    def checkToken(self, token: Optional[str]) -> None:
        """404, as if there were no screen, for a missing or wrong token (or a screen turned off)."""
        expected = self._token()
        if not expected or not token or not secrets.compare_digest(str(token), expected):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such screen")

    # What it shows -------------------------------------------------------------------------------------
    def view(self, today: Optional[datetime.date] = None) -> Dict[str, Any]:
        sessions = FacilitySessionService(self.db)
        today = today or datetime.date.today()
        people: Dict[int, Optional[str]] = {}

        def person(userId: Optional[int]) -> Optional[str]:
            if userId is None:
                return None
            if int(userId) not in people:
                people[int(userId)] = _name(sessions.mapper.getUser(int(userId)))
            return people[int(userId)]

        pis: Dict[int, Optional[str]] = {}

        def pi(groupId: Optional[int]) -> Optional[str]:
            if groupId is None:
                return None
            if int(groupId) not in pis:
                pis[int(groupId)] = _name(sessions.mapper.getGroupPi(int(groupId)))
            return pis[int(groupId)]

        alertsBySession: Dict[int, List[Dict[str, Any]]] = {}
        for alert in FacilityAlerts(self.db).listAlerts():
            alertsBySession.setdefault(int(alert["sessionId"]), []).append(
                {"kind": alert["kind"], "folder": alert["folder"], "taken": bool(alert["acknowledgedAt"])})

        def shown(session: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "name": session["name"], "technique": session["technique"], "status": session["status"],
                "scheduledOn": str(session["scheduledOn"]) if session.get("scheduledOn") else None,
                "startedAt": session.get("startedAt"), "technician": person(session.get("createdBy")),
                "user": session.get("userName") or None, "pi": pi(session.get("groupId")),
                "group": session.get("groupName"),
                "datasets": [{"number": dataset["number"], "folder": dataset["folder"], "watch": dataset.get("watch"),
                              "movieCount": dataset.get("movieCount") or 0,
                              "minutesSinceLastMovie": dataset.get("minutesSinceLastMovie"),
                              "processing": (dataset.get("processing") or {}).get("state"),
                              "sample": ((dataset.get("grid") or {}).get("sampleCode"))}
                             for dataset in session.get("datasets") or [] if dataset["kind"] == "data"],
                "alerts": alertsBySession.get(int(session["id"]), []),
            }

        active = sessions.listSessions(["acquiring", "planned"])
        microscopes = []
        for microscope in FacilityMicroscopePostgresqlMapper(self.db).listMicroscopes():
            mine = [session for session in active if int(session["microscopeId"]) == int(microscope["id"])]
            acquiring = [session for session in mine if session["status"] == "acquiring"]
            preparing = [session for session in mine if session["status"] == "planned"
                         and _day(session.get("scheduledOn")) in (today, None)]
            if microscope["status"] == "out_of_service":
                state, current = "outOfService", None
            elif microscope["status"] == "maintenance":
                state, current = "maintenance", None
            elif acquiring:
                state, current = "acquiring", acquiring[0]
            elif preparing:
                state, current = "preparing", preparing[0]
            else:
                state, current = "idle", None
            microscopes.append({"id": microscope["id"], "name": microscope["name"], "code": microscope.get("code") or "",
                                "state": state, "photoVersion": microscope.get("photoUpdatedAt"),
                                "session": shown(current) if current else None})

        upcoming = []
        horizon = today + datetime.timedelta(days=UPCOMING_DAYS)
        for session in active:
            day = _day(session.get("scheduledOn"))
            if session["status"] == "planned" and day is not None and today < day <= horizon:
                upcoming.append({"day": day.isoformat(), "microscope": session["microscopeName"],
                                 "name": session["name"], "technique": session["technique"],
                                 "user": session.get("userName") or None, "pi": pi(session.get("groupId"))})
        upcoming.sort(key=lambda item: (item["day"], item["microscope"]))
        return {"now": datetime.datetime.now(datetime.timezone.utc).isoformat(), "microscopes": microscopes,
                "upcoming": upcoming}

    def photo(self, microscopeId: int) -> Dict[str, Any]:
        photo = FacilityMicroscopePostgresqlMapper(self.db).getPhoto(microscopeId)
        if photo is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No photo")
        return photo
