"""Talking to the assistant's model: the chat protocol the OpenAI API made common, which OpenAI, Google, Mistral
and the usual local model servers all speak (POST <base>/chat/completions, GET <base>/models).

Errors come out as AssistantProviderError with a sentence for the administrator or the user; the key is never part
of one.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 90.0
MODELS_TIMEOUT_SECONDS = 20.0


class AssistantProviderError(Exception):
    def __init__(self, message: str, statusCode: Optional[int] = None):
        super().__init__(message)
        self.statusCode = statusCode


def _explain(statusCode: int, body: str) -> str:
    if statusCode in (401, 403):
        return "The provider did not accept the key"
    if statusCode == 404:
        return "The provider does not know that model or address"
    if statusCode == 429:
        lowered = body.lower()
        if "quota" in lowered or "billing" in lowered or "credit" in lowered:
            return ("The provider account has no credit left for its API (a chat subscription does not include it): "
                    "add credit in the provider's billing page")
        return "The provider says there were too many questions in a short time; try again in a minute"
    if statusCode >= 500:
        return "The provider is not answering properly right now (error %d); try later" % statusCode
    detail = body.strip().replace("\n", " ")[:300]
    return "The provider refused the question (error %d)%s" % (statusCode, ": " + detail if detail else "")


class AssistantProvider:
    def __init__(self, baseUrl: str, key: str = "", model: str = "", http=None):
        self.baseUrl = baseUrl.rstrip("/")
        self.key = key
        self.model = model
        self._http = http

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        return headers

    def _request(self, method: str, path: str, timeout: float, json: Optional[Dict[str, Any]] = None):
        import httpx

        http = self._http or httpx
        try:
            response = http.request(method, self.baseUrl + path, headers=self._headers(), json=json, timeout=timeout)
        except httpx.TimeoutException:
            raise AssistantProviderError("The provider took too long to answer")
        except httpx.HTTPError as error:
            raise AssistantProviderError("Could not reach the provider at %s (%s)" % (self.baseUrl,
                                                                                      type(error).__name__))
        if response.status_code >= 400:
            raise AssistantProviderError(_explain(response.status_code, response.text), response.status_code)
        try:
            return response.json()
        except ValueError:
            raise AssistantProviderError("The provider answered something that is not JSON")

    def models(self) -> List[str]:
        """The models the key can use, by name."""
        data = self._request("GET", "/models", MODELS_TIMEOUT_SECONDS)
        items = data.get("data") if isinstance(data, dict) else data
        names = []
        for item in items or []:
            name = item.get("id") if isinstance(item, dict) else item
            if name:
                # Google names its models "models/<name>"
                names.append(str(name).split("/", 1)[1] if str(name).startswith("models/") else str(name))
        return sorted(set(names))

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """{message, usage}: the model's reply (its text and the tools it wants used) and the tokens it took."""
        if not self.model:
            raise AssistantProviderError("No model is chosen")
        body: Dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
        data = self._request("POST", "/chat/completions", TIMEOUT_SECONDS, json=body)
        choices = data.get("choices") or []
        if not choices:
            raise AssistantProviderError("The provider gave no answer")
        usage = data.get("usage") or {}
        return {
            "message": choices[0].get("message") or {},
            "finishReason": choices[0].get("finish_reason"),
            "usage": {"inputTokens": int(usage.get("prompt_tokens") or 0),
                      "outputTokens": int(usage.get("completion_tokens") or 0)},
        }
