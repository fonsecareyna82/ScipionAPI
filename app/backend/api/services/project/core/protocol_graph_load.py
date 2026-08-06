"""Loading all PostgreSQL-backed data needed to build the project protocol
graph (rows, dependency adjacency, tags, persisted outputs, step summaries).
Read-only, no Scipion runtime involved.
"""
import logging
from typing import Any, Dict, List

from app.backend.runtime import RuntimeProtocolOutputPersistenceService

logger = logging.getLogger(__name__)


def loadProjectGraphDataFromPostgresql(
        mapper,
        projectId: int,
        loadPersistedOutputsByProtocolIdCallback=None,
) -> Dict[str, Any]:
    """
    Load all PostgreSQL-backed data needed to build the project protocol graph.

    This does not touch Scipion runtime. It only reads PostgreSQL protocol
    rows, dependencies, tags and persisted output summaries.
    """
    tags: Dict[str, List[str]] = {}
    dependencyMap: Dict[str, Dict[str, List[str]]] = {}
    protocolRows: List[Dict[str, Any]] = []
    persistedOutputsByProtocolId: Dict[str, Dict[str, Dict[str, Any]]] = {}
    protocolStepSummaryByProtocolId: Dict[str, Dict[str, Any]] = {}
    inputRefsByProtocolId: Dict[str, List[Dict[str, Any]]] = {}

    if mapper is None:
        return {
            "tags": tags,
            "dependencyMap": dependencyMap,
            "protocolRows": protocolRows,
            "persistedOutputsByProtocolId": persistedOutputsByProtocolId,
            "protocolStepSummaryByProtocolId": protocolStepSummaryByProtocolId,
            "inputRefsByProtocolId": inputRefsByProtocolId,
        }

    try:
        tags = mapper.getProjectProtocolTagIdsByProtocolId(projectId) or {}
    except Exception:
        logger.exception(
            "Failed to load protocol tags from PostgreSQL for project %s",
            projectId,
        )
        tags = {}

    try:
        dependencyMap = mapper.getProjectProtocolAdjacencyMap(projectId) or {}
    except Exception:
        logger.exception(
            "Failed to load protocol dependencies from PostgreSQL for project %s",
            projectId,
        )
        dependencyMap = {}

    try:
        inputRefs = mapper.listProtocolInputRefs(
            projectId
        ) or []

        for inputRef in inputRefs:
            protocolId = str(
                inputRef.get("protocolId") or ""
            ).strip()

            if not protocolId:
                continue

            inputRefsByProtocolId.setdefault(
                protocolId,
                [],
            ).append(dict(inputRef))

    except Exception:
        logger.exception(
            "Failed to load protocol input refs from PostgreSQL for project %s",
            projectId,
        )
        inputRefsByProtocolId = {}

    try:
        getStepSummary = getattr(
            mapper,
            "getProjectProtocolStepSummaryByProtocolId",
            None,
        )
        if callable(getStepSummary):
            protocolStepSummaryByProtocolId = getStepSummary(projectId) or {}
    except Exception:
        logger.exception(
            "Failed to load protocol step summaries from PostgreSQL for project %s",
            projectId,
        )
        protocolStepSummaryByProtocolId = {}

    try:
        protocolRows = mapper.getProtocols(projectId) or []
    except Exception:
        logger.exception(
            "Failed to load protocol rows from PostgreSQL for project %s",
            projectId,
        )
        protocolRows = []

    loadPersistedOutputs = (
        loadPersistedOutputsByProtocolIdCallback
        or (lambda m, pid: RuntimeProtocolOutputPersistenceService().loadPersistedOutputsByProtocolId(
            mapper=m,
            projectId=pid,
        ))
    )

    try:
        persistedOutputsByProtocolId = loadPersistedOutputs(mapper, projectId) or {}
    except Exception:
        logger.exception(
            "Failed to load persisted Scipion outputs for graph. projectId=%s",
            projectId,
        )
        persistedOutputsByProtocolId = {}

    return {
        "tags": tags,
        "dependencyMap": dependencyMap,
        "protocolRows": protocolRows,
        "persistedOutputsByProtocolId": persistedOutputsByProtocolId,
        "protocolStepSummaryByProtocolId": protocolStepSummaryByProtocolId,
        "inputRefsByProtocolId": inputRefsByProtocolId,
    }
