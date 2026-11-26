"""Talking to Claude (Anthropic) for the AI assistant, through Anthropic's official SDK (the `anthropic` package).

The agent (assistant_agent.py) speaks the chat format the other providers share; this client turns it into
Anthropic's Messages API and back, with the same answer shape as AssistantProvider.chat:
- the first system message becomes `system`; a later one (the language reminder) goes into the next user turn;
- an assistant turn with tool calls becomes text + `tool_use` blocks, and the tool results of one turn go together
  in one user message as `tool_result` blocks;
- Claude's own content (its thinking blocks with the rest) comes back in "_raw" and is sent back unchanged on the
  next request of the same question, as the API asks.
Without the package the assistant says so (an administrator installs it: pip install anthropic).
"""
import json
import logging
from typing import Any, Dict, List, Optional

from app.backend.api.services.assistant_provider import AssistantProviderError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
TIMEOUT_SECONDS = 180.0
# Models that, when they decline a request, can have it answered by another one on Anthropic's side
FALLBACK_MODELS = ("claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
REFUSED = ("The model declined to answer this request. Ask it in other words, or use the help without the "
           "assistant.")


def _client(key: str):
    try:
        import anthropic
    except ImportError:
        raise AssistantProviderError("The server cannot talk to Claude: its administrator has to install the "
                                     "anthropic package (pip install anthropic), or update ScipionWeb")
    return anthropic.Anthropic(api_key=key, timeout=TIMEOUT_SECONDS)


def _failure(error: Exception) -> AssistantProviderError:
    """The SDK's error in words for the administrator or the user; never the key."""
    import anthropic

    if isinstance(error, anthropic.AuthenticationError):
        return AssistantProviderError("Anthropic did not accept the key", 401)
    if isinstance(error, anthropic.PermissionDeniedError):
        return AssistantProviderError("The key cannot use that model or feature", 403)
    if isinstance(error, anthropic.NotFoundError):
        return AssistantProviderError("Anthropic does not know that model", 404)
    if isinstance(error, anthropic.RateLimitError):
        return AssistantProviderError("Anthropic says there were too many questions in a short time, or the "
                                      "account has reached its limit; try again later", 429)
    if isinstance(error, anthropic.BadRequestError):
        text = str(getattr(error, "message", "") or error)
        if "credit" in text.lower() or "billing" in text.lower():
            return AssistantProviderError("The Anthropic account has no credit left for its API (a Claude "
                                          "subscription does not include it): add credit in its billing page", 400)
        return AssistantProviderError("Anthropic refused the question: %s" % text[:300], 400)
    if isinstance(error, anthropic.APIStatusError):
        return AssistantProviderError("Anthropic is not answering properly right now (error %s); try later"
                                      % error.status_code, error.status_code)
    if isinstance(error, anthropic.APIConnectionError):
        return AssistantProviderError("Could not reach Anthropic (%s)" % type(error).__name__)
    return AssistantProviderError("Anthropic could not answer (%s)" % type(error).__name__)


def toolsFor(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """The agent's tools (each {"type": "function", "function": {...}}) as Anthropic's tool definitions."""
    converted = []
    for tool in tools or []:
        function = tool.get("function") or {}
        converted.append({"name": function.get("name"), "description": function.get("description") or "",
                          "input_schema": function.get("parameters") or {"type": "object", "properties": {}}})
    return converted


def messagesFor(messages: List[Dict[str, Any]]):
    """(system, messages) in Anthropic's shape from the agent's chat messages."""
    system: List[str] = []
    result: List[Dict[str, Any]] = []
    notes: List[str] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            if not result:
                system.append(str(message.get("content") or ""))
            else:
                notes.append(str(message.get("content") or ""))
            continue
        if role == "user":
            text = str(message.get("content") or "")
            if notes:
                text = "\n".join("[ScipionWeb: %s]" % note for note in notes) + "\n\n" + text
                notes = []
            result.append({"role": "user", "content": text})
        elif role == "assistant":
            if message.get("_raw"):
                # Claude's own blocks, its thinking with them, unchanged
                result.append({"role": "assistant", "content": message["_raw"]})
                continue
            blocks: List[Dict[str, Any]] = []
            if message.get("content"):
                blocks.append({"type": "text", "text": str(message["content"])})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except ValueError:
                    arguments = {}
                blocks.append({"type": "tool_use", "id": call.get("id"), "name": function.get("name"),
                               "input": arguments})
            result.append({"role": "assistant", "content": blocks or str(message.get("content") or "")})
        elif role == "tool":
            block = {"type": "tool_result", "tool_use_id": message.get("tool_call_id"),
                     "content": str(message.get("content") or "")}
            previous = result[-1] if result else None
            # The results of one turn go together, in one user message
            if previous and previous["role"] == "user" and isinstance(previous["content"], list) \
                    and all(item.get("type") == "tool_result" for item in previous["content"]):
                previous["content"].append(block)
            else:
                result.append({"role": "user", "content": [block]})
    return "\n\n".join(part for part in system if part), result


def _plain(block: Any) -> Dict[str, Any]:
    for name in ("to_dict", "model_dump"):
        method = getattr(block, name, None)
        if callable(method):
            try:
                return method(exclude_none=True) if name == "model_dump" else method()
            except TypeError:
                return method()
    return dict(block)


class AnthropicProvider:
    def __init__(self, key: str = "", model: str = "", client=None):
        self.key = key
        self.model = model
        self._client = client

    def _api(self):
        if self._client is None:
            self._client = _client(self.key)
        return self._client

    def models(self) -> List[str]:
        api = self._api()
        try:
            return sorted({str(item.id) for item in api.models.list()})
        except AssistantProviderError:
            raise
        except Exception as error:
            raise _failure(error)

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """{message, finishReason, usage} in the shape AssistantProvider.chat gives."""
        if not self.model:
            raise AssistantProviderError("No model is chosen")
        api = self._api()
        system, converted = messagesFor(messages)
        request: Dict[str, Any] = {"model": self.model, "max_tokens": MAX_TOKENS, "messages": converted}
        if system:
            request["system"] = system
        if tools:
            request["tools"] = toolsFor(tools)
        try:
            if self.model in FALLBACK_MODELS:
                # When the model declines, another one answers inside the same request (Anthropic routes it)
                response = api.beta.messages.create(betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"},
                                                    **request)
            else:
                response = api.messages.create(**request)
        except AssistantProviderError:
            raise
        except Exception as error:
            raise _failure(error)
        usage = getattr(response, "usage", None)
        tokens = {"inputTokens": int(getattr(usage, "input_tokens", 0) or 0),
                  "outputTokens": int(getattr(usage, "output_tokens", 0) or 0)}
        if getattr(response, "stop_reason", None) == "refusal":
            return {"message": {"content": REFUSED}, "finishReason": "refusal", "usage": tokens}
        blocks = list(getattr(response, "content", None) or [])
        text = "\n\n".join(block.text for block in blocks if getattr(block, "type", None) == "text").strip()
        calls = [{"id": block.id, "type": "function",
                  "function": {"name": block.name, "arguments": json.dumps(block.input or {})}}
                 for block in blocks if getattr(block, "type", None) == "tool_use"]
        message: Dict[str, Any] = {"content": text}
        if calls:
            message["tool_calls"] = calls
            message["_raw"] = [_plain(block) for block in blocks]
        return {"message": message, "finishReason": getattr(response, "stop_reason", None), "usage": tokens}
