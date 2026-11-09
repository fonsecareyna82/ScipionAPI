"""Importing EMhub from a copy of its SQLite database (made up here, with EMhub's tables and columns)."""
import json
import sqlite3
from uuid import uuid4

import pytest

from app.backend.api.services.facility_service import FacilityService
from app.backend.importers import emhub
from app.backend.mapper.import_mapper import ImportPostgresqlMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64), email VARCHAR(80), phone VARCHAR(80),
                    name VARCHAR(256), created DATETIME, status VARCHAR(32), roles JSON, password_hash VARCHAR(256),
                    profile_image VARCHAR(256), pi_id INTEGER, extra JSON);
CREATE TABLE resources (id INTEGER PRIMARY KEY, name VARCHAR(64), status VARCHAR(32), tags VARCHAR(256),
                        image VARCHAR(64), color VARCHAR(16), extra JSON);
CREATE TABLE bookings (id INTEGER PRIMARY KEY, title VARCHAR(256), start DATETIME, "end" DATETIME, type VARCHAR(16),
                       slot_auth JSON, description TEXT, repeat_id VARCHAR(256), repeat_value VARCHAR(32),
                       resource_id INTEGER, creator_id INTEGER, owner_id INTEGER, operator_id INTEGER,
                       application_id INTEGER, project_id INTEGER, experiment JSON, extra JSON);
CREATE TABLE sessions (id INTEGER PRIMARY KEY, name VARCHAR(256), start DATETIME, "end" DATETIME, status VARCHAR(32),
                       data_path VARCHAR(256), acquisition JSON, stats JSON, resource_id INTEGER, booking_id INTEGER,
                       operator_id INTEGER, extra JSON);
