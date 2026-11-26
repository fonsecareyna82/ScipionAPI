import json
from types import SimpleNamespace as NS

import pytest

from app.backend.api.services import assistant_anthropic
from app.backend.api.services.assistant_anthropic import AnthropicProvider, messagesFor, toolsFor
from app.backend.api.services.assistant_provider import AssistantProviderError


class Block(NS):
    def to_dict(self):
        return dict(self.__dict__)


class FakeMessages:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)
        self.beta = NS(messages=self.messages)
        self.models = NS(list=lambda: [NS(id="claude-sonnet-5-5"), NS(id="claude-opus-5-5")])


def reply(blocks, stop="end_turn"):
    return NS(content=blocks, stop_reason=stop, usage=NS(input_tokens=120, output_tokens=30))


TOOLS = [{"type": "function", "function": {"name": "protocol_log", "description": "The end of a log.",
                                           "parameters": {"type": "object", "properties": {"projectId": {}}}}}]


def test_ToolsTakeAnthropicsShape():
    assert toolsFor(TOOLS) == [{"name": "protocol_log", "description": "The end of a log.",
                                "input_schema": {"type": "object", "properties": {"projectId": {}}}}]


def test_MessagesTakeAnthropicsShape():
    system, messages = messagesFor([
        {"role": "system", "content": "You are the assistant."},
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Hola, ¿qué tal?"},
        {"role": "system", "content": "Reply in the language of the next user message."},
        {"role": "user", "content": "Why did #145 fail?"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "t1", "function": {"name": "protocol_log", "arguments": '{"projectId": 7}'}},
            {"id": "t2", "function": {"name": "explain_failure", "arguments": "{bad"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "CUDA out of memory"},
        {"role": "tool", "tool_call_id": "t2", "content": "{}"},
    ])
    assert system == "You are the assistant."
    assert messages[2] == {"role": "user", "content": "[ScipionWeb: Reply in the language of the next user "
                                                      "message.]\n\nWhy did #145 fail?"}
    assert messages[3]["content"][0] == {"type": "tool_use", "id": "t1", "name": "protocol_log",
                                         "input": {"projectId": 7}}
    assert messages[3]["content"][1]["input"] == {}
    # The results of one turn go in one user message
    assert messages[4] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "CUDA out of memory"},
        {"type": "tool_result", "tool_use_id": "t2", "content": "{}"}]}


def test_ClaudesOwnBlocksGoBackUnchanged():
    raw = [{"type": "thinking", "thinking": "", "signature": "sig"},
           {"type": "tool_use", "id": "t1", "name": "list_projects", "input": {}}]
    _, messages = messagesFor([{"role": "user", "content": "x"},
                               {"role": "assistant", "content": None, "tool_calls": [], "_raw": raw}])
    assert messages[1] == {"role": "assistant", "content": raw}


def test_AToolCallComesBackWithItsRawContent():
    client = FakeClient([reply([Block(type="thinking", thinking="", signature="s"),
                                Block(type="text", text="Let me look."),
                                Block(type="tool_use", id="t1", name="protocol_log", input={"projectId": 7})],
                               "tool_use")])
    answer = AnthropicProvider("sk-ant", "claude-haiku-5-5", client).chat(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}], TOOLS)
    call = client.messages.calls[0]
    assert call["model"] == "claude-haiku-5-5" and call["system"] == "S" and call["max_tokens"] > 1000
    assert call["tools"][0]["name"] == "protocol_log" and "betas" not in call
    assert answer["message"]["content"] == "Let me look."
    assert answer["message"]["tool_calls"] == [{"id": "t1", "type": "function", "function": {
        "name": "protocol_log", "arguments": json.dumps({"projectId": 7})}}]
    assert answer["message"]["_raw"][0] == {"type": "thinking", "thinking": "", "signature": "s"}
    assert answer["usage"] == {"inputTokens": 120, "outputTokens": 30}


