"""The facility's resources and bookings, against the migrated database."""
import datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.backend.api.services.facility_booking_service import FacilityBookingService
from app.backend.api.services.facility_service import FacilityService
from app.backend.api.services.facility_session_service import FacilitySessionService
from app.backend.mapper.postgresql import PostgresqlFlatMapper


def _user(db, firstName):
    flat = PostgresqlFlatMapper(db)
    return flat.insertUser(email="booking-%s@example.com" % uuid4().hex, hashedPassword="test", firstName=firstName,
                           lastName="Test", institution=None, role="user", isActive=True, isVerified=True,
                           verificationCode="")


@pytest.fixture
def booking(postgresqlIntegrationDb, postgresqlMigratedEnv, keptSettings):
    """A microscope that runs sessions (with its resource), a plunger, a user in a group, another user and a
    technician; all they make is removed after the test."""
    db = postgresqlIntegrationDb
    microscope = FacilityService(db).saveMicroscope({"name": "Krios %s" % uuid4().hex[:8], "sessionsEnabled": True})
    service = FacilityBookingService(db)
    resources = {resource["microscopeId"]: resource for resource in service.mapper.listResources()}
    krios = service.saveResource(dict(resources[microscope["id"]], minHours=24, maxHours=72),
                                 resources[microscope["id"]]["id"])
    plunger = service.saveResource({"name": "Vitrobot %s" % uuid4().hex[:6], "unit": "hour", "minHours": 1})
    userId, otherId, staffId = _user(db, "Gaoxin"), _user(db, "Marta"), _user(db, "Ana")
    group = db.fetchOne("INSERT INTO user_groups (name) VALUES (%s) RETURNING id", ("Lab %s" % uuid4().hex[:6],))
    db.execute('INSERT INTO user_group_members ("groupId", "userId", "groupRole") VALUES (%s, %s, %s)',
               (group["id"], userId, "member"))
    people = {"user": {"id": userId, "permissions": []}, "other": {"id": otherId, "permissions": []},
              "staff": {"id": staffId, "permissions": ["facility.sessions"]}}
    try:
        yield service, krios, plunger, people, group["id"]
    finally:
        db.execute('DELETE FROM facility_bookings WHERE "resourceId" IN (%s, %s)', (krios["id"], plunger["id"]))
        db.execute('DELETE FROM facility_sessions WHERE "microscopeId" = %s', (microscope["id"],))
        db.execute("DELETE FROM facility_resources WHERE id IN (%s, %s)", (krios["id"], plunger["id"]))
        db.execute("DELETE FROM facility_microscopes WHERE id = %s", (microscope["id"],))
        db.execute("DELETE FROM user_groups WHERE id = %s", (group["id"],))
        db.execute("DELETE FROM users WHERE id IN (%s, %s, %s)", (userId, otherId, staffId))


@pytest.fixture
def keptSettings(postgresqlIntegrationDb):
    from app.backend.mapper.facility_settings_mapper import FacilitySettingsPostgresqlMapper

    db = postgresqlIntegrationDb
    kept = [dict(row) for row in db.fetchAll("SELECT key, value FROM facility_settings") or []]
    try:
        yield
    finally:
        db.execute("DELETE FROM facility_settings")
        for row in kept:
            FacilitySettingsPostgresqlMapper(db).saveSettings({row["key"]: row["value"]}, None)


def _at(days, hour=8, minute=0):
    """A moment some days from now, at an hour UTC (09:00 in Madrid in winter is 08:00 UTC)."""
    day = datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=days)
    return datetime.datetime(day.year, day.month, day.day, hour, minute, tzinfo=datetime.timezone.utc).isoformat()


def _status(call):
    with pytest.raises(HTTPException) as error:
        call()
    return error.value.status_code, error.value.detail


