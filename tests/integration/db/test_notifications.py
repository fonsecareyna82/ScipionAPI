"""The users' notifications against the migrated database: channels, the outbox, the sender and the mail."""
import datetime
import smtplib
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.backend.api.services import notification_sender as sender
from app.backend.api.services.mail_service import MailService
from app.backend.api.services.notifications import Notifications
from app.backend.mapper.postgresql import PostgresqlFlatMapper


class FakeSmtp:
    """An SMTP server that keeps what it is given; one whose host starts with "down" refuses everything."""
    sent = []

    def __init__(self, host, port, timeout=None):
        if host.startswith("down"):
            raise OSError("Connection refused")
        self.login_ = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        self.login_ = (user, password)

    def send_message(self, message):
        FakeSmtp.sent.append({"to": message["To"], "subject": message["Subject"], "body": message.get_content(),
                              "login": self.login_})


@pytest.fixture
def outbox(postgresqlIntegrationDb, postgresqlMigratedEnv, monkeypatch):
    """Two users, a fake mail server, and the notification settings put back after the test (with the notices it
    made removed)."""
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    kept = [dict(row) for row in db.fetchAll("SELECT key, value FROM notification_settings") or []]
    keptPreferences = db.fetchOne("SELECT COUNT(*) AS n FROM notification_preferences")["n"]
    first = db.fetchOne("SELECT COALESCE(MAX(id), 0) AS id FROM notifications")["id"]
    # Notices of other tests waiting in this database are not this test's to send
    db.execute("""UPDATE notifications SET "emailState" = 'skipped' WHERE "emailState" IN ('pending', 'digest')""")
    users = [flat.insertUser(email="notice-%s-%s@example.com" % (name, uuid4().hex), hashedPassword="test",
                             firstName=name, lastName="Test", institution=None, role="user", isActive=True,
                             isVerified=True, verificationCode="") for name in ("Ana", "Luis")]
    FakeSmtp.sent = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(sender, "requestSend", lambda: None)
    try:
        yield {"db": db, "users": users, "first": first}
    finally:
        db.execute("DELETE FROM notifications WHERE id > %s", (first,))
        db.execute("DELETE FROM users WHERE id = ANY(%s)", (users,))
        db.execute("DELETE FROM notification_settings")
        for row in kept:
            Notifications(db).mapper.saveSettings({row["key"]: row["value"]}, None)
        assert db.fetchOne("SELECT COUNT(*) AS n FROM notification_preferences")["n"] == keptPreferences


def _mail(db, **change):
    return MailService(db).saveSettings(dict({"host": "smtp.example.org", "port": 587, "security": "starttls",
                                              "user": "scipion", "password": "s3cret", "sender": "scipion@example.org",
                                              "publicUrl": "https://scipion.example.org/"}, **change))


def _rows(outbox):
    return outbox["db"].fetchAll('SELECT id, "userId", kind, "inWeb", "emailState", "emailAttempts", "emailError" '
                                 "FROM notifications WHERE id > %s ORDER BY id", (outbox["first"],))


def test_TheMailPasswordIsKeptEncryptedAndNeverAnswered(outbox):
    db = outbox["db"]
    settings = _mail(db)

    assert settings["passwordSet"] and settings["enabled"] and "password" not in settings
    assert settings["publicUrl"] == "https://scipion.example.org"
    assert "s3cret" not in str(db.fetchOne("SELECT value FROM notification_settings WHERE key = 'mail'")["value"])
    # Left out, the password stays
    assert MailService(db).saveSettings({"host": "smtp.example.org", "sender": "scipion@example.org"})["passwordSet"]
    with pytest.raises(HTTPException):
        MailService(db).saveSettings({"publicUrl": "scipion.example.org"})
    with pytest.raises(HTTPException):
        MailService(db).saveSettings({"digest": {"hour": 25}})


def test_EachUserGetsANoticeAsTheyChose(outbox):
    db = outbox["db"]
    ana, luis = outbox["users"]
    notifications = Notifications(db)
    user = {"id": luis, "permissions": []}

    # Mandatory kinds cannot be turned off
    with pytest.raises(HTTPException):
        notifications.savePreferences(user, {"facility.retention": "off"}, True)
    notifications.savePreferences(user, {"facility.booking": "digest"}, True)
    notifications.notify([ana, luis, ana], "facility.booking", "Booking of Krios: is confirmed", "Yours.", "/facility/calendar")
    notifications.savePreferences(user, {"facility.booking": "off"}, True)
    notifications.notify([luis], "facility.booking", "Booking of Krios: was cancelled")
    notifications.savePreferences(user, {"facility.booking": "web"}, True)
    notifications.notify([luis], "facility.booking", "Booking of Krios: was moved")

    rows = _rows(outbox)
    assert [(row["userId"], row["emailState"], row["inWeb"]) for row in rows] == [
        (ana, "pending", True), (luis, "digest", True), (luis, "skipped", True)]
    preferences = notifications.preferencesOf(user, True)
    booking = next(kind for kind in preferences["kinds"] if kind["kind"] == "facility.booking")
    assert booking["channel"] == "web" and booking["chosen"] and booking["default"] == "instant"
    # The staff's kinds are not offered to who does not run sessions, nor the facility's without a facility
    assert "facility.alert" not in [kind["kind"] for kind in preferences["kinds"]]
    assert notifications.preferencesOf(user, False)["kinds"] == []
    # Back to the default
    notifications.savePreferences(user, {"facility.booking": None}, True)
    assert not next(kind for kind in notifications.preferencesOf(user, True)["kinds"]
                    if kind["kind"] == "facility.booking")["chosen"]

    # The administrator's default applies to whoever did not choose
    notifications.saveDefaults({"facility.booking": "web"})
    notifications.notify([ana], "facility.booking", "Booking of Krios: is confirmed")
    assert _rows(outbox)[-1]["emailState"] == "skipped"
    with pytest.raises(HTTPException):
        notifications.saveDefaults({"facility.retention": "web"})


