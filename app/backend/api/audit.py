"""The audit log: who did what to whom, for whoever holds audit.view.

Routes record an event once what they did succeeded (a failed sign-in is an event too). Recording
never fails the request: a lost event is logged and the action stands.
"""
import logging
from contextvars import ContextVar
from typing import Any, Dict, Optional

from app.backend.mapper.audit_mapper import AuditPostgresqlMapper

logger = logging.getLogger(__name__)

# The kinds of events, by the first part of their action (the web filters by them)
AUDIT_CATEGORIES: Dict[str, str] = {
    "auth": "Sign-in, sign-up and passwords",
    "users": "Accounts: activation, roles and groups",
    "roles": "Roles and their permissions",
    "groups": "Groups, their members and roles",
    "projects": "Projects created, renamed, deleted and shared",
    "settings": "Instance, host and environment settings",
    "plugins": "Plugins installed and uninstalled",
    "jobs": "Workers started, stopped and restarted",
}

# Where the request came from, set for every request by ClientAddressMiddleware
_clientAddress: ContextVar[Optional[str]] = ContextVar("auditClientAddress", default=None)


class ClientAddressMiddleware:
    """Keeps the address of the request's client for the events it records."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            client = scope.get("client")
            token = _clientAddress.set(client[0] if client else None)
            try:
                await self.app(scope, receive, send)
            finally:
                _clientAddress.reset(token)
        else:
            await self.app(scope, receive, send)


def recordAudit(mapper, actor: Optional[dict], action: str, targetType: Optional[str] = None,
                targetId: Any = None, targetName: Optional[str] = None,
                details: Optional[Dict[str, Any]] = None, actorEmail: Optional[str] = None) -> None:
    """Keep an event done by actor (a user dict, or None and actorEmail for a sign-in).

    mapper is the route's mapper (or its db); without a database nothing is kept.
    """
    db = getattr(mapper, "db", mapper)
    if db is None:
        return
    try:
        AuditPostgresqlMapper(db).insertEvent(
            userId=int(actor["id"]) if actor and actor.get("id") is not None else None,
            userEmail=(actor or {}).get("email") or actorEmail,
            action=action,
            targetType=targetType,
            targetId=None if targetId is None else str(targetId),
            targetName=targetName,
            details=details or {},
            clientAddress=_clientAddress.get(),
        )
    except Exception:
        logger.exception("Could not record the audit event %s", action)


def userLabel(user: Optional[dict]) -> Optional[str]:
    """Name (email) of a user record, or its email alone."""
    if not user:
        return None
    name = " ".join(part for part in (user.get("firstName"), user.get("lastName")) if part)
    email = user.get("email")
    return "%s (%s)" % (name, email) if name and email else name or email


def recordAuditOwnConnection(actor: Optional[dict], action: str, targetType: Optional[str] = None,
                             targetId: Any = None, targetName: Optional[str] = None,
                             details: Optional[Dict[str, Any]] = None) -> None:
    """recordAudit for routes that hold no database connection: opens one for the event."""
    mapper = None
    try:
        from app.backend.database import getMapper

        mapper = getMapper()
        recordAudit(mapper, actor, action, targetType, targetId, targetName, details)
    except Exception:
        logger.exception("Could not record the audit event %s", action)
    finally:
        try:
            if mapper is not None:
                mapper.db.close()
        except Exception:
            pass


def audited(action: str, targetType: str, describe):
    """Decorate an async route so that, once it returns, it records action.

    describe(kwargs) gives (targetId, targetName, details) from the route's arguments; the route must
    take currentUser.
    """
    import functools

    from starlette.concurrency import run_in_threadpool

    def decorate(endpoint):
        @functools.wraps(endpoint)
        async def wrapper(*args, **kwargs):
            result = await endpoint(*args, **kwargs)
            try:
                targetId, targetName, details = describe(kwargs)
            except Exception:
                targetId, targetName, details = None, None, {}
            await run_in_threadpool(recordAuditOwnConnection, kwargs.get("currentUser"), action, targetType,
                                    targetId, targetName, details)
            return result
        return wrapper
    return decorate