def test_AUserAsksForTimeTheResourceAllowsAndThatIsFree(booking):
    service, krios, plunger, people, groupId = booking
    user = people["user"]

    asked = service.create({"resourceId": krios["id"], "startsAt": _at(10), "endsAt": _at(11), "technique": "tomo"},
                           user)
    assert (asked["status"], asked["ownerId"], asked["groupId"], asked["technique"]) == (
        "requested", user["id"], groupId, "tomo")
    assert asked["sessionId"] is None

    assert _status(lambda: service.create({"resourceId": krios["id"], "startsAt": _at(10), "endsAt": _at(10, 12)},
                                          user)) == (400, "%s is booked for 24 hours at least" % krios["name"])
    assert _status(lambda: service.create({"resourceId": krios["id"], "startsAt": _at(10), "endsAt": _at(14)},
                                          user))[0] == 400
    assert _status(lambda: service.create({"resourceId": krios["id"], "startsAt": _at(-2), "endsAt": _at(-1)},
                                          user)) == (400, "A request is for a time still to come")
    assert _status(lambda: service.create({"resourceId": krios["id"], "startsAt": "2026-12-01T09:00:00",
                                           "endsAt": _at(11)}, user)) == (400, "startsAt needs its time zone")
    assert _status(lambda: service.create({"resourceId": krios["id"], "kind": "maintenance", "startsAt": _at(10),
                                           "endsAt": _at(11)}, user))[0] == 403
    # Another group than theirs
    assert _status(lambda: service.create({"resourceId": krios["id"], "startsAt": _at(20), "endsAt": _at(21),
                                           "groupId": groupId + 100000}, user))[0] == 400

    # Confirmed, the time is taken for everybody
    service.decide(asked["id"], {"action": "confirm"}, people["staff"])
    code, detail = _status(lambda: service.create({"resourceId": krios["id"], "startsAt": _at(10, 20),
                                                   "endsAt": _at(12)}, people["other"]))
    assert code == 409 and detail.startswith("That time is taken: booked from")


def test_AConfirmedBookingOfAMicroscopeHasItsPlannedSessionThatFollowsIt(booking, postgresqlIntegrationDb):
    service, krios, plunger, people, groupId = booking
    user, staff = people["user"], people["staff"]
    sessions = FacilitySessionService(postgresqlIntegrationDb)
    # 23:30 UTC is already the next day in Madrid
    asked = service.create({"resourceId": krios["id"], "startsAt": _at(10, 23, 30), "endsAt": _at(11, 23, 30)}, user)

    confirmed = service.decide(asked["id"], {"action": "confirm", "reason": "Fits"}, staff)
    assert (confirmed["status"], confirmed["decidedBy"], confirmed["decisionReason"]) == ("confirmed", staff["id"],
                                                                                          "Fits")
    session = sessions.getSession(confirmed["sessionId"])
    nextDay = datetime.datetime.fromisoformat(_at(11)).date()
    assert (session["status"], session["userId"], session["groupId"], session["scheduledOn"]) == (
        "planned", user["id"], groupId, nextDay)
    assert (session["ctfMinDefocus"], session["ctfMaxResolution"]) == (5000, 8)

    # The facility moves it: the planned session goes with it
    moved = service.update(asked["id"], {"startsAt": _at(15), "endsAt": _at(16)}, staff)
    assert sessions.getSession(moved["sessionId"])["scheduledOn"] == datetime.datetime.fromisoformat(_at(15)).date()
    assert moved["sessionId"] == confirmed["sessionId"]

    # Cancelled, its planned session goes away
    cancelled = service.cancel(asked["id"], "The microscope broke", staff)
    assert (cancelled["status"], cancelled["sessionId"], cancelled["decisionReason"]) == (
        "cancelled", None, "The microscope broke")
    assert sessions.mapper.getSession(confirmed["sessionId"]) is None


def test_ASessionUnderWayIsNotTouchedByItsBooking(booking, postgresqlIntegrationDb):
    service, krios, plunger, people, groupId = booking
    sessions = FacilitySessionService(postgresqlIntegrationDb)
    made = service.create({"resourceId": krios["id"], "ownerId": people["user"]["id"], "startsAt": _at(3),
                           "endsAt": _at(4)}, people["staff"])
    session = sessions.getSession(made["sessionId"])
    sessions.mapper.db.execute("UPDATE facility_sessions SET status = 'acquiring' WHERE id = %s", (session["id"],))

    service.cancel(made["id"], "", people["staff"])

    assert sessions.getSession(session["id"])["status"] == "acquiring"


def test_TheFacilityOffersAnotherTimeThatTheUserTakesOrNot(booking):
    service, krios, plunger, people, groupId = booking
    user, staff = people["user"], people["staff"]
    asked = service.create({"resourceId": plunger["id"], "startsAt": _at(5, 9), "endsAt": _at(5, 11)}, user)

    offered = service.decide(asked["id"], {"action": "propose", "proposedStartsAt": _at(6, 9),
                                           "proposedEndsAt": _at(6, 11), "reason": "Busy that morning"}, staff)
    assert offered["status"] == "alternative" and offered["proposedStartsAt"] is not None
    assert _status(lambda: service.answer(asked["id"], True, people["other"]))[0] == 404

    taken = service.answer(asked["id"], True, user)
    assert taken["status"] == "confirmed" and taken["proposedStartsAt"] is None
    assert taken["startsAt"] == datetime.datetime.fromisoformat(_at(6, 9))
    # A plunger has no sessions
    assert taken["sessionId"] is None

    second = service.create({"resourceId": plunger["id"], "startsAt": _at(7, 9), "endsAt": _at(7, 10)}, user)
    service.decide(second["id"], {"action": "propose", "proposedStartsAt": _at(8, 9), "proposedEndsAt": _at(8, 10)},
                   staff)
    assert service.answer(second["id"], False, user)["status"] == "cancelled"

    third = service.create({"resourceId": plunger["id"], "startsAt": _at(9, 9), "endsAt": _at(9, 10)}, user)
    rejected = service.decide(third["id"], {"action": "reject", "reason": "No sample yet"}, staff)
    assert (rejected["status"], rejected["decisionReason"]) == ("rejected", "No sample yet")
    assert _status(lambda: service.decide(third["id"], {"action": "confirm"}, staff))[0] == 409


