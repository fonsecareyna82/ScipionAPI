"""The audit log against the migrated database: what routes record and how it is read back."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.backend.api.audit import recordAudit
from app.backend.api.permissions import withPermissions
from app.backend.api.services.access_service import AccessService
from app.backend.mapper.access_mapper import AccessPostgresqlMapper
from app.backend.mapper.audit_mapper import AuditPostgresqlMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper


@pytest.fixture
def audit(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    marker = uuid4().hex
    created = []

    def user(roleNames=()):
        userId = flat.insertUser(email="audit-%s-%s@example.com" % (marker, uuid4().hex[:6]), hashedPassword="x",
                                 firstName="Audit", lastName="User", institution=None, role="user", isActive=True,
                                 isVerified=True, verificationCode="")
        created.append(userId)
        roles = {role["name"]: role["id"] for role in AccessPostgresqlMapper(db).listRoles()}
        AccessPostgresqlMapper(db).setUserRoles(userId, [roles[name] for name in roleNames])
        return withPermissions(flat, flat.getUserById(userId))

    try:
        yield db, flat, user, marker
    finally:
        db.execute("DELETE FROM audit_events WHERE \"userEmail\" LIKE %s OR \"targetName\" LIKE %s",
                   ("%" + marker + "%", "%" + marker + "%"))
        for userId in created:
            db.execute("DELETE FROM users WHERE id = %s", (userId,))


def test_AnEventIsKeptAndReadBackNewestFirstWithItsFilters(audit):
    db, _, user, marker = audit
    admin = user(["Administrator"])
    recordAudit(db, admin, "roles.created", "role", 1, "Role %s" % marker, {"permissions": ["files.download"]})
    recordAudit(db, admin, "users.updated", "user", 2, "Someone %s" % marker, {"isActive": True})
    recordAudit(db, None, "auth.signInFailed", details={"reason": "unknown account"},
                actorEmail="nobody-%s@example.com" % marker)

    events = AuditPostgresqlMapper(db).listEvents(10, text=marker)
    assert [event["action"] for event in events] == ["auth.signInFailed", "users.updated", "roles.created"]
    assert events[2]["details"] == {"permissions": ["files.download"]}
    assert events[2]["userId"] == admin["id"] and events[0]["userId"] is None
    assert events[0]["userEmail"] == "nobody-%s@example.com" % marker

    # A category is the first part of the action; an action matches itself
    assert [event["action"] for event in AuditPostgresqlMapper(db).listEvents(10, action="users", text=marker)] == [
        "users.updated"]
    assert len(AuditPostgresqlMapper(db).listEvents(10, action="roles.created", text=marker)) == 1
    assert AuditPostgresqlMapper(db).listEvents(10, action="role", text=marker) == []
    # The next page starts below the last id seen
    assert [event["action"] for event in AuditPostgresqlMapper(db).listEvents(10, before=events[1]["id"],
                                                                              text=marker)] == ["roles.created"]


def test_TheEventOutlivesItsActor(audit):
    db, _, user, marker = audit
    actor = user(["User"])
    recordAudit(db, actor, "projects.created", "project", 9, "Project %s" % marker)
    db.execute("DELETE FROM users WHERE id = %s", (actor["id"],))

    event = AuditPostgresqlMapper(db).listEvents(1, text=marker)[0]
    assert event["userId"] is None and event["userEmail"] == actor["email"]


def test_RaisingWhatAGroupsPisReachNeedsAsMuchOverEveryProject(audit):
    db, _, user, marker = audit
    service = AccessService(db)
    manager = user(["Facility manager"])  # holds projects.viewAll, not projects.manageAll
    admin = user(["Administrator"])
    group = service.saveGroup(manager, {"name": "Lab %s" % marker})
    try:
        assert group["piAccess"] == "view"
        with pytest.raises(HTTPException) as error:
            service.saveGroup(manager, {"name": "Lab %s" % marker, "piAccess": "work"}, groupId=group["id"])
        assert error.value.status_code == 403 and "projects.manageAll" in error.value.detail
        # Lowering it is giving less; an administrator raises it
        assert service.saveGroup(manager, {"name": "Lab %s" % marker, "piAccess": "none"},
                                 groupId=group["id"])["piAccess"] == "none"
        assert service.saveGroup(admin, {"name": "Lab %s" % marker, "piAccess": "manage"},
                                 groupId=group["id"])["piAccess"] == "manage"
        with pytest.raises(HTTPException):
            service.saveGroup(admin, {"name": "Lab %s" % marker, "piAccess": "everything"}, groupId=group["id"])
    finally:
        db.execute("DELETE FROM user_groups WHERE id = %s", (group["id"],))
