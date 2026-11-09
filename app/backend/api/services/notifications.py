"""Notices for the users: in the web (the bell) and by mail, each kind as each user chooses.

``notify`` is the one way to tell users something: it keeps a notice per user in the outbox and returns at once.
How it reaches each one is their channel for its kind:

* instant: in the web and mailed at once (by the sender, in the background);
* digest: in the web and mailed in one mail a day;
* web: only in the web;
* off: nowhere.

A user's channel is their choice, else the administrator's default for the kind, else the kind's own. Mandatory
kinds (what someone must hear, e.g. their data are about to go) are always mailed: instantly or in the digest.
A notice can also go to mail addresses outside the users (``notifyAddresses``: the facility's alert list).
Nothing is mailed while there is no mail server: the notices wait (``notification_sender``), and still show in
the web.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException, status

from app.backend.mapper.notifications_mapper import NotificationsPostgresqlMapper

logger = logging.getLogger(__name__)

CHANNELS = ("instant", "digest", "web", "off")
MANDATORY_CHANNELS = ("instant", "digest")
DEFAULTS_KEY = "defaults"
TITLE_LIMIT = 300
BODY_LIMIT = 5000

# Every kind of notice: who it is for (a group of the preferences), what it says, its channel unless the user or
# the administrator chose, whether it can be turned off, and the permission it needs to be offered
KINDS: Dict[str, Dict[str, Any]] = {
    "account.activated": {
        "group": "Account", "label": "My account is active",
        "description": "When an administrator activates your account, so you can sign in.",
        "default": "instant", "mandatory": True,
    },
    # Mailed at once, never shown in the web, and its text (the link) forgotten once sent
    "account.passwordReset": {
        "group": "Account", "label": "Resetting my password",
        "description": "The link to choose a new password, when you ask for it.",
        "default": "instant", "mandatory": True, "instantOnly": True, "secret": True, "hidden": True,
    },
    "project.shared": {
        "group": "Projects", "label": "A project shared with me",
        "description": "Someone shares a project with you or with a group of yours.",
        "default": "instant", "mandatory": False,
    },
    "protocol.failed": {
        "group": "Projects", "label": "A protocol failed",
        "description": "A protocol you launched, or one of a project of yours, failed.",
        "default": "instant", "mandatory": False,
    },
    "protocol.finished": {
        "group": "Projects", "label": "A long run of mine finished",
        "description": "A protocol you launched finished after running more than %d minutes." % 30,
        "default": "off", "mandatory": False,
    },
    "facility.session": {
        "group": "Facility", "label": "My session started or finished",
        "description": "Your acquisition session (or one of your group, as its PI) started or finished.",
        "default": "instant", "mandatory": False, "facility": True,
    },
    "facility.processing": {
        "group": "Facility", "label": "My data are being processed",
        "description": "The project of a DATA of your session was made and launched: its monitor shows it live.",
        "default": "instant", "mandatory": False, "facility": True,
    },
    "facility.bookingRequest": {
        "group": "Facility staff", "label": "A booking was requested",
        "description": "A user asks for time on a resource: it waits for the staff.",
        "default": "instant", "mandatory": False, "facility": True, "permission": "facility.sessions",
    },
    "facility.booking": {
        "group": "Facility", "label": "My bookings",
        "description": "A booking of yours confirmed, moved, offered another time, rejected or cancelled.",
        "default": "instant", "mandatory": False, "facility": True,
    },
    "facility.retention": {
        "group": "Facility", "label": "My session's data are about to be deleted",
        "description": "Before the facility deletes the data of a session of yours (or of your group, as its PI).",
        "default": "instant", "mandatory": True, "facility": True,
    },
    "facility.alert": {
        "group": "Facility staff", "label": "Facility alerts",
        "description": "A DATA without new movies, a processing or a protocol that failed in the sessions.",
        "default": "instant", "mandatory": False, "facility": True, "permission": "facility.sessions",
    },
}


def _badRequest(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def emailStateOf(channel: str) -> str:
    return {"instant": "pending", "digest": "digest"}.get(channel, "skipped")


class Notifications:
    def __init__(self, db):
        self.db = db
        self.mapper = NotificationsPostgresqlMapper(db)

    # Channels ------------------------------------------------------------------------------------------
    def defaults(self) -> Dict[str, str]:
        """The channel of each kind for whoever did not choose: the administrator's, else the kind's own."""
        chosen = self.mapper.getSettings().get(DEFAULTS_KEY) or {}
        return {kind: chosen.get(kind) if chosen.get(kind) in self.channelsOf(kind) else spec["default"]
                for kind, spec in KINDS.items()}

    @staticmethod
    def channelsOf(kind: str) -> tuple:
        if KINDS[kind].get("instantOnly"):
            return ("instant",)
        return MANDATORY_CHANNELS if KINDS[kind]["mandatory"] else CHANNELS

    def channelFor(self, kind: str, preferences: Dict[str, str], defaults: Dict[str, str]) -> str:
        channel = preferences.get(kind)
        return channel if channel in self.channelsOf(kind) else defaults[kind]

    # Telling -------------------------------------------------------------------------------------------
    def notify(self, userIds: Iterable[int], kind: str, title: str, body: str = "", link: str = "") -> List[int]:
        """Keep a notice for each active user given (once each), by their channel for the kind; answers the ids.

        The sender is woken to mail the instant ones; this never waits for a mail."""
        if kind not in KINDS:
            raise ValueError("Unknown notification kind: %s" % kind)
        userIds = self.mapper.activeUserIds(userIds)
        if not userIds:
            return []
        title, body = str(title)[:TITLE_LIMIT], str(body or "")[:BODY_LIMIT]
        defaults = self.defaults()
        preferences = self.mapper.preferencesOf(userIds)
        ids = []
        for userId in userIds:
            channel = self.channelFor(kind, preferences.get(userId, {}), defaults)
            if channel == "off":
                continue
            ids.append(self.mapper.insert(userId, None, kind, title, body, str(link or ""),
                                          not KINDS[kind].get("secret"), emailStateOf(channel)))
        self._wakeSender()
        return ids

    def notifyAddresses(self, addresses: Iterable[str], kind: str, title: str, body: str = "",
                        link: str = "") -> List[int]:
        """Mail a notice to addresses outside the users (nothing shows in the web)."""
        ids = [self.mapper.insert(None, address, kind, str(title)[:TITLE_LIMIT], str(body or "")[:BODY_LIMIT],
                                  str(link or ""), False, "pending")
               for address in dict.fromkeys(address.strip() for address in addresses if address and address.strip())]
        if ids:
            self._wakeSender()
        return ids

    @staticmethod
    def _wakeSender() -> None:
        from app.backend.api.services.notification_sender import requestSend

        requestSend()

    # A user's notices ------------------------------------------------------------------------------------
    def listMine(self, userId: int, limit: int = 50) -> Dict[str, Any]:
        return {"notifications": self.mapper.listMine(userId, min(max(int(limit), 1), 200)),
                "unread": self.mapper.countUnread(userId)}

    def markRead(self, userId: int, ids: Optional[List[int]] = None) -> Dict[str, Any]:
        self.mapper.markRead(userId, ids)
        return {"unread": self.mapper.countUnread(userId)}

    def preferencesOf(self, user: Dict[str, Any], facilityOn: bool) -> Dict[str, Any]:
        """The kinds a user may hear of, with their channel and the default; whether the mail is on."""
        from app.backend.api.permissions import hasPermission
        from app.backend.api.services.mail_service import MailService

        defaults = self.defaults()
        mine = self.mapper.preferencesOf([int(user["id"])]).get(int(user["id"]), {})
        kinds = []
        for kind, spec in KINDS.items():
            if spec.get("hidden") or (spec.get("facility") and not facilityOn):
                continue
            if spec.get("permission") and not (hasPermission(user, spec["permission"])
                                               or hasPermission(user, "facility.manage")):
                continue
            kinds.append({"kind": kind, "group": spec["group"], "label": spec["label"],
                          "description": spec["description"], "mandatory": spec["mandatory"],
                          "channels": list(self.channelsOf(kind)), "default": defaults[kind],
                          "channel": self.channelFor(kind, mine, defaults), "chosen": kind in mine})
        return {"kinds": kinds, "mailEnabled": MailService(self.db).enabled()}

    def savePreferences(self, user: Dict[str, Any], channels: Dict[str, Optional[str]],
                        facilityOn: bool) -> Dict[str, Any]:
        """A user's channel per kind (None: the default again)."""
        for kind, channel in channels.items():
            if kind not in KINDS:
                raise _badRequest("Unknown notification kind: %s" % kind)
            if channel is not None and channel not in self.channelsOf(kind):
                raise _badRequest("%s goes %s" % (KINDS[kind]["label"], " or ".join(self.channelsOf(kind))))
        self.mapper.savePreferences(int(user["id"]), channels)
        return self.preferencesOf(user, facilityOn)

    # The administrator's ---------------------------------------------------------------------------------
    def getDefaults(self) -> Dict[str, Any]:
        defaults = self.defaults()
        return {"kinds": [{"kind": kind, "group": spec["group"], "label": spec["label"],
                           "description": spec["description"], "mandatory": spec["mandatory"],
                           "channels": list(self.channelsOf(kind)), "default": spec["default"],
                           "channel": defaults[kind]} for kind, spec in KINDS.items() if not spec.get("hidden")]}

    def saveDefaults(self, channels: Dict[str, str], userId: Optional[int] = None) -> Dict[str, Any]:
        saved = dict(self.mapper.getSettings().get(DEFAULTS_KEY) or {})
        for kind, channel in channels.items():
            if kind not in KINDS:
                raise _badRequest("Unknown notification kind: %s" % kind)
            if channel not in self.channelsOf(kind):
                raise _badRequest("%s goes %s" % (KINDS[kind]["label"], " or ".join(self.channelsOf(kind))))
            saved[kind] = channel
        self.mapper.saveSettings({DEFAULTS_KEY: saved}, userId)
        return self.getDefaults()

    def outbox(self, limit: int = 200) -> List[Dict[str, Any]]:
        """The latest mails: to whom, their state and why one failed."""
        rows = self.mapper.outbox(min(max(int(limit), 1), 500))
        for row in rows:
            row["label"] = KINDS.get(row["kind"], {}).get("label", row["kind"])
        return rows
