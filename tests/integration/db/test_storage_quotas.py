"""Disk quotas against the migrated database: usage by owner and group, refusing launches, and the notices."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.backend.api.services import notification_sender, storage_quotas
from app.backend.mapper.postgresql import PostgresqlFlatMapper

GB = 1024 ** 3


@pytest.fixture
def lab(postgresqlIntegrationDb, postgresqlMigratedEnv, monkeypatch, tmp_path):
    """Two users in a group, each with a project measured (Ana 30 GB, Luis 50 GB), and an admin."""
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    monkeypatch.setattr(notification_sender, "requestSend", lambda: None)
    users = {name: flat.insertUser(email="%s-%s@example.org" % (name, uuid4().hex), hashedPassword="x", firstName=name,
                                   lastName="Test", institution=None, role="user", isActive=True, isVerified=True,
                                   verificationCode="") for name in ("ana", "luis", "admin")}
    group = db.fetchOne("INSERT INTO user_groups (name) VALUES (%s) RETURNING id", ("Lab %s" % uuid4().hex[:6],))["id"]
    db.execute('INSERT INTO user_group_members ("groupId", "userId", "groupRole") VALUES (%s, %s, %s), (%s, %s, %s)',
               (group, users["ana"], "pi", group, users["luis"], "member"))
    projects = {}
    for name, size in (("ana", 30 * GB), ("luis", 50 * GB)):
        projects[name] = flat.insertProject(ownerId=users[name], name=str(tmp_path / ("P-%s" % name)))
        db.execute('INSERT INTO project_disk_usage ("projectId", "totalBytes") VALUES (%s, %s)', (projects[name], size))
    first = db.fetchOne("SELECT COALESCE(MAX(id), 0) AS id FROM notifications")["id"]
    try:
        yield {"db": db, "users": users, "group": group, "projects": projects, "first": first}
    finally:
        db.execute("DELETE FROM notifications WHERE id > %s", (first,))
        db.execute("DELETE FROM projects WHERE id = ANY(%s)", (list(projects.values()),))
        db.execute("DELETE FROM user_groups WHERE id = %s", (group,))
        db.execute("DELETE FROM users WHERE id = ANY(%s)", (list(users.values()),))


def test_AQuotaCountsTheProjectsOfItsUserOrOfItsGroupsMembers(lab):
    db, users = lab["db"], lab["users"]

    storage_quotas.saveQuota(db, "user", users["ana"], 40 * GB, users["admin"])
    quotas = storage_quotas.saveQuota(db, "group", lab["group"], 100 * GB, users["admin"])

    mine = {quota["kind"]: quota for quota in quotas if quota["targetId"] in (users["ana"], lab["group"])}
    assert mine["user"]["usedBytes"] == 30 * GB and mine["user"]["percent"] == 75.0
    assert mine["group"]["usedBytes"] == 80 * GB and not mine["group"]["full"]
    assert {quota["kind"] for quota in storage_quotas.quotasOf(db, users["luis"])} == {"group"}
    with pytest.raises(HTTPException):
        storage_quotas.saveQuota(db, "user", users["ana"], 0, users["admin"])
    with pytest.raises(HTTPException):
        storage_quotas.saveQuota(db, "planet", 1, GB, users["admin"])


def test_NothingNewRunsWhereAQuotaIsFullAndItsUsersAreToldOnce(lab):
    db, users, projects = lab["db"], lab["users"], lab["projects"]
    storage_quotas.saveQuota(db, "group", lab["group"], 100 * GB, users["admin"])
    storage_quotas.checkLaunch(db, projects["luis"])

    # 80 GB of 100: the members are told once
    assert storage_quotas.refreshNotices(db) and storage_quotas.refreshNotices(db) == []
    # Full: launches in the members' projects are refused, and they are told again
    db.execute('UPDATE project_disk_usage SET "totalBytes" = %s WHERE "projectId" = %s', (70 * GB, projects["luis"]))
    with pytest.raises(HTTPException) as error:
        storage_quotas.checkLaunch(db, projects["ana"])
    assert error.value.status_code == 409 and "group" in error.value.detail
    assert [notice["level"] for notice in storage_quotas.refreshNotices(db)] == [100]
    titles = [row["title"] for row in db.fetchAll(
        'SELECT title FROM notifications WHERE id > %s AND "userId" = %s ORDER BY id', (lab["first"], users["ana"]))]
    assert titles[0].endswith("is at 80 %") and titles[1].endswith("is full")
    # Raised: launches go on, and the level starts again
    storage_quotas.saveQuota(db, "group", lab["group"], 500 * GB, users["admin"])
    storage_quotas.checkLaunch(db, projects["ana"])


def test_AQuotaGoesWithItsUser(lab):
    db, users = lab["db"], lab["users"]
    storage_quotas.saveQuota(db, "user", users["luis"], 10 * GB, users["admin"])

    db.execute("DELETE FROM projects WHERE id = %s", (lab["projects"]["luis"],))
    db.execute("DELETE FROM users WHERE id = %s", (users["luis"],))

    assert db.fetchOne('SELECT COUNT(*) AS n FROM storage_quotas WHERE kind = %s AND "targetId" = %s',
                       ("user", users["luis"]))["n"] == 0
