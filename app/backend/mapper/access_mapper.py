"""The queries of roles, groups and the permissions they give to users."""
from typing import Any, Dict, Iterable, List, Optional

# The permissions of a user's roles and of their groups' roles; a system role holds them all
USER_PERMISSIONS_SQL = """
    WITH held AS (
        SELECT "roleId" FROM user_access_roles WHERE "userId" = %(userId)s
        UNION
        SELECT gr."roleId"
          FROM user_group_members m
          JOIN user_group_roles gr ON gr."groupId" = m."groupId"
         WHERE m."userId" = %(userId)s
    )
    SELECT EXISTS (SELECT 1 FROM held JOIN access_roles r ON r.id = held."roleId" WHERE r."isSystem")
               AS "isSystem",
           COALESCE((SELECT ARRAY_AGG(DISTINCT p.permission)
                       FROM held JOIN access_role_permissions p ON p."roleId" = held."roleId"),
                    ARRAY[]::TEXT[]) AS permissions
"""

LIST_ROLES_SQL = """
    SELECT r.id, r.name, r.description, r."isSystem", r."isDefault",
           COALESCE(ARRAY_AGG(p.permission ORDER BY p.permission) FILTER (WHERE p.permission IS NOT NULL),
                    ARRAY[]::TEXT[]) AS permissions,
           (SELECT COUNT(*) FROM user_access_roles ur WHERE ur."roleId" = r.id) AS "usersCount",
           (SELECT COUNT(*) FROM user_group_roles gr WHERE gr."roleId" = r.id) AS "groupsCount"
      FROM access_roles r
      LEFT JOIN access_role_permissions p ON p."roleId" = r.id
     GROUP BY r.id
     ORDER BY r."isSystem" DESC, r.name
"""

LIST_GROUPS_SQL = """
    SELECT g.id, g.name, g.description, g."piAccess",
           COALESCE((SELECT ARRAY_AGG(gr."roleId" ORDER BY gr."roleId")
                       FROM user_group_roles gr WHERE gr."groupId" = g.id), ARRAY[]::INTEGER[]) AS "roleIds",
           COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('userId', m."userId", 'groupRole', m."groupRole",
                                                       'email', u.email, 'firstName', u."firstName",
                                                       'lastName', u."lastName")
                                     ORDER BY u."firstName", u."lastName", u.email)
                       FROM user_group_members m JOIN users u ON u.id = m."userId"
                      WHERE m."groupId" = g.id), '[]'::JSON) AS members
      FROM user_groups g
     ORDER BY g.name
"""

USERS_ACCESS_SQL = """
    SELECT u.id,
           COALESCE((SELECT ARRAY_AGG(ur."roleId" ORDER BY ur."roleId")
                       FROM user_access_roles ur WHERE ur."userId" = u.id), ARRAY[]::INTEGER[]) AS "roleIds",
           COALESCE((SELECT ARRAY_AGG(m."groupId" ORDER BY m."groupId")
                       FROM user_group_members m WHERE m."userId" = u.id), ARRAY[]::INTEGER[]) AS "groupIds"
      FROM users u
"""

# Give a user the system role (installing ScipionWeb ensures its administrator holds it)
GRANT_SYSTEM_ROLE_SQL = """
    INSERT INTO user_access_roles ("userId", "roleId")
    SELECT %(userId)s, id FROM access_roles WHERE "isSystem"
    ON CONFLICT DO NOTHING
"""

# Active users holding the system role, directly or through a group
ACTIVE_SYSTEM_USERS_SQL = """
    SELECT DISTINCT u.id
      FROM users u
      JOIN (SELECT ur."userId", ur."roleId" FROM user_access_roles ur
            UNION
            SELECT m."userId", gr."roleId" FROM user_group_members m
              JOIN user_group_roles gr ON gr."groupId" = m."groupId") held ON held."userId" = u.id
      JOIN access_roles r ON r.id = held."roleId" AND r."isSystem"
     WHERE u."isActive"
"""


# Accounts waiting for an administrator, created after a time
PENDING_ACCOUNTS_SQL = """
    SELECT id, email, "firstName", "lastName", "createdAt"
      FROM users
     WHERE NOT "isActive"
       AND "createdAt" > %s
     ORDER BY "createdAt" DESC
     LIMIT %s
"""


class AccessPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    # Permissions of a user -------------------------------------------------------------------
    def getUserPermissions(self, userId: int) -> Dict[str, Any]:
        """{"isSystem": bool, "permissions": [...]} of the roles userId holds, directly or by group."""
        row = self.db.fetchOne(USER_PERMISSIONS_SQL, {"userId": int(userId)}) or {}
        return {"isSystem": bool(row.get("isSystem")), "permissions": list(row.get("permissions") or [])}

    def grantSystemRole(self, userId: int) -> None:
        self.db.execute(GRANT_SYSTEM_ROLE_SQL, {"userId": int(userId)})

    def listActiveSystemUserIds(self) -> List[int]:
        return [int(row["id"]) for row in self.db.fetchAll(ACTIVE_SYSTEM_USERS_SQL) or []]

    def listPendingAccountsSince(self, since, limit: int) -> List[Dict[str, Any]]:
        return self.db.fetchAll(PENDING_ACCOUNTS_SQL, (since, int(limit))) or []

    # Roles -------------------------------------------------------------------------------------
    def listRoles(self) -> List[Dict[str, Any]]:
        return self.db.fetchAll(LIST_ROLES_SQL) or []

    def getRole(self, roleId: int) -> Optional[Dict[str, Any]]:
        return next((role for role in self.listRoles() if int(role["id"]) == int(roleId)), None)

    def insertRole(self, name: str, description: str, isDefault: bool, permissions: Iterable[str]) -> int:
        with self.db.transaction():
            row = self.db.fetchOne(
                'INSERT INTO access_roles (name, description, "isDefault") VALUES (%s, %s, %s) RETURNING id',
                (name, description, bool(isDefault)))
            self._replaceRolePermissions(int(row["id"]), permissions)
        return int(row["id"])

    def updateRole(self, roleId: int, name: str, description: str, isDefault: bool,
                   permissions: Iterable[str]) -> None:
        with self.db.transaction():
            self.db.execute('UPDATE access_roles SET name = %s, description = %s, "isDefault" = %s WHERE id = %s',
                            (name, description, bool(isDefault), int(roleId)), commit=False)
            self._replaceRolePermissions(int(roleId), permissions)

    def deleteRole(self, roleId: int) -> None:
        self.db.execute("DELETE FROM access_roles WHERE id = %s", (int(roleId),))

    def _replaceRolePermissions(self, roleId: int, permissions: Iterable[str]) -> None:
        self.db.execute('DELETE FROM access_role_permissions WHERE "roleId" = %s', (roleId,), commit=False)
        for permission in sorted(set(permissions)):
            self.db.execute('INSERT INTO access_role_permissions ("roleId", permission) VALUES (%s, %s)',
                            (roleId, permission), commit=False)

    def listDefaultRoleIds(self) -> List[int]:
        rows = self.db.fetchAll('SELECT id FROM access_roles WHERE "isDefault" AND NOT "isSystem"') or []
        return [int(row["id"]) for row in rows]

    # Groups ------------------------------------------------------------------------------------
    def listGroups(self) -> List[Dict[str, Any]]:
        return self.db.fetchAll(LIST_GROUPS_SQL) or []

    def getGroup(self, groupId: int) -> Optional[Dict[str, Any]]:
        return next((group for group in self.listGroups() if int(group["id"]) == int(groupId)), None)

    def insertGroup(self, name: str, description: str, roleIds: Iterable[int],
                    members: Iterable[Dict[str, Any]], piAccess: str = "view") -> int:
        with self.db.transaction():
            row = self.db.fetchOne('INSERT INTO user_groups (name, description, "piAccess") VALUES (%s, %s, %s) '
                                   'RETURNING id', (name, description, piAccess))
            self._replaceGroupContents(int(row["id"]), roleIds, members)
        return int(row["id"])

    def updateGroup(self, groupId: int, name: str, description: str, roleIds: Iterable[int],
                    members: Iterable[Dict[str, Any]], piAccess: str = "view") -> None:
        with self.db.transaction():
            self.db.execute('UPDATE user_groups SET name = %s, description = %s, "piAccess" = %s WHERE id = %s',
                            (name, description, piAccess, int(groupId)), commit=False)
            self._replaceGroupContents(int(groupId), roleIds, members)

    def deleteGroup(self, groupId: int) -> None:
        self.db.execute("DELETE FROM user_groups WHERE id = %s", (int(groupId),))

    def _replaceGroupContents(self, groupId: int, roleIds: Iterable[int], members: Iterable[Dict[str, Any]]) -> None:
        self.db.execute('DELETE FROM user_group_roles WHERE "groupId" = %s', (groupId,), commit=False)
        for roleId in sorted({int(roleId) for roleId in roleIds}):
            self.db.execute('INSERT INTO user_group_roles ("groupId", "roleId") VALUES (%s, %s)',
                            (groupId, roleId), commit=False)
        self.db.execute('DELETE FROM user_group_members WHERE "groupId" = %s', (groupId,), commit=False)
        for member in members:
            self.db.execute('INSERT INTO user_group_members ("groupId", "userId", "groupRole") VALUES (%s, %s, %s)',
                            (groupId, int(member["userId"]), member.get("groupRole") or "member"), commit=False)

    # Roles and groups of users -----------------------------------------------------------------
    def listUsersAccess(self) -> Dict[int, Dict[str, List[int]]]:
        return {int(row["id"]): {"roleIds": list(row["roleIds"]), "groupIds": list(row["groupIds"])}
                for row in self.db.fetchAll(USERS_ACCESS_SQL) or []}

    def setUserRoles(self, userId: int, roleIds: Iterable[int], commit: bool = True) -> None:
        def replace():
            self.db.execute('DELETE FROM user_access_roles WHERE "userId" = %s', (int(userId),), commit=False)
            for roleId in sorted({int(roleId) for roleId in roleIds}):
                self.db.execute('INSERT INTO user_access_roles ("userId", "roleId") VALUES (%s, %s)',
                                (int(userId), roleId), commit=False)
        if commit:
            with self.db.transaction():
                replace()
        else:
            replace()

    def setUserGroups(self, userId: int, groupIds: Iterable[int], commit: bool = True) -> None:
        """userId's groups become groupIds, keeping their role in the groups they stay in."""
        def replace():
            groupIds_ = sorted({int(groupId) for groupId in groupIds})
            self.db.execute('DELETE FROM user_group_members WHERE "userId" = %s AND NOT ("groupId" = ANY(%s))',
                            (int(userId), groupIds_), commit=False)
            for groupId in groupIds_:
                self.db.execute('INSERT INTO user_group_members ("groupId", "userId") VALUES (%s, %s) '
                                'ON CONFLICT DO NOTHING', (groupId, int(userId)), commit=False)
        if commit:
            with self.db.transaction():
                replace()
        else:
            replace()
