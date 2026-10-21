"""A project at a glance: its runs by status, what runs or failed, run times, and disk usage.

Run times come from the protocol steps: a run starts with its first step and
ends with its last one, so editing a finished protocol does not change them.

Disk usage walks the protocol folders (``Runs/<id>_<class>``), which can take
a while on big projects, so it is computed in a background thread and kept in
memory; the answer says when it was computed and whether a new count runs.
Symbolic links are not followed: Scipion links the inputs of a protocol to
the outputs of another, which are counted where they are.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.backend.api.services.fs_browser import protocolFolder
from app.backend.mapper.project_overview_mapper import ProjectOverviewPostgresqlMapper

logger = logging.getLogger(__name__)

LIVE_STATUSES = ("launched", "running", "scheduled")
FAILED_STATUSES = ("failed", "aborted")
LIST_LIMIT = 10
DISK_USAGE_MAX_AGE_SECONDS = 15 * 60


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        if getattr(value, "tzinfo", None) is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _seconds(start, end) -> Optional[float]:
    if start is None or end is None or not hasattr(start, "timestamp") or not hasattr(end, "timestamp"):
        return None
    return max(0.0, end.timestamp() - start.timestamp())


def _aware(value):
    if value is not None and hasattr(value, "tzinfo") and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def projectOverview(mapper, projectId: int, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The runs of a project by status, the ones running, failed or recent, and their times."""
    now = now or datetime.now(timezone.utc)
    rows = ProjectOverviewPostgresqlMapper(mapper.db).listRuns(projectId)
    counts: Dict[str, int] = {}
    runs: List[Dict[str, Any]] = []
    computeSeconds = 0.0
    for row in rows:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        startedAt = _aware(row.get("startedAt"))
        endedAt = _aware(row.get("endedAt"))
        live = status in LIVE_STATUSES
        duration = _seconds(startedAt, now if live else endedAt)
        if duration is not None and not live:
            computeSeconds += duration
        runs.append({
            "protocolId": str(row["protocolId"]),
            "protocolClassName": str(row.get("protocolClassName") or ""),
            "label": str(row.get("label") or ""),
            "status": status,
            "startedAt": _iso(startedAt),
            "endedAt": None if live else _iso(endedAt),
            "seconds": duration,
            "steps": int(row.get("stepCount") or 0),
            "stepsDone": int(row.get("stepsDone") or 0),
            "_sortEnd": (endedAt or _aware(row.get("updatedAt"))),
        })

    def newestFirst(items: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
        return sorted(items, key=lambda item: (item[key] is not None, item[key] or 0), reverse=True)

    def public(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{k: v for k, v in item.items() if not k.startswith("_")} for item in items[:LIST_LIMIT]]

    running = newestFirst([run for run in runs if run["status"] in LIVE_STATUSES], "startedAt")
    failed = newestFirst([run for run in runs if run["status"] in FAILED_STATUSES], "_sortEnd")
    recent = newestFirst([run for run in runs if run["status"] == "finished"], "_sortEnd")
    longest = sorted((run for run in runs if run["seconds"] is not None and run["status"] not in LIVE_STATUSES),
                     key=lambda run: run["seconds"], reverse=True)
    return {
        "now": now.isoformat(),
        "protocols": len(runs),
        "counts": counts,
        "computeSeconds": computeSeconds,
        "running": public(running),
        "failed": public(failed),
        "recent": public(recent),
        "longest": public(longest),
    }


# -- disk usage -----------------------------------------------------------------

def folderUsage(folder: Path) -> Tuple[int, int]:
    """Bytes and files under ``folder``, without following symbolic links."""
    total = 0
    files = 0
    stack = [str(folder)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, files


class DiskUsageCache:
    """Disk usage of the projects, counted in the background and kept for a while."""

    def __init__(self, maxAgeSeconds: float = DISK_USAGE_MAX_AGE_SECONDS):
        self.maxAgeSeconds = maxAgeSeconds
        self._lock = threading.Lock()
        self._results: Dict[int, Dict[str, Any]] = {}
        self._running: Dict[int, threading.Thread] = {}

    def get(self, projectId: int, projectPath: str, protocols: List[Dict[str, Any]],
            refresh: bool = False, background: bool = True) -> Dict[str, Any]:
        """The last count (possibly none yet); a new one starts when it is old or asked for.

        ``background=False`` counts in the calling thread (tests).
        """
        projectId = int(projectId)
        with self._lock:
            result = self._results.get(projectId)
            stale = result is None or refresh or (time.time() - result["computedAtEpoch"]) > self.maxAgeSeconds
            start = stale and projectId not in self._running
            if start:
                self._running[projectId] = threading.current_thread()
        if start:
            if background:
                threading.Thread(target=self._compute, args=(projectId, projectPath, protocols),
                                 name="disk-usage-%d" % projectId, daemon=True).start()
            else:
                self._compute(projectId, projectPath, protocols)
        with self._lock:
            result = self._results.get(projectId)
            computing = projectId in self._running
        payload = {k: v for k, v in (result or {}).items() if k != "computedAtEpoch"}
        payload.setdefault("computedAt", None)
        payload.setdefault("totalBytes", None)
        payload.setdefault("protocols", [])
        payload["computing"] = computing
        return payload

    def _compute(self, projectId: int, projectPath: str, protocols: List[Dict[str, Any]]) -> None:
        try:
            items = []
            for protocol in protocols:
                try:
                    folder = protocolFolder(projectPath, protocol["protocolId"], protocol["protocolClassName"])
                except (TypeError, ValueError):
                    continue
                if not folder.is_dir():
                    continue
                size, files = folderUsage(folder)
                items.append({
                    "protocolId": str(protocol["protocolId"]),
                    "protocolClassName": str(protocol["protocolClassName"]),
                    "label": str(protocol.get("label") or ""),
                    "status": str(protocol.get("status") or ""),
                    "bytes": size,
                    "files": files,
                })
            items.sort(key=lambda item: item["bytes"], reverse=True)
            computedAt = datetime.now(timezone.utc)
            result = {
                "computedAt": computedAt.isoformat(),
                "computedAtEpoch": computedAt.timestamp(),
                "totalBytes": sum(item["bytes"] for item in items),
                "protocols": items,
            }
            with self._lock:
                self._results[projectId] = result
        except Exception:
            logger.exception("Disk usage of project %s could not be counted", projectId)
        finally:
            with self._lock:
                self._running.pop(projectId, None)


diskUsageCache = DiskUsageCache()


def projectProtocols(mapper, projectId: int) -> List[Dict[str, Any]]:
    return [dict(row) for row in ProjectOverviewPostgresqlMapper(mapper.db).listProtocols(projectId)]
