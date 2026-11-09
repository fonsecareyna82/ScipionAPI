"""ScipionWeb's mail: its server, the web's public address (for the links in the mails) and the digest's hour.

Off until a server is set. The password is kept encrypted with the API's SECRET_KEY and never answered back (only
whether there is one). It was the facility's mail before (its key derivation is kept, so a password saved then
still opens). Nothing here is called while a request waits for a mail to go, but the test mail: the notices go
through the outbox (``notifications``) and its sender.
"""
from __future__ import annotations

import base64
import hashlib
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.mapper.notifications_mapper import NotificationsPostgresqlMapper

MAIL_KEY = "mail"
SECURITIES = ("starttls", "ssl", "none")
MAIL_FIELDS = ("host", "port", "security", "user", "sender")
DEFAULT_MAIL = {"host": "", "port": 587, "security": "starttls", "user": "", "sender": ""}
# The web's address as its users open it (https://scipion.example.org): the mails link to its pages
PUBLIC_URL_KEY = "publicUrl"
# Whether notices are mailed at all: off until an administrator turns it on (the server alone does not)
MAIL_ON_KEY = "mailOn"
# When the day's digest is mailed: an hour of the day in a time zone
DIGEST_KEY = "digest"
DEFAULT_DIGEST = {"hour": 8, "timezone": "Europe/Madrid"}
TIMEOUT_SECONDS = 20
# The salt of the password's key: the facility's, where the mail was first set
_KEY_SALT = "facility-mail:"