def test_AUserReadsTheirNoticesInTheWeb(outbox):
    db = outbox["db"]
    ana, luis = outbox["users"]
    notifications = Notifications(db)
    ids = notifications.notify([ana], "facility.booking", "One")
    notifications.notify([ana], "facility.booking", "Two")
    notifications.notify([luis], "facility.booking", "Luis's")

    mine = notifications.listMine(ana)
    assert [notice["title"] for notice in mine["notifications"]] == ["Two", "One"] and mine["unread"] == 2
    unread = notifications.mapper.listUnreadSince(ana, None)
    assert [notice["title"] for notice in unread] == ["Two", "One"]
    assert notifications.markRead(ana, ids)["unread"] == 1
    assert notifications.markRead(ana)["unread"] == 0
    assert notifications.listMine(luis)["unread"] == 1


def test_TheSenderMailsWhatIsPendingWithItsLinkAndRetriesWhatFails(outbox):
    db = outbox["db"]
    ana, luis = outbox["users"]
    notifications = Notifications(db)
    notifications.notify([ana], "facility.booking", "Booking of Krios: is confirmed", "Your booking is confirmed.",
                         "/facility/calendar")
    notifications.notifyAddresses(["ops@example.org"], "facility.alert", "Facility: 1 new alert", "boom")

    # Without a mail server nothing goes, and nothing is lost
    assert sender.sendOnce(db) == {"sent": [], "digests": []}
    assert {row["emailState"] for row in _rows(outbox)} == {"pending"}

    _mail(db)
    sent = sender.sendOnce(db)["sent"]

    assert len(sent) == 2 and {row["emailState"] for row in _rows(outbox)} == {"sent"}
    toAna = next(mail for mail in FakeSmtp.sent if mail["subject"] == "Booking of Krios: is confirmed")
    assert "https://scipion.example.org/facility/calendar" in toAna["body"]
    assert "https://scipion.example.org/settings?tab=notifications" in toAna["body"]
    assert toAna["login"] == ("scipion", "s3cret")
    assert next(mail for mail in FakeSmtp.sent if mail["subject"] == "Facility: 1 new alert")["to"] == "ops@example.org"

    # A server that does not take it: tried again later, then given up
    _mail(db, host="down.example.org")
    notifications.notify([luis], "facility.booking", "Booking of Krios: was moved")
    sender.sendOnce(db)
    failing = _rows(outbox)[-1]
    assert (failing["emailState"], failing["emailAttempts"]) == ("pending", 1)
    assert "Connection refused" in failing["emailError"]
    for _ in range(sender.MAX_ATTEMPTS):
        db.execute('UPDATE notifications SET "emailNextAt" = NOW() WHERE id = %s', (failing["id"],))
        sender.sendOnce(db)
    assert _rows(outbox)[-1]["emailState"] == "failed"
    assert Notifications(db).outbox()[0]["emailState"] == "failed"


def test_TheDigestMailsADaysNoticesOnceAtItsHour(outbox):
    db = outbox["db"]
    ana, _ = outbox["users"]
    notifications = Notifications(db)
    _mail(db, digest={"hour": 8, "timezone": "Europe/Madrid"})
    notifications.savePreferences({"id": ana, "permissions": []}, {"facility.booking": "digest"}, True)
    notifications.notify([ana], "facility.booking", "Booking of Krios: is confirmed", link="/facility/calendar")
    notifications.notify([ana], "facility.booking", "Booking of Talos: was cancelled")
    mail = MailService(db)
    early = datetime.datetime(2026, 11, 9, 6, 30, tzinfo=datetime.timezone.utc)  # 07:30 in Madrid
    later = datetime.datetime(2026, 11, 9, 7, 30, tzinfo=datetime.timezone.utc)  # 08:30 in Madrid

    assert sender.sendDigest(db, mail, now=early) == []
    assert sender.sendDigest(db, mail, now=later) == [ana]
    digest = FakeSmtp.sent[-1]
    assert digest["subject"] == "ScipionWeb: 2 notices of the day"
    assert "Booking of Talos: was cancelled" in digest["body"] and "https://scipion.example.org/facility/calendar" in digest["body"]
    assert {row["emailState"] for row in _rows(outbox)} == {"sent"}
    # Once a day
    notifications.notify([ana], "facility.booking", "Booking of Glacios: is confirmed")
    assert sender.sendDigest(db, mail, now=later + datetime.timedelta(hours=3)) == []
    db.execute('DELETE FROM notification_preferences WHERE "userId" = %s', (ana,))


def test_ABookingDecisionIsNoticedToItsUser(outbox):
    import datetime as dt

    from app.backend.api.services.facility_booking_service import FacilityBookingService

    db = outbox["db"]
    ana, _ = outbox["users"]
    starts = dt.datetime(2026, 11, 10, 8, tzinfo=dt.timezone.utc)
    booking = {"id": 1, "ownerId": ana, "resourceName": "Titan Krios G5", "startsAt": starts,
               "endsAt": starts + dt.timedelta(hours=24), "decisionReason": "Gun maintenance",
               "proposedStartsAt": None}

    FacilityBookingService(db).notify(booking, "cannot be at that time")

    notice = Notifications(db).listMine(ana)["notifications"][0]
    assert notice["title"] == "Booking of Titan Krios G5: cannot be at that time"
    assert "Reason: Gun maintenance" in notice["body"] and notice["link"] == "/facility/calendar"
    # Never fails, also for a booking without a user
    FacilityBookingService(db).notify(dict(booking, ownerId=None), "is confirmed")
