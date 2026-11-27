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
    conversationsKept = {}
    messagesKept = []

    def conversation(self, userId, conversationId):
        kept = _Usage.conversationsKept.get(conversationId)
        return kept if kept and kept["userId"] == userId else None

    def addConversation(self, userId, projectId, title, mode=""):
        conversationId = len(_Usage.conversationsKept) + 1
        _Usage.conversationsKept[conversationId] = {"id": conversationId, "userId": userId, "projectId": projectId,
                                                    "title": title, "mode": mode}
        return conversationId

    def addMessage(self, conversationId, role, text, answer=None):
        _Usage.messagesKept.append({"conversationId": conversationId, "role": role, "text": text, "answer": answer})

    def messages(self, conversationId, limit=None):
        rows = [dict(row) for row in _Usage.messagesKept if row["conversationId"] == conversationId]
        return rows[-limit:] if limit else rows

    def conversations(self, userId, limit):
        import datetime
        now = datetime.datetime(2026, 11, 27, tzinfo=datetime.timezone.utc)
        return [dict(item, createdAt=now, updatedAt=now, projectPath=None, messages=2)
                for item in _Usage.conversationsKept.values() if item["userId"] == userId]

    def projectOutputs(self, projectId):
        return [{"protocolId": "2", "className": "ProtImportMovies", "status": "finished", "label": "import",
                 "outputClass": "SetOfMovies", "size": "30"},
                {"protocolId": "3", "className": "ProtMotionCorr", "status": "running", "label": "align",
                 "outputClass": None, "size": None}]

    def deleteConversation(self, userId, conversationId):
        if not self.conversation(userId, conversationId):
            return False
        return _Usage.conversationsKept.pop(conversationId, None) is not None

    def protocol(self, projectId, protocolId):
        return _Usage.protocolRow

    def pointerParams(self, projectId, protocolId):
        return {"inputParticles": "22.outputParticles"}

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
    _Usage.conversationsKept, _Usage.messagesKept = {}, []
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
        return {"status": 0, "errors": [], "duplicated": [{"sourceId": item.id, "newId": str(200 + index)}
                                                          for index, item in enumerate(items)]}

    comment = "old note"

    def _getScipionProtocolByScipionId(self, protocolId):
        return type("Protocol", (), {"getObjComment": lambda self: _Service.comment})()

    def renameProtocol(self, mapper, projectId, protocolId, newName, newComment, protocolIdIsScipionId=False):
        _Service.calls.append(("rename", protocolId, newName, newComment))
        return {"status": 0, "errors": []}

    def launchProtocol(self, **kwargs):
        _Service.calls.append(("launch", kwargs))
        return {"status": 0, "errors": []}

    def resetProtocolFrom(self, mapper, projectId, protocolId, includeRoot=True):
        _Service.calls.append(("reset", protocolId))
        return {"status": 0, "errors": []}

    tags = {}
    projectTags = []

    def listProtocolTags(self, mapper, projectId, protocolId, currentUser, protocolIdIsScipionId=False):
        return {"protocolId": str(protocolId), "tagIds": list(_Service.tags.get(str(protocolId), []))}

    def setProtocolTags(self, mapper, projectId, protocolId, tagIds, currentUser, protocolIdIsScipionId=False):
        _Service.calls.append(("tags", str(protocolId), list(tagIds)))
        _Service.tags[str(protocolId)] = list(tagIds)

    def createProjectTag(self, mapper, projectId, currentUser, payload):
        tag = {"id": "t-new", "title": payload.title, "color": None}
        _Service.calls.append(("newTag", payload.title))
        _Service.projectTags.append(tag)
        return tag

    def getMetadataTableSchemaService(self, **kwargs):
        return {"columns": [{"name": "id"}, {"name": "_resolution"}], "actions": ["CTFModel"]}

    def getMetadataTablePageService(self, page, pageSize, **kwargs):
        rows = [{"id": 1, "values": [1, 3.1]}, {"id": 2, "values": [2, 6.0]}, {"id": 3, "values": [3, 2.8]}]
        return {"totalRows": 3, "rows": rows if page == 1 else []}

    def runMetadataTableActionService(self, **kwargs):
        _Service.calls.append(("subset", kwargs["ids"], kwargs["action"], kwargs["subsetName"]))
        return {"success": True}

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
    _Service.tags, _Service.projectTags = {}, [{"id": "t1", "title": "Good", "color": "#0a0"}]
    monkeypatch.setattr(services, "ProjectService", _Service)
    # Internal ids differ from the numbers the user sees (the launch takes internal ones)
    identity = importlib.import_module("app.backend.runtime.protocol_identity")
    monkeypatch.setattr(identity.ProtocolIdentityResolver, "resolvePostgresqlProtocolDbIdFromScipionProtocolId",
                        lambda self, protocolId: int(protocolId) + 9000)
    monkeypatch.setattr(router, "_projectTag", lambda mapper, projectId, title: next(
        (tag for tag in _Service.projectTags if tag["title"].lower() == title.lower()), None))
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
    assert kwargs["params"] == {"inputParticles": "22.outputParticles", "numberOfClasses": 100}
    assert kwargs["mode"] == "restart" and kwargs["scope"] == "single"
    # The internal id of #37, never 37 itself (another protocol may have that internal id)
    assert kwargs["protocolId"] == 9037


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
    assert _Service.calls == [("duplicate", ["37"]),
                              ("save", "200", {"inputParticles": "22.outputParticles", "numberOfClasses": 30})]


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


