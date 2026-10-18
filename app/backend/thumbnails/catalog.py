"""The outputs of a project that can have a thumbnail, read from the database only.

Each output gets a signature from what the database records about it (class,
last update, number of items): a thumbnail stored under a signature stays
valid while the output does not change, and an output that grows (streaming)
gets a new signature, hence a new thumbnail.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.backend.utils.thumbnail_service import scoreOutputClass

# Part of every signature: bump it when the thumbnails are drawn differently.
RENDER_VERSION = "3"


@dataclass(frozen=True)
class ThumbnailOutput:
    protocolId: str
    protocolLabel: str
    protocolStatus: str
    outputName: str
    className: str
    itemsCount: Optional[int]
    score: int
    signature: str


def _jsonDict(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return {}
    return value if isinstance(value, dict) else {}


def _protocolLabel(row: Dict[str, Any], protocolClasses: Dict[str, Any]) -> str:
    params = _jsonDict(row.get("params"))
    className = str(row.get("protocolClassName") or "").strip()
    protocolClass = protocolClasses.get(className)
    try:
        classLabel = str(protocolClass.getClassLabel() or "").strip() if protocolClass is not None else ""
    except Exception:
        classLabel = ""
    for key in ("object.label", "title", "_title", "objLabel", "_objLabel", "runName", "_runName"):
        value = params.get(key)
        if isinstance(value, dict):
            value = value.get("value")
        if value not in (None, ""):
            return classLabel or str(value)
    return classLabel or className or str(row.get("protocolId") or "")


def outputSignature(className: str, summary: Dict[str, Any]) -> str:
    parts = [
        RENDER_VERSION,
        str(className or ""),
        str(summary.get("updatedAt") or ""),
        str(summary.get("itemsCount") if summary.get("itemsCount") is not None else ""),
        str(summary.get("maxItemId") if summary.get("maxItemId") is not None else ""),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def loadProjectThumbnailCatalog(mapper, projectId: int, protocolId: Optional[str] = None) -> List[ThumbnailOutput]:
    """Every output of the project (or of one protocol) that a thumbnail can show, best first."""
    from app.backend.runtime.protocol_output_persistence_service import (
        RuntimeProtocolOutputPersistenceService,
    )
    from app.backend.api.services.scipion_class_hierarchy import ScipionClassHierarchyResolver

    rows = mapper.db.fetchAll(
        'SELECT id, "protocolId", "protocolClassName", status, params FROM protocols WHERE "projectId" = %s',
        (int(projectId),),
    ) or []
    protocolRows = {str(row.get("protocolId")): row for row in rows}
    if protocolId is not None:
        protocolRows = {key: row for key, row in protocolRows.items() if key == str(protocolId)}
    summaries = RuntimeProtocolOutputPersistenceService().loadPersistedOutputSummariesByProtocolId(
        mapper=mapper,
        projectId=int(projectId),
    ) or {}
    try:
        protocolClasses = ScipionClassHierarchyResolver.loadScipionProtocolClasses() or {}
    except Exception:
        protocolClasses = {}

    catalog: List[ThumbnailOutput] = []
    for key, row in protocolRows.items():
        outputs = summaries.get(key) or {}
        if not outputs:
            continue
        label = _protocolLabel(row, protocolClasses)
        status = str(row.get("status") or "")
        for outputName, summary in outputs.items():
            className = str(summary.get("className") or summary.get("rootObjectClassName")
                            or summary.get("itemClassName") or "")
            itemsCount = summary.get("itemsCount")
            score = scoreOutputClass(outputName, className, itemsCount)
            if score <= 0:
                continue
            catalog.append(ThumbnailOutput(
                protocolId=key,
                protocolLabel=label,
                protocolStatus=status,
                outputName=str(outputName),
                className=className,
                itemsCount=itemsCount,
                score=score,
                signature=outputSignature(className, summary),
            ))
    catalog.sort(key=lambda item: (-item.score, -(item.itemsCount or 0), item.protocolId, item.outputName))
    return catalog


_STATUS_SCORES = (
    (("finished", "done", "complete", "success"), 120),
    (("running", "launched", "active", "progress"), 70),
    (("scheduled", "waiting", "queued"), 40),
    (("saved", "new"), 20),
    (("failed", "error", "aborted", "stopped"), -200),
)


def statusScore(status: str) -> int:
    text = (status or "").lower()
    for tokens, score in _STATUS_SCORES:
        if any(token in text for token in tokens):
            return score
    return 10


def selectProjectCardOutputs(catalog: List[ThumbnailOutput], maxProtocols: int,
                             maxOutputsPerProtocol: int) -> List[List[ThumbnailOutput]]:
    """The best protocols of a project for its card, with their best outputs (as the project thumbnail chose)."""
    byProtocol: Dict[str, List[ThumbnailOutput]] = {}
    for item in catalog:
        byProtocol.setdefault(item.protocolId, []).append(item)
    ranked = sorted(
        byProtocol.values(),
        key=lambda items: -(items[0].score + statusScore(items[0].protocolStatus) + min(items[0].itemsCount or 0, 8)),
    )
    chosen = [items for items in ranked
              if items[0].score + statusScore(items[0].protocolStatus) >= 60][:max(1, int(maxProtocols))]
    return [items[:max(1, int(maxOutputsPerProtocol))] for items in chosen]