def _badRequest(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _fernet():
    from cryptography.fernet import Fernet

    from app.backend.utils.jwt import SECRET_KEY

    return Fernet(base64.urlsafe_b64encode(hashlib.sha256((_KEY_SALT + SECRET_KEY).encode()).digest()))


def addresses(text: Any) -> List[str]:
    """Mail addresses written separated by commas, semicolons or lines."""
    return [part.strip() for part in str(text or "").replace(";", ",").replace("\n", ",").split(",") if part.strip()]


class MailService:
    def __init__(self, db):
        self.db = db
        self.mapper = NotificationsPostgresqlMapper(db)

    def _stored(self) -> Dict[str, Any]:
        return dict(DEFAULT_MAIL, **(self.mapper.getSettings().get(MAIL_KEY) or {}))

    def enabled(self) -> bool:
        """A mail server is set (the test mail works)."""
        return bool(self._stored().get("host"))

    def sending(self) -> bool:
        """Notices are mailed: a server is set and an administrator turned the mail on."""
        settings = self.mapper.getSettings()
        return bool((settings.get(MAIL_KEY) or {}).get("host")) and settings.get(MAIL_ON_KEY) is True

    def getSettings(self) -> Dict[str, Any]:
        """The mail settings as the web shows them: the password only as whether there is one."""
        settings = self.mapper.getSettings()
        stored = dict(DEFAULT_MAIL, **(settings.get(MAIL_KEY) or {}))
        answer = {field: stored.get(field, DEFAULT_MAIL.get(field)) for field in MAIL_FIELDS}
        answer["passwordSet"] = bool(stored.get("passwordEncrypted"))
        answer["enabled"] = bool(stored.get("host"))
        answer["mailOn"] = settings.get(MAIL_ON_KEY) is True
        answer["sending"] = answer["enabled"] and answer["mailOn"]
        answer["publicUrl"] = str(settings.get(PUBLIC_URL_KEY) or "")
        answer["digest"] = dict(DEFAULT_DIGEST, **(settings.get(DIGEST_KEY) or {}))
        return answer

    def publicUrl(self) -> str:
        return str(self.mapper.getSettings().get(PUBLIC_URL_KEY) or "").rstrip("/")

    def digestSettings(self) -> Dict[str, Any]:
        return dict(DEFAULT_DIGEST, **(self.mapper.getSettings().get(DIGEST_KEY) or {}))

    def saveSettings(self, payload: Dict[str, Any], userId: Optional[int] = None) -> Dict[str, Any]:
        """Keep the mail settings; a password left out (None) keeps the one there is, an empty one removes it."""
        stored = self._stored()
        values = {field: payload.get(field, stored.get(field)) for field in MAIL_FIELDS}
        values["host"] = str(values["host"] or "").strip()
        try:
            values["port"] = int(values["port"] or 0)
        except (TypeError, ValueError):
            raise _badRequest("The mail server's port is a number")
        if values["host"] and not 0 < values["port"] < 65536:
            raise _badRequest("The mail server's port is 1 to 65535")
        if values["security"] not in SECURITIES:
            raise _badRequest("The connection is starttls, ssl or none")
        values["user"] = str(values["user"] or "").strip()
        values["sender"] = str(values["sender"] or "").strip()
        if values["host"] and "@" not in values["sender"]:
            raise _badRequest("The mail needs a sender address")
        password = payload.get("password")
        if password is None:
            values["passwordEncrypted"] = stored.get("passwordEncrypted") or ""
        else:
            values["passwordEncrypted"] = _fernet().encrypt(str(password).encode()).decode() if password else ""
        saved = {MAIL_KEY: values}
        if payload.get("mailOn") is not None:
            saved[MAIL_ON_KEY] = bool(payload["mailOn"])
            if not saved[MAIL_ON_KEY]:
                # What waits is not mailed later, all at once, when it is turned on again
                self.mapper.skipWaiting("The mail was turned off")
        if payload.get("publicUrl") is not None:
            url = str(payload["publicUrl"]).strip().rstrip("/")
            if url and not url.startswith(("http://", "https://")):
                raise _badRequest("The web's address starts with http:// or https://")
            saved[PUBLIC_URL_KEY] = url
        if payload.get("digest") is not None:
            digest = dict(self.digestSettings(), **{key: value for key, value in dict(payload["digest"]).items()
                                                    if key in DEFAULT_DIGEST and value is not None})
            try:
                digest["hour"] = int(digest["hour"])
            except (TypeError, ValueError):
                raise _badRequest("The digest's hour is 0 to 23")
            if not 0 <= digest["hour"] <= 23:
                raise _badRequest("The digest's hour is 0 to 23")
            from dateutil import tz

            if tz.gettz(str(digest["timezone"])) is None:
                raise _badRequest("Unknown time zone: %s (written as Europe/Madrid)" % digest["timezone"])
            saved[DIGEST_KEY] = digest
        self.mapper.saveSettings(saved, userId)
        return self.getSettings()

    def send(self, subject: str, body: str, to: List[str]) -> List[str]:
        """Send a mail now; answers who it went to. Raises RuntimeError when it cannot go."""
        stored = self._stored()
        if not stored.get("host"):
            raise RuntimeError("No mail server is set")
        if not to:
            raise RuntimeError("Nobody to send it to")
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = stored["sender"]
        message["To"] = ", ".join(to)
        message.set_content(body)
        password = _fernet().decrypt(stored["passwordEncrypted"].encode()).decode() if stored.get("passwordEncrypted") else ""
        context = ssl.create_default_context()
        try:
            if stored["security"] == "ssl":
                server = smtplib.SMTP_SSL(stored["host"], int(stored["port"]), timeout=TIMEOUT_SECONDS, context=context)
            else:
                server = smtplib.SMTP(stored["host"], int(stored["port"]), timeout=TIMEOUT_SECONDS)
            with server:
                if stored["security"] == "starttls":
                    server.starttls(context=context)
                if stored.get("user"):
                    server.login(stored["user"], password)
                server.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise RuntimeError("The mail server did not take it: %s" % error)
        return to

    def sendTest(self, to: str) -> Dict[str, Any]:
        """A test mail to the given address; 400 with why it did not go."""
        recipients = addresses(to)
        if not recipients:
            raise _badRequest("Write the address to send the test mail to")
        try:
            sent = self.send("ScipionWeb: test mail",
                             "This is a test mail of ScipionWeb's notifications: the mail server works.", recipients)
        except RuntimeError as error:
            raise _badRequest(str(error))
        return {"sentTo": sent}