def test_NoLimitWhenItIsZero(router):
    _turnOn(router, limit=1)
    router.AssistantSettings(None).save({"dailyLimit": 0}, 1)
    client = _client(router, ["assistant.use"])
    assert client.get("/help-chat/status").json() == {"assistant": True, "dailyLimit": 0}
    for _ in range(3):
        answer = client.post("/help-chat/ask", json={"question": "again"})
        assert answer.status_code == 200
        assert "left" not in answer.json()


def test_TheNoticeSwitchesAreSaved(router):
    admin = _client(router, ["settings.manage"])
    response = admin.put("/help-chat/settings", json={"explainFailures": True, "summarizeSessions": True})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["explainFailures"] is True and saved["summarizeSessions"] is True


def test_ReportGivesTheWorkflowFileAndThePdf(router, monkeypatch):
    from app.backend.api.services import workflow_report, workflow_report_pdf

    report = {"project": "SPA demo", "projectId": 7, "workflowFile": '["workflow"]', "protocols": []}
    monkeypatch.setattr(workflow_report, "reportData", lambda *args: report)
    monkeypatch.setattr(workflow_report_pdf, "render", lambda report, methods, version: b"%PDF-fake " +
                        str(methods).encode())
    client = _client(router, [])
    workflow = client.post("/help-chat/report", json={"projectId": 7, "protocolId": "37", "format": "workflow"})
    assert workflow.text == '["workflow"]'
    assert 'filename="SPA_demo_up_to_37_workflow.json"' in workflow.headers["content-disposition"]
    pdf = client.post("/help-chat/report", json={"projectId": 7})
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content == b"%PDF-fake None"


def test_ReportWithMethodsFromTheAssistant(router, monkeypatch):
    from app.backend.api.services import workflow_report, workflow_report_pdf

    _turnOn(router)
    monkeypatch.setattr(workflow_report, "reportData", lambda *args: {"project": "SPA", "projectId": 7,
                                                                      "workflowFile": "", "protocols": []})
    monkeypatch.setattr(workflow_report, "writeMethods", lambda provider, report: {
        "text": "Methods text.", "usage": {"inputTokens": 5, "outputTokens": 2}})
    monkeypatch.setattr(workflow_report_pdf, "render", lambda report, methods, version: methods.encode())
    pdf = _client(router, ["assistant.use"]).post("/help-chat/report", json={"projectId": 7})
    assert pdf.content == b"Methods text."
    assert _Usage.rows[3]["questions"] == 1


def test_ReportWithoutThePdfLibraryIsSaid(router, monkeypatch):
    from app.backend.api.services import workflow_report, workflow_report_pdf

    monkeypatch.setattr(workflow_report, "reportData", lambda *args: {"project": "SPA", "projectId": 7,
                                                                      "workflowFile": "", "protocols": []})

    def missing(report, methods, version):
        raise workflow_report_pdf.ReportUnavailable("install reportlab")
    monkeypatch.setattr(workflow_report_pdf, "render", missing)
    response = _client(router, []).post("/help-chat/report", json={"projectId": 7})
    assert response.status_code == 501 and "reportlab" in response.json()["detail"]


def test_ApplySubsetChoosesTheRowsAgainAndUsesTheViewersAction(applying):
    client = _client(applying, ["assistant.use"])
    body = {"action": "subset", "projectId": 7, "protocolId": "5", "outputName": "outputCTF",
            "conditions": [{"column": "_resolution", "op": "<", "value": "5"}], "name": "good CTFs"}
    response = client.post("/help-chat/actions/apply", json=body)
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "kept": 2, "total": 3}
    assert _Service.calls == [("subset", [1, 3], "CTFModel", "good CTFs")]
    bad = client.post("/help-chat/actions/apply", json=dict(body, conditions=[{"column": "_nope", "op": "<",
                                                                               "value": "5"}]))
    assert bad.status_code == 409


