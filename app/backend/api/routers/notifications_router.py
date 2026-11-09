"""A user's notifications and how they want them; the mail server and the defaults, for the administrators."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.backend.api.audit import recordAudit
from app.backend.api.dependencies import getCurrentUser
from app.backend.api.permissions import requirePermission
from app.backend.api.services.facility_service import facilityModeEnabled
from app.backend.api.services.mail_service import MailService
from app.backend.api.services.notifications import Notifications
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class ReadPayload(BaseModel):
    # The notices read; none: all of them
    ids: Optional[List[int]] = None


class DigestPayload(BaseModel):
    hour: Optional[int] = None
    timezone: Optional[str] = None


class MailSettingsPayload(BaseModel):
    host: Optional[str] = ""
    port: Optional[int] = 587
    security: str = "starttls"
    user: Optional[str] = ""
    # None keeps the password there is; "" removes it
    password: Optional[str] = None
    sender: Optional[str] = ""
    # The web's address as its users open it, for the links of the mails
    publicUrl: Optional[str] = None
    digest: Optional[DigestPayload] = None
    # Notices are mailed only once this is on (off by default)
    mailOn: Optional[bool] = None


class TestMailPayload(BaseModel):
    to: str


@router.get("")
def listMyNotifications(limit: int = Query(50, ge=1, le=200), mapper: PostgresqlFlatMapper = Depends(getMapper),
                        currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    """The user's notices in the web, the newest first, and how many are unread."""
    return Notifications(mapper.db).listMine(int(currentUser["id"]), limit)


@router.post("/read")
def markMyNotificationsRead(payload: ReadPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                            currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    return Notifications(mapper.db).markRead(int(currentUser["id"]), payload.ids)


@router.get("/preferences")
def getMyNotificationPreferences(mapper: PostgresqlFlatMapper = Depends(getMapper),
                                 currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    """The kinds of notices the user may get, each with how they get it and the default."""
    return Notifications(mapper.db).preferencesOf(currentUser, facilityModeEnabled())


@router.put("/preferences")
def saveMyNotificationPreferences(payload: Dict[str, Optional[str]], mapper: PostgresqlFlatMapper = Depends(getMapper),
                                  currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    """{kind: instant | digest | web | off}; null goes back to the default."""
    return Notifications(mapper.db).savePreferences(currentUser, payload, facilityModeEnabled())


@router.get("/settings/mail")
def getMailSettings(mapper: PostgresqlFlatMapper = Depends(getMapper),
                    currentUser: dict = Depends(requirePermission("settings.manage"))) -> Dict[str, Any]:
    return MailService(mapper.db).getSettings()


@router.put("/settings/mail")
def saveMailSettings(payload: MailSettingsPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                     currentUser: dict = Depends(requirePermission("settings.manage"))) -> Dict[str, Any]:
    values = payload.dict()
    if payload.digest is not None:
        values["digest"] = payload.digest.dict()
    settings = MailService(mapper.db).saveSettings(values, userId=currentUser.get("id"))
    recordAudit(mapper, currentUser, "settings.mailUpdated", "settings", None, "mail",
                {"host": settings["host"], "sender": settings["sender"], "publicUrl": settings["publicUrl"],
                 "mailOn": settings["mailOn"],
                 "password": "changed" if payload.password is not None else "kept"})
    return settings


@router.post("/settings/mail/test")
def sendTestMail(payload: TestMailPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                 currentUser: dict = Depends(requirePermission("settings.manage"))) -> Dict[str, Any]:
    """Send a test mail now (the only mail sent while the request waits); 400 with why it did not go."""
    return MailService(mapper.db).sendTest(payload.to)


@router.get("/settings/defaults")
def getNotificationDefaults(mapper: PostgresqlFlatMapper = Depends(getMapper),
                            currentUser: dict = Depends(requirePermission("settings.manage"))) -> Dict[str, Any]:
    """How each kind of notice reaches whoever did not choose."""
    return Notifications(mapper.db).getDefaults()


@router.put("/settings/defaults")
def saveNotificationDefaults(payload: Dict[str, str], mapper: PostgresqlFlatMapper = Depends(getMapper),
                             currentUser: dict = Depends(requirePermission("settings.manage"))) -> Dict[str, Any]:
    defaults = Notifications(mapper.db).saveDefaults(payload, userId=currentUser.get("id"))
    recordAudit(mapper, currentUser, "settings.notificationDefaultsUpdated", "settings", None, "notifications", payload)
    return defaults


@router.get("/outbox")
def listNotificationOutbox(limit: int = Query(200, ge=1, le=500), mapper: PostgresqlFlatMapper = Depends(getMapper),
                           currentUser: dict = Depends(requirePermission("settings.manage"))) -> List[Dict[str, Any]]:
    """The latest mails: to whom, whether they went, and why one did not."""
    return Notifications(mapper.db).outbox(limit)
