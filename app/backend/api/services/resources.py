"""What the machines have in use right now, for everyone: processors, memory, disks and each GPU with whose run
holds it, the runs going on and the protocols waiting (and why).

Each worker reports its own machine (report_node_resources); a process on a GPU is tied to its run by the worker
process the run recorded (pid on that host) being the process or one it descends from. A run given GPUs on its
machine (not through a queue) holds them even while idle.

Privacy: who may see everyone's computing (storage.view) sees every run; anyone else sees their own runs in full
and the others only as "another user" (no name, project or protocol), and only their own waiting protocols.
"""
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.backend.api.permissions import hasPermission
from app.backend.api.services.compute_usage import staleSeconds
from app.backend.mapper.resources_mapper import ResourcesPostgresqlMapper

VIEW_ALL_PERMISSION = "storage.view"


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _name(row: Dict[str, Any]) -> str:
    name = " ".join(part for part in (row.get("userFirstName"), row.get("userLastName"))
                    if part and str(part).strip()).strip()
    return name or row.get("userEmail") or "Unknown user"


def _projectName(path: Any) -> Optional[str]:
    text = str(path or "").rstrip("/")
    return Path(text).name or text or None


def collectReports(replies: Iterable[Any]) -> List[Dict[str, Any]]:
    """One report per machine from the workers' replies (several workers of a machine answer the same)."""
    byHost: Dict[str, Dict[str, Any]] = {}
    for envelope in replies or []:
        if not isinstance(envelope, dict):
            continue
        for workerName, payload in envelope.items():
            if not isinstance(payload, dict):
                continue
            host = str(payload.get("hostname") or "").strip() or str(workerName or "").partition("@")[2].strip()
            if host and (host not in byHost or byHost[host].get("error")):
                byHost[host] = dict(payload, hostname=host)
    return [byHost[host] for host in sorted(byHost)]


def _runOut(run: Dict[str, Any], visible: bool, mine: bool) -> Dict[str, Any]:
    out = {"id": int(run["id"]), "mine": mine, "host": run.get("host"), "gpus": int(run.get("gpus") or 0),
           "gpuIds": [gpu for gpu in str(run.get("gpuIds") or "").split(",") if gpu],
           "queued": bool(run.get("queueName")), "startedAt": _iso(run.get("startedAt")),
           "streaming": bool(run.get("streaming"))}
    if visible:
        out.update({"userId": run.get("userId"), "userName": _name(run), "projectId": run.get("projectId"),
                    "projectName": _projectName(run.get("projectPath")), "protocolId": run.get("protocolId"),
                    "protocolClassName": run.get("protocolClassName"), "protocolLabel": run.get("protocolLabel"),
                    "queueName": run.get("queueName"), "queueJobId": run.get("queueJobId")})
    return out


def _waitReason(row: Dict[str, Any]) -> str:
    slot = row.get("waitingForSlot")
    if isinstance(slot, dict) and slot.get("limit"):
        return "Waits for a free run slot: %s of %s in use" % (slot.get("inUse"), slot.get("limit"))
    if row.get("status") == "scheduled":
        return "Waits for its inputs"
    return "Waits for a free worker"


def _gpuView(gpu: Dict[str, Any], hostRuns: List[Dict[str, Any]], runsOut: Dict[int, Dict[str, Any]],
             seeAll: bool) -> Dict[str, Any]:
    byPid = {int(run["pid"]): run for run in hostRuns if run.get("pid")}
    uses: List[Dict[str, Any]] = []
    holding = set()
    for process in gpu.get("processes") or []:
        chain = [int(process.get("pid") or 0)] + [int(pid) for pid in process.get("ancestors") or []]
        run = next((byPid[pid] for pid in chain if pid in byPid), None)
        if run is not None:
            holding.add(int(run["id"]))
            existing = next((use for use in uses if use.get("run", {}).get("id") == int(run["id"])), None)
            if existing:
                existing["memoryBytes"] += int(process.get("memoryBytes") or 0)
            else:
                uses.append({"kind": "run", "run": runsOut[int(run["id"])],
                             "memoryBytes": int(process.get("memoryBytes") or 0)})
        else:
            use = {"kind": "other", "memoryBytes": int(process.get("memoryBytes") or 0)}
            if seeAll:
                use["pid"] = process.get("pid")
            uses.append(use)
    # Given to a run (on this machine, not through a queue) that does not use it now
    for run in hostRuns:
        ids = [gpu for gpu in str(run.get("gpuIds") or "").split(",") if gpu]
        if not run.get("queueName") and str(gpu.get("index")) in ids and int(run["id"]) not in holding:
            uses.append({"kind": "reserved", "run": runsOut[int(run["id"])], "memoryBytes": 0})
    state = "free"
    if any(use["kind"] in ("run", "other") for use in uses):
        state = "busy"
    elif uses:
        state = "reserved"
    view = {key: gpu.get(key) for key in ("index", "name", "busy", "memoryUsedBytes", "memoryTotalBytes",
                                          "temperature")}
    view.update(state=state, uses=uses)
    return view


def resourcesView(db, user: Dict[str, Any], reports: List[Dict[str, Any]], available: bool = True,
                  error: Optional[str] = None) -> Dict[str, Any]:
    seeAll = hasPermission(user, VIEW_ALL_PERMISSION)
    userId = int(user["id"])
    mapper = ResourcesPostgresqlMapper(db)
    runs = mapper.openRuns(staleSeconds())
    runsOut = {}
    for run in runs:
        mine = run.get("userId") is not None and int(run["userId"]) == userId
        runsOut[int(run["id"])] = _runOut(run, seeAll or mine, mine)

    machines = []
    for report in reports:
        host = report.get("hostname")
        hostRuns = [run for run in runs if run.get("host") == host]
        machine = {key: report.get(key) for key in ("hostname", "error", "cpuCount", "load1", "load5",
                                                    "memoryTotalBytes", "memoryAvailableBytes", "gpuError")}
        machine["disks"] = report.get("disks") or []
        machine["gpus"] = [_gpuView(gpu, hostRuns, runsOut, seeAll) for gpu in report.get("gpus") or []]
        machine["runs"] = len(hostRuns)
        machines.append(machine)

    running = {(str(run.get("projectId")), str(run.get("protocolId"))) for run in runs}
    waiting = []
    for row in mapper.waitingProtocols():
        if (str(row.get("projectId")), str(row.get("protocolId"))) in running:
            continue
        mine = row.get("userId") is not None and int(row["userId"]) == userId
        if not (seeAll or mine):
            continue
        waiting.append({"mine": mine, "userName": _name(row), "projectId": row.get("projectId"),
                        "projectName": _projectName(row.get("projectPath")), "protocolId": row.get("protocolId"),
                        "protocolClassName": row.get("protocolClassName"), "status": row.get("status"),
                        "since": _iso(row.get("since")), "reason": _waitReason(row)})

    return {"available": available, "error": error, "seeAll": seeAll, "machines": machines,
            "runs": list(runsOut.values()), "waiting": waiting}
