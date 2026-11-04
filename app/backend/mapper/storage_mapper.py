"""The queries of the projects' disk usage and of the users' projects folders."""
from typing import Any, Dict, List, Optional, Sequence

MEASURE_LOCK_SQL = "SELECT pg_try_advisory_lock(hashtext('project_disk_usage')) AS locked"
MEASURE_UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtext('project_disk_usage')) AS unlocked"

# The last change of a project: its protocols' last update
LAST_ACTIVITY_SQL = """
    SELECT MAX(COALESCE(pr."updatedAt", pr."createdAt")) AS "lastActivity"
      FROM protocols pr
     WHERE pr."projectId" = p.id
"""

# The project to measure next: one asked for first, then one never measured, then the oldest measure; a measure
# is old after maxAgeSeconds, or after activitySeconds when the project changed since
NEXT_TO_MEASURE_SQL = """
    SELECT p.id, p.name AS path, d."measuredAt", d."requestedAt"
      FROM projects p
      LEFT JOIN project_disk_usage d ON d."projectId" = p.id
      LEFT JOIN LATERAL (%(lastActivity)s) activity ON TRUE
     WHERE p.status IS DISTINCT FROM 'deleting'
       AND (d."measuredAt" IS NULL
            OR d."requestedAt" > d."measuredAt"
            OR d."measuredAt" < NOW() - make_interval(secs => %%(maxAgeSeconds)s)
            OR (activity."lastActivity" > d."measuredAt"
                AND d."measuredAt" < NOW() - make_interval(secs => %%(activitySeconds)s)))
     ORDER BY CASE WHEN d."requestedAt" IS NOT NULL
                        AND (d."measuredAt" IS NULL OR d."requestedAt" > d."measuredAt") THEN 0
                   WHEN d."measuredAt" IS NULL THEN 1
                   ELSE 2 END,
              d."measuredAt" NULLS FIRST, p.id
     LIMIT 1
""" % {"lastActivity": LAST_ACTIVITY_SQL}

START_MEASURE_SQL = """
    INSERT INTO project_disk_usage ("projectId", "startedAt") VALUES (%(projectId)s, %(startedAt)s)
    ON CONFLICT ("projectId") DO UPDATE SET "startedAt" = EXCLUDED."startedAt"
"""

# measuredAt is when the measure started: a request made while it ran is still pending afterwards
SAVE_MEASURE_SQL = """
    UPDATE project_disk_usage
       SET "totalBytes" = %(totalBytes)s, files = %(files)s, "runsBytes" = %(runsBytes)s,
           "uploadsBytes" = %(uploadsBytes)s, location = %(location)s, "measuredPath" = %(measuredPath)s,
           "measuredAt" = %(measuredAt)s, "durationSeconds" = %(durationSeconds)s, error = %(error)s,
           "startedAt" = NULL
     WHERE "projectId" = %(projectId)s
"""

REQUEST_MEASURE_SQL = """
    INSERT INTO project_disk_usage ("projectId", "requestedAt")
    SELECT p.id, NOW()
      FROM projects p
     WHERE p.status IS DISTINCT FROM 'deleting'
       AND (%(all)s OR p.id = ANY(%(projectIds)s::INTEGER[]))
    ON CONFLICT ("projectId") DO UPDATE SET "requestedAt" = NOW()
"""

LIST_PROJECT_USAGE_SQL = """
    SELECT p.id, p.name AS path, p."ownerId", u.email AS "ownerEmail", u."firstName" AS "ownerFirstName",
           u."lastName" AS "ownerLastName", d."totalBytes", d.files, d."runsBytes", d."uploadsBytes", d.location,
           d."measuredAt", d."durationSeconds", d.error, d."startedAt", d."requestedAt", activity."lastActivity"
      FROM projects p
      JOIN users u ON u.id = p."ownerId"
      LEFT JOIN project_disk_usage d ON d."projectId" = p.id
      LEFT JOIN LATERAL (%(lastActivity)s) activity ON TRUE
     WHERE p.status IS DISTINCT FROM 'deleting'
     ORDER BY d."totalBytes" DESC NULLS LAST, p.id
""" % {"lastActivity": LAST_ACTIVITY_SQL}

