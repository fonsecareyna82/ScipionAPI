"""Disk quotas: how much the projects of a user, or of a group's members, may take.

An administrator sets a limit for a user or a group. A project counts for its owner (whoever launches in it), as
the disk measurer last measured it, so the usage lags a little behind the disk. A launch in a project whose owner
(or one of their groups) is at or over a limit is refused; what runs goes on. At 80 % and at 100 % the user (or the
group's members) are told once (``refreshNotices``, after the measurer's turns), and again only after usage dropped.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.mapper.storage_quota_mapper import StorageQuotaPostgresqlMapper

logger = logging.getLogger(__name__)

KINDS = ("user", "group")
WARN_PERCENT = 80
NOTICE_EVERY_SECONDS = 600.0

_noticeLock = threading.Lock()
_lastNoticeAt = 0.0


def _size(value: int) -> str:
    from app.backend.api.services.project_storage import formatSize

    return formatSize(value) or "0 B"


def _withUsage(mapper: StorageQuotaPostgresqlMapper, quota: Dict[str, Any]) -> Dict[str, Any]:
    used = mapper.used(quota["kind"], quota["targetId"])
    limit = int(quota["limitBytes"])
    return dict(quota, usedBytes=used, percent=round(100.0 * used / limit, 1) if limit else None,
                full=used >= limit)


def listQuotas(db) -> List[Dict[str, Any]]:
    mapper = StorageQuotaPostgresqlMapper(db)
    return [_withUsage(mapper, quota) for quota in mapper.listQuotas()]


def quotasOf(db, userId: int) -> List[Dict[str, Any]]:
    """The quotas a user's projects count against, with their usage (for the user to see)."""
    mapper = StorageQuotaPostgresqlMapper(db)
    return [{key: value for key, value in _withUsage(mapper, quota).items()
             if key in ("kind", "targetId", "name", "limitBytes", "usedBytes", "percent", "full")}
            for quota in mapper.quotasCovering(userId)]


def saveQuota(db, kind: str, targetId: int, limitBytes: Optional[int], userId: Optional[int]) -> List[Dict[str, Any]]:
    if kind not in KINDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A quota is for a user or a group")
    mapper = StorageQuotaPostgresqlMapper(db)
    if not mapper.exists(kind, targetId):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such %s" % kind)
    if limitBytes is not None and int(limitBytes) <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A quota is more than 0 bytes")
    mapper.save(kind, targetId, limitBytes, userId)
    return listQuotas(db)


def checkLaunch(db, projectId: int) -> None:
    """409 when the project's owner, or one of their groups, has used its whole quota: nothing new may run there
    until space is freed or the quota raised (what runs goes on)."""
    if db is None:
        return
    mapper = StorageQuotaPostgresqlMapper(db)
    ownerId = mapper.projectOwner(projectId)
    if ownerId is None:
        return
    for quota in mapper.quotasCovering(ownerId):
        quota = _withUsage(mapper, quota)
        if quota["full"]:
            whose = "its owner's quota" if quota["kind"] == "user" else "the quota of the group %s" % quota["name"]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Nothing new can run in this project: %s is full (%s of %s). Delete what is not needed, or "
                       "ask an administrator to raise it. What runs goes on." % (
                           whose, _size(quota["usedBytes"]), _size(int(quota["limitBytes"]))))


def refreshNotices(db) -> List[Dict[str, Any]]:
    """Tell the users of a quota reaching 80 % or 100 % (once per level, again after usage drops)."""
    from app.backend.api.services.notifications import Notifications

    mapper = StorageQuotaPostgresqlMapper(db)
    told = []
    for quota in mapper.listQuotas():
        quota = _withUsage(mapper, quota)
        level = 100 if quota["full"] else (WARN_PERCENT if quota["percent"] >= WARN_PERCENT else 0)
        if level == int(quota["notifiedLevel"] or 0):
            continue
        mapper.setNotifiedLevel(quota["id"], level)
        if level <= int(quota["notifiedLevel"] or 0):
            continue
        userIds = [quota["targetId"]] if quota["kind"] == "user" else mapper.groupMembers(quota["targetId"])
        whose = "Your disk quota" if quota["kind"] == "user" else "The disk quota of the group %s" % quota["name"]
        used, limit = _size(quota["usedBytes"]), _size(int(quota["limitBytes"]))
        if level == 100:
            title = "%s is full" % whose
            body = ("%s is full: %s of %s. No new protocol can be launched in its projects until space is freed or "
                    "an administrator raises it; what runs goes on." % (whose, used, limit))
        else:
            title = "%s is at %d %%" % (whose, int(quota["percent"]))
            body = "%s is at %d %%: %s of %s. At 100 %% no new protocol can be launched in its projects." % (
                whose, int(quota["percent"]), used, limit)
        Notifications(db).notify(userIds, "storage.quota", title, body, "/projects")
        told.append({"quotaId": quota["id"], "level": level})
    return told


def refreshNoticesNow(db, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """The measurer's turn: at most every NOTICE_EVERY_SECONDS; never fails."""
    global _lastNoticeAt
    now = time.time() if now is None else now
    with _noticeLock:
        if now - _lastNoticeAt < NOTICE_EVERY_SECONDS:
            return []
        _lastNoticeAt = now
    try:
        return refreshNotices(db)
    except Exception:
        logger.warning("Could not tell of the disk quotas", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return []
