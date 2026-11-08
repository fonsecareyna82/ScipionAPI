"""Mailing the notices of the outbox, in the background.

Every SEND_SECONDS (or at once when a notice is kept: ``requestSend``) the sender mails the pending notices whose
time came. One that the server does not take is tried again later (RETRY_MINUTES, doubling) and given up after
MAX_ATTEMPTS. Once a day, at the digest's hour, each user with notices for the digest gets them in one mail.

While there is no mail server nothing is mailed and the notices wait; after STALE_DAYS they are not mailed any
more (they still show in the web). Only one server process sends at a time (an advisory lock).
"""
from __future__ import annotations

import datetime
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from app.backend.api.services.mail_service import MailService
from app.backend.mapper.notifications_mapper import NotificationsPostgresqlMapper

logger = logging.getLogger(__name__)

SEND_SECONDS = 30.0
MAX_ATTEMPTS = 6
RETRY_MINUTES = 2.0
STALE_DAYS = 7.0
BATCH = 100
LAST_DIGEST_KEY = "lastDigestOn"

_wakeUp = threading.Event()
_startLock = threading.Lock()
_thread: Optional[threading.Thread] = None


def mailText(notice: Dict[str, Any], publicUrl: str) -> str:
    """A notice as a mail's text: what it says, and the page it is about when the web's address is known."""
    parts = [str(notice.get("body") or notice["title"]).strip()]
    if notice.get("link") and publicUrl:
        parts.append("Open it: %s%s" % (publicUrl, notice["link"]))
    return "\n\n".join(part for part in parts if part)


def footer(publicUrl: str) -> str:
    where = "%s/settings?tab=notifications" % publicUrl if publicUrl else "ScipionWeb, Settings, Notifications"
    return "\n\n--\nScipionWeb. Choose which notices you get by mail in %s.\n" % where


def sendDue(db, mail: Optional[MailService] = None) -> List[int]:
    """Mail the pending notices whose time came; answers the ids sent."""
    mail = mail or MailService(db)
    mapper = NotificationsPostgresqlMapper(db)
    publicUrl = mail.publicUrl()
    sent = []
    for notice in mapper.due(BATCH):
        if not notice.get("address") or (notice.get("userId") is not None and not notice.get("active")):
            mapper.markSkipped([notice["id"]], "No active user with a mail address")
            continue
        try:
            mail.send(notice["title"], mailText(notice, publicUrl) + footer(publicUrl), [notice["address"]])
        except RuntimeError as error:
            attempts = int(notice.get("emailAttempts") or 0) + 1
            mapper.markRetry(notice["id"], str(error), RETRY_MINUTES * 2 ** (attempts - 1), attempts >= MAX_ATTEMPTS)
            logger.warning("Could not mail notice %s (attempt %d): %s", notice["id"], attempts, error)
            continue
        mapper.markSent([notice["id"]])
        sent.append(int(notice["id"]))
    return sent


def digestDue(mail: MailService, mapper: NotificationsPostgresqlMapper,
              now: Optional[datetime.datetime] = None) -> Optional[datetime.date]:
    """The day whose digest is to be mailed now (None: not its hour yet, or mailed already)."""
    from dateutil import tz

    digest = mail.digestSettings()
    zone = tz.gettz(str(digest["timezone"])) or tz.UTC
    local = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(zone)
    if local.hour < int(digest["hour"]):
        return None
    if str(mapper.getSettings().get(LAST_DIGEST_KEY) or "") == local.date().isoformat():
        return None
    return local.date()


def sendDigest(db, mail: Optional[MailService] = None, now: Optional[datetime.datetime] = None,
               force: bool = False) -> List[int]:
    """Mail each user the notices kept for the digest, in one mail, once a day; answers the users mailed."""
    mail = mail or MailService(db)
    mapper = NotificationsPostgresqlMapper(db)
    day = digestDue(mail, mapper, now)
    if day is None and not force:
        return []
    publicUrl = mail.publicUrl()
    byUser: Dict[int, List[Dict[str, Any]]] = {}
    for notice in mapper.digest():
        byUser.setdefault(int(notice["userId"]), []).append(notice)
    mailed = []
    for userId, notices in byUser.items():
        ids = [int(notice["id"]) for notice in notices]
        if not notices[0].get("address") or not notices[0].get("active"):
            mapper.markSkipped(ids, "No active user with a mail address")
            continue
        lines = ["- %s\n  %s" % (notice["title"], mailText(notice, publicUrl).replace("\n", "\n  "))
                 for notice in notices]
        subject = "ScipionWeb: %d notice%s of the day" % (len(notices), "" if len(notices) == 1 else "s")
        try:
            mail.send(subject, "What happened since the last digest:\n\n%s%s" % ("\n\n".join(lines), footer(publicUrl)),
                      [notices[0]["address"]])
        except RuntimeError as error:
            # Kept for the next look
            logger.warning("Could not mail the digest of user %s: %s", userId, error)
            continue
        mapper.markSent(ids)
        mailed.append(userId)
    if day is not None:
        mapper.saveSettings({LAST_DIGEST_KEY: day.isoformat()}, None)
    return mailed


def sendOnce(db) -> Dict[str, Any]:
    """One turn of the sender: nothing while another process sends, or without a mail server."""
    mapper = NotificationsPostgresqlMapper(db)
    if not mapper.tryLock():
        return {"sent": [], "digests": []}
    try:
        mapper.skipStale(STALE_DAYS)
        mail = MailService(db)
        if not mail.enabled():
            return {"sent": [], "digests": []}
        return {"sent": sendDue(db, mail), "digests": sendDigest(db, mail)}
    finally:
        mapper.unlock()
        try:
            db.rollback()
        except Exception:
            pass


def requestSend() -> None:
    """Mail now instead of at the next turn (a no-op where the sender was not started)."""
    _wakeUp.set()


def startNotificationSender(openDb: Callable[[], object]) -> None:
    """Start the sender thread of this process, once; openDb gives it a connection of its own."""
    global _thread
    with _startLock:
        if _thread is not None:
            return
        _thread = threading.Thread(target=_run, args=(openDb,), name="notification-sender", daemon=True)
        _thread.start()


def _run(openDb: Callable[[], object]) -> None:
    db = None
    while True:
        _wakeUp.clear()
        try:
            if db is None:
                db = openDb()
            sendOnce(db)
        except Exception:
            logger.warning("Could not mail the notifications; trying again later", exc_info=True)
            try:
                db.close()
            except Exception:
                pass
            db = None
        _wakeUp.wait(SEND_SECONDS)