CREATE TABLE applications (id INTEGER PRIMARY KEY, code VARCHAR(32), title VARCHAR(256));
"""


@pytest.fixture
def emhubCopy(postgresqlIntegrationDb, postgresqlMigratedEnv, tmp_path):
    """A made-up EMhub: a PI with two lab members (one already has an account here), a manager, a user without
    address, a Krios (a microscope here by that name) and a Vitrobot, bookings and two sessions."""
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    mark = uuid4().hex[:8]
    krios = FacilityService(db).saveMicroscope({"name": "Krios %s" % mark, "sessionsEnabled": True})
    existing = flat.insertUser(email="luis-%s@example.org" % mark, hashedPassword="x", firstName="Luis",
                               lastName="Here", institution=None, role="user", isActive=True, isVerified=True,
                               verificationCode="")
    file = tmp_path / "emhub.sqlite"
    connection = sqlite3.connect(str(file))
    connection.executescript(SCHEMA)
    users = [
        (1, "ana", "ana-%s@example.org" % mark, "Ana Pi Garcia", "2024-01-10 09:00:00", "active", ["user", "pi"], None,
         {"institution": "CNB-CSIC"}),
        (2, "luis", "LUIS-%s@example.org" % mark, "Luis Here", "2024-02-01 09:00:00", "active", ["user"], 1, {}),
        (3, "marta", "marta-%s@example.org" % mark, "Marta Lab", "2024-03-01 09:00:00", "inactive", ["user"], 1, {}),
        (4, "mikel", "mikel-%s@example.org" % mark, "Mikel Staff", "2023-01-01 09:00:00", "active",
         ["user", "manager"], None, {}),
        (5, "noaddress", "", "No Address", "2023-01-01 09:00:00", "active", ["user"], None, {}),
    ]
    connection.executemany("INSERT INTO users (id, username, email, name, created, status, roles, pi_id, extra) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           [(u[0], u[1], u[2], u[3], u[4], u[5], json.dumps(u[6]), u[7], json.dumps(u[8])) for u in users])
    connection.executemany("INSERT INTO resources (id, name, status, tags, image, color, extra) VALUES (?, ?, ?, ?, ?, ?, ?)", [
        (1, "Krios %s" % mark, "active", "microscope krios", "krios.png", "#4a7ab5", json.dumps({"min_booking": 24, "max_booking": 72})),
        (2, "Vitrobot %s" % mark, "active", "instrument", "vitrobot.png", "#999999", json.dumps({})),
        (3, "Old scope %s" % mark, "inactive", "", "", "", None),
    ])
    connection.executemany('INSERT INTO bookings (id, title, start, "end", type, description, resource_id, creator_id, '
                           'owner_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [
        (1, "Ana on the Krios", "2026-10-01 07:00:00", "2026-10-02 07:00:00", "booking", "grids NZ251", 1, 4, 1),
        (2, "Maintenance", "2026-10-05 07:00:00", "2026-10-06 07:00:00", "maintenance", "", 1, 4, 4),
        (3, "Open slot", "2026-10-07 07:00:00", "2026-10-08 07:00:00", "slot", "", 1, 4, None),
        (4, "Plunging", "2026-10-03 09:00:00", "2026-10-03 11:00:00", "booking", "", 2, 2, 2),
        (5, "Bad", "2026-10-03 11:00:00", "2026-10-03 09:00:00", "booking", "", 2, 2, 2),
        (6, "Old", "2024-01-03 09:00:00", "2024-01-03 11:00:00", "booking", "", 2, 2, 2),
        (7, "Nowhere", "2026-10-03 09:00:00", "2026-10-03 11:00:00", "booking", "", 99, 2, 2),
    ])
    connection.executemany('INSERT INTO sessions (id, name, start, "end", status, data_path, resource_id, booking_id, '
                           'operator_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [
        (1, "2026_10_01_Ana-Pi_%s" % mark, "2026-10-01 08:00:00", "2026-10-02 06:00:00", "finished", "/data/x", 1, 1, 4),
        (2, "2026_10_03_plunge_%s" % mark, "2026-10-03 09:00:00", None, "created", "", 2, 4, 2),
    ])
    connection.execute("INSERT INTO applications (id, code, title) VALUES (1, 'CEM00001', 'Instruct')")
    connection.commit()
    connection.close()
    try:
        yield {"db": db, "file": str(file), "mark": mark, "krios": krios, "existingId": existing}
    finally:
        links = ImportPostgresqlMapper(db)
        made = {kind: list(links.links(emhub.SOURCE, kind).values()) for kind in ("user", "group", "resource", "booking", "session")}
        db.execute("DELETE FROM facility_sessions WHERE id = ANY(%s)", (made["session"],))
        db.execute("DELETE FROM facility_bookings WHERE id = ANY(%s)", (made["booking"],))
        db.execute("DELETE FROM facility_resources WHERE id = ANY(%s) AND \"microscopeId\" IS NULL", (made["resource"],))
        db.execute("DELETE FROM facility_microscopes WHERE id = %s", (krios["id"],))
        db.execute("DELETE FROM user_groups WHERE id = ANY(%s)", (made["group"],))
        db.execute("DELETE FROM users WHERE id = ANY(%s) OR id = %s", (made["user"], existing))
        db.execute("DELETE FROM import_links WHERE source = %s", (emhub.SOURCE,))


def test_TheImportShowsWhatItWouldDoWithoutWritingAnything(emhubCopy):
    db = emhubCopy["db"]
    data = emhub.readEmhub(emhubCopy["file"])

    report = emhub.plan(data, ImportPostgresqlMapper(db), withSessions=True)
    counts = emhub.summary(report)

    assert counts["users"] == {"create": 3, "match": 1}
    assert counts["groups"] == {"create": 1} and report["groups"][0]["members"] == 2
    assert counts["resources"] == {"create": 2, "match": 1}
    assert counts["bookings"] == {"create": 5}
    assert counts["sessions"] == {"create": 2}
    assert {(entry["kind"], entry["why"]) for entry in report["skipped"]} == {
        ("user", "no mail address"), ("booking", "no valid times"), ("booking", "its resource is not imported")}
    assert report["staffRoles"] == [{"email": "mikel-%s@example.org" % emhubCopy["mark"], "roles": ["manager"]}]
    assert report["countedOnly"]["applications"] == 1
    assert ImportPostgresqlMapper(db).links(emhub.SOURCE, "user") == {}
    # Only what ends from a day on
    import datetime

    since = emhub.plan(data, ImportPostgresqlMapper(db), since=datetime.date(2025, 1, 1))
    assert emhub.summary(since)["bookings"] == {"create": 4}


def test_TheImportMakesEachThingOnceAndKeepsWhatExists(emhubCopy):
    db, mark = emhubCopy["db"], emhubCopy["mark"]
    flat = PostgresqlFlatMapper(db)
    data = emhub.readEmhub(emhubCopy["file"])

    report = emhub.apply(data, db, withSessions=True)

    users = {entry["email"]: entry["targetId"] for entry in report["users"]}
    luis = "luis-%s@example.org" % mark
    assert users[luis] == emhubCopy["existingId"]
    ana = flat.getUserById(users["ana-%s@example.org" % mark])
    assert (ana["firstName"], ana["lastName"], ana["institution"], ana["isActive"]) == ("Ana", "Pi Garcia", "CNB-CSIC", True)
    assert flat.getUserById(users["marta-%s@example.org" % mark])["isActive"] is False
    # A new account gets the default roles, never EMhub's staff roles
    roles = db.fetchAll('SELECT r.name FROM user_access_roles ur JOIN access_roles r ON r.id = ur."roleId" '
                        'WHERE ur."userId" = %s', (users["mikel-%s@example.org" % mark],))
    assert [row["name"] for row in roles] == [row["name"] for row in db.fetchAll(
        'SELECT name FROM access_roles WHERE "isDefault" ORDER BY id')]
    # Ana's lab: Ana its PI, Luis and Marta its members
    group = report["groups"][0]["targetId"]
    members = {row["userId"]: row["groupRole"] for row in db.fetchAll(
        'SELECT "userId", "groupRole" FROM user_group_members WHERE "groupId" = %s', (group,))}
    assert members == {users["ana-%s@example.org" % mark]: "pi", users[luis]: "member",
                       users["marta-%s@example.org" % mark]: "member"}
    # The Krios is the microscope's resource here; the bookings are on it, a slot as special
    resources = {entry["name"]: entry["targetId"] for entry in report["resources"]}
    kriosResource = db.fetchOne('SELECT id FROM facility_resources WHERE "microscopeId" = %s', (emhubCopy["krios"]["id"],))
    assert resources["Krios %s" % mark] == kriosResource["id"]
    kinds = sorted(row["kind"] for row in db.fetchAll('SELECT kind FROM facility_bookings WHERE "resourceId" = %s',
                                                      (kriosResource["id"],)))
    assert kinds == ["booking", "maintenance", "special"]
    made = db.fetchOne("SELECT min_hours, max_hours FROM (SELECT \"minHours\" AS min_hours, \"maxHours\" AS max_hours "
                       "FROM facility_resources WHERE id = %s) r", (resources["Vitrobot %s" % mark],))
    assert made == {"min_hours": None, "max_hours": None}
    # The Krios session is history (archived, its user the booking's owner); the Vitrobot is no microscope here
    session = db.fetchOne('SELECT status, "userId", notes FROM facility_sessions WHERE name = %s',
                          ("2026_10_01_Ana-Pi_%s" % mark,))
    assert session["status"] == "archived" and session["userId"] == users["ana-%s@example.org" % mark]
    assert "/data/x" in session["notes"]
    assert any(entry["kind"] == "session" and "not a microscope" in entry["why"] for entry in report["skipped"])

    # Again: nothing is made twice
    again = emhub.apply(data, db, withSessions=True)
    assert set(emhub.summary(again)["users"]) == {"linked"} and set(emhub.summary(again)["bookings"]) == {"linked"}
    assert db.fetchOne("SELECT COUNT(*) AS n FROM users WHERE email LIKE %s", ("%%-%s@example.org" % mark,))["n"] == 4
