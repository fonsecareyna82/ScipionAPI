"""The computing each user, group, protocol and machine used in a period, from the protocol runs record.

Hours are a run's wall time inside the period; GPU hours are those hours times the GPUs the run was given (what
it took from the others, whether it kept them busy or not). A run still going counts up to now; one whose worker
was killed counts up to its last heartbeat.
"""
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.backend.mapper.compute_usage_mapper import ComputeUsagePostgresqlMapper
from app.backend.mapper.storage_mapper import StoragePostgresqlMapper

# How long a run without an end may go without a heartbeat before it is taken as ended (its worker died)
MIN_STALE_SECONDS = 300.0
# The runs of one user listed at most
USER_RUNS_LIMIT = 500


def staleSeconds() -> float:
    try:
        heartbeat = float(os.environ.get("SCIPION_POSTGRESQL_COORDINATOR_HEARTBEAT_SECONDS", "60") or 60)
    except ValueError:
        heartbeat = 60.0
    return max(MIN_STALE_SECONDS, 3 * max(15.0, heartbeat))


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _personName(row: Dict[str, Any]) -> str:
    name = " ".join(part for part in (row.get("userFirstName"), row.get("userLastName"))
                    if part and str(part).strip()).strip()
    return name or row.get("userEmail") or ("Unknown user" if row.get("userId") is None else "Deleted user")


