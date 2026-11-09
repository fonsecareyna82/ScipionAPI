"""The queries of importing from another system: the links to what was imported, and what is matched or made."""
from typing import Any, Dict, Iterable, List, Optional


class ImportPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    # Links ----------------------------------------------------------------------------------------------
    def links(self, source: str, kind: str) -> Dict[str, int]:
        """{source id: id here} of what was imported of a kind."""
        rows = self.db.fetchAll('SELECT "sourceId", "targetId" FROM import_links WHERE source = %s AND kind = %s',
                                (source, kind))
        return {str(row["sourceId"]): int(row["targetId"]) for row in rows or []}

    def link(self, source: str, kind: str, sourceId: Any, targetId: int) -> None:
        self.db.execute('INSERT INTO import_links (source, kind, "sourceId", "targetId") VALUES (%s, %s, %s, %s) '
                        'ON CONFLICT (source, kind, "sourceId") DO UPDATE SET "targetId" = EXCLUDED."targetId", '
                        '"importedAt" = NOW()', (source, kind, str(sourceId), int(targetId)), commit=False)

    # Matching what exists ---------------------------------------------------------------------------------
    def userIdsByEmail(self) -> Dict[str, int]:
        rows = self.db.fetchAll("SELECT id, LOWER(email) AS email FROM users")
        return {row["email"]: int(row["id"]) for row in rows or [] if row["email"]}

    def groupIdsByName(self) -> Dict[str, int]:
        return {row["name"].lower(): int(row["id"]) for row in self.db.fetchAll("SELECT id, name FROM user_groups") or []}

    def resourcesByName(self) -> Dict[str, Dict[str, Any]]:
        """Resources by their name and by their microscope's name (lower case); a microscope without its resource
        yet (made the first time the resources are listed) is there too, its id None."""
        rows = self.db.fetchAll('SELECT r.id, r.name, r."microscopeId", m.name AS "microscopeName" '
                                "FROM facility_resources r LEFT JOIN facility_microscopes m ON m.id = r.\"microscopeId\" "
                                "UNION ALL SELECT NULL, m.name, m.id, m.name FROM facility_microscopes m "
                                "WHERE NOT EXISTS (SELECT 1 FROM facility_resources r WHERE r.\"microscopeId\" = m.id)")
        found: Dict[str, Dict[str, Any]] = {}
        for row in rows or []:
            for name in (row["name"], row.get("microscopeName")):
                if name:
                    found.setdefault(str(name).lower(), dict(row))
        return found

    def addMicroscopeResources(self) -> None:
        """Every microscope gets its resource (as listing the resources does)."""
        from app.backend.mapper.facility_booking_mapper import ADD_MICROSCOPE_RESOURCES_SQL

        self.db.execute(ADD_MICROSCOPE_RESOURCES_SQL, commit=False)

    def resourceMicroscopes(self) -> Dict[int, Optional[int]]:
        return {int(row["id"]): row["microscopeId"]
                for row in self.db.fetchAll('SELECT id, "microscopeId" FROM facility_resources') or []}

    def sessionIdsByName(self) -> Dict[str, int]:
        return {row["name"].lower(): int(row["id"]) for row in self.db.fetchAll("SELECT id, name FROM facility_sessions") or []}

    # Making what is missing (inside the import's transaction) ------------------------------------------------
    def insertUser(self, values: Dict[str, Any]) -> int:
        row = self.db.fetchOne('INSERT INTO users (email, "hashedPassword", "firstName", "lastName", institution, role, '
                               '"isActive", "isVerified", "verificationCode", "createdAt") '
                               "VALUES (%(email)s, %(hashedPassword)s, %(firstName)s, %(lastName)s, %(institution)s, "
                               "'user', %(isActive)s, TRUE, '', COALESCE(%(createdAt)s, NOW())) RETURNING id", values)
        return int(row["id"])

    def insertGroup(self, name: str, description: str) -> int:
        row = self.db.fetchOne("INSERT INTO user_groups (name, description) VALUES (%s, %s) RETURNING id",
                               (name, description))
        return int(row["id"])

    def addMember(self, groupId: int, userId: int, groupRole: str) -> None:
        self.db.execute('INSERT INTO user_group_members ("groupId", "userId", "groupRole") VALUES (%s, %s, %s) '
                        'ON CONFLICT DO NOTHING', (int(groupId), int(userId), groupRole), commit=False)

    def insertResource(self, values: Dict[str, Any]) -> int:
        row = self.db.fetchOne('INSERT INTO facility_resources (name, color, unit, "minHours", "maxHours", active, notes) '
                               "VALUES (%(name)s, %(color)s, %(unit)s, %(minHours)s, %(maxHours)s, %(active)s, %(notes)s) "
                               "RETURNING id", values)
        return int(row["id"])

    def insertBooking(self, values: Dict[str, Any]) -> int:
        row = self.db.fetchOne('INSERT INTO facility_bookings ("resourceId", kind, status, "startsAt", "endsAt", title, '
                               '"ownerId", "requestedBy", notes) VALUES (%(resourceId)s, %(kind)s, \'confirmed\', '
                               "%(startsAt)s, %(endsAt)s, %(title)s, %(ownerId)s, %(requestedBy)s, %(notes)s) RETURNING id",
                               values)
        return int(row["id"])

    def insertSession(self, values: Dict[str, Any]) -> int:
        row = self.db.fetchOne('INSERT INTO facility_sessions (name, "microscopeId", technique, status, "userId", '
                               '"scheduledOn", "startedAt", "finishedAt", notes, "templateId", "autoProcess", '
                               '"createdBy") VALUES (%(name)s, %(microscopeId)s, %(technique)s, \'archived\', %(userId)s, '
                               '%(scheduledOn)s, %(startedAt)s, %(finishedAt)s, %(notes)s, \'\', FALSE, %(createdBy)s) '
                               "RETURNING id", values)
        return int(row["id"])

    def defaultRoleIds(self) -> List[int]:
        return [int(row["id"]) for row in self.db.fetchAll('SELECT id FROM access_roles WHERE "isDefault"') or []]

    def giveRoles(self, userId: int, roleIds: Iterable[int]) -> None:
        for roleId in roleIds:
            self.db.execute('INSERT INTO user_access_roles ("userId", "roleId") VALUES (%s, %s) ON CONFLICT DO NOTHING',
                            (int(userId), int(roleId)), commit=False)
