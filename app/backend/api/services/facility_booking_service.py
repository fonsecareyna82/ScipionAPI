"""The facility's bookings: users ask for time on a resource, the facility decides, moves and blocks.

A user asks for a resource (requested), within its shortest and longest booking and never over a confirmed one.
The facility confirms it, offers another time (alternative: the user accepts or declines it) or rejects it,
always with a reason it may give; it books directly too (confirmed), and blocks a resource for downtime,
maintenance or a special use. Two confirmed bookings or blocks of a resource never overlap: what was confirmed is
moved first. Everything the facility does is audited by the routes, and its user told by mail when the
facility's mail is on.

A confirmed booking of a microscope that runs sessions has its planned session (its user, group and day, the day
it starts on where the facility is); moving the booking moves the session while it is planned, and a booking
cancelled or rejected takes its planned session away. A session under way is never touched.

The facility (facility.sessions or facility.manage) sees everything; a user sees their own bookings and when the
resources are taken, without whose.
"""
import datetime
import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.api.permissions import hasPermission
from app.backend.api.services.facility_settings_service import FacilitySettingsService
from app.backend.mapper.facility_booking_mapper import BOOKING_FIELDS, RESOURCE_FIELDS, FacilityBookingPostgresqlMapper

logger = logging.getLogger(__name__)

KINDS = ("booking", "downtime", "maintenance", "special")
STATUSES = ("requested", "confirmed", "alternative", "rejected", "cancelled")
# Still waiting: for the facility (requested) or for the user (alternative)
OPEN_STATUSES = ("requested", "alternative")
# Over: nothing more is done with them
CLOSED_STATUSES = ("rejected", "cancelled")
UNITS = ("session", "hour", "half_hour", "service")
TECHNIQUES = ("spa", "tomo")
PRIORITIES = (0, 1, 2, 3, 4)
TEXT_LIMIT = 2000
NAME_LIMIT = 100
# The longest a booking or block may be: a mistyped year is not a booking
MAX_DAYS = 366
KIND_TITLES = {"booking": "Booked", "downtime": "Downtime", "maintenance": "Maintenance", "special": "Special use"}
# What a user sees of a time somebody else holds
PUBLIC_FIELDS = ("id", "resourceId", "resourceName", "resourceColor", "kind", "status", "startsAt", "endsAt")


