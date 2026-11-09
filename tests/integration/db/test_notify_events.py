"""What tells users of what happened, and resetting a forgotten password, against the migrated database."""
import datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.backend.api.services import notification_sender as sender
from app.backend.api.services import notify_events, password_reset
from app.backend.api.services.mail_service import MailService
from app.backend.api.services.notifications import Notifications
from app.backend.mapper.postgresql import PostgresqlFlatMapper


@pytest.fixture
def world(postgresqlIntegrationDb, postgresqlMigratedEnv, monkeypatch, tmp_path):
    """Three users (one in a group), a project of the first, the web's address; what the test makes goes after it."""
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    kept = [dict(row) for row in db.fetchAll("SELECT key, value FROM notification_settings") or []]
    first = db.fetchOne("SELECT COALESCE(MAX(id), 0) AS id FROM notifications")["id"]
    users = {name: flat.insertUser(email="%s-%s@example.org" % (name.lower(), uuid4().hex), hashedPassword="x",
                                   firstName=name, lastName="Test", institution=None, role="user", isActive=True,
                                   isVerified=True, verificationCode="") for name in ("Ana", "Luis", "Marta")}
    group = db.fetchOne("INSERT INTO user_groups (name) VALUES (%s) RETURNING id", ("Lab %s" % uuid4().hex[:6],))["id"]
    db.execute('INSERT INTO user_group_members ("groupId", "userId", "groupRole") VALUES (%s, %s, %s)',
               (group, users["Marta"], "member"))
    projectId = flat.insertProject(ownerId=users["Ana"], name=str(tmp_path / "Workflow_2D"))
    monkeypatch.setattr(sender, "requestSend", lambda: None)
    Notifications(db).mapper.saveSettings({"publicUrl": "https://scipion.example.org"}, None)
    try:
        yield {"db": db, "flat": flat, "users": users, "group": group, "projectId": projectId, "first": first}
    finally:
        db.execute("DELETE FROM notifications WHERE id > %s", (first,))
        db.execute("DELETE FROM protocol_runs WHERE \"projectId\" = %s", (projectId,))
        db.execute("DELETE FROM projects WHERE id = %s", (projectId,))
        db.execute("DELETE FROM user_groups WHERE id = %s", (group,))
        db.execute("DELETE FROM users WHERE id = ANY(%s)", (list(users.values()),))
        db.execute("DELETE FROM notification_settings")
        for row in kept:
            Notifications(db).mapper.saveSettings({row["key"]: row["value"]}, None)


def _notices(world, userId):
    return world["db"].fetchAll('SELECT kind, title, body, link, "inWeb", "emailState" FROM notifications '
                                'WHERE id > %s AND "userId" = %s ORDER BY id', (world["first"], userId))


def test_AnActivatedAccountIsTold(world):
    notify_events.accountActivated(world["db"], world["users"]["Luis"])

    notice = _notices(world, world["users"]["Luis"])[0]
    assert notice["kind"] == "account.activated" and notice["emailState"] == "pending" and notice["link"] == "/home"


def test_ASharedProjectIsToldToTheUsersAndTheGroupsMembersButTheSharer(world):
    users = world["users"]
    sharer = {"id": users["Ana"], "firstName": "Ana", "lastName": "Test"}

    notify_events.projectShared(world["db"], sharer, world["projectId"], "/data/Workflow_2D", [users["Luis"], users["Ana"]],
                                [world["group"]], "view")

    for name in ("Luis", "Marta"):
        notice = _notices(world, users[name])[0]
        assert notice["title"] == "Ana Test shared the project Workflow_2D with you"
        assert "to see" in notice["body"] and notice["link"] == "/project/load/%d" % world["projectId"]
    assert _notices(world, users["Ana"]) == []


