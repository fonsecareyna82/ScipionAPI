"""The AI assistant's settings: which provider and model answer, the key, what it may do and how much.

Off until an administrator turns it on: nothing is sent anywhere before that. The key is kept encrypted with the
API's SECRET_KEY and never answered back (only whether there is one). Kept in the facility settings, one row.
"""
import base64
import hashlib
import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

from app.backend.mapper.facility_settings_mapper import FacilitySettingsPostgresqlMapper

logger = logging.getLogger(__name__)

ASSISTANT_KEY = "assistant"
_KEY_SALT = "assistant-key:"

# The providers offered. Every one here speaks the same chat protocol (the one OpenAI made common), so one
# client talks to all; "local" is any server of the centre that speaks it too (it needs its address).
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {"label": "OpenAI (ChatGPT)", "baseUrl": "https://api.openai.com/v1", "needsKey": True},
    "google": {"label": "Google (Gemini)", "baseUrl": "https://generativelanguage.googleapis.com/v1beta/openai",
               "needsKey": True},
    "mistral": {"label": "Mistral", "baseUrl": "https://api.mistral.ai/v1", "needsKey": True},
    "local": {"label": "Local or compatible model", "baseUrl": "", "needsKey": False},
}

# What it may do: only read and answer, or also propose actions the user confirms (see assistant_actions.py)
MODES = ("answer", "propose")

DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "provider": "openai",
    "baseUrl": "",
    "model": "",
    "keyEncrypted": "",
    "mode": "answer",
    # Proposing to delete protocols: on top of proposing, off unless an administrator turns it on
    "allowDelete": False,
    # Explaining every failed protocol in its notice (one question to the model each), off by default
    "explainFailures": False,
    "dailyLimit": 50,
}

MAX_DAILY_LIMIT = 10000


def _badRequest(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _fernet():
    from cryptography.fernet import Fernet

    from app.backend.utils.jwt import SECRET_KEY

    return Fernet(base64.urlsafe_b64encode(hashlib.sha256((_KEY_SALT + SECRET_KEY).encode()).digest()))


def encryptKey(key: str) -> str:
    return _fernet().encrypt(key.encode()).decode() if key else ""


def decryptKey(stored: Optional[str]) -> str:
    if not stored:
        return ""
    try:
        return _fernet().decrypt(stored.encode()).decode()
    except Exception:
        logger.warning("The assistant's key cannot be read (the server key changed?)")
        return ""


def baseUrlOf(stored: Dict[str, Any]) -> str:
    """Where the provider answers: its own address, or the one written for a local model."""
    provider = PROVIDERS.get(stored.get("provider") or "") or {}
    return (str(stored.get("baseUrl") or "").strip() or provider.get("baseUrl") or "").rstrip("/")


class AssistantSettings:
    def __init__(self, db):
        self.mapper = FacilitySettingsPostgresqlMapper(db)

    def stored(self) -> Dict[str, Any]:
        return dict(DEFAULTS, **(self.mapper.getSettings().get(ASSISTANT_KEY) or {}))

    def ready(self) -> bool:
        """On, with a model, and a key where the provider needs one."""
        stored = self.stored()
        provider = PROVIDERS.get(stored.get("provider") or "")
        return bool(stored.get("enabled") and provider and stored.get("model") and baseUrlOf(stored)
                    and (stored.get("keyEncrypted") or not provider["needsKey"]))

    def view(self) -> Dict[str, Any]:
        """The settings as the web shows them: the key only as whether there is one."""
        stored = self.stored()
        answer = {key: stored[key] for key in DEFAULTS if key != "keyEncrypted"}
        answer["keySet"] = bool(stored.get("keyEncrypted"))
        answer["ready"] = self.ready()
        answer["providers"] = [dict(value, key=key) for key, value in PROVIDERS.items()]
        answer["modes"] = list(MODES)
        return answer

    def merged(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """The stored settings with the payload's changes, checked; a key left out (None) keeps the one there is,
        an empty one removes it."""
        stored = self.stored()
        values = dict(stored)
        provider = payload.get("provider", stored["provider"])
        if provider not in PROVIDERS:
            raise _badRequest("Unknown provider: %s" % provider)
        if provider != stored["provider"]:
            # Another provider's key and model do not work with this one
            values["keyEncrypted"] = ""
            values["model"] = ""
        values["provider"] = provider
        for key in ("baseUrl", "model"):
            if payload.get(key) is not None:
                values[key] = str(payload[key]).strip()
        if values["baseUrl"] and not values["baseUrl"].startswith(("http://", "https://")):
            raise _badRequest("The address must start with http:// or https://")
        if payload.get("mode") is not None:
            if payload["mode"] not in MODES:
                raise _badRequest("Unknown mode: %s" % payload["mode"])
            values["mode"] = payload["mode"]
        if payload.get("allowDelete") is not None:
            values["allowDelete"] = bool(payload["allowDelete"])
        if payload.get("explainFailures") is not None:
            values["explainFailures"] = bool(payload["explainFailures"])
        if payload.get("dailyLimit") is not None:
            # 0 (or empty): no limit, e.g. for a model the centre runs itself
            text = str(payload["dailyLimit"]).strip()
            try:
                limit = int(text) if text else 0
            except (TypeError, ValueError):
                raise _badRequest("The daily limit must be a number")
            if not 0 <= limit <= MAX_DAILY_LIMIT:
                raise _badRequest("The daily limit must be between 0 (no limit) and %d" % MAX_DAILY_LIMIT)
            values["dailyLimit"] = limit
        key = payload.get("key")
        if key is not None:
            values["keyEncrypted"] = encryptKey(str(key).strip())
        if payload.get("enabled") is not None:
            values["enabled"] = bool(payload["enabled"])
        return values

    def save(self, payload: Dict[str, Any], userId: Optional[int]) -> Dict[str, Any]:
        values = self.merged(payload)
        if values["enabled"]:
            if not baseUrlOf(values):
                raise _badRequest("A local model needs its address")
            if PROVIDERS[values["provider"]]["needsKey"] and not values["keyEncrypted"]:
                raise _badRequest("Write the provider's key before turning the assistant on")
            if not values["model"]:
                raise _badRequest("Choose a model before turning the assistant on")
        self.mapper.saveSettings({ASSISTANT_KEY: {key: values[key] for key in DEFAULTS}}, userId)
        return self.view()
