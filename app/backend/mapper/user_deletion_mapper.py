"""The queries of deleting an account: what it owns, and removing it once its projects are gone."""
from typing import Any, Dict, List, Optional

from app.backend.mapper.postgresql import PostgresqlFlatMapper

LIVE_STATUSES = ("launched", "running", "scheduled")

# The projects a user owns (not those already being deleted), with their size, who else sees them and what runs
OWNED_PROJECTS_SQL = """
    SELECT p.id, p.name, du."totalBytes" AS bytes,
           (SELECT COUNT(*) FROM project_shares s WHERE s."projectId" = p.id) AS shares,
           (SELECT COUNT(*) FROM protocols pr WHERE pr."projectId" = p.id
               AND LOWER(COALESCE(pr.status, '')) = ANY(%(live)s)) AS running
      FROM projects p
      LEFT JOIN project_disk_usage du ON du."projectId" = p.id
     WHERE p."ownerId" = %(userId)s AND p.status IS DISTINCT FROM %(deleting)s
     ORDER BY p.id
"""

# What stays of the account in the facility, without it (their sessions, bookings and samples)
FACILITY_TRACES_SQL = """
    SELECT (SELECT COUNT(*) FROM facility_sessions WHERE "userId" = %(userId)s) AS sessions,
           (SELECT COUNT(*) FROM facility_bookings WHERE "ownerId" = %(userId)s) AS bookings,
           (SELECT COUNT(*) FROM facility_samples WHERE "ownerId" = %(userId)s) AS samples
"""


class UserDeletionPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def ownedProjects(self, userId: int) -> List[Dict[str, Any]]:
        rows = self.db.fetchAll(OWNED_PROJECTS_SQL, {"userId": int(userId), "live": list(LIVE_STATUSES),
                                                     "deleting": PostgresqlFlatMapper.DELETING_STATUS})
        return [dict(row) for row in rows or []]

    def facilityTraces(self, userId: int) -> Dict[str, int]:
        """How many facility sessions, bookings and samples are the user's (none without the facility's tables)."""
        try:
            row = self.db.fetchOne(FACILITY_TRACES_SQL, {"userId": int(userId)}) or {}
        except Exception:
            self.db.rollback()
            return {"sessions": 0, "bookings": 0, "samples": 0}
        return {key: int(row.get(key) or 0) for key in ("sessions", "bookings", "samples")}

    def markDeleting(self, userId: int) -> None:
        """The account stops at once: it cannot sign in, and lists no longer show it."""
        self.db.execute('UPDATE users SET "isActive" = FALSE, "deletingAt" = NOW() WHERE id = %s', (int(userId),))

    def deleteIfNoProjects(self, userId: int) -> bool:
        """Remove a user being deleted once no project of theirs is left; answers whether it went."""
        cursor = self.db.execute('DELETE FROM users WHERE id = %s AND "deletingAt" IS NOT NULL '
                                 'AND NOT EXISTS (SELECT 1 FROM projects WHERE "ownerId" = %s)',
                                 (int(userId), int(userId)))
        return bool(getattr(cursor, "rowcount", 0))

    def listDeletingUserIds(self) -> List[int]:
        return [int(row["id"]) for row in self.db.fetchAll('SELECT id FROM users WHERE "deletingAt" IS NOT NULL') or []]

    def deletingAt(self, userId: int) -> Optional[Any]:
        row = self.db.fetchOne('SELECT "deletingAt" FROM users WHERE id = %s', (int(userId),))
        return row["deletingAt"] if row else None
