import json

import pytest

from app.backend.api.services.assistant_agent import AssistantAgent, AssistantTools
from app.backend.api.services.assistant_browse import (
    MAX_PAGE_SIZE, READ_ROUTES, WebReader, allowedPath, catalogue, cleanQuery,
)


@pytest.mark.parametrize("path", [
    "/projects/", "/projects", "projects/7/overview", "/api/projects/7/protocols/12/steps",
    "/projects/7/protocols/12/outputs/outputCTF/ctf",
    "/projects/7/protocols/12/outputs/outputParticles/metadata/tables/objects/page",
    "/facility/sessions/3", "/resources", "/settings/jobs", "/settings/jobs/nodes", "/plugins/tasks/abc-1/log",
])
def test_ListedPagesAreAllowed(path):
    assert allowedPath(path) is not None


@pytest.mark.parametrize("path", [
    "/settings/environment", "/settings/host", "/settings/sign-in-providers", "/users", "/audit", "/auth/me",
    "/notifications/settings/mail",
    "/projects/7/protocols/12/fs/download", "/projects/7/protocols/12/logs/raw",
    "/projects/7/protocols/12/outputs/x/metadata/tables/objects/export",
    "/projects/7/../../settings", "/projects/7/overview?x=1", "/projects//overview", "http://evil/projects/",
    "/projects/7/shares",
])
def test_EverythingElseIsRefused(path):
    assert allowedPath(path) is None


def test_NothingPrivateIsListed():
    paths = [template for template, _ in READ_ROUTES]
    for word in ("settings/environment", "settings/host", "settings/mail", "users", "auth", "audit", "access",
                 "fs/", "download", "export", "/raw", "mail", "shares", "sign-in"):
        assert not [path for path in paths if word in path], word
    assert "/projects/{projectId}/overview" in catalogue()


def test_PagesOfRowsAreKeptSmall():
    template = allowedPath("/projects/7/protocols/12/outputs/o/metadata/tables/objects/page")
    assert cleanQuery(template, {"pageSize": "5000"})["pageSize"] == str(MAX_PAGE_SIZE)
    assert cleanQuery(template, {})["pageSize"] == "20"
    assert cleanQuery("/resources", {"x": 1}) == {"x": "1"}


class FakeSend:
    def __init__(self, status=200, body=None, contentType="application/json"):
        self.status, self.body, self.contentType, self.calls = status, body, contentType, []

    def __call__(self, path, query, headers):
        self.calls.append((path, query, headers))
        text = self.body if isinstance(self.body, str) else json.dumps(self.body)
        return self.status, self.contentType, text


def test_ReadsAsTheUserWithTheirSignIn():
    send = FakeSend(body={"protocols": 3})
    answer = WebReader("Bearer user-token", send).read("/api/projects/7/overview")
    assert answer == {"page": "/projects/7/overview", "data": {"protocols": 3}}
    assert send.calls == [("/projects/7/overview", {}, {"Authorization": "Bearer user-token"})]


def test_RefusedPagesNeverReachTheApi():
    send = FakeSend()
    with pytest.raises(ValueError):
        WebReader("Bearer t", send).read("/settings/environment")
    assert send.calls == []


@pytest.mark.parametrize("status, error, said", [
    (403, PermissionError, "may not see"),
    (404, ValueError, "Not found"),
    (500, ValueError, "boom"),
])
def test_ErrorsAreToldToTheModel(status, error, said):
    with pytest.raises(error) as raised:
        WebReader("Bearer t", FakeSend(status=status, body={"detail": "boom"})).read("/resources")
    assert said in str(raised.value)


def test_OnlyData():
    with pytest.raises(ValueError):
        WebReader("Bearer t", FakeSend(body="<png>", contentType="image/png")).read("/resources")


class ScriptedModel:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def chat(self, messages, tools=None):
        self.sent.append({"messages": json.loads(json.dumps(messages)), "tools": tools})
        return {"message": self.replies.pop(0), "usage": {"inputTokens": 1, "outputTokens": 1}}


def test_AgentReadsPagesWhenGivenTheReader():
    read = [lambda: [], lambda p: [], lambda p, q: None, lambda p, q, c: "", lambda p, q: {}, lambda q: []]
    send = FakeSend(body={"steps": [{"name": "align", "status": "running"}]})
    tools = AssistantTools(*read, readPage=WebReader("Bearer t", send).read)
    model = ScriptedModel([
        {"content": None, "tool_calls": [{"id": "c1", "function": {"name": "read_page", "arguments": json.dumps(
            {"path": "/projects/7/protocols/12/steps", "query": []})}}]},
        {"content": "It is aligning."}])
    answer = AssistantAgent(model, tools).answer("where is #12?", "")
    assert "read_page" in {tool["function"]["name"] for tool in model.sent[0]["tools"]}
    assert "align" in model.sent[1]["messages"][-1]["content"]
    assert answer["steps"] == ["Read /projects/7/protocols/12/steps"]

    model = ScriptedModel([{"content": "ok"}])
    AssistantAgent(model, AssistantTools(*read)).answer("hi", "")
    assert "read_page" not in {tool["function"]["name"] for tool in model.sent[0]["tools"]}


def test_RefusedPageIsExplainedToTheModel():
    read = [lambda: [], lambda p: [], lambda p, q: None, lambda p, q, c: "", lambda p, q: {}, lambda q: []]
    tools = AssistantTools(*read, readPage=WebReader("Bearer t", FakeSend()).read)
    model = ScriptedModel([
        {"content": None, "tool_calls": [{"id": "c1", "function": {"name": "read_page", "arguments": json.dumps(
            {"path": "/settings/environment"})}}]},
        {"content": "I cannot read that."}])
    AssistantAgent(model, tools).answer("show the env", "")
    assert "not one the assistant may read" in model.sent[1]["messages"][-1]["content"]
