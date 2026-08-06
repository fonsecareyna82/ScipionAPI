"""Registering a protocol's outputs into PostgreSQL. All of these are thin
wrappers around RuntimeProtocolOutputPersistenceService - callable directly
by anyone that needs them (see protocol_steps_sync.py), no need to go
through ProjectService.
"""
import os
from typing import Any, Dict, List, Optional, Sequence, Union

from fastapi import HTTPException, status

from app.backend.runtime import RuntimeProtocolOutputPersistenceService


def getCurrentProjectPath(currentProject) -> Optional[str]:
    if currentProject is None:
        return None

    for attrName in ("path", "_path"):
        value = getattr(currentProject, attrName, None)
        if value:
            return str(value)

    try:
        value = currentProject.getPath()
    except Exception:
        return None

    return str(value) if value else None


def shouldRegisterProtocolOutputs(protocol: Any) -> bool:
    return RuntimeProtocolOutputPersistenceService().shouldRegisterProtocolOutputs(
        protocol=protocol,
    )


def isPersistableNonSetOutput(outputObj: Any) -> bool:
    return RuntimeProtocolOutputPersistenceService().isPersistableNonSetOutput(
        outputObj=outputObj,
    )


def isScipionSetLikeOutput(outputObj: Any) -> bool:
    return RuntimeProtocolOutputPersistenceService().isScipionSetLikeOutput(
        outputObj=outputObj,
    )


def registerOutput(
        currentProject,
        projectId: int,
        protocol: Any,
        mapper,
        returnReport: bool = False,
        projectPaths: Optional[Sequence[str]] = None,
        allowDetachedSetOutputs: bool = False,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    resolvedProjectPaths = []

    for candidatePath in list(projectPaths or []) + [getCurrentProjectPath(currentProject)]:
        if not candidatePath:
            continue

        normalizedPath = os.path.abspath(os.path.expanduser(str(candidatePath)))

        if normalizedPath not in resolvedProjectPaths:
            resolvedProjectPaths.append(normalizedPath)

    try:
        return RuntimeProtocolOutputPersistenceService().registerOutput(
            projectId=projectId,
            protocol=protocol,
            mapper=mapper,
            returnReport=returnReport,
            projectPaths=resolvedProjectPaths,
            allowDetachedSetOutputs=allowDetachedSetOutputs,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
