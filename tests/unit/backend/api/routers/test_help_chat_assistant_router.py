"""The help chat routes with the AI assistant: who gets it, its daily limit, and the settings only for admins."""
import importlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _Settings:
    store = {}

    def __init__(self, db):
        pass

    def getSettings(self):
        return dict(_Settings.store)

    def saveSettings(self, values, userId):
        _Settings.store.update(json.loads(json.dumps(values)))


class _Usage:
    rows = {}

    def __init__(self, db):
        pass

    def usageToday(self, userId):
        return dict(_Usage.rows.get(userId, {"questions": 0, "inputTokens": 0, "outputTokens": 0}))

    def addUsage(self, userId, questions, inputTokens, outputTokens):
        row = self.usageToday(userId)
        row["questions"] += questions
        row["inputTokens"] += inputTokens
        row["outputTokens"] += outputTokens
        _Usage.rows[userId] = row

    protocolRow = None

    def protocol(self, projectId, protocolId):
        return _Usage.protocolRow

    def totals(self, days):
        return {"users": len(_Usage.rows), "questions": sum(r["questions"] for r in _Usage.rows.values()),
                "inputTokens": 0, "outputTokens": 0}


class _Model:
    def __init__(self, *args, **kwargs):
        self.model = "gpt-x"

    def chat(self, messages, tools=None):
        return {"message": {"content": "From the model"}, "usage": {"inputTokens": 50, "outputTokens": 5}}

    def models(self):
        return ["gpt-x", "gpt-y"]


@pytest.fixture
def router(authTestEnv, monkeypatch):
    module = importlib.import_module("app.backend.api.routers.help_chat_router")
    settingsModule = importlib.import_module("app.backend.api.services.assistant_settings")
    _Settings.store, _Usage.rows = {}, {}
    monkeypatch.setattr(settingsModule, "FacilitySettingsPostgresqlMapper", _Settings)
    monkeypatch.setattr(module, "AssistantPostgresqlMapper", _Usage)
    monkeypatch.setattr(module, "AssistantProvider", _Model)
    monkeypatch.setattr(module, "recordAudit", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_projectTools", lambda mapper, user, *flags: module.AssistantTools(
        lambda: [], lambda p: [], lambda p, q: None, lambda p, q, c: "", lambda p, q: {}, lambda q: []))
    return module


def _client(module, permissions):
    dependencies = importlib.import_module("app.backend.api.dependencies")
    database = importlib.import_module("app.backend.database")
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[dependencies.getCurrentUser] = lambda: {"id": 3, "permissions": list(permissions)}
    app.dependency_overrides[database.getMapperDependency] = lambda: type("Mapper", (), {"db": None})()
    return TestClient(app)


def _turnOn(module, limit=50):
    module.AssistantSettings(None).save({"provider": "openai", "key": "sk-test", "model": "gpt-x",
                                         "enabled": True, "dailyLimit": limit}, 1)


def test_RuleBasedChatWhileTheAssistantIsOff(router, monkeypatch):
    monkeypatch.setattr(router.HelpChat, "answer", lambda self, question, protocolId=None: {"text": "rules",
                                                                                         "cards": []})
    client = _client(router, ["assistant.use"])
    assert client.get("/help-chat/status").json() == {"assistant": False}
    assert client.post("/help-chat/ask", json={"question": "hi"}).json()["text"] == "rules"


def test_WithoutThePermissionTheUserKeepsTheRuleBasedChat(router, monkeypatch):
    _turnOn(router)
    monkeypatch.setattr(router.HelpChat, "answer", lambda self, question, protocolId=None: {"text": "rules",
                                                                                         "cards": []})
    client = _client(router, [])
    assert client.get("/help-chat/status").json() == {"assistant": False}
    assert client.post("/help-chat/ask", json={"question": "hi"}).json()["text"] == "rules"


def test_AssistantAnswersAndCountsTheQuestion(router):
    _turnOn(router, limit=5)
    client = _client(router, ["assistant.use"])
    assert client.get("/help-chat/status").json() == {"assistant": True, "dailyLimit": 5, "left": 5}
    answer = client.post("/help-chat/ask", json={"question": "hi", "history": [{"role": "user", "text": "a"}]}).json()
    assert answer["text"] == "From the model"
    assert answer["assistant"] is True
    assert answer["left"] == 4
    assert _Usage.rows[3] == {"questions": 1, "inputTokens": 50, "outputTokens": 5}


