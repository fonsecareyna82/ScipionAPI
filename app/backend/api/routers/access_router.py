"""The permission catalogue, roles and groups, as administrators manage them."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from app.backend.api.audit import AUDIT_CATEGORIES, recordAudit
from app.backend.api.dependencies import getCurrentUser
from app.backend.api.permissions import requirePermission
from app.backend.mapper.audit_mapper import AuditPostgresqlMapper
from app.backend.api.services.access_service import AccessService
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

router = APIRouter(prefix="/access", tags=["Access"])


class RolePayload(BaseModel):
    name: str
    description: Optional[str] = ""
    isDefault: bool = False
    permissions: List[str] = []


class GroupMemberPayload(BaseModel):
    userId: int
    groupRole: str = "member"


class GroupPayload(BaseModel):
    name: str
    description: Optional[str] = ""
    roleIds: List[int] = []
    members: List[GroupMemberPayload] = []
    # What the group's PIs may do in its members' projects: none, view, work or manage
    piAccess: str = "view"


def _service(mapper: PostgresqlFlatMapper) -> AccessService:
    return AccessService(mapper.db)


def _payload(model: BaseModel) -> Dict[str, Any]:
    return model.dict()


def _listChange(before, after) -> Dict[str, List[Any]]:
    """What after adds to before and takes from it."""
    before, after = set(before or ()), set(after or ())
    change = {}
    if after - before:
        change["added"] = sorted(after - before)
    if before - after:
        change["removed"] = sorted(before - after)
    return change


def _groupMembers(group: Optional[Dict[str, Any]]) -> Dict[str, str]:
    return {member.get("email") or "#%s" % member["userId"]: member.get("groupRole") or "member"
            for member in (group or {}).get("members") or ()}


def _groupChanges(before: Optional[Dict[str, Any]], after: Dict[str, Any], roleNames: Dict[int, str]) -> Dict[str, Any]:
    roles = lambda group: [roleNames.get(int(roleId), "#%s" % roleId) for roleId in (group or {}).get("roleIds") or ()]
    membersBefore, membersAfter = _groupMembers(before), _groupMembers(after)
    changes = {"roles": _listChange(roles(before), roles(after)),
               "members": _listChange(membersBefore, membersAfter),
               "pis": _listChange([email for email, role in membersBefore.items() if role == "pi"],
                                  [email for email, role in membersAfter.items() if role == "pi"])}
    changes = {key: value for key, value in changes.items() if value}
    if (before or {}).get("piAccess") != after.get("piAccess"):
        changes["piAccess"] = after.get("piAccess")
    if before and before.get("name") != after.get("name"):
        changes["renamedFrom"] = before.get("name")
    return changes


@router.get("/permissions")
def listPermissions(currentUser: dict = Depends(getCurrentUser)) -> List[Dict[str, str]]:
    return AccessService.listPermissions()


@router.get("/roles")
def listRoles(mapper: PostgresqlFlatMapper = Depends(getMapper),
              currentUser: dict = Depends(getCurrentUser)) -> List[Dict[str, Any]]:
    return _service(mapper).listRoles()


@router.post("/roles", status_code=status.HTTP_201_CREATED)
def createRole(payload: RolePayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
               currentUser: dict = Depends(requirePermission("roles.manage"))) -> Dict[str, Any]:
    role = _service(mapper).saveRole(currentUser, _payload(payload))
    recordAudit(mapper, currentUser, "roles.created", "role", role["id"], role["name"],
                {"permissions": list(role["permissions"])})
    return role


@router.put("/roles/{roleId}")
def updateRole(roleId: int, payload: RolePayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
               currentUser: dict = Depends(requirePermission("roles.manage"))) -> Dict[str, Any]:
    service = _service(mapper)
    before = service.mapper.getRole(roleId)
    role = service.saveRole(currentUser, _payload(payload), roleId=roleId)
    changes = {"permissions": _listChange((before or {}).get("permissions"), role["permissions"])}
    changes = {key: value for key, value in changes.items() if value}
    if before and before["name"] != role["name"]:
        changes["renamedFrom"] = before["name"]
    if before and bool(before["isDefault"]) != bool(role["isDefault"]):
        changes["isDefault"] = bool(role["isDefault"])
    recordAudit(mapper, currentUser, "roles.updated", "role", roleId, role["name"], changes)
    return role


@router.delete("/roles/{roleId}", status_code=status.HTTP_204_NO_CONTENT)
def deleteRole(roleId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
               currentUser: dict = Depends(requirePermission("roles.manage"))) -> None:
    service = _service(mapper)
    role = service.mapper.getRole(roleId)
    service.deleteRole(currentUser, roleId)
    recordAudit(mapper, currentUser, "roles.deleted", "role", roleId, (role or {}).get("name"),
                {"permissions": list((role or {}).get("permissions") or ())})


@router.get("/groups/names")
def listGroupNames(mapper: PostgresqlFlatMapper = Depends(getMapper),
                   currentUser: dict = Depends(getCurrentUser)) -> List[Dict[str, Any]]:
    """The groups a project can be shared with."""
    return _service(mapper).listGroupNames()


@router.get("/groups")
def listGroups(mapper: PostgresqlFlatMapper = Depends(getMapper),
               currentUser: dict = Depends(requirePermission("groups.manage"))) -> List[Dict[str, Any]]:
    return _service(mapper).listGroups()


@router.post("/groups", status_code=status.HTTP_201_CREATED)
def createGroup(payload: GroupPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                currentUser: dict = Depends(requirePermission("groups.manage"))) -> Dict[str, Any]:
    service = _service(mapper)
    group = service.saveGroup(currentUser, _payload(payload))
    roleNames = {int(role["id"]): role["name"] for role in service.listRoles()}
    recordAudit(mapper, currentUser, "groups.created", "group", group["id"], group["name"],
                _groupChanges(None, group, roleNames))
    return group


@router.put("/groups/{groupId}")
def updateGroup(groupId: int, payload: GroupPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                currentUser: dict = Depends(requirePermission("groups.manage"))) -> Dict[str, Any]:
    service = _service(mapper)
    before = service.mapper.getGroup(groupId)
    group = service.saveGroup(currentUser, _payload(payload), groupId=groupId)
    roleNames = {int(role["id"]): role["name"] for role in service.listRoles()}
    recordAudit(mapper, currentUser, "groups.updated", "group", groupId, group["name"],
                _groupChanges(before, group, roleNames))
    return group


@router.delete("/groups/{groupId}", status_code=status.HTTP_204_NO_CONTENT)
def deleteGroup(groupId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                currentUser: dict = Depends(requirePermission("groups.manage"))) -> None:
    service = _service(mapper)
    group = service.mapper.getGroup(groupId)
    service.deleteGroup(currentUser, groupId)
    recordAudit(mapper, currentUser, "groups.deleted", "group", groupId, (group or {}).get("name"),
                {"members": sorted(_groupMembers(group))})


# The audit log ------------------------------------------------------------------------------------

@router.get("/audit/categories")
def listAuditCategories(currentUser: dict = Depends(requirePermission("audit.view"))) -> List[Dict[str, str]]:
    return [{"name": name, "description": description} for name, description in AUDIT_CATEGORIES.items()]


@router.get("/audit")
def listAuditEvents(
    limit: int = Query(100, ge=1, le=500),
    before: Optional[int] = Query(None, description="Only events older than this id (the next page)"),
    action: Optional[str] = Query(None, description="An action, or a category such as users"),
    userId: Optional[int] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    text: Optional[str] = Query(None, description="Found in the actor's email, the target or the details"),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    currentUser: dict = Depends(requirePermission("audit.view")),
) -> Dict[str, Any]:
    """The newest events first; nextBefore asks for the page after this one."""
    events = AuditPostgresqlMapper(mapper.db).listEvents(limit + 1, before=before, action=action, userId=userId,
                                                         since=since, until=until, text=text)
    page = events[:limit]
    return {"events": page, "nextBefore": page[-1]["id"] if len(events) > limit else None}