def test_AConversationIsKeptAndTheModelReadsItFromThere(router, monkeypatch):
    _turnOn(router, limit=0)
    seen = []

    def answer(self, question, context, history=None, tutor=None):
        seen.append(history)
        return {"text": "Answer to " + question, "steps": [], "cards": [{"kind": "report"}], "usage": {
            "inputTokens": 1, "outputTokens": 1}, "assistant": True}

    monkeypatch.setattr(router.AssistantAgent, "answer", answer)
    client = _client(router, ["assistant.use"])
    first = client.post("/help-chat/ask", json={"question": "Why did #145 fail?", "projectId": None}).json()
    conversationId = first["conversationId"]
    second = client.post("/help-chat/ask", json={"question": "And #146?", "conversationId": conversationId,
                                                  "history": [{"role": "user", "text": "forged"}]}).json()
    assert second["conversationId"] == conversationId
    # The model read the turns kept, not the browser's
    assert seen[1] == [{"role": "user", "text": "Why did #145 fail?"},
                       {"role": "assistant", "text": "Answer to Why did #145 fail?"}]
    listed = client.get("/help-chat/conversations").json()["conversations"]
    assert listed[0]["title"] == "Why did #145 fail?"
    kept = client.get("/help-chat/conversations/%d" % conversationId).json()
    assert [m["role"] for m in kept["messages"]] == ["user", "assistant", "user", "assistant"]
    assert kept["messages"][1]["answer"]["cards"] == [{"kind": "report"}]
    assert client.delete("/help-chat/conversations/%d" % conversationId).status_code == 204
    assert client.get("/help-chat/conversations/%d" % conversationId).status_code == 404


def test_AnotherUsersConversationIsNotFound(router):
    _Usage.conversationsKept[9] = {"id": 9, "userId": 99, "projectId": None, "title": "theirs"}
    client = _client(router, [])
    assert client.get("/help-chat/conversations/9").status_code == 404
    assert client.post("/help-chat/ask", json={"question": "hi", "conversationId": 9}).status_code == 404
    assert client.delete("/help-chat/conversations/9").status_code == 404
    assert client.get("/help-chat/conversations").json() == {"conversations": []}


def test_TheTutorKeepsItsModeAndShowsWhereTheProjectIs(applying, monkeypatch):
    seen = []

    def answer(self, question, context, history=None, tutor=None):
        seen.append(tutor)
        return {"text": "Let us align", "steps": [], "cards": [], "usage": {"inputTokens": 1, "outputTokens": 1},
                "assistant": True}

    monkeypatch.setattr(applying.AssistantAgent, "answer", answer)
    client = _client(applying, ["assistant.use"])
    first = client.post("/help-chat/ask", json={"question": "Guide me", "projectId": 7, "mode": "tutor"}).json()
    assert first["mode"] == "tutor"
    card = first["cards"][0]
    assert card["kind"] == "tutorial" and card["road"] == "spa" and card["current"] == "micrographs"
    assert [stage["state"] for stage in card["stages"][:3]] == ["done", "running", "pending"]
    assert "micrographs [movie alignment]: running" in seen[0]
    # The next question goes on in tutor mode without saying it again
    second = client.post("/help-chat/ask", json={"question": "And now?", "projectId": 7,
                                                  "conversationId": first["conversationId"]}).json()
    assert second["mode"] == "tutor" and seen[1]
    assert client.get("/help-chat/conversations").json()["conversations"][0]["mode"] == "tutor"
    # An ordinary conversation is not the tutor
    plain = client.post("/help-chat/ask", json={"question": "hi", "projectId": 7}).json()
    assert "mode" not in plain and seen[2] is None


def test_TheTutorWithoutAProjectAsksToOpenOne(applying, monkeypatch):
    seen = []

    def answer(self, question, context, history=None, tutor=None):
        seen.append(tutor)
        return {"text": "Open your project", "steps": [], "cards": [], "usage": {"inputTokens": 1,
                                                                                 "outputTokens": 1}}

    monkeypatch.setattr(applying.AssistantAgent, "answer", answer)
    answer_ = _client(applying, ["assistant.use"]).post("/help-chat/ask", json={"question": "Guide me",
                                                                                "mode": "tutor"}).json()
    assert seen == [""] and answer_["cards"] == []


