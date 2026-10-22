"""The queries of the protocol activity of a user's projects (the notification bell)."""
from typing import Any, Dict, List, Sequence


PROTOCOL_ACTIVITY_SQL = """
    SELECT p."projectId", pr.name AS "projectPath", p."protocolId", p."protocolClassName", p.status,
           COALESCE(NULLIF(p.params->>'runName', ''), p."protocolClassName") AS label,
           COALESCE(steps."endedAt", p."updatedAt") AS "endedAt"
      FROM protocols p
      JOIN projects pr ON pr.id = p."projectId"
      LEFT JOIN LATERAL (
            SELECT MAX(s."endTime") AS "endedAt"
              FROM protocol_steps s
             WHERE s."protocolDbId" = p.id
      ) steps ON TRUE
     WHERE p."projectId" = ANY(%s)
       AND LOWER(COALESCE(p.status, '')) = ANY(%s)
       AND COALESCE(steps."endedAt", p."updatedAt") > %s
     ORDER BY "endedAt" DESC
     LIMIT %s
"""

LIVE_COUNT_SQL = """
    SELECT COUNT(*) AS live
      FROM protocols
     WHERE "projectId" = ANY(%s) AND LOWER(COALESCE(status, '')) = ANY(%s)
"""

LIVE_PROJECTS_SQL = """
    SELECT DISTINCT "projectId"
      FROM protocols
     WHERE "projectId" = ANY(%s) AND LOWER(COALESCE(status, '')) = ANY(%s)
     ORDER BY "projectId"
     LIMIT %s
"""


class ProtocolActivityPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def listEndedProtocols(self, projectIds: Sequence[int], statuses: Sequence[str], since,
                           limit: int) -> List[Dict[str, Any]]:
        """Protocols of these projects with one of these statuses whose last step ended after ``since``."""
        return self.db.fetchAll(PROTOCOL_ACTIVITY_SQL, (list(projectIds), list(statuses), since, int(limit))) or []

    def countLiveProtocols(self, projectIds: Sequence[int], statuses: Sequence[str]) -> int:
        row = self.db.fetchOne(LIVE_COUNT_SQL, (list(projectIds), list(statuses))) or {}
        return int(row.get("live") or 0)

    def listLiveProjectIds(self, projectIds: Sequence[int], statuses: Sequence[str], limit: int) -> List[int]:
        """The projects with a protocol in one of these statuses."""
        rows = self.db.fetchAll(LIVE_PROJECTS_SQL, (list(projectIds), list(statuses), int(limit))) or []
        return [int(row["projectId"]) for row in rows]
