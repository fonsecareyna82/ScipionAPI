"""The queries of the project overview: its runs with their step times, and its protocols."""
from typing import Any, Dict, List


PROJECT_RUNS_SQL = """
    SELECT p."protocolId", p."protocolClassName", LOWER(COALESCE(p.status, '')) AS status,
           COALESCE(NULLIF(p.params->>'runName', ''), p."protocolClassName") AS label,
           p."updatedAt",
           steps."startedAt", steps."endedAt", steps."stepCount", steps."stepsDone"
      FROM protocols p
      LEFT JOIN LATERAL (
            SELECT MIN(s."initTime") AS "startedAt", MAX(s."endTime") AS "endedAt",
                   COUNT(*) AS "stepCount",
                   COUNT(*) FILTER (WHERE LOWER(s.status) = 'finished') AS "stepsDone"
              FROM protocol_steps s
             WHERE s."protocolDbId" = p.id
      ) steps ON TRUE
     WHERE p."projectId" = %s AND p."protocolId" <> 'PROJECT'
"""

PROJECT_PROTOCOLS_SQL = """
    SELECT p."protocolId", p."protocolClassName", LOWER(COALESCE(p.status, '')) AS status,
           COALESCE(NULLIF(p.params->>'runName', ''), p."protocolClassName") AS label
      FROM protocols p
     WHERE p."projectId" = %s AND p."protocolId" <> 'PROJECT'
"""


class ProjectOverviewPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def listRuns(self, projectId: int) -> List[Dict[str, Any]]:
        """The protocols of a project with their status, label and the times and count of their steps."""
        return self.db.fetchAll(PROJECT_RUNS_SQL, (int(projectId),)) or []

    def listProtocols(self, projectId: int) -> List[Dict[str, Any]]:
        """The protocols of a project with their status and label."""
        return self.db.fetchAll(PROJECT_PROTOCOLS_SQL, (int(projectId),)) or []