def test_TheTutorNeedsTheAssistant(router):
    client = _client(router, ["assistant.use"])
    assert client.post("/help-chat/ask", json={"question": "Guide me", "mode": "tutor"}).status_code == 400


def _withChildren(monkeypatch, module, outputs=None):
    _Service.affected = [{"protocolId": "37", "level": 0}, {"protocolId": "105", "runName": "subset",
                                                            "status": "finished"},
                         {"protocolId": "106", "runName": "initial", "status": "finished"}]
    monkeypatch.setattr(module.HelpChatPostgresqlMapper, "protocolOutputs",
                        lambda self, p, q: (outputs or {}).get(q, []))


def test_DuplicateAndLaunchTheCopy(applying):
    client = _client(applying, ["assistant.use"])
    response = client.post("/help-chat/actions/apply", json={"action": "duplicate", "projectId": 7, "protocolId": "37",
                                                             "launch": True})
    assert response.json() == {"ok": True, "newProtocolId": "200", "started": True}
    launched = _Service.calls[-1]
    assert launched[0] == "workflow" and launched[1]["protocolId"] == 9200 and launched[1]["scope"] == "single"
    assert launched[1]["params"] == {"inputParticles": "22.outputParticles"}


def test_CopyTheSubworkflowAsListedAndLaunchItsFirstCopy(applying, monkeypatch):
    _withChildren(monkeypatch, applying)
    client = _client(applying, ["assistant.use"])
    body = {"action": "copyworkflow", "projectId": 7, "protocolId": "37", "protocolIds": ["37", "105"]}
    # A protocol was added after it since the card: nothing is copied
    changed = client.post("/help-chat/actions/apply", json=body)
    assert changed.status_code == 409 and "changed" in changed.json()["detail"]
    assert _Service.calls == []
    response = client.post("/help-chat/actions/apply", json=dict(body, protocolIds=["37", "105", "106"], launch=True))
    assert response.json() == {"ok": True, "protocols": 3, "newProtocolId": "200", "started": True}
    assert _Service.calls[0] == ("duplicate", ["37", "105", "106"])
    assert _Service.calls[1][1]["protocolId"] == 9200 and _Service.calls[1][1]["scope"] == "all"


def test_ResetOnlyWhenNothingRuns(applying, monkeypatch):
    _withChildren(monkeypatch, applying, {"105": [{"outputName": "outputParticles"}]})
    _Service.affected[2]["status"] = "running"
    _Service.affected[2]["active"] = True
    client = _client(applying, ["assistant.use"])
    body = {"action": "reset", "projectId": 7, "protocolId": "37", "protocolIds": ["37", "105", "106"]}
    refused = client.post("/help-chat/actions/apply", json=body)
    assert refused.status_code == 409 and "#106" in refused.json()["detail"]
    _Service.affected[2].update(status="finished", active=False)
    assert client.post("/help-chat/actions/apply", json=body).json() == {"ok": True, "protocols": 3}
    assert _Service.calls == [("reset", 37)]


def test_DeleteFromNeedsTheSwitchTheSameListAndHowMany(applying, monkeypatch):
    _withChildren(monkeypatch, applying, {"105": [{"outputName": "outputParticles"}]})
    client = _client(applying, ["assistant.use"])
    body = {"action": "deletefrom", "projectId": 7, "protocolId": "37", "protocolIds": ["37", "105", "106"],
            "confirm": "3"}
    assert client.post("/help-chat/actions/apply", json=body).status_code == 403
    applying.AssistantSettings(None).save({"allowDelete": True}, 1)
    assert client.post("/help-chat/actions/apply", json=dict(body, confirm="37")).status_code == 409
    assert client.post("/help-chat/actions/apply", json=dict(body, protocolIds=["37", "105"],
                                                             confirm="2")).status_code == 409
    assert _Service.calls == []
    # Children with results do not stop it (the card listed them), unlike deleting one protocol
    assert client.post("/help-chat/actions/apply", json=body).json() == {"ok": True, "protocols": 3}
    assert _Service.calls == [("delete", ["37", "105", "106"])]


