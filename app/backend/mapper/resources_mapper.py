"""The queries of the resources page: the runs going on now and the protocols waiting to run."""
from typing import Any, Dict, List

# A run without an end whose heartbeat is recent
OPEN_RUNS_SQL = """
    SELECT r.id, r."projectId", COALESCE(pj.name, r."projectPath") AS "projectPath", r."protocolId",
           r."protocolClassName", r."protocolLabel", r."userId", u.email AS "userEmail",
           u."firstName" AS "userFirstName", u."lastName" AS "userLastName", r.host, r.pid, r.gpus, r."gpuIds",
           r."queueName", r."queueJobId", r.streaming, r."startedAt"
      FROM protocol_runs r
      LEFT JOIN users u ON u.id = r."userId"
      LEFT JOIN projects pj ON pj.id = r."projectId"
     WHERE r."endedAt" IS NULL
       AND r."lastSeenAt" >= NOW() - make_interval(secs => %(staleSeconds)s)
     ORDER BY r."startedAt"
"""

# Who launched a protocol, when it says so with a number
LAUNCHED_BY = """CASE WHEN p.params::jsonb -> '_scipionWebRuntime' ->> 'launchedByUserId' ~ '^[0-9]+$'
                      THEN (p.params::jsonb -> '_scipionWebRuntime' ->> 'launchedByUserId')::INTEGER END"""

# Launched or scheduled protocols; whose they are is who launched them, else the project's owner
WAITING_SQL = """
    SELECT p."projectId", pj.name AS "projectPath", p."protocolId", p."protocolClassName",
           LOWER(COALESCE(p.status, '')) AS status, COALESCE(p."updatedAt", p."createdAt") AS since,
           p.params::jsonb -> '_scipionWebRuntime' -> 'waitingForSlot' AS "waitingForSlot",
           COALESCE(""" + LAUNCHED_BY + """, pj."ownerId") AS "userId",
           u.email AS "userEmail", u."firstName" AS "userFirstName", u."lastName" AS "userLastName"
      FROM protocols p
      JOIN projects pj ON pj.id = p."projectId"
      LEFT JOIN users u ON u.id = COALESCE(""" + LAUNCHED_BY + """, pj."ownerId")
     WHERE LOWER(COALESCE(p.status, '')) IN ('launched', 'scheduled')
       AND pj.status IS DISTINCT FROM 'deleting'
     ORDER BY COALESCE(p."updatedAt", p."createdAt")
     LIMIT %(limit)s
"""


class ResourcesPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def openRuns(self, staleSeconds: float) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(OPEN_RUNS_SQL, {"staleSeconds": staleSeconds}) or []]

    def waitingProtocols(self, limit: int = 500) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(WAITING_SQL, {"limit": limit}) or []]