def test_ModelsThatCanFallBackAskForIt():
    client = FakeClient([reply([Block(type="text", text="Done.")])])
    answer = AnthropicProvider("sk-ant", "claude-opus-5-5", client).chat([{"role": "user", "content": "Q"}])
    assert answer["message"] == {"content": "Done."}
    call = client.messages.calls[0]
    assert call["betas"] == [assistant_anthropic.FALLBACK_BETA]
    assert call["extra_body"] == {"fallbacks": "default"}


def test_ARefusalIsSaid():
    client = FakeClient([reply([], "refusal")])
    answer = AnthropicProvider("sk-ant", "claude-opus-5-5", client).chat([{"role": "user", "content": "Q"}])
    assert answer["finishReason"] == "refusal" and "declined" in answer["message"]["content"]


def test_ModelsAreListed():
    assert AnthropicProvider("sk-ant", "", FakeClient([])).models() == ["claude-opus-5-5", "claude-sonnet-5-5"]


def test_NoModelNoQuestion():
    with pytest.raises(AssistantProviderError):
        AnthropicProvider("sk-ant", "", FakeClient([])).chat([])


def test_WithoutThePackageItSaysSo(monkeypatch):
    import builtins

    real = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(AssistantProviderError) as error:
        AnthropicProvider("sk-ant", "claude-opus-5-5").chat([{"role": "user", "content": "Q"}])
    assert "pip install anthropic" in str(error.value)


def test_ErrorsAreSaidWithoutTheKey():
    anthropic = pytest.importorskip("anthropic")
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(401, request=request)
    error = anthropic.AuthenticationError("invalid x-api-key sk-ant-secret", response=response, body=None)
    client = FakeClient([])
    client.messages.create = lambda **kwargs: (_ for _ in ()).throw(error)
    with pytest.raises(AssistantProviderError) as raised:
        AnthropicProvider("sk-ant-secret", "claude-haiku-5-5", client).chat([{"role": "user", "content": "Q"}])
    assert "did not accept the key" in str(raised.value) and "sk-ant-secret" not in str(raised.value)


def test_TheOtherProvidersNeverSendTheRawContent():
    from app.backend.api.services.assistant_provider import AssistantProvider

    class Http:
        def request(self, method, url, headers=None, json=None, timeout=None):
            self.sent = json
            return NS(status_code=200, text="", json=lambda: {"choices": [{"message": {"content": "ok"}}]})

    http = Http()
    AssistantProvider("http://x/v1", "", "m", http=http).chat(
        [{"role": "assistant", "content": None, "tool_calls": [], "_raw": [{"type": "thinking"}]}])
    assert "_raw" not in http.sent["messages"][0]


def test_TheSettingsPickTheClient():
    from app.backend.api.services.assistant_provider import AssistantProvider
    from app.backend.api.services.assistant_settings import PROVIDERS, providerFor

    assert PROVIDERS["anthropic"]["label"] == "Anthropic (Claude)"
    assert isinstance(providerFor({"provider": "anthropic", "model": "claude-opus-5-5"}), AnthropicProvider)
    assert isinstance(providerFor({"provider": "openai", "model": "m"}), AssistantProvider)


def test_TheAgentKeepsClaudesContentForTheNextStep():
    from app.backend.api.services.assistant_agent import AssistantAgent, AssistantTools

    raw = [{"type": "thinking", "thinking": "", "signature": "s"},
           {"type": "tool_use", "id": "t1", "name": "list_projects", "input": {}}]

    class Model:
        def __init__(self):
            self.sent = []
            self.replies = [{"content": "", "tool_calls": [{"id": "t1", "function": {"name": "list_projects",
                                                                                   "arguments": "{}"}}],
                             "_raw": raw}, {"content": "You have one project."}]

        def chat(self, messages, tools=None):
            self.sent.append([dict(message) for message in messages])
            return {"message": self.replies.pop(0), "usage": {"inputTokens": 1, "outputTokens": 1}}

    model = Model()
    read = [lambda: [{"id": 7}], lambda p: [], lambda p, q: None, lambda p, q, c: "", lambda p, q: {}, lambda q: []]
    AssistantAgent(model, AssistantTools(*read)).answer("projects?", "")
    assistantTurn = [message for message in model.sent[1] if message["role"] == "assistant"][0]
    assert assistantTurn["_raw"] == raw
