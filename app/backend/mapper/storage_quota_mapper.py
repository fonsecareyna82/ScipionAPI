"""The queries of disk quotas: the limits, and how much the projects they cover take."""
from typing import Any, Dict, List, Optional

# A user's projects; a group's: those its members own (each once)
_USED = """
    SELECT COALESCE(SUM(d."totalBytes"), 0) AS used
      FROM projects p
      LEFT JOIN project_disk_usage d ON d."projectId" = p.id
     WHERE p.status IS DISTINCT FROM 'deleting' AND %s
"""
USED_BY_USER_SQL = _USED % 'p."ownerId" = %(targetId)s'
USED_BY_GROUP_SQL = _USED % ('p."ownerId" IN (SELECT m."userId" FROM user_group_members m '
                             'WHERE m."groupId" = %(targetId)s)')

LIST_SQL = """
    SELECT q.id, q.kind, q."targetId", q."limitBytes", q."notifiedLevel", q."updatedAt",
           CASE WHEN q.kind = 'user' THEN COALESCE(NULLIF(TRIM(COALESCE(u."firstName", '') || ' ' ||
                COALESCE(u."lastName", '')), ''), u.email) ELSE g.name END AS name,
           u.email
      FROM storage_quotas q
      LEFT JOIN users u ON q.kind = 'user' AND u.id = q."targetId"
      LEFT JOIN user_groups g ON q.kind = 'group' AND g.id = q."targetId"
"""


class StorageQuotaPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def listQuotas(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(LIST_SQL + " ORDER BY q.kind DESC, name") or []]

    def quotasCovering(self, ownerId: int) -> List[Dict[str, Any]]:
        """The quotas a user's projects count against: theirs and their groups'."""
        rows = self.db.fetchAll(LIST_SQL + " WHERE (q.kind = 'user' AND q.\"targetId\" = %s) OR (q.kind = 'group' AND "
                                "q.\"targetId\" IN (SELECT \"groupId\" FROM user_group_members WHERE \"userId\" = %s))",
                                (int(ownerId), int(ownerId)))
        return [dict(row) for row in rows or []]

    def used(self, kind: str, targetId: int) -> int:
        sql = USED_BY_USER_SQL if kind == "user" else USED_BY_GROUP_SQL
        row = self.db.fetchOne(sql, {"targetId": int(targetId)})
        return int(row["used"] or 0) if row else 0

    def save(self, kind: str, targetId: int, limitBytes: Optional[int], userId: Optional[int]) -> None:
        """Set a quota (None: remove it)."""
        if limitBytes is None:
            self.db.execute('DELETE FROM storage_quotas WHERE kind = %s AND "targetId" = %s', (kind, int(targetId)))
            return
        self.db.execute('INSERT INTO storage_quotas (kind, "targetId", "limitBytes", "updatedBy") '
                        'VALUES (%s, %s, %s, %s) ON CONFLICT (kind, "targetId") DO UPDATE SET '
                        '"limitBytes" = EXCLUDED."limitBytes", "updatedBy" = EXCLUDED."updatedBy", '
                        '"updatedAt" = NOW(), "notifiedLevel" = 0', (kind, int(targetId), int(limitBytes), userId))

    def setNotifiedLevel(self, quotaId: int, level: int) -> None:
        self.db.execute('UPDATE storage_quotas SET "notifiedLevel" = %s WHERE id = %s', (int(level), int(quotaId)))

    def exists(self, kind: str, targetId: int) -> bool:
        table = "users" if kind == "user" else "user_groups"
        return self.db.fetchOne("SELECT 1 AS found FROM %s WHERE id = %%s" % table, (int(targetId),)) is not None

    def projectOwner(self, projectId: int) -> Optional[int]:
        row = self.db.fetchOne('SELECT "ownerId" FROM projects WHERE id = %s', (int(projectId),))
        return int(row["ownerId"]) if row and row["ownerId"] is not None else None

    def groupMembers(self, groupId: int) -> List[int]:
        return [int(row["userId"]) for row in
                self.db.fetchAll('SELECT "userId" FROM user_group_members WHERE "groupId" = %s', (int(groupId),)) or []]
