"""The permission catalogue, roles and groups, as administrators manage them."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.permissions import requirePermission
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


def _service(mapper: PostgresqlFlatMapper) -> AccessService:
    return AccessService(mapper.db)


def _payload(model: BaseModel) -> Dict[str, Any]:
    return model.dict()


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
    return _service(mapper).saveRole(currentUser, _payload(payload))


@router.put("/roles/{roleId}")
def updateRole(roleId: int, payload: RolePayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
               currentUser: dict = Depends(requirePermission("roles.manage"))) -> Dict[str, Any]:
    return _service(mapper).saveRole(currentUser, _payload(payload), roleId=roleId)


@router.delete("/roles/{roleId}", status_code=status.HTTP_204_NO_CONTENT)
def deleteRole(roleId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
               currentUser: dict = Depends(requirePermission("roles.manage"))) -> None:
    _service(mapper).deleteRole(currentUser, roleId)


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
    return _service(mapper).saveGroup(currentUser, _payload(payload))


@router.put("/groups/{groupId}")
def updateGroup(groupId: int, payload: GroupPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                currentUser: dict = Depends(requirePermission("groups.manage"))) -> Dict[str, Any]:
    return _service(mapper).saveGroup(currentUser, _payload(payload), groupId=groupId)


@router.delete("/groups/{groupId}", status_code=status.HTTP_204_NO_CONTENT)
def deleteGroup(groupId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                currentUser: dict = Depends(requirePermission("groups.manage"))) -> None:
    _service(mapper).deleteGroup(currentUser, groupId)