def test_AUserSeesTheirBookingsAndOnlyWhenTheOthersHoldTheResources(booking):
    service, krios, plunger, people, groupId = booking
    user, other, staff = people["user"], people["other"], people["staff"]
    confirmed = service.create({"resourceId": plunger["id"], "ownerId": user["id"], "startsAt": _at(5, 9),
                                "endsAt": _at(5, 10), "notes": "Bring the tweezers"}, staff)
    service.create({"resourceId": plunger["id"], "startsAt": _at(5, 12), "endsAt": _at(5, 13),
                    "justification": "Second try"}, user)
    blocked = service.create({"resourceId": plunger["id"], "kind": "maintenance", "startsAt": _at(5, 14),
                              "endsAt": _at(5, 16)}, staff)
    assert (blocked["status"], blocked["ownerId"], blocked["priority"]) == ("confirmed", None, 0)

    seen = service.listBookings(other, _at(4), _at(6), [plunger["id"]])
    assert [(row["title"], row["mine"]) for row in seen] == [("Booked", False), ("Maintenance", False)]
    assert "ownerName" not in seen[0] and "notes" not in seen[0]
    assert _status(lambda: service.update(confirmed["id"], {"startsAt": _at(5, 8)}, other))[0] == 403

    mine = service.listBookings(user, _at(4), _at(6), [plunger["id"]])
    assert [row["status"] for row in mine] == ["confirmed", "requested", "confirmed"]
    assert mine[0]["notes"] == "Bring the tweezers" and mine[0]["mine"] is True

    assert len(service.listBookings(staff, _at(4), _at(6), [plunger["id"]], ["requested"])) == 1
    assert [group["id"] for group in service.myBookings(user)["groups"]] == [groupId]
    # A block over a confirmed booking: the booking is moved first
    assert _status(lambda: service.create({"resourceId": plunger["id"], "kind": "downtime", "startsAt": _at(5, 9),
                                           "endsAt": _at(5, 11)}, staff))[0] == 409


def test_AResourceIsCheckedAndOneWithBookingsStays(booking):
    service, krios, plunger, people, groupId = booking
    assert _status(lambda: service.saveResource({"name": plunger["name"]}))[0] == 409
    assert _status(lambda: service.saveResource({"name": "GP2 %s" % uuid4().hex[:6], "minHours": 5,
                                                 "maxHours": 2}))[0] == 400
    assert _status(lambda: service.saveResource({"name": "GP2 %s" % uuid4().hex[:6], "dayStart": "9h"}))[0] == 400
    assert _status(lambda: service.saveResource({"name": "GP2 %s" % uuid4().hex[:6], "unit": "day"}))[0] == 400
    assert _status(lambda: service.saveResource({"name": "Other %s" % uuid4().hex[:6],
                                                 "microscopeId": krios["microscopeId"]}))[0] == 409
    spare = service.saveResource({"name": "ICE %s" % uuid4().hex[:6], "unit": "service"})
    service.deleteResource(spare["id"])

    service.create({"resourceId": plunger["id"], "startsAt": _at(5, 9), "endsAt": _at(5, 10)}, people["user"])
    assert _status(lambda: service.deleteResource(plunger["id"]))[0] == 409
    retired = service.saveResource(dict(plunger, active=False), plunger["id"])
    assert plunger["id"] not in [resource["id"] for resource in service.listResources(people["user"])]
    assert plunger["id"] in [resource["id"] for resource in service.listResources(people["staff"])]
    assert _status(lambda: service.create({"resourceId": retired["id"], "startsAt": _at(9, 9), "endsAt": _at(9, 10)},
                                          people["user"]))[0] == 400


def test_TheFacilitysTimeZoneIsOneThatExists(booking, postgresqlIntegrationDb):
    from app.backend.api.services.facility_settings_service import FacilitySettingsService

    settings = FacilitySettingsService(postgresqlIntegrationDb)
    assert _status(lambda: settings.saveSettings({"timezone": "Madrid"}))[0] == 400
    assert settings.saveSettings({"timezone": "Atlantic/Canary"})["settings"]["timezone"] == "Atlantic/Canary"
