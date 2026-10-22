"""The parameters of every launch of a protocol, and who launched it.

A launch keeps the parameters as the protocol stored them right after it was
launched (its own bookkeeping, the keys starting with "_", is left out).
Launches are kept while the protocol exists; deleting it deletes them.
A database without the table (not migrated yet) only loses the history.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.backend.mapper.protocol_launch_mapper import ProtocolLaunchPostgresqlMapper

logger = logging.getLogger(__name__)

RECORDED_MODES = ("launch", "restart", "continue", "schedule")
HISTORY_LIMIT = 50


def launchParams(params: Any) -> Dict[str, Any]:
    """The parameters worth keeping: the protocol's own, not ScipionWeb's bookkeeping."""
    if not isinstance(params, dict):
        return {}
    return {key: value for key, value in params.items() if not str(key).startswith("_")}


def recordLaunch(mapper, projectId: int, protocolId, userId: Optional[int], mode: str) -> bool:
    """Keep the parameters a protocol has just been launched with. Never fails the launch."""
    if mode not in RECORDED_MODES or not str(protocolId or "").strip().isdigit():
        return False
    try:
        row = mapper.getProjectProtocolByProtocolId(projectId=int(projectId), protocolId=int(protocolId))
        if not row:
            return False
        ProtocolLaunchPostgresqlMapper(mapper.db).insertLaunch(
            projectId, row["id"], row["protocolId"], userId, mode, launchParams(row.get("params")))
        return True
    except Exception:
        logger.warning("The parameters of launch %s of protocol %s (project %s) were not kept",
                       mode, protocolId, projectId, exc_info=True)
        return False


def _userName(row: Dict[str, Any]) -> str:
    name = " ".join(part for part in (row.get("firstName"), row.get("lastName")) if part)
    return name or str(row.get("email") or "")


def listLaunches(mapper, projectId: int, protocolId, limit: int = HISTORY_LIMIT) -> List[Dict[str, Any]]:
    """The launches of a protocol, newest first."""
    try:
        rows = ProtocolLaunchPostgresqlMapper(mapper.db).listLaunches(projectId, protocolId, limit)
    except Exception:
        logger.warning("The launches of protocol %s (project %s) could not be read", protocolId, projectId, exc_info=True)
        return []
    launches = []
    for row in rows:
        launchedAt = row.get("launchedAt")
        launches.append({
            "id": int(row["id"]),
            "mode": str(row.get("mode") or ""),
            "launchedAt": launchedAt.isoformat() if hasattr(launchedAt, "isoformat") else str(launchedAt or ""),
            "user": None if row.get("userId") is None else {"id": int(row["userId"]), "name": _userName(row)},
            "params": launchParams(row.get("params")),
        })
    return launches
