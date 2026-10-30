"""Roles, groups and what each user may do, as an administrator manages them.

No one gives what they do not hold: the permissions a change grants (through a role, a group's roles
or a group membership) must all be held by whoever makes it, and only a holder of the system role
gives that role. At least one active user always keeps the system role.
"""
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException, status

from app.backend.api.permissions import PERMISSIONS, validPermissions
from app.backend.mapper.access_mapper import AccessPostgresqlMapper

GROUP_ROLES = ("member", "pi")


def _badRequest(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class AccessService:
    def __init__(self, db):
        self.mapper = AccessPostgresqlMapper(db)
        self.db = db

    # What the actor may give ------------------------------------------------------------------
    def _rolesById(self) -> Dict[int, Dict[str, Any]]:
        return {int(role["id"]): role for role in self.mapper.listRoles()}

    def _checkCanGive(self, actor: dict, roles: Iterable[Dict[str, Any]]) -> None:
        held = set(actor.get("permissions") or ())
        for role in roles:
            if role["isSystem"] and not actor.get("isSystemAdmin"):
                raise _forbidden("Only an administrator can give the %s role" % role["name"])
            missing = sorted(set(role["permissions"]) - held)
            if missing:
                raise _forbidden("You cannot give permissions you do not hold: %s" % ", ".join(missing))

    def _rolesFor(self, roleIds: Iterable[int]) -> List[Dict[str, Any]]:
        rolesById = self._rolesById()
        unknown = sorted({int(roleId) for roleId in roleIds} - set(rolesById))
        if unknown:
            raise _badRequest("Unknown roles: %s" % ", ".join(map(str, unknown)))
        return [rolesById[int(roleId)] for roleId in set(roleIds)]

    def _groupRoles(self, groupIds: Iterable[int]) -> List[Dict[str, Any]]:
        groupsById = {int(group["id"]): group for group in self.mapper.listGroups()}
        unknown = sorted({int(groupId) for groupId in groupIds} - set(groupsById))
        if unknown:
            raise _badRequest("Unknown groups: %s" % ", ".join(map(str, unknown)))
        return self._rolesFor(roleId for groupId in set(groupIds) for roleId in groupsById[int(groupId)]["roleIds"])

    def _checkAnAdministratorRemains(self) -> None:
        if not self.mapper.listActiveSystemUserIds():
            raise _badRequest("At least one active user must keep the Administrator role")

    # Catalogue and roles ---------------------------------------------------------------------
    @staticmethod
    def listPermissions() -> List[Dict[str, str]]:
        return [{"name": name, "description": description} for name, description in PERMISSIONS.items()]

    def listRoles(self) -> List[Dict[str, Any]]:
        return self.mapper.listRoles()

    def saveRole(self, actor: dict, payload: Dict[str, Any], roleId: Optional[int] = None) -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise _badRequest("A role needs a name")
        permissions = validPermissions(payload.get("permissions") or ())
        self._checkCanGive(actor, [{"name": name, "isSystem": False, "permissions": permissions}])
        sameName = [role for role in self.mapper.listRoles()
                    if role["name"].lower() == name.lower() and (roleId is None or int(role["id"]) != int(roleId))]
        if sameName:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A role named %s exists" % name)
        description = str(payload.get("description") or "").strip()
        isDefault = bool(payload.get("isDefault"))
        if roleId is None:
            roleId = self.mapper.insertRole(name, description, isDefault, permissions)
        else:
            role = self.mapper.getRole(roleId)
            if role is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
            if role["isSystem"]:
                raise _badRequest("The Administrator role cannot be changed")
            # Taking permissions away is giving less: only what is added must be held
            self._checkCanGive(actor, [role])
            self.mapper.updateRole(roleId, name, description, isDefault, permissions)
        return self.mapper.getRole(roleId)

    def deleteRole(self, actor: dict, roleId: int) -> None:
        role = self.mapper.getRole(roleId)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        if role["isSystem"]:
            raise _badRequest("The Administrator role cannot be deleted")
        self._checkCanGive(actor, [role])
        self.mapper.deleteRole(roleId)

    # Groups ------------------------------------------------------------------------------------
    def listGroups(self) -> List[Dict[str, Any]]:
        return self.mapper.listGroups()

    def listGroupNames(self) -> List[Dict[str, Any]]:
        return [{"id": group["id"], "name": group["name"]} for group in self.mapper.listGroups()]

    def saveGroup(self, actor: dict, payload: Dict[str, Any], groupId: Optional[int] = None) -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise _badRequest("A group needs a name")
        sameName = [group for group in self.mapper.listGroups()
                    if group["name"].lower() == name.lower() and (groupId is None or int(group["id"]) != int(groupId))]
        if sameName:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A group named %s exists" % name)
        roleIds = [int(roleId) for roleId in payload.get("roleIds") or ()]
        members = []
        for member in payload.get("members") or ():
            groupRole = str(member.get("groupRole") or "member")
            if groupRole not in GROUP_ROLES:
                raise _badRequest("Unknown group role: %s" % groupRole)
            members.append({"userId": int(member["userId"]), "groupRole": groupRole})
        roles = self._rolesFor(roleIds)
        # Its roles reach every member, so the actor must hold what they give (also the ones it had)
        if groupId is not None:
            current = self.mapper.getGroup(groupId)
            if current is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
            roles += self._rolesFor(current["roleIds"])
        self._checkCanGive(actor, roles)
        description = str(payload.get("description") or "").strip()
        with self.db.transaction():
            if groupId is None:
                groupId = self.mapper.insertGroup(name, description, roleIds, members)
            else:
                self.mapper.updateGroup(groupId, name, description, roleIds, members)
            self._checkAnAdministratorRemains()
        return self.mapper.getGroup(groupId)

    def deleteGroup(self, actor: dict, groupId: int) -> None:
        group = self.mapper.getGroup(groupId)
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
        self._checkCanGive(actor, self._rolesFor(group["roleIds"]))
        with self.db.transaction():
            self.mapper.deleteGroup(groupId)
            self._checkAnAdministratorRemains()

    # Users -------------------------------------------------------------------------------------
    def withAccess(self, users: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        access = self.mapper.listUsersAccess()
        return [dict(user, **access.get(int(user["id"]), {"roleIds": [], "groupIds": []})) for user in users]

    def updateUserAccess(self, actor: dict, userId: int, updates: Dict[str, Any], updateUserFields) -> None:
        """Apply isActive, roleIds and groupIds of updates to userId, all or nothing."""
        current = self.mapper.listUsersAccess().get(int(userId), {"roleIds": [], "groupIds": []})
        with self.db.transaction():
            if "roleIds" in updates and updates["roleIds"] is not None:
                roleIds = [int(roleId) for roleId in updates["roleIds"]]
                changed = set(roleIds) ^ set(current["roleIds"])
                self._checkCanGive(actor, self._rolesFor(changed))
                self.mapper.setUserRoles(userId, roleIds, commit=False)
            if "groupIds" in updates and updates["groupIds"] is not None:
                groupIds = [int(groupId) for groupId in updates["groupIds"]]
                changed = set(groupIds) ^ set(current["groupIds"])
                self._checkCanGive(actor, self._groupRoles(changed))
                self.mapper.setUserGroups(userId, groupIds, commit=False)
            if "isActive" in updates and updates["isActive"] is not None:
                updateUserFields(userId, {"isActive": bool(updates["isActive"])})
            self._checkAnAdministratorRemains()

    def giveDefaultRoles(self, userId: int) -> None:
        self.mapper.setUserRoles(userId, self.mapper.listDefaultRoleIds())
