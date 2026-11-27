"""Custom operations: protocols that run a Python script written by a user (or by the assistant for them) on the
server. Only users with the protocols.customCode permission may launch them."""
from typing import Iterable

from fastapi import HTTPException, status

CUSTOM_CLASSES = frozenset({"ProtCustomOperation"})
PERMISSION = "protocols.customCode"


def isCustom(className) -> bool:
    return str(className or "") in CUSTOM_CLASSES


def checkLaunch(mapper, userId, protocols: Iterable) -> None:
    """403 when userId launches a custom operation without the permission (no user: an internal launch)."""
    if userId is None:
        return
    if not any(isCustom(protocol.getClassName()) for protocol in protocols if protocol is not None):
        return
    from app.backend.mapper.access_mapper import AccessPostgresqlMapper

    held = AccessPostgresqlMapper(mapper.db).getUserPermissions(int(userId))
    if not (held["isSystem"] or PERMISSION in held["permissions"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Running a custom operation (a Python script) needs the %s permission"
                                   % PERMISSION)
