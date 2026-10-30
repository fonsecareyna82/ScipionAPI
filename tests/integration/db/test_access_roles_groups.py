"""Roles, groups and the permissions they give, against the migrated database."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.backend.api.dependencies import withPermissions
from app.backend.api.permissions import PERMISSIONS
from app.backend.api.services.access_service import AccessService
from app.backend.mapper.access_mapper import AccessPostgresqlMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper


class MapperStub:
    def __init__(self, db):
        self.db = db


@pytest.fixture
def access(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    service = AccessService(db)
    created = {"users": [], "roles": [], "groups": []}

    def user(roleNames=(), active=True):
        userId = flat.insertUser(email="access-%s@example.com" % uuid4().hex, hashedPassword="x", firstName="A",
                                 lastName="B", institution=None, role="user", isActive=active, isVerified=True,
                                 verificationCode="")
        created["users"].append(userId)
        roles = {role["name"]: role["id"] for role in service.listRoles()}
        AccessPostgresqlMapper(db).setUserRoles(userId, [roles[name] for name in roleNames])
        return withPermissions(MapperStub(db), flat.getUserById(userId))

    try:
        yield db, service, user, created
    finally:
        for groupId in created["groups"]:
            db.execute("DELETE FROM user_groups WHERE id = %s", (groupId,))
        for roleId in created["roles"]:
            db.execute("DELETE FROM access_roles WHERE id = %s", (roleId,))
        for userId in created["users"]:
            db.execute("DELETE FROM users WHERE id = %s", (userId,))


def test_TheMigrationStartsWithTheDefaultRoles(access):
    _, service, _, _ = access
    roles = {role["name"]: role for role in service.listRoles()}

    assert set(roles) >= {"Administrator", "Facility manager", "Technician", "User", "Guest"}
    assert roles["Administrator"]["isSystem"] and not roles["User"]["isSystem"]
    assert roles["User"]["isDefault"]
    assert roles["User"]["permissions"] == ["files.download", "projects.create", "projects.share"]
    assert roles["Guest"]["permissions"] == []


def test_AUserHoldsTheirRolesAndTheirGroupsRoles(access):
    _, service, user, created = access
    admin = user(["Administrator"])
    member = user(["User"])
    technician = next(role for role in service.listRoles() if role["name"] == "Technician")

    group = service.saveGroup(admin, {"name": "Facility staff %s" % uuid4().hex, "roleIds": [technician["id"]],
                                      "members": [{"userId": member["id"], "groupRole": "member"}]})
    created["groups"].append(group["id"])

    held = withPermissions(MapperStub(access[0]), member)["permissions"]
    assert set(held) == {"projects.create", "projects.share", "files.download"} | set(technician["permissions"])
    assert admin["isSystemAdmin"] and admin["permissions"] == sorted(PERMISSIONS)


def test_NoOneGivesWhatTheyDoNotHold(access):
    _, service, user, created = access
    manager = user(["Facility manager"])
    target = user(["User"])
    roles = {role["name"]: role["id"] for role in service.listRoles()}

    with pytest.raises(HTTPException) as error:
        service.updateUserAccess(manager, target["id"], {"roleIds": [roles["Administrator"]]}, lambda *args: None)
    assert error.value.status_code == 403

    # A role with a permission the manager lacks, given through a group, is refused too
    admin = user(["Administrator"])
    plugins = service.saveRole(admin, {"name": "Plugins %s" % uuid4().hex, "permissions": ["plugins.manage"]})
    created["roles"].append(plugins["id"])
    with pytest.raises(HTTPException) as error:
        service.saveGroup(manager, {"name": "Escalation %s" % uuid4().hex, "roleIds": [plugins["id"]],
                                    "members": [{"userId": manager["id"]}]})
    assert error.value.status_code == 403

    # What the manager holds can be given
    service.updateUserAccess(manager, target["id"], {"roleIds": [roles["User"], roles["Technician"]]},
                             lambda *args: None)
    assert set(AccessPostgresqlMapper(access[0]).listUsersAccess()[target["id"]]["roleIds"]) == {
        roles["User"], roles["Technician"]}


def test_TheAdministratorRoleCannotBeChangedAndAnAdministratorAlwaysRemains(access):
    db, service, user, _ = access
    roles = {role["name"]: role["id"] for role in service.listRoles()}
    admin = user(["Administrator"])
    with pytest.raises(HTTPException):
        service.saveRole(admin, {"name": "Administrator", "permissions": []}, roleId=roles["Administrator"])
    with pytest.raises(HTTPException):
        service.deleteRole(admin, roles["Administrator"])

    # Every other administrator leaves: the last one cannot lose the role or be deactivated
    mapper = AccessPostgresqlMapper(db)
    others = [userId for userId in mapper.listActiveSystemUserIds() if userId != admin["id"]]
    for userId in others:
        db.execute("UPDATE users SET \"isActive\" = FALSE WHERE id = %s", (userId,))
    try:
        with pytest.raises(HTTPException) as error:
            service.updateUserAccess(admin, admin["id"], {"roleIds": [roles["User"]]}, lambda *args: None)
        assert "Administrator" in error.value.detail
        assert roles["Administrator"] in mapper.listUsersAccess()[admin["id"]]["roleIds"]
    finally:
        for userId in others:
            db.execute("UPDATE users SET \"isActive\" = TRUE WHERE id = %s", (userId,))