def _badRequest(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _notFound() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such booking")


def isBookingStaff(user: Dict[str, Any]) -> bool:
    """Who decides on bookings: the staff who run sessions and the facility's managers."""
    return hasPermission(user, "facility.sessions") or hasPermission(user, "facility.manage")


def _text(payload: Dict[str, Any], field: str, limit: int = TEXT_LIMIT) -> str:
    value = str(payload.get(field) or "").strip()
    if len(value) > limit:
        raise _badRequest("%s is longer than %d characters" % (field, limit))
    return value


def _optionalId(payload: Dict[str, Any], field: str) -> Optional[int]:
    value = payload.get(field)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise _badRequest("%s must be an id" % field)


def moment(value: Any, field: str) -> datetime.datetime:
    """A moment with its time zone (2026-11-05T09:00:00+01:00, or Z for UTC)."""
    if isinstance(value, datetime.datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            raise _badRequest("%s is missing" % field)
        try:
            parsed = datetime.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        except ValueError:
            raise _badRequest("%s is not a date and time: %s" % (field, text))
    if parsed.tzinfo is None:
        raise _badRequest("%s needs its time zone" % field)
    return parsed


def _hours(start: datetime.datetime, end: datetime.datetime) -> float:
    return (end - start).total_seconds() / 3600.0


def _personName(user: Optional[Dict[str, Any]]) -> str:
    if not user:
        return ""
    return ("%s %s" % (user.get("firstName") or "", user.get("lastName") or "")).strip() or str(user.get("email") or "")


def _format(value: Any) -> str:
    return value.strftime("%Y-%m-%d %H:%M %Z").strip() if isinstance(value, datetime.datetime) else str(value or "")


class FacilityBookingService:
    def __init__(self, db):
        self.db = db
        self.mapper = FacilityBookingPostgresqlMapper(db)

    # Resources ---------------------------------------------------------------------------------
    def listResources(self, user: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Every resource for the facility; the ones in use for a user."""
        return self.mapper.listResources(activeOnly=not isBookingStaff(user))

    def getResource(self, resourceId: int) -> Dict[str, Any]:
        resource = self.mapper.getResource(resourceId)
        if resource is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such resource")
        return resource

    def saveResource(self, payload: Dict[str, Any], resourceId: Optional[int] = None) -> Dict[str, Any]:
        if resourceId is not None:
            self.getResource(resourceId)
        name = _text(payload, "name", NAME_LIMIT)
        if not name:
            raise _badRequest("A resource needs a name")
        other = self.mapper.findResourceIdByName(name)
        if other is not None and other != resourceId:
            raise _conflict("There is a resource called %s already" % name)
        microscopeId = _optionalId(payload, "microscopeId")
        if microscopeId is not None:
            if not self.mapper.microscopeExists(microscopeId):
                raise _badRequest("Unknown microscope: %s" % microscopeId)
            holder = self.mapper.resourceIdOfMicroscope(microscopeId)
            if holder is not None and holder != resourceId:
                raise _conflict("That microscope is another resource already")
        unit = str(payload.get("unit") or "session")
        if unit not in UNITS:
            raise _badRequest("A resource is charged by %s" % ", ".join(UNITS))
        limits = {}
        for field in ("minHours", "maxHours"):
            value = payload.get(field)
            if value is None or value == "":
                limits[field] = None
                continue
            try:
                limits[field] = float(value)
            except (TypeError, ValueError):
                raise _badRequest("%s is a number of hours" % field)
            if not 0 < limits[field] <= MAX_DAYS * 24:
                raise _badRequest("%s is more than 0 and at most %d hours" % (field, MAX_DAYS * 24))
        if limits["minHours"] is not None and limits["maxHours"] is not None and limits["minHours"] > limits["maxHours"]:
            raise _badRequest("The shortest booking is longer than the longest")
        dayStart = str(payload.get("dayStart") or "09:00").strip()
        try:
            datetime.datetime.strptime(dayStart, "%H:%M")
        except ValueError:
            raise _badRequest("The day starts at a time written HH:MM: %s" % dayStart)
        color = _text(payload, "color", 20)
        values = {"name": name, "microscopeId": microscopeId, "color": color, "unit": unit, **limits,
                  "dayStart": dayStart, "requiresAuthorization": bool(payload.get("requiresAuthorization")),
                  "active": bool(payload.get("active", True)), "notes": _text(payload, "notes")}
        assert set(values) == set(RESOURCE_FIELDS)
        return self.getResource(self.mapper.saveResource(values, resourceId))

    def deleteResource(self, resourceId: int) -> Dict[str, Any]:
        """A resource with bookings stays (its history): it is set out of use instead."""
        resource = self.getResource(resourceId)
        if self.mapper.resourceHasBookings(resourceId):
            raise _conflict("%s has bookings: set it out of use instead" % resource["name"])
        self.mapper.deleteResource(resourceId)
        return resource

    # Reading -----------------------------------------------------------------------------------
    def _shownTo(self, booking: Dict[str, Any], user: Dict[str, Any], staff: bool) -> Dict[str, Any]:
        mine = booking.get("ownerId") is not None and int(booking["ownerId"]) == int(user["id"])
        if staff or mine:
            return dict(booking, mine=mine)
        shown = {field: booking.get(field) for field in PUBLIC_FIELDS}
        shown.update(title=KIND_TITLES[booking["kind"]], mine=False)
        return shown

    def listBookings(self, user: Dict[str, Any], start=None, end=None, resourceIds: Optional[List[int]] = None,
                     statuses: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """The bookings in a time. A user sees all of theirs and the confirmed ones of the others, without whose."""
        for value in statuses or []:
            if value not in STATUSES:
                raise _badRequest("Unknown booking status: %s" % value)
        start = moment(start, "start") if start else None
        end = moment(end, "end") if end else None
        staff = isBookingStaff(user)
        rows = self.mapper.listBookings(start, end, resourceIds, statuses)
        if not staff:
            rows = [row for row in rows if row["status"] == "confirmed"
                    or (row.get("ownerId") is not None and int(row["ownerId"]) == int(user["id"]))]
        return [self._shownTo(row, user, staff) for row in rows]

    def myBookings(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """A user's bookings, with the groups they may book for."""
        return {"bookings": [dict(row, mine=True) for row in self.mapper.listBookings(ownerId=int(user["id"]))],
                "groups": self.mapper.groupsOf(int(user["id"]))}

    def getBooking(self, bookingId: int) -> Dict[str, Any]:
        booking = self.mapper.getBooking(bookingId)
        if booking is None:
            raise _notFound()
        return booking

    def bookingFor(self, bookingId: int, user: Dict[str, Any]) -> Dict[str, Any]:
        booking = self.getBooking(bookingId)
        staff = isBookingStaff(user)
        if not staff and booking["status"] != "confirmed" and not self._owns(booking, user):
            raise _notFound()
        return self._shownTo(booking, user, staff)

    @staticmethod
    def _owns(booking: Dict[str, Any], user: Dict[str, Any]) -> bool:
        return booking.get("ownerId") is not None and int(booking["ownerId"]) == int(user["id"])

    # Checks ------------------------------------------------------------------------------------
    def _times(self, payload: Dict[str, Any], prefix: str = ""):
        startField, endField = (prefix + "StartsAt", prefix + "EndsAt") if prefix else ("startsAt", "endsAt")
        start = moment(payload.get(startField), startField)
        end = moment(payload.get(endField), endField)
        if end <= start:
            raise _badRequest("It ends before it starts")
        if _hours(start, end) > MAX_DAYS * 24:
            raise _badRequest("A booking is at most %d days" % MAX_DAYS)
        return start, end

    @staticmethod
    def _withinLimits(resource: Dict[str, Any], start: datetime.datetime, end: datetime.datetime) -> None:
        """A user's request lasts what the resource allows (the facility books as it needs)."""
        hours = _hours(start, end)
        if resource.get("minHours") and hours + 1e-6 < float(resource["minHours"]):
            raise _badRequest("%s is booked for %g hours at least" % (resource["name"], float(resource["minHours"])))
        if resource.get("maxHours") and hours - 1e-6 > float(resource["maxHours"]):
            raise _badRequest("%s is booked for %g hours at most" % (resource["name"], float(resource["maxHours"])))

    def _free(self, resourceId: int, start, end, bookingId: Optional[int] = None) -> None:
        """409 when a confirmed booking or block of the resource takes some of the time."""
        taken = self.mapper.overlaps(resourceId, start, end, bookingId)
        if taken:
            first = taken[0]
            raise _conflict("That time is taken: %s from %s to %s%s" % (
                KIND_TITLES[first["kind"]].lower(), _format(first["startsAt"]), _format(first["endsAt"]),
                " (and %d more)" % (len(taken) - 1) if len(taken) > 1 else ""))

    def _people(self, payload: Dict[str, Any], user: Dict[str, Any], staff: bool, kind: str):
        """Who a booking is for and its group: the user themselves (one of their groups), or whom the facility says."""
        if staff:
            ownerId = _optionalId(payload, "ownerId")
            if ownerId is not None and self.mapper.getUser(ownerId) is None:
                raise _badRequest("Unknown user: %s" % ownerId)
            if ownerId is None and kind == "booking" and "ownerId" not in payload:
                ownerId = int(user["id"])
            groupId = _optionalId(payload, "groupId")
            if groupId is not None and not self.mapper.groupExists(groupId):
                raise _badRequest("Unknown group: %s" % groupId)
            operatorId = _optionalId(payload, "operatorId")
            if operatorId is not None and self.mapper.getUser(operatorId) is None:
                raise _badRequest("Unknown user: %s" % operatorId)
            return ownerId, groupId, operatorId
        groups = self.mapper.groupsOf(int(user["id"]))
        groupId = _optionalId(payload, "groupId")
        if groupId is None:
            groupId = groups[0]["id"] if groups else None
        elif groupId not in [group["id"] for group in groups]:
            raise _badRequest("You book for one of your groups")
        return int(user["id"]), groupId, None

    def _priority(self, payload: Dict[str, Any], current: Optional[int]) -> Optional[int]:
        value = payload.get("priority", current)
        if value is None or value == "":
            return None
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise _badRequest("The priority is 0 (the facility) to 4 (external)")
        if value not in PRIORITIES:
            raise _badRequest("The priority is 0 (the facility) to 4 (external)")
        return value

    # Saving ------------------------------------------------------------------------------------
    def create(self, payload: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
        """A user's request, or a booking or block the facility makes (confirmed at once)."""
        staff = isBookingStaff(user)
        resourceId = _optionalId(payload, "resourceId")
        resource = self.getResource(resourceId) if resourceId is not None else None
        if resource is None:
            raise _badRequest("A booking needs a resource")
        kind = str(payload.get("kind") or "booking")
        if kind not in KINDS:
            raise _badRequest("Unknown kind of booking: %s" % kind)
        if not staff and kind != "booking":
            raise _forbidden("Only the facility blocks a resource")
        if not resource["active"] and not staff:
            raise _badRequest("%s is not in use" % resource["name"])
        start, end = self._times(payload)
        now = datetime.datetime.now(datetime.timezone.utc)
        if not staff:
            if start <= now:
                raise _badRequest("A request is for a time still to come")
            self._withinLimits(resource, start, end)
        ownerId, groupId, operatorId = self._people(payload, user, staff, kind)
        technique = self._technique(payload, resource, kind)
        values = {
            "resourceId": resource["id"], "kind": kind, "status": "confirmed" if staff else "requested",
            "startsAt": start, "endsAt": end, "proposedStartsAt": None, "proposedEndsAt": None,
            "title": _text(payload, "title", 200), "ownerId": ownerId, "groupId": groupId, "operatorId": operatorId,
            "technique": technique, "priority": self._priority(payload, 0 if staff and kind != "booking" else None)
            if staff else None,
            "justification": _text(payload, "justification"), "notes": _text(payload, "notes") if staff else "",
            "requestedBy": int(user["id"]), "decidedBy": int(user["id"]) if staff else None,
            "decidedAt": now if staff else None, "decisionReason": "", "sessionId": None,
        }
        assert set(values) == set(BOOKING_FIELDS)
        with self.db.transaction():
            self.mapper.lockResource(resource["id"])
            self._free(resource["id"], start, end)
            bookingId = self.mapper.insertBooking(values)
            booking = self._syncSession(self.getBooking(bookingId), user)
        return booking

    @staticmethod
    def _technique(payload: Dict[str, Any], resource: Dict[str, Any], kind: str) -> Optional[str]:
        if kind != "booking" or resource.get("microscopeId") is None:
            return None
        technique = str(payload.get("technique") or "spa")
        if technique not in TECHNIQUES:
            raise _badRequest("Unknown technique: %s" % technique)
        return technique

    def update(self, bookingId: int, payload: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
        """The facility changes anything of a booking not over; a user, their request while it waits."""
        booking = self.getBooking(bookingId)
        staff = isBookingStaff(user)
        if not staff:
            if not self._owns(booking, user):
                raise _notFound() if booking["status"] != "confirmed" else _forbidden("This booking is not yours")
            if booking["status"] != "requested":
                raise _conflict("Only a request still waiting can be changed: cancel it and ask again")
        if booking["status"] in CLOSED_STATUSES:
            raise _conflict("This booking is %s" % booking["status"])
        resourceId = _optionalId(payload, "resourceId") or booking["resourceId"]
        resource = self.getResource(resourceId)
        kind = str(payload.get("kind") or booking["kind"]) if staff else "booking"
        if kind not in KINDS:
            raise _badRequest("Unknown kind of booking: %s" % kind)
        start, end = self._times(dict({"startsAt": booking["startsAt"], "endsAt": booking["endsAt"]},
                                      **{key: payload[key] for key in ("startsAt", "endsAt") if payload.get(key)}))
        if not staff:
            if start <= datetime.datetime.now(datetime.timezone.utc):
                raise _badRequest("A request is for a time still to come")
            self._withinLimits(resource, start, end)
        people = {key: payload.get(key, booking.get(key)) for key in ("ownerId", "groupId", "operatorId")}
        ownerId, groupId, operatorId = self._people(people, user, staff, kind)
        values = {field: booking.get(field) for field in BOOKING_FIELDS}
        values.update(resourceId=resource["id"], kind=kind, startsAt=start, endsAt=end, ownerId=ownerId,
                      groupId=groupId, operatorId=operatorId, title=_text(dict(booking, **payload), "title", 200),
                      technique=self._technique(dict(booking, **payload), resource, kind),
                      justification=_text(dict(booking, **payload), "justification"))
        if staff:
            values.update(notes=_text(dict(booking, **payload), "notes"),
                          priority=self._priority(payload, booking.get("priority")))
        with self.db.transaction():
            self.mapper.lockResource(resource["id"])
            if values["status"] == "confirmed":
                self._free(resource["id"], start, end, bookingId)
            self.mapper.updateBooking(bookingId, values)
            saved = self._syncSession(self.getBooking(bookingId), user)
        return saved

    def decide(self, bookingId: int, payload: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
        """The facility's answer to a request: confirm, alternative (another time) or reject, with a reason."""
        booking = self.getBooking(bookingId)
        if booking["status"] not in OPEN_STATUSES:
            raise _conflict("This booking is %s: there is nothing to decide" % booking["status"])
        action = str(payload.get("action") or "")
        values = {field: booking.get(field) for field in BOOKING_FIELDS}
        values.update(decidedBy=int(user["id"]), decidedAt=datetime.datetime.now(datetime.timezone.utc),
                      decisionReason=_text(payload, "reason"),
                      priority=self._priority(payload, booking.get("priority")))
        with self.db.transaction():
            self.mapper.lockResource(booking["resourceId"])
            if action == "confirm":
                self._free(booking["resourceId"], booking["startsAt"], booking["endsAt"], bookingId)
                values.update(status="confirmed", proposedStartsAt=None, proposedEndsAt=None)
            elif action == "propose":
                start, end = self._times(payload, "proposed")
                self._free(booking["resourceId"], start, end, bookingId)
                values.update(status="alternative", proposedStartsAt=start, proposedEndsAt=end)
            elif action == "reject":
                values.update(status="rejected", proposedStartsAt=None, proposedEndsAt=None)
            else:
                raise _badRequest("The facility confirms, proposes another time or rejects")
            self.mapper.updateBooking(bookingId, values)
            saved = self._syncSession(self.getBooking(bookingId), user)
        return saved

    def answer(self, bookingId: int, accept: bool, user: Dict[str, Any]) -> Dict[str, Any]:
        """The user takes the time the facility offered (confirmed) or does not (cancelled)."""
        booking = self.getBooking(bookingId)
        if not self._owns(booking, user):
            raise _notFound()
        if booking["status"] != "alternative":
            raise _conflict("The facility has offered no other time for this booking")
        values = {field: booking.get(field) for field in BOOKING_FIELDS}
        with self.db.transaction():
            self.mapper.lockResource(booking["resourceId"])
            if accept:
                self._free(booking["resourceId"], booking["proposedStartsAt"], booking["proposedEndsAt"], bookingId)
                values.update(status="confirmed", startsAt=booking["proposedStartsAt"],
                              endsAt=booking["proposedEndsAt"], proposedStartsAt=None, proposedEndsAt=None)
            else:
                values.update(status="cancelled")
            self.mapper.updateBooking(bookingId, values)
            saved = self._syncSession(self.getBooking(bookingId), user)
        return saved

    def cancel(self, bookingId: int, reason: str, user: Dict[str, Any]) -> Dict[str, Any]:
        """A user cancels their booking before it starts; the facility, any not over (its reason is kept)."""
        booking = self.getBooking(bookingId)
        staff = isBookingStaff(user)
        if not staff:
            if not self._owns(booking, user):
                raise _notFound() if booking["status"] != "confirmed" else _forbidden("This booking is not yours")
            if booking["startsAt"] <= datetime.datetime.now(datetime.timezone.utc):
                raise _conflict("It has started: ask the facility")
        if booking["status"] in CLOSED_STATUSES:
            raise _conflict("This booking is %s already" % booking["status"])
        values = {field: booking.get(field) for field in BOOKING_FIELDS}
        values.update(status="cancelled", proposedStartsAt=None, proposedEndsAt=None)
        if staff:
            values.update(decidedBy=int(user["id"]), decidedAt=datetime.datetime.now(datetime.timezone.utc),
                          decisionReason=str(reason or "").strip()[:TEXT_LIMIT])
        with self.db.transaction():
            self.mapper.updateBooking(bookingId, values)
            saved = self._syncSession(self.getBooking(bookingId), user)
        return saved

    # The session of a booking --------------------------------------------------------------------
    def _syncSession(self, booking: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
        """Give a confirmed booking of a microscope that runs sessions its planned session, keep it with the
        booking while it is planned, and take it away when the booking no longer holds."""
        from app.backend.api.services.facility_session_service import FacilitySessionService

        sessions = FacilitySessionService(self.db)
        resource = self.getResource(booking["resourceId"])
        wanted = (booking["status"] == "confirmed" and booking["kind"] == "booking"
                  and resource.get("microscopeId") is not None and resource.get("runsSessions"))
        session = sessions.mapper.getSession(booking["sessionId"]) if booking.get("sessionId") else None
        if session is not None and session["status"] != "planned":
            # Under way or over: what happens to it is the staff's, in the session
            return booking
        if session is not None and (not wanted or int(session["microscopeId"]) != int(resource["microscopeId"])):
            self.mapper.updateBooking(booking["id"], dict({field: booking.get(field) for field in BOOKING_FIELDS},
                                                          sessionId=None))
            sessions.mapper.deleteSession(session["id"])
            session = None
            booking = self.getBooking(booking["id"])
        if not wanted:
            return booking
        settings = FacilitySettingsService(self.db).values()
        day = self.mapper.localDate(booking["startsAt"], settings["timezone"])
        if session is None:
            payload = {"microscopeId": resource["microscopeId"], "technique": booking.get("technique") or "spa",
                       "status": "planned", "groupId": booking.get("groupId"), "userId": booking.get("ownerId"),
                       "scheduledOn": day, "notes": "", "autoProcess": True,
                       "ctfMinDefocus": settings["ctfMinDefocus"], "ctfMaxDefocus": settings["ctfMaxDefocus"],
                       "ctfMaxResolution": settings["ctfMaxResolution"], "datasets": []}
            created = sessions.saveSession(payload, userId=int(user["id"]))
            self.mapper.updateBooking(booking["id"], dict({field: booking.get(field) for field in BOOKING_FIELDS},
                                                          sessionId=created["id"]))
            return self.getBooking(booking["id"])
        if (session.get("scheduledOn") != day or session.get("userId") != booking.get("ownerId")
                or session.get("groupId") != booking.get("groupId")
                or session.get("technique") != (booking.get("technique") or "spa")):
            payload = {key: session.get(key) for key in ("name", "microscopeId", "status", "bookingRef", "notes",
                                                         "templateId", "autoProcess", "oneProject", "userNotes",
                                                         "ctfMinDefocus", "ctfMaxDefocus", "ctfMaxResolution")}
            payload.update(technique=booking.get("technique") or "spa", groupId=booking.get("groupId"),
                           userId=booking.get("ownerId"), scheduledOn=day,
                           datasets=[{key: dataset.get(key) for key in ("id", "kind", "number", "gridId",
                                                                        "detectorId", "notes")}
                                     for dataset in session.get("datasets") or []])
            sessions.saveSession(payload, sessionId=session["id"], userId=int(user["id"]))
        return booking

    # Telling the user ----------------------------------------------------------------------------
    def notify(self, booking: Dict[str, Any], what: str) -> None:
        """Mail the booking's user what the facility did, when the facility's mail is on; never fails."""
        if not booking.get("ownerEmail"):
            return
        from app.backend.api.services.facility_mail import FacilityMail

        mail = FacilityMail(self.db)
        if not mail.getSettings().get("enabled"):
            return
        lines = ["Your booking of %s, %s to %s, %s." % (booking["resourceName"], _format(booking["startsAt"]),
                                                       _format(booking["endsAt"]), what)]
        if booking.get("proposedStartsAt"):
            lines.append("The facility offers %s to %s instead: accept or decline it in ScipionWeb, Facility, "
                         "Calendar." % (_format(booking["proposedStartsAt"]), _format(booking["proposedEndsAt"])))
        if booking.get("decisionReason"):
            lines.append("Reason: %s" % booking["decisionReason"])
        try:
            mail.send("Booking of %s: %s" % (booking["resourceName"], what), "\n\n".join(lines),
                      to=[booking["ownerEmail"]])
        except Exception:
            logger.warning("Could not mail booking %s to its user", booking["id"], exc_info=True)