def period(since: Optional[datetime], until: Optional[datetime],
           now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """The period asked for; this month up to now without one."""
    now = now or datetime.now(timezone.utc)
    until = until or now
    since = since or now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if since >= until:
        raise ValueError("The period must start before it ends")
    return since, until


def runOut(row: Dict[str, Any]) -> Dict[str, Any]:
    hours = float(row.get("seconds") or 0) / 3600.0
    gpus = int(row.get("gpus") or 0)
    path = str(row.get("projectPath") or "")
    return {
        "id": int(row["id"]),
        "projectId": row.get("projectId"),
        "projectName": Path(path).name or path or None,
        "protocolId": row.get("protocolId"),
        "protocolClassName": row.get("protocolClassName"),
        "protocolLabel": row.get("protocolLabel"),
        "userId": row.get("userId"),
        "userName": _personName(row),
        "userEmail": row.get("userEmail"),
        "host": row.get("host"),
        "queueName": row.get("queueName"),
        "queueJobId": row.get("queueJobId"),
        "gpus": gpus,
        "gpuIds": [gpu for gpu in str(row.get("gpuIds") or "").split(",") if gpu],
        "threads": row.get("threads"),
        "mpi": row.get("mpi"),
        "streaming": bool(row.get("streaming")),
        "startedAt": _iso(row.get("startedAt")),
        "endedAt": _iso(row.get("endedAt")),
        "running": bool(row.get("running")),
        "status": row.get("status"),
        "hours": hours,
        "gpuHours": hours * gpus,
    }


def _emptyTotals() -> Dict[str, Any]:
    return {"runs": 0, "hours": 0.0, "gpuHours": 0.0, "failed": 0, "running": 0}


def _add(totals: Dict[str, Any], run: Dict[str, Any]) -> None:
    totals["runs"] += 1
    totals["hours"] += run["hours"]
    totals["gpuHours"] += run["gpuHours"]
    totals["failed"] += 1 if run["status"] == "failed" else 0
    totals["running"] += 1 if run["running"] else 0


def _sum(runs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    totals = _emptyTotals()
    for run in runs:
        _add(totals, run)
    return totals


def _mostUsed(runs: List[Dict[str, Any]]) -> Optional[str]:
    """The protocol that took most of these runs' GPU hours (of their hours, without GPUs)."""
    weights: Dict[str, Tuple[float, float]] = {}
    for run in runs:
        name = run["protocolClassName"] or "?"
        gpuHours, hours = weights.get(name, (0.0, 0.0))
        weights[name] = (gpuHours + run["gpuHours"], hours + run["hours"])
    return max(weights, key=lambda name: weights[name]) if weights else None


def _byKey(runs: List[Dict[str, Any]], key) -> Dict[Any, List[Dict[str, Any]]]:
    grouped: Dict[Any, List[Dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault(key(run), []).append(run)
    return grouped


def _ordered(rows: List[Dict[str, Any]], name: str = "name") -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda row: (-row["gpuHours"], -row["hours"], str(row.get(name) or "").lower()))


def summarize(runs: List[Dict[str, Any]], groupMembers: List[Dict[str, Any]], since: datetime,
              until: datetime) -> Dict[str, Any]:
    """The runs of a period summed in all and by user, group (a user in two groups counts in both), protocol and
    machine, and the ones running now."""
    byUser = _byKey(runs, lambda run: run["userId"])
    users = []
    for userId, owned in byUser.items():
        users.append(dict(_sum(owned), userId=userId, name=owned[0]["userName"], email=owned[0]["userEmail"],
                          mostUsed=_mostUsed(owned)))

    groups: Dict[int, Dict[str, Any]] = {}
    for row in groupMembers:
        group = groups.setdefault(int(row["id"]), {"groupId": int(row["id"]), "name": row["name"], "members": []})
        if row.get("userId") is not None:
            group["members"].append(int(row["userId"]))
    groupList = []
    for group in groups.values():
        owned = [run for member in group["members"] for run in byUser.get(member, [])]
        groupList.append(dict(_sum(owned), groupId=group["groupId"], name=group["name"],
                              members=len(group["members"]),
                              activeMembers=sum(1 for member in group["members"] if member in byUser),
                              mostUsed=_mostUsed(owned)))

    protocols = []
    for className, owned in _byKey(runs, lambda run: run["protocolClassName"] or "?").items():
        protocols.append(dict(_sum(owned), protocolClassName=className, name=className,
                              users=len({run["userId"] for run in owned})))

    machines = []
    for host, owned in _byKey(runs, lambda run: run["host"] or "?").items():
        # Without a queue a run's GPU ids are the machine's own; a queue renumbers them inside each job
        gpuHoursById: Dict[str, float] = {}
        for run in owned:
            if run["queueJobId"]:
                continue
            for gpu in run["gpuIds"]:
                gpuHoursById[gpu] = gpuHoursById.get(gpu, 0.0) + run["hours"]
        machines.append(dict(_sum(owned), host=host, name=host, users=len({run["userId"] for run in owned}),
                             gpuHoursById=dict(sorted(gpuHoursById.items(),
                                                      key=lambda item: (len(item[0]), item[0])))))

    total = dict(_sum(runs), users=len(byUser))
    return {
        "since": _iso(since),
        "until": _iso(until),
        "periodHours": (until - since).total_seconds() / 3600.0,
        "total": total,
        "users": _ordered(users),
        "groups": _ordered(groupList),
        "protocols": _ordered(protocols),
        "machines": _ordered(machines),
        "running": [run for run in runs if run["running"]],
    }


def usageReport(db, since: Optional[datetime] = None, until: Optional[datetime] = None) -> Dict[str, Any]:
    since, until = period(since, until)
    runs = [runOut(row) for row in ComputeUsagePostgresqlMapper(db).runsInPeriod(since, until, staleSeconds())]
    return summarize(runs, StoragePostgresqlMapper(db).listGroupMembers(), since, until)


def userRuns(db, userId: Optional[int], since: Optional[datetime] = None,
             until: Optional[datetime] = None) -> Dict[str, Any]:
    """One user's runs in the period, the newest first (at most USER_RUNS_LIMIT), and their totals."""
    since, until = period(since, until)
    rows = ComputeUsagePostgresqlMapper(db).runsInPeriod(since, until, staleSeconds(), userId=userId,
                                                         limit=USER_RUNS_LIMIT + 1)
    runs = [runOut(row) for row in rows]
    return {"since": _iso(since), "until": _iso(until), "runs": runs[:USER_RUNS_LIMIT],
            "truncated": len(runs) > USER_RUNS_LIMIT}


def ownUsage(db, userId: int, since: Optional[datetime] = None,
             until: Optional[datetime] = None) -> Dict[str, Any]:
    """What one user used in the period, in all."""
    since, until = period(since, until)
    runs = [runOut(row) for row in ComputeUsagePostgresqlMapper(db).runsInPeriod(since, until, staleSeconds(),
                                                                                 userId=userId)]
    return dict(_sum(runs), since=_iso(since), until=_iso(until))