LIST_GROUP_MEMBERS_SQL = """
    SELECT g.id, g.name, m."userId", m."groupRole"
      FROM user_groups g
      LEFT JOIN user_group_members m ON m."groupId" = g.id
     ORDER BY g.name, g.id
"""

USAGE_OF_PROJECTS_SQL = """
    SELECT "projectId", "totalBytes", "measuredAt" FROM project_disk_usage
     WHERE "projectId" = ANY(%(projectIds)s::INTEGER[]) AND "measuredAt" IS NOT NULL
"""

PROJECTS_FOLDER_OF_SQL = 'SELECT "projectsFolder" FROM users WHERE id = %(userId)s'

FOLDERS_LIKE_SQL = """
    SELECT "projectsFolder" FROM users WHERE "projectsFolder" = %(base)s OR "projectsFolder" LIKE %(pattern)s
"""

CLAIM_PROJECTS_FOLDER_SQL = """
    UPDATE users SET "projectsFolder" = %(folder)s
     WHERE id = %(userId)s AND "projectsFolder" IS NULL
       AND NOT EXISTS (SELECT 1 FROM users other WHERE other."projectsFolder" = %(folder)s)
    RETURNING "projectsFolder"
"""


class StoragePostgresqlMapper:
    def __init__(self, db):
        self.db = db

    # The measurer ---------------------------------------------------------------------------------------------

    def lockMeasure(self) -> bool:
        """Whether this process measures now: only one at a time does."""
        row = self.db.fetchOne(MEASURE_LOCK_SQL)
        return bool(row and row["locked"])

    def unlockMeasure(self) -> None:
        self.db.fetchOne(MEASURE_UNLOCK_SQL)

    def nextToMeasure(self, maxAgeSeconds: float, activitySeconds: float) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(NEXT_TO_MEASURE_SQL, {"maxAgeSeconds": maxAgeSeconds,
                                                     "activitySeconds": activitySeconds})
        return dict(row) if row else None

    def startMeasure(self, projectId: int, startedAt) -> None:
        self.db.execute(START_MEASURE_SQL, {"projectId": projectId, "startedAt": startedAt})

    def saveMeasure(self, projectId: int, values: Dict[str, Any]) -> None:
        self.db.execute(SAVE_MEASURE_SQL, dict(values, projectId=projectId))

    def requestMeasure(self, projectIds: Optional[Sequence[int]] = None) -> None:
        """Ask for a new measure of these projects (of all of them, without any)."""
        ids = [int(projectId) for projectId in projectIds or []]
        self.db.execute(REQUEST_MEASURE_SQL, {"all": not ids, "projectIds": ids})

    # What they use ---------------------------------------------------------------------------------------------

    def listProjectUsage(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(LIST_PROJECT_USAGE_SQL) or []]

    def listGroupMembers(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(LIST_GROUP_MEMBERS_SQL) or []]

    def usageOfProjects(self, projectIds: Sequence[int]) -> Dict[int, Dict[str, Any]]:
        ids = [int(projectId) for projectId in projectIds]
        if not ids:
            return {}
        rows = self.db.fetchAll(USAGE_OF_PROJECTS_SQL, {"projectIds": ids}) or []
        return {int(row["projectId"]): dict(row) for row in rows}

    # The users' projects folders -----------------------------------------------------------------------------

    def projectsFolderOf(self, userId: int) -> Optional[str]:
        row = self.db.fetchOne(PROJECTS_FOLDER_OF_SQL, {"userId": userId})
        return row["projectsFolder"] if row else None

    def foldersLike(self, base: str) -> List[str]:
        pattern = base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "\\_%"
        rows = self.db.fetchAll(FOLDERS_LIKE_SQL, {"base": base, "pattern": pattern}) or []
        return [row["projectsFolder"] for row in rows]

    def claimProjectsFolder(self, userId: int, folder: str) -> Optional[str]:
        """Give the user this folder if they have none and nobody else has it; None when not given."""
        row = self.db.executeReturningOne(CLAIM_PROJECTS_FOLDER_SQL, {"userId": userId, "folder": folder})
        return row["projectsFolder"] if row else None
