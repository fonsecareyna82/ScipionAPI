"""The audit log's recording: never failing the request, the client address and the decorated routes."""
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.backend.api import audit


class FakeDb:
    def __init__(self, fail=False):
        self.fail = fail
        self.events = []

    def execute(self, query, params=None, commit=True):
        if self.fail:
            raise RuntimeError("the database is down")
        self.events.append(params)


def test_AnEventKeepsItsActorTargetDetailsAndTheClientAddress():
    db = FakeDb()
    token = audit._clientAddress.set("10.0.0.7")
    try:
        audit.recordAudit(type("Mapper", (), {"db": db})(), {"id": 3, "email": "ana@example.com"}, "roles.created",
                          "role", 12, "Microscopists", {"permissions": ["files.download"]})
    finally:
        audit._clientAddress.reset(token)

    event = db.events[0]
    assert (event["userId"], event["userEmail"], event["action"], event["targetId"]) == (
        3, "ana@example.com", "roles.created", "12")
    assert event["details"] == '{"permissions": ["files.download"]}'
    assert event["clientAddress"] == "10.0.0.7"


def test_RecordingNeverFailsTheRequest():
    audit.recordAudit(FakeDb(fail=True), {"id": 1}, "users.updated")
    # Without a database (a route tested with a fake mapper) nothing is kept
    audit.recordAudit(type("FakeMapper", (), {})(), {"id": 1}, "users.updated")
    audit.recordAudit(None, None, "auth.signIn")


def test_TheMiddlewareGivesEachRequestItsClientAddress():
    seen = []
    app = FastAPI()

    @app.get("/where")
    def where():
        seen.append(audit._clientAddress.get())
        return {}

    TestClient(audit.ClientAddressMiddleware(app)).get("/where")
    assert seen == ["testclient"]
    assert audit._clientAddress.get() is None


audited_install = audit.audited("plugins.installed", "plugin",
                                lambda kw: (kw["pluginName"], kw["pluginName"], {}))


def test_ADecoratedRouteRecordsOnlyWhenItSucceeds(monkeypatch):
    recorded = []
    monkeypatch.setattr(audit, "recordAuditOwnConnection", lambda *args: recorded.append(args))
    app = FastAPI()
    user = {"id": 5, "email": "admin@example.com"}

    def currentUserDependency():
        return user

    @app.post("/install/{pluginName}")
    @audited_install
    async def install(pluginName: str, currentUser=Depends(currentUserDependency)):
        if pluginName == "broken":
            raise HTTPException(status_code=500, detail="failed")
        return {"started": pluginName}

    client = TestClient(app)
    assert client.post("/install/scipion-em-xmipp").json() == {"started": "scipion-em-xmipp"}
    assert client.post("/install/broken").status_code == 500

    assert recorded == [(user, "plugins.installed", "plugin", "scipion-em-xmipp", "scipion-em-xmipp", {})]


def test_UserLabel():
    assert audit.userLabel({"firstName": "Ana", "lastName": "Ruiz", "email": "ana@example.com"}) == \
        "Ana Ruiz (ana@example.com)"
    assert audit.userLabel({"email": "ana@example.com"}) == "ana@example.com"
    assert audit.userLabel(None) is None


def test_AGroupsChangeSaysWhoAndWhatCameAndWent(authTestEnv):
    # Imported here: the router loads the app's database setup, which needs the environment authTestEnv sets
    from app.backend.api.routers.access_router import _groupChanges

    before = {"name": "Lab", "piAccess": "view", "roleIds": [1],
              "members": [{"userId": 1, "email": "ana@example.com", "groupRole": "pi"},
                          {"userId": 2, "email": "luis@example.com", "groupRole": "member"}]}
    after = {"name": "Lab A", "piAccess": "work", "roleIds": [1, 2],
             "members": [{"userId": 2, "email": "luis@example.com", "groupRole": "pi"},
                         {"userId": 3, "email": "eva@example.com", "groupRole": "member"}]}

    assert _groupChanges(before, after, {1: "User", 2: "Technician"}) == {
        "roles": {"added": ["Technician"]},
        "members": {"added": ["eva@example.com"], "removed": ["ana@example.com"]},
        "pis": {"added": ["luis@example.com"], "removed": ["ana@example.com"]},
        "piAccess": "work",
        "renamedFrom": "Lab",
    }
