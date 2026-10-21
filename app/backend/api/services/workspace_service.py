"""What spans every project of a user: protocol activity (to notify when runs end).

A run ends when its protocol reaches a final or waiting status (finished,
failed, aborted, interactive). The moment it ended is the end of its last
step, so editing a finished protocol (its label, a comment) is not taken for
a new end. Clients pass the server time of their previous call ("since"), so
their clock does not matter.

Streaming projects (those with a protocol running) also tell when a run of
micrographs starts going past one of their monitor thresholds (status
"alert"); see streaming_monitor.alertsSince.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

ENDED_STATUSES = ("finished", "failed", "aborted", "interactive")
LIVE_STATUSES = ("launched", "running", "scheduled")
# A first call without "since" reports nothing; a very old "since" is capped.
MAX_LOOKBACK = timedelta(hours=6)
MAX_EVENTS = 50
# Streaming projects whose monitor alerts are looked at in one call
MAX_MONITORED_PROJECTS = 10

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


def _monitorAlerts(mapper, projects: Dict[int, Dict[str, Any]], projectIds: List[int],
                   since: datetime) -> List[Dict[str, Any]]:
    """Runs of micrographs past a monitor threshold that started after ``since``, in the streaming projects."""
    from app.backend.api.services import streaming_monitor

    events = []
    rows = mapper.db.fetchAll(LIVE_PROJECTS_SQL, (projectIds, list(LIVE_STATUSES), MAX_MONITORED_PROJECTS)) or []
    for row in rows:
        projectId = int(row["projectId"])
        try:
            runs = streaming_monitor.alertsSince(mapper, projectId, since)
        except Exception:
            # The monitor of one project never stops the activity of the others
            logger.warning("The monitor alerts of project %s could not be read", projectId, exc_info=True)
            continue
        for run in runs:
            count = int(run["count"])
            events.append({
                "projectId": projectId,
                "projectName": _projectName(projects.get(projectId, {})),
                "protocolId": str(run["protocolId"]),
                "protocolClassName": str(run["protocolClassName"]),
                "label": "%s: %s%s" % (run["text"], run["micrographName"],
                                       " and %d more" % (count - 1) if count > 1 else ""),
                "status": "alert",
                "threshold": run["kind"],
                "endedAt": str(run["startedAt"]),
            })
    return events


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
            if live:
                events.extend(_monitorAlerts(mapper, projects, projectIds, since))
                events = sorted(events, key=lambda event: event["endedAt"], reverse=True)[:MAX_EVENTS]
    return {"now": now.isoformat(), "live": live, "events": events}
