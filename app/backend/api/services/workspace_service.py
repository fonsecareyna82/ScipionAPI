"""What spans every project of a user: protocol activity (to notify when runs end).

A run ends when its protocol reaches a final or waiting status (finished,
failed, aborted, interactive). The moment it ended is the end of its last
step, so editing a finished protocol (its label, a comment) is not taken for
a new end. Clients pass the server time of their previous call ("since"), so
their clock does not matter.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

ENDED_STATUSES = ("finished", "failed", "aborted", "interactive")
LIVE_STATUSES = ("launched", "running", "scheduled")
# A first call without "since" reports nothing; a very old "since" is capped.
MAX_LOOKBACK = timedelta(hours=6)
MAX_EVENTS = 50

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


def _accessibleProjects(mapper, userId: int) -> Dict[int, Dict[str, Any]]:
    return {int(row["id"]): row for row in (mapper.listProjects(int(userId)) or [])}


def _projectName(row: Dict[str, Any]) -> str:
    for key in ("shortName", "label", "title"):
        if row.get(key):
            return str(row[key])
    return str(row.get("name") or "").rstrip("/").rsplit("/", 1)[-1]


def protocolActivity(mapper, userId: int, since: Optional[datetime], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Runs of the user's projects that ended after ``since``, and how many still run."""
    now = now or datetime.now(timezone.utc)
    projects = _accessibleProjects(mapper, userId)
    projectIds: List[int] = sorted(projects)
    events: List[Dict[str, Any]] = []
    live = 0
    if projectIds:
        live = int((mapper.db.fetchOne(LIVE_COUNT_SQL, (projectIds, list(LIVE_STATUSES))) or {}).get("live") or 0)
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            since = max(since, now - MAX_LOOKBACK)
            rows: Sequence[Dict[str, Any]] = mapper.db.fetchAll(
                PROTOCOL_ACTIVITY_SQL, (projectIds, list(ENDED_STATUSES), since, MAX_EVENTS)) or []
            for row in rows:
                project = projects.get(int(row["projectId"]), {})
                endedAt = row.get("endedAt")
                events.append({
                    "projectId": int(row["projectId"]),
                    "projectName": _projectName(project) or _projectName({"name": row.get("projectPath")}),
                    "protocolId": str(row["protocolId"]),
                    "protocolClassName": str(row.get("protocolClassName") or ""),
                    "label": str(row.get("label") or ""),
                    "status": str(row.get("status") or "").lower(),
                    "endedAt": endedAt.isoformat() if hasattr(endedAt, "isoformat") else str(endedAt or ""),
                })
    return {"now": now.isoformat(), "live": live, "events": events}
