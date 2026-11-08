"""Deleting an account with its projects, against the migrated database."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.backend.api.permissions import withPermissions
from app.backend.api.services import user_deletion
from app.backend.mapper.access_mapper import AccessPostgresqlMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.utils.background_delete import waitForBackgroundDeletes


def _user(flat, name):
    return flat.insertUser(email="%s-%s@example.org" % (name, uuid4().hex), hashedPassword="test", firstName=name,
                           lastName="Test", institution=None, role="user", isActive=True, isVerified=True,
                           verificationCode="")


@pytest.fixture
def accounts(postgresqlIntegrationDb, postgresqlMigratedEnv, tmp_path):
    """An administrator, a user with two projects (one shared with another user) and that other user."""
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    adminId, userId, otherId = _user(flat, "admin"), _user(flat, "leaving"), _user(flat, "other")
    AccessPostgresqlMapper(db).grantSystemRole(adminId)
    projects = [flat.insertProject(ownerId=userId, name=str(tmp_path / ("P%d-%s" % (index, uuid4().hex))))
                for index in (1, 2)]
    db.execute('INSERT INTO project_shares ("projectId", "userId", permission) VALUES (%s, %s, %s)',
               (projects[0], otherId, "view"))
    try:
        yield {"db": db, "flat": flat, "admin": withPermissions(flat, flat.getUserById(adminId)), "userId": userId,
               "otherId": otherId, "projects": projects}
    finally:
        waitForBackgroundDeletes(timeout=60)
        db.execute("DELETE FROM projects WHERE id = ANY(%s)", (projects,))
        db.execute("DELETE FROM users WHERE id = ANY(%s)", ([adminId, userId, otherId],))


def test_ThePreviewSaysWhatGoesAndWhatStopsIt(accounts):
    db, flat, admin = accounts["db"], accounts["flat"], accounts["admin"]

    preview = user_deletion.deletionPreview(flat, admin, accounts["userId"])

    assert [project["id"] for project in preview["projects"]] == accounts["projects"]
    assert preview["projects"][0]["shares"] == 1 and preview["blockers"] == []
    # Oneself, and while a protocol runs
    assert user_deletion.deletionPreview(flat, admin, admin["id"])["blockers"]
    db.execute('INSERT INTO protocols ("protocolId", "projectId", "protocolClassName", params, status) '
               "VALUES (%s, %s, %s, %s, %s)", (5, accounts["projects"][1], "ProtMotionCorr", "{}", "running"))
    blocked = user_deletion.deletionPreview(flat, admin, accounts["userId"])["blockers"]
    assert len(blocked) == 1 and "stop them first" in blocked[0]
    with pytest.raises(HTTPException) as error:
        user_deletion.deleteUser(flat, admin, accounts["userId"], flat.getUserById(accounts["userId"])["email"])
    assert error.value.status_code == 409
    # Who cannot manage every project cannot take the projects with the account
    weak = dict(admin, permissions=["users.manage"], isSystemAdmin=False)
    db.execute('DELETE FROM protocols WHERE "projectId" = %s', (accounts["projects"][1],))
    assert any("manage every project" in blocker
               for blocker in user_deletion.deletionPreview(flat, weak, accounts["userId"])["blockers"])


def test_TheAccountGoesWithItsProjectsOnceConfirmed(accounts):
    db, flat, admin, userId = accounts["db"], accounts["flat"], accounts["admin"], accounts["userId"]
    email = flat.getUserById(userId)["email"]

    with pytest.raises(HTTPException) as error:
        user_deletion.deleteUser(flat, admin, userId, "someone@else.org")
    assert error.value.status_code == 400

    result = user_deletion.deleteUser(flat, admin, userId, email.upper())

    assert [project["id"] for project in result["deleted"]] == accounts["projects"] and result["failed"] == []
    # At once: it cannot sign in, and the lists no longer show it
    stopped = db.fetchOne('SELECT "isActive", "deletingAt" FROM users WHERE id = %s', (userId,))
    assert stopped is None or (not stopped["isActive"] and stopped["deletingAt"] is not None)
    assert userId not in [row["id"] for row in flat.listUsersForAdmin()]
    assert userId not in [row["id"] for row in flat.listUsers()]
    waitForBackgroundDeletes(timeout=60)
    assert db.fetchOne("SELECT COUNT(*) AS n FROM projects WHERE id = ANY(%s)", (accounts["projects"],))["n"] == 0
    assert db.fetchOne("SELECT id FROM users WHERE id = %s", (userId,)) is None
