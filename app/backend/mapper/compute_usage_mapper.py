"""The queries of the protocol runs record: who ran what, where, for how long and with which GPUs."""
from datetime import datetime
from typing import Any, Dict, List, Optional

START_RUN_SQL = """
    INSERT INTO protocol_runs ("projectId", "projectPath", "protocolId", "protocolClassName", "protocolLabel",
                               "userId", "executionId", "coordinatorRunId", host, "queueName", "queueJobId",
                               gpus, "gpuIds", threads, mpi, streaming)
    VALUES (%(projectId)s, %(projectPath)s, %(protocolId)s, %(protocolClassName)s, %(protocolLabel)s,
            %(userId)s, %(executionId)s, %(coordinatorRunId)s, %(host)s, %(queueName)s, %(queueJobId)s,
            %(gpus)s, %(gpuIds)s, %(threads)s, %(mpi)s, %(streaming)s)
    RETURNING id
"""

# The runs of this protocol a killed worker left open end at their last heartbeat
CLOSE_LEFT_OPEN_SQL = """
    UPDATE protocol_runs SET "endedAt" = "lastSeenAt", status = 'interrupted'
     WHERE "projectId" = %(projectId)s AND "protocolId" = %(protocolId)s AND "endedAt" IS NULL
"""

TOUCH_RUN_SQL = 'UPDATE protocol_runs SET "lastSeenAt" = NOW() WHERE id = %(runId)s AND "endedAt" IS NULL'

# What the looks at the run's GPUs found so far (they add up from the start of the run)
SAVE_GPU_USE_SQL = """
    UPDATE protocol_runs SET "gpuSamples" = %(samples)s, "gpuBusySum" = %(busySum)s,
                             "gpuMemoryPeakBytes" = %(memoryPeakBytes)s
     WHERE id = %(runId)s
"""

END_RUN_SQL = """
    UPDATE protocol_runs SET "endedAt" = NOW(), "lastSeenAt" = NOW(), status = %(status)s
     WHERE id = %(runId)s AND "endedAt" IS NULL
"""

# A run without an end is still running while its heartbeat is recent and its protocol runs; otherwise it ended
# at its last heartbeat. seconds is the part of each run inside the period.
RUNS_IN_PERIOD_SQL = """
    WITH runs AS (
        SELECT r.*,
               r."endedAt" IS NULL
               AND r."lastSeenAt" >= NOW() - make_interval(secs => %(staleSeconds)s)
               AND LOWER(COALESCE(p.status, '')) IN ('running', 'launched') AS running
          FROM protocol_runs r
          LEFT JOIN protocols p ON p."projectId" = r."projectId" AND p."protocolId" = r."protocolId"
         WHERE r."startedAt" < %(until)s
           AND (%(userId)s::INTEGER IS NULL OR r."userId" = %(userId)s::INTEGER)
    ), bounded AS (
        SELECT runs.*,
               CASE WHEN runs."endedAt" IS NOT NULL THEN runs."endedAt"
                    WHEN runs.running THEN NOW()
                    ELSE runs."lastSeenAt" END AS "effectiveEnd"
          FROM runs
    )
    SELECT b.id, b."projectId", COALESCE(pj.name, b."projectPath") AS "projectPath", b."protocolId",
           b."protocolClassName", b."protocolLabel", b."userId", u.email AS "userEmail",
           u."firstName" AS "userFirstName", u."lastName" AS "userLastName", b.host, b."queueName",
           b."queueJobId", b.gpus, b."gpuIds", b."gpuSamples", b."gpuBusySum", b."gpuMemoryPeakBytes", b.threads, b.mpi, b.streaming, b."startedAt", b."endedAt",
           b."effectiveEnd", b.running,
           CASE WHEN b."endedAt" IS NOT NULL THEN b.status
                WHEN b.running THEN 'running'
                ELSE 'interrupted' END AS status,
           GREATEST(0, EXTRACT(EPOCH FROM (LEAST(b."effectiveEnd", %(until)s)
                                           - GREATEST(b."startedAt", %(since)s))))::DOUBLE PRECISION AS seconds
      FROM bounded b
      LEFT JOIN users u ON u.id = b."userId"
      LEFT JOIN projects pj ON pj.id = b."projectId"
     WHERE b."effectiveEnd" > %(since)s
     ORDER BY b."startedAt" DESC, b.id DESC
     LIMIT %(limit)s
"""


class ComputeUsagePostgresqlMapper:
    def __init__(self, db):
        self.db = db

    # The worker's record -----------------------------------------------------------------------------------------

    def startRun(self, values: Dict[str, Any]) -> Optional[int]:
        """Close what a killed worker left open for this protocol, and open this run; answers its id."""
        self.db.execute(CLOSE_LEFT_OPEN_SQL, {"projectId": values["projectId"], "protocolId": values["protocolId"]})
        row = self.db.executeReturningOne(START_RUN_SQL, values)
        return int(row["id"]) if row else None

    def touchRun(self, runId: int) -> None:
        self.db.execute(TOUCH_RUN_SQL, {"runId": runId})

    def endRun(self, runId: int, status: str) -> None:
        self.db.execute(END_RUN_SQL, {"runId": runId, "status": status})

    def saveGpuUse(self, runId: int, samples: int, busySum: float, memoryPeakBytes: Optional[int]) -> None:
        self.db.execute(SAVE_GPU_USE_SQL, {"runId": runId, "samples": int(samples), "busySum": float(busySum),
                                           "memoryPeakBytes": memoryPeakBytes})

    # What was run -------------------------------------------------------------------------------------------------

    def runsInPeriod(self, since: datetime, until: datetime, staleSeconds: float, userId: Optional[int] = None,
                     limit: int = 200000) -> List[Dict[str, Any]]:
        rows = self.db.fetchAll(RUNS_IN_PERIOD_SQL, {"since": since, "until": until, "staleSeconds": staleSeconds,
                                                     "userId": userId, "limit": limit}) or []
        return [dict(row) for row in rows]