def test_DailyLimitStopsTheAssistant(router):
    _turnOn(router, limit=1)
    client = _client(router, ["assistant.use"])
    assert client.post("/help-chat/ask", json={"question": "one"}).status_code == 200
    response = client.post("/help-chat/ask", json={"question": "two"})
    assert response.status_code == 429
    assert "tomorrow" in response.json()["detail"]


def test_SettingsOnlyForAdministratorsAndWithoutTheKey(router):
    assert _client(router, ["assistant.use"]).get("/help-chat/settings").status_code == 403
    admin = _client(router, ["settings.manage"])
    saved = admin.put("/help-chat/settings", json={"provider": "openai", "key": "sk-very-secret"}).json()
    assert saved["keySet"] is True
    shown = admin.get("/help-chat/settings")
    assert shown.status_code == 200
    assert "sk-very-secret" not in shown.text


def test_ModelsAndTestUseTheFormBeforeSaving(router):
    admin = _client(router, ["settings.manage"])
    assert admin.post("/help-chat/settings/models", json={"provider": "openai"}).status_code == 400
    models = admin.post("/help-chat/settings/models", json={"provider": "openai", "key": "sk-1"})
    assert models.json() == {"models": ["gpt-x", "gpt-y"]}
    test = admin.post("/help-chat/settings/test", json={"provider": "openai", "key": "sk-1", "model": "gpt-x"})
    assert test.json()["ok"] is True
    # Nothing was saved by asking
    assert _Settings.store == {}


# Applying a proposal ---------------------------------------------------------------------------------------------

class _Service:
    calls = []
    access = "work"
    affected = []

    def getProjectDbRow(self, mapper, projectId, currentUser):
        return {"id": projectId, "name": "p", "access": _Service.access}

    def loadPostgresqlRuntimeProjectForMutation(self, mapper, projectId, currentUser):
        return {"id": projectId}

    def getProtocolWorkflowExecutionPreflight(self, mapper, projectId, protocolId, mode):
        return {"affectedProtocols": _Service.affected}

    def executeProtocolWorkflow(self, **kwargs):
        _Service.calls.append(("workflow", kwargs))
        return {"status": 0, "errors": []}

    def stopProtocol(self, mapper, projectId, protocolIds, protocolIdIsScipionId=False):
        _Service.calls.append(("stop", protocolIds))
        return {"status": 0, "errors": []}

    def deleteProtocol(self, mapper, projectId, protocolIds, protocolIdIsScipionId=False):
        _Service.calls.append(("delete", protocolIds))
        return {"status": 0, "errors": []}

    def duplicateProtocol(self, mapper, projectId, items, protocolIdIsScipionId=False):
        _Service.calls.append(("duplicate", [item.id for item in items]))
        return {"status": 0, "errors": [], "duplicated": [{"sourceId": items[0].id, "newId": "200"}]}

    def saveProtocol(self, mapper, projectId, protocolId, className, params, setToSave=True,
                     protocolIdIsScipionId=False):
        _Service.calls.append(("save", protocolId, params))
        return None, []


HELP = {"className": "Prot2D", "label": "2D", "params": [{"name": "numberOfClasses", "label": "Classes",
                                                          "pointer": False}]}


@pytest.fixture
def applying(router, monkeypatch):
    services = importlib.import_module("app.backend.api.services.project_service")
    _Service.calls, _Service.access, _Service.affected = [], "work", []
    monkeypatch.setattr(services, "ProjectService", _Service)
    monkeypatch.setattr(router.help_index, "protocolHelp", lambda className: HELP)
    _Usage.protocolRow = {"protocolId": "37", "label": "2D", "className": "Prot2D", "status": "finished",
                          "params": {"numberOfClasses": 50}}
    module = router
    module.AssistantSettings(None).save({"provider": "openai", "key": "sk", "model": "m", "enabled": True,
                                         "mode": "propose"}, 1)
    return module


