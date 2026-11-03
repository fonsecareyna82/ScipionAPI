"""Mail from the facility to its operators: its server, kept in the facility's settings.

Off until a server is set. The password is kept encrypted with the API's SECRET_KEY and never answered back
(only whether there is one). Recipients are the facility's list, else every active user who runs sessions
(facility.sessions).
"""
import base64
import hashlib
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.mapper.facility_alerts_mapper import FacilityAlertsPostgresqlMapper
from app.backend.mapper.facility_settings_mapper import FacilitySettingsPostgresqlMapper

MAIL_KEY = "mail"
SECURITIES = ("starttls", "ssl", "none")
MAIL_FIELDS = ("host", "port", "security", "user", "sender", "recipients")
DEFAULT_MAIL = {"host": "", "port": 587, "security": "starttls", "user": "", "sender": "", "recipients": ""}
TIMEOUT_SECONDS = 20


def _badRequest(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _fernet():
    from cryptography.fernet import Fernet

    from app.backend.utils.jwt import SECRET_KEY

    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("facility-mail:" + SECRET_KEY).encode()).digest()))


def _addresses(text: str) -> List[str]:
    return [part.strip() for part in str(text or "").replace(";", ",").replace("\n", ",").split(",") if part.strip()]


class FacilityMail:
    def __init__(self, db):
        self.settings = FacilitySettingsPostgresqlMapper(db)
        self.alerts = FacilityAlertsPostgresqlMapper(db)

    def _stored(self) -> Dict[str, Any]:
        return dict(DEFAULT_MAIL, **(self.settings.getSettings().get(MAIL_KEY) or {}))

    def getSettings(self) -> Dict[str, Any]:
        """The mail settings as the web shows them: the password only as whether there is one."""
        stored = self._stored()
        answer = {field: stored.get(field, DEFAULT_MAIL.get(field)) for field in MAIL_FIELDS}
        answer["passwordSet"] = bool(stored.get("passwordEncrypted"))
        answer["enabled"] = bool(stored.get("host"))
        return answer

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
        values["recipients"] = ", ".join(_addresses(values["recipients"]))
        if values["host"] and "@" not in values["sender"]:
            raise _badRequest("The mail needs a sender address")
        if any("@" not in address for address in _addresses(values["recipients"])):
            raise _badRequest("The recipients are mail addresses, separated by commas")
        password = payload.get("password")
        if password is None:
            values["passwordEncrypted"] = stored.get("passwordEncrypted") or ""
        else:
            values["passwordEncrypted"] = _fernet().encrypt(str(password).encode()).decode() if password else ""
        self.settings.saveSettings({MAIL_KEY: values}, userId)
        return self.getSettings()

    def recipients(self) -> List[str]:
        stored = self._stored()
        listed = _addresses(stored.get("recipients"))
        return listed or [user["email"] for user in self.alerts.usersWithPermission("facility.sessions")]

    def send(self, subject: str, body: str, to: Optional[List[str]] = None) -> List[str]:
        """Send a mail; answers who it went to. Raises RuntimeError when it cannot go."""
        stored = self._stored()
        if not stored.get("host"):
            raise RuntimeError("No mail server is set")
        to = to if to is not None else self.recipients()
        if not to:
            raise RuntimeError("Nobody to send it to: no recipients and no user runs sessions")
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

    def sendTest(self, to: Optional[str] = None) -> Dict[str, Any]:
        """A test mail (to the given address, else to the recipients); 400 with why it did not go."""
        try:
            sent = self.send("ScipionWeb facility: test mail",
                             "This is a test mail of ScipionWeb's facility alerts: the mail server works.",
                             _addresses(to) or None)
        except RuntimeError as error:
            raise _badRequest(str(error))
        return {"sentTo": sent}
