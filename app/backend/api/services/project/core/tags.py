"""Project and protocol tag CRUD against the PostgreSQL mapper. Tags are
pure PostgreSQL-side concepts (no Scipion runtime object involved), so
every function here only needs a mapper and the relevant ids.
"""
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import HTTPException, status

from app.backend.api.services.project.core.protocol_resolution import (
    resolvePostgresqlProtocolDbId,
)


def listProjectTags(
        mapper,
        projectId: int,
) -> List[Dict[str, Any]]:
    listFn = getattr(mapper, "listProjectTags", None)
    if callable(listFn):
        return listFn(projectId=projectId)

    # mapperMethodFallback: keep backward compatibility with older mapper name
    legacyListFn = getattr(mapper, "listProtocolTags", None)
    if callable(legacyListFn):
        return legacyListFn(projectId=projectId)

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Mapper does not implement listProjectTags",
    )


def createProjectTag(
        mapper,
        projectId: int,
        payload,
) -> Dict[str, Any]:
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    tagId = (payload.id or "").strip() if getattr(payload, "id", None) else ""
    if not tagId:
        tagId = str(uuid4())

    tag = {
        "id": tagId,
        "title": title,
        "description": getattr(payload, "description", None),
        "color": getattr(payload, "color", None),
    }

    try:
        return mapper.upsertProtocolTag(projectId=projectId, tag=tag)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create tag: {e}",
        )


def updateProjectTag(
        mapper,
        projectId: int,
        tagId: str,
        payload,
) -> Dict[str, Any]:
    tagId = (tagId or "").strip()
    if not tagId:
        raise HTTPException(status_code=400, detail="tagId is required")

    existing = None
    for t in listProjectTags(mapper=mapper, projectId=projectId):
        if str(t.get("id", "")).strip() == tagId:
            existing = t
            break

    if not existing:
        raise HTTPException(status_code=404, detail="Tag not found")

    nextTitle = getattr(payload, "title", None)
    if nextTitle is None:
        nextTitle = existing.get("title")
    nextTitle = (nextTitle or "").strip()
    if not nextTitle:
        raise HTTPException(status_code=400, detail="title cannot be empty")

    nextDescription = getattr(payload, "description", None)
    if nextDescription is None:
        nextDescription = existing.get("description")

    nextColor = getattr(payload, "color", None)
    if nextColor is None:
        nextColor = existing.get("color")

    tag = {
        "id": tagId,
        "title": nextTitle,
        "description": nextDescription,
        "color": nextColor,
    }

    try:
        return mapper.upsertProtocolTag(projectId=projectId, tag=tag)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update tag: {e}",
        )


def deleteProjectTag(
        mapper,
        projectId: int,
        tagId: str,
) -> bool:
    tagId = (tagId or "").strip()
    if not tagId:
        raise HTTPException(status_code=400, detail="tagId is required")

    # cascadeBehavior: protocol_tag_assignments(tagId) has ON DELETE CASCADE
    try:
        return bool(mapper.deleteProtocolTag(projectId=projectId, tagId=tagId))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete tag: {e}",
        )


def listProtocolTags(
        mapper,
        projectId: int,
        protocolId: int,
) -> Dict[str, Any]:
    protocolDbId = resolvePostgresqlProtocolDbId(
        mapper=mapper,
        projectId=projectId,
        protocolId=protocolId,
    )

    if protocolDbId is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Protocol not found in PostgreSQL: {protocolId}",
        )

    try:
        tagIds = mapper.getProtocolTagIds(
            projectId=projectId,
            protocolDbId=protocolDbId,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list protocol tags: {e}",
        )

    return {
        "protocolId": str(protocolId),
        "protocolDbId": protocolDbId,
        "tagIds": tagIds,
    }


def setProtocolTags(
        mapper,
        projectId: int,
        protocolId: int,
        tagIds: List[str],
) -> Dict[str, Any]:
    protocolDbId = resolvePostgresqlProtocolDbId(
        mapper=mapper,
        projectId=projectId,
        protocolId=protocolId,
    )

    if protocolDbId is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Protocol not found in PostgreSQL: {protocolId}",
        )

    try:
        setByDbId = getattr(mapper, "setProtocolTagIdsByProtocolDbId", None)
        if callable(setByDbId):
            return setByDbId(
                projectId=projectId,
                protocolDbId=protocolDbId,
                tagIds=tagIds or [],
            )

        return mapper.setProtocolTagIds(
            projectId=projectId,
            protocolId=int(protocolId),
            tagIds=tagIds or [],
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set protocol tags: {e}",
        )