def test_ApplyRelaunchSendsOnlyTheChangedParams(applying):
    client = _client(applying, ["assistant.use"])
    response = client.post("/help-chat/actions/apply", json={"action": "relaunch", "projectId": 7, "protocolId": "37",
                                                             "mode": "restart", "changes": {"numberOfClasses": "100"}})
    assert response.status_code == 200, response.text
    kind, kwargs = _Service.calls[0]
    assert kind == "workflow"
    assert kwargs["params"] == {"numberOfClasses": 100}
    assert kwargs["mode"] == "restart" and kwargs["scope"] == "single"


def test_ApplyWithChildrenNeedsTheUserToChoose(applying):
    _Service.affected = [{"protocolId": "37"}, {"protocolId": "105", "runName": "subset"}]
    client = _client(applying, ["assistant.use"])
    body = {"action": "relaunch", "projectId": 7, "protocolId": "37", "mode": "restart"}
    assert client.post("/help-chat/actions/apply", json=body).status_code == 409
    assert client.post("/help-chat/actions/apply", json=dict(body, scope="all")).status_code == 200
    assert _Service.calls[0][1]["scope"] == "all"


def test_ApplyStopOnlyWhenRunning(applying):
    client = _client(applying, ["assistant.use"])
    body = {"action": "stop", "projectId": 7, "protocolId": "37"}
    assert client.post("/help-chat/actions/apply", json=body).status_code == 409
    _Usage.protocolRow = dict(_Usage.protocolRow, status="running")
    assert client.post("/help-chat/actions/apply", json=body).status_code == 200
    assert _Service.calls == [("stop", ["37"])]


def test_ApplyNeedsWorkAccessAndTheProposeMode(applying):
    _Service.access = "view"
    client = _client(applying, ["assistant.use"])
    body = {"action": "relaunch", "projectId": 7, "protocolId": "37", "mode": "restart"}
    assert client.post("/help-chat/actions/apply", json=body).status_code == 403
    _Service.access = "work"
    applying.AssistantSettings(None).save({"mode": "answer"}, 1)
    assert client.post("/help-chat/actions/apply", json=body).status_code == 403
    assert _Service.calls == []


def test_ApplyDuplicateMakesTheCopyWithTheChanges(applying):
    client = _client(applying, ["assistant.use"])
    response = client.post("/help-chat/actions/apply", json={"action": "duplicate", "projectId": 7, "protocolId": "37",
                                                             "changes": {"numberOfClasses": "30"}})
    assert response.json() == {"ok": True, "newProtocolId": "200"}
    assert _Service.calls == [("duplicate", ["37"]), ("save", "200", {"numberOfClasses": 30})]


def test_ApplyDeleteOnlyTurnedOnAndConfirmedWithTheNumber(applying, monkeypatch):
    monkeypatch.setattr(applying.HelpChatPostgresqlMapper, "protocolOutputs", lambda self, p, q: [])
    client = _client(applying, ["assistant.use"])
    body = {"action": "delete", "projectId": 7, "protocolId": "37", "confirm": "37"}
    assert client.post("/help-chat/actions/apply", json=body).status_code == 403
    applying.AssistantSettings(None).save({"allowDelete": True}, 1)
    assert client.post("/help-chat/actions/apply", json=dict(body, confirm="3")).status_code == 409
    assert client.post("/help-chat/actions/apply", json=body).status_code == 200
    assert _Service.calls == [("delete", ["37"])]


def test_ApplyDeleteRefusedWhenAChildHasResults(applying, monkeypatch):
    applying.AssistantSettings(None).save({"allowDelete": True}, 1)
    _Service.affected = [{"protocolId": "37"}, {"protocolId": "105", "runName": "subset", "status": "finished"}]
    monkeypatch.setattr(applying.HelpChatPostgresqlMapper, "protocolOutputs",
                        lambda self, p, q: [{"outputName": "x"}] if q == "105" else [])
    client = _client(applying, ["assistant.use"])
    response = client.post("/help-chat/actions/apply", json={"action": "delete", "projectId": 7, "protocolId": "37",
                                                             "confirm": "37"})
    assert response.status_code == 409 and "#105" in response.json()["detail"]
    assert _Service.calls == []