def test_AFailedRunIsToldToWhoLaunchedItAndTheOwnerAndALongOneToWhoChose(world):
    from app.backend.mapper.compute_usage_mapper import ComputeUsagePostgresqlMapper

    db, users = world["db"], world["users"]
    runs = ComputeUsagePostgresqlMapper(db)

    def run(status, minutes):
        runId = runs.startRun({"projectId": world["projectId"], "projectPath": "/data/Workflow_2D", "protocolId": "7",
                               "protocolClassName": "ProtMotionCorr", "protocolLabel": "motioncor", "userId": users["Luis"],
                               "executionId": None, "coordinatorRunId": None, "host": "h", "queueName": None,
                               "queueJobId": None, "gpus": 0, "gpuIds": None, "threads": 1, "mpi": 1,
                               "streaming": False})
        db.execute('UPDATE protocol_runs SET "startedAt" = NOW() - %s * INTERVAL \'1 minute\' WHERE id = %s',
                   (minutes, runId))
        runs.endRun(runId, status)
        return notify_events.runEnded(db, runId, status)

    run("failed", 2)
    assert [notice["kind"] for notice in _notices(world, users["Luis"])] == ["protocol.failed"]
    assert _notices(world, users["Ana"])[0]["title"] == "motioncor failed in Workflow_2D"
    assert "?protocol=7" in _notices(world, users["Ana"])[0]["link"]
    # A long run that finished: told only to who chose it (off by default), and only past the minutes
    assert run("finished", 45) == []
    Notifications(db).savePreferences({"id": users["Luis"], "permissions": []}, {"protocol.finished": "web"}, False)
    assert run("finished", 5) == []
    assert len(run("finished", 45)) == 1
    assert _notices(world, users["Luis"])[-1]["title"] == "motioncor finished in Workflow_2D"
    db.execute('DELETE FROM notification_preferences WHERE "userId" = %s', (users["Luis"],))


def test_AForgottenPasswordIsResetOnceWithTheMailedLink(world, monkeypatch):
    import smtplib

    from app.backend.utils.security import verifyPassword

    db, flat, users = world["db"], world["flat"], world["users"]
    email = flat.getUserById(users["Luis"])["email"]
    sent = []

    class FakeSmtp:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self, context=None):
            pass

        def login(self, *args):
            pass

        def send_message(self, message):
            sent.append(message.get_content())

    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    db.execute("""UPDATE notifications SET "emailState" = 'skipped' WHERE "emailState" IN ('pending', 'digest')""")
    MailService(db).saveSettings({"host": "smtp.example.org", "sender": "scipion@example.org"})

    # The same answer for an address without an account
    assert password_reset.askReset(flat, "nobody@example.org") == password_reset.askReset(flat, email)
    notices = _notices(world, users["Luis"])
    assert [notice["kind"] for notice in notices] == ["account.passwordReset"] and not notices[0]["inWeb"]
    # Asking again at once sends nothing new
    password_reset.askReset(flat, email)
    assert len(_notices(world, users["Luis"])) == 1
    sender.sendOnce(db)
    link = next(line for line in sent[-1].splitlines() if "/reset-password?token=" in line).strip()
    token = link.split("token=")[1]
    # Mailed, its text (the link) is not kept
    assert _notices(world, users["Luis"])[0]["body"] == ""

    with pytest.raises(HTTPException):
        password_reset.reset(flat, "not-the-token", "n3wPassword")
    password_reset.reset(flat, token, "n3wPassword")
    assert verifyPassword("n3wPassword", flat.getUserById(users["Luis"])["hashedPassword"])
    with pytest.raises(HTTPException) as error:
        password_reset.reset(flat, token, "an0therOne")
    assert error.value.status_code == 400


def test_AResetLinkExpires(world):
    db, flat, users = world["db"], world["flat"], world["users"]
    from app.backend.api.services.password_reset import _hash
    from app.backend.mapper.password_reset_mapper import PasswordResetPostgresqlMapper

    PasswordResetPostgresqlMapper(db).create(users["Marta"], _hash("old-token"), -1)

    with pytest.raises(HTTPException):
        password_reset.reset(flat, "old-token", "n3wPassword")