def test_TagMadeWhenNewAndAddedToTheOthersTags(applying):
    _Service.tags = {"37": ["t1"]}
    _Usage.protocolRow = dict(_Usage.protocolRow)
    client = _client(applying, ["assistant.use"])
    response = client.post("/help-chat/actions/apply", json={"action": "tag", "projectId": 7, "protocolId": "37",
                                                             "protocolIds": ["37"], "tag": "  to  check "})
    assert response.json() == {"ok": True, "tag": "to check", "newTag": True, "tagged": ["37"]}
    assert _Service.calls == [("newTag", "to check"), ("tags", "37", ["t1", "t-new"])]
    again = client.post("/help-chat/actions/apply", json={"action": "tag", "projectId": 7, "protocolId": "37",
                                                          "protocolIds": ["37"], "tag": "GOOD"}).json()
    assert again["newTag"] is False and _Service.tags["37"] == ["t1", "t-new"] and again["tagged"] == []


def test_ARefusedLaunchIsToldInWords(applying, monkeypatch):
    def refuse(self, **kwargs):
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=["Input particles: no particles", "Choose a volume"])

    monkeypatch.setattr(_Service, "executeProtocolWorkflow", refuse)
    client = _client(applying, ["assistant.use"])
    response = client.post("/help-chat/actions/apply", json={"action": "duplicate", "projectId": 7, "protocolId": "37",
                                                             "launch": True})
    assert response.status_code == 422
    assert response.json()["detail"] == "Input particles: no particles; Choose a volume"


def test_AFailedCopyIsToldInWords(applying, monkeypatch):
    def fail(self, mapper, projectId, items, protocolIdIsScipionId=False):
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Failed to restore duplicated protocol pointers")

    monkeypatch.setattr(_Service, "duplicateProtocol", fail)
    client = _client(applying, ["assistant.use"])
    response = client.post("/help-chat/actions/apply", json={"action": "duplicate", "projectId": 7, "protocolId": "37"})
    assert response.status_code == 422
    assert response.json()["detail"] == "The copy could not be made: Failed to restore duplicated protocol pointers"


def test_TagTakenOffOnlyWhereItIsAndTheTagStays(applying):
    _Service.tags = {"37": ["t1", "t9"], "38": ["t9"]}
    client = _client(applying, ["assistant.use"])
    body = {"action": "untag", "projectId": 7, "protocolId": "37", "protocolIds": ["37"], "tag": "good"}
    assert client.post("/help-chat/actions/apply", json=body).json() == {"ok": True, "tag": "Good",
                                                                          "untagged": ["37"]}
    assert _Service.tags["37"] == ["t9"] and _Service.projectTags[0]["id"] == "t1"
    # Nothing to take off, and an unknown tag
    assert client.post("/help-chat/actions/apply", json=body).json()["untagged"] == []
    unknown = client.post("/help-chat/actions/apply", json=dict(body, tag="nope"))
    assert unknown.status_code == 409 and "no tag called nope" in unknown.json()["detail"]



def test_RenameKeepsWhatTheCardDidNotChange(applying):
    client = _client(applying, ["assistant.use"])
    body = {"action": "rename", "projectId": 7, "protocolId": "37",
            "renames": [{"field": "comment", "to": "old note\nthick ice"}]}
    assert client.post("/help-chat/actions/apply", json=body).json() == {"ok": True, "name": "2D"}
    assert _Service.calls == [("rename", "37", "2D", "old note\nthick ice")]


def test_ScheduleAddsToTheWaitListAndLaunchesBySchedule(applying):
    _Usage.protocolRow = dict(_Usage.protocolRow, status="saved", params={"_prerequisites": "12"})
    client = _client(applying, ["assistant.use"])
    body = {"action": "schedule", "projectId": 7, "protocolId": "37", "protocolIds": ["37"]}
    # It cannot wait for itself
    refused = client.post("/help-chat/actions/apply", json=body)
    assert refused.status_code == 409 and "itself" in refused.json()["detail"]


def test_ScheduleLaunchesBySchedule(applying, monkeypatch):
    rows = {"37": dict(_Usage.protocolRow, status="saved", params={"_prerequisites": "12"}),
            "30": {"protocolId": "30", "label": "ctf", "className": "Ctf", "status": "running"}}
    monkeypatch.setattr(_Usage, "protocol", lambda self, projectId, protocolId: rows.get(str(protocolId)))
    client = _client(applying, ["assistant.use"])
    response = client.post("/help-chat/actions/apply", json={"action": "schedule", "projectId": 7,
                                                             "protocolId": "37", "protocolIds": ["30"]})
    assert response.json() == {"ok": True, "waitFor": ["30"]}
    kind, kwargs = _Service.calls[-1]
    assert kind == "launch" and kwargs["executeMode"] == "schedule" and kwargs["protocolIdIsScipionId"] is True
    assert kwargs["params"]["_prerequisites"] == "12,30"
    assert kwargs["params"]["inputParticles"] == "22.outputParticles"
