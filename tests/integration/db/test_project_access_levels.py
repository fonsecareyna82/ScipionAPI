"""What each user may do to a project, through the routes' access check and the database's access rule."""
from uuid import uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.backend.api.permissions import withPermissions
from app.backend.api.services.access_service import AccessService
from app.backend.mapper.access_mapper import AccessPostgresqlMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper


@pytest.fixture
def project(postgresqlIntegrationDb, postgresqlMigratedEnv, authTestEnv):
    # Imported here: they load the app's database setup, which needs the environment authTestEnv sets
    from app.backend.api.dependencies import getCurrentUser
    from app.backend.api.project_access import projectRouteAccess

    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    access = AccessPostgresqlMapper(db)
    roles = {role["name"]: role["id"] for role in access.listRoles()}
    users, groups = {}, []

    def user(name, roleNames):
        userId = flat.insertUser(email="%s-%s@example.com" % (name, uuid4().hex), hashedPassword="x", firstName=name,
                                 lastName="", institution=None, role="user", isActive=True, isVerified=True,
                                 verificationCode="")
        access.setUserRoles(userId, [roles[roleName] for roleName in roleNames])
        users[name] = userId
        return userId

    owner = user("owner", ["User"])
    viewer = user("viewer", ["User"])
    member = user("member", ["User"])
    user("technician", ["Technician"])
    user("guest", ["Guest"])
    user("admin", ["Administrator"])
    projectId = flat.insertProject(ownerId=owner, name="/tmp/access-%s" % uuid4().hex, description="Access")
    flat.shareProjectWithUser(projectId, viewer, "view")
    groupId = access.insertGroup("Lab %s" % uuid4().hex, "", [], [{"userId": member, "groupRole": "member"}])
    groups.append(groupId)
    flat.shareProjectWithGroup(projectId, groupId, "work")

    signedIn = {}
    router = APIRouter(prefix="/projects", dependencies=[Depends(projectRouteAccess(lambda: flat))])

    # The same route templates as the real routes; each answers as they do for a project out of reach
    def found(projectId: int, currentUser: dict = Depends(getCurrentUser)):
        if flat.getProject(projectId=projectId, userId=currentUser["id"]) is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"ok": True}

    router.get("/{projectId}/protocols")(found)
    router.post("/{projectId}/launch")(found)
    router.post("/{projectId}/protocols/{protocolId}/logs/chunk")(found)
    router.delete("/{projectId}")(found)
    router.post("/{projectId}/share")(found)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[getCurrentUser] = lambda: signedIn["user"]

    def asUser(name):
        signedIn["user"] = withPermissions(flat, flat.getUserById(users[name]))
        return TestClient(app)

    try:
        yield projectId, asUser, flat, users
    finally:
        flat.deleteProject(projectId=projectId, ownerId=owner)
        for groupId in groups:
            db.execute("DELETE FROM user_groups WHERE id = %s", (groupId,))
        for userId in users.values():
            db.execute("DELETE FROM users WHERE id = %s", (userId,))


@pytest.mark.parametrize("name,expected", [
    # read, launch, a POST that only reads, delete, share
    ("owner", (200, 200, 200, 200, 200)),
    ("viewer", (200, 403, 200, 403, 403)),
    ("member", (200, 200, 200, 403, 403)),
    ("technician", (200, 403, 200, 403, 403)),
    # Sharing asks for projects.share first, which says nothing about the project
    ("guest", (404, 404, 404, 404, 403)),
    ("admin", (200, 200, 200, 200, 200)),
])
def test_EachUserMayDoWhatTheirAccessAllows(project, name, expected):
    projectId, asUser, _, _ = project
    client = asUser(name)

    answers = (
        client.get("/projects/%s/protocols" % projectId).status_code,
        client.post("/projects/%s/launch" % projectId).status_code,
        client.post("/projects/%s/protocols/3/logs/chunk" % projectId).status_code,
        client.delete("/projects/%s" % projectId).status_code,
        client.post("/projects/%s/share" % projectId).status_code,
    )

    assert answers == expected


def test_TheProjectsListShowsWhatEachUserReaches(project):
    projectId, _, flat, users = project

    def listed(name):
        return {row["id"]: row["access"] for row in flat.listProjects(users[name])}.get(projectId)

    assert [listed(name) for name in ("owner", "viewer", "member", "technician", "guest", "admin")] == [
        "manage", "view", "work", "view", None, "manage"]


def test_SharingNeedsTheSharePermission(project):
    projectId, asUser, flat, users = project
    # The owner without projects.share (a Guest who owns a project) manages it but cannot share it
    AccessService(flat.db).mapper.setUserRoles(users["owner"], [])

    assert asUser("owner").post("/projects/%s/share" % projectId).status_code == 403
    assert asUser("owner").delete("/projects/%s" % projectId).status_code == 200


def test_APiReachesTheProjectsOfTheirGroupsMembersAtTheGroupsPiAccess(project):
    projectId, asUser, flat, users = project
    access = AccessPostgresqlMapper(flat.db)
    # A Guest holds no permission of their own: only being the PI of the owner's group reaches the project
    pi = flat.insertUser(email="pi-%s@example.com" % uuid4().hex, hashedPassword="x", firstName="pi", lastName="",
                         institution=None, role="user", isActive=True, isVerified=True, verificationCode="")
    users["pi"] = pi
    access.setUserRoles(pi, [role["id"] for role in access.listRoles() if role["name"] == "Guest"])
    members = [{"userId": users["owner"], "groupRole": "member"}, {"userId": pi, "groupRole": "pi"}]
    groupId = access.insertGroup("Lab of the PI %s" % uuid4().hex, "", [], members)

    def reached():
        row = flat.getProject(projectId=projectId, userId=pi)
        return row and (row["access"], row["accessVia"])

    try:
        assert reached() == ("view", "group")
        assert asUser("pi").get("/projects/%s/protocols" % projectId).status_code == 200
        assert asUser("pi").post("/projects/%s/launch" % projectId).status_code == 403

        access.updateGroup(groupId, "Lab of the PI %s" % uuid4().hex, "", [], members, piAccess="work")
        assert reached() == ("work", "group")
        assert asUser("pi").post("/projects/%s/launch" % projectId).status_code == 200

        access.updateGroup(groupId, "Lab of the PI %s" % uuid4().hex, "", [], members, piAccess="none")
        assert not reached()

        # A plain member of the group is no PI: the group alone does not reach the owner's projects
        access.updateGroup(groupId, "Lab of the PI %s" % uuid4().hex, "", [],
                           [dict(member, groupRole="member") for member in members], piAccess="manage")
        assert not reached()
    finally:
        flat.db.execute("DELETE FROM user_groups WHERE id = %s", (groupId,))


def test_TheAccessSaysWhereItComesFrom(project):
    projectId, _, flat, users = project

    def via(name):
        return (flat.getProject(projectId=projectId, userId=users[name]) or {}).get("accessVia")

    assert [via(name) for name in ("owner", "viewer", "member", "technician", "admin")] == [
        "owner", "share", "share", "role", "role"]
