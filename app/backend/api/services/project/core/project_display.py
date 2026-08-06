"""Building the JSON-friendly project summary row (display name, disk
usage, protocol count, thumbnail urls) shown in project listings.
"""
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


def buildProjectThumbnailUrl(projectId: int) -> str:
    return f"/projects/{projectId}/thumbnail"


def buildProjectThumbnailRebuildUrl(projectId: int) -> str:
    return f"/projects/{projectId}/thumbnail/rebuild"


def buildProjectThumbnailItemsUrl(projectId: int) -> str:
    return f"/projects/{projectId}/thumbnail-items"


def getProjectDisplayNameFromPostgresqlPath(storedProjectPath: Any) -> str:
    pathText = str(storedProjectPath or "").strip()
    if not pathText:
        return ""

    return Path(pathText).expanduser().name or pathText


def countProjectProtocolsFromPostgresql(
        mapper,
        projectId: int,
) -> int:
    countProjectProtocols = getattr(mapper, "countProjectProtocols", None)
    if not callable(countProjectProtocols):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PostgreSQL mapper does not expose countProjectProtocols",
        )

    try:
        return int(countProjectProtocols(projectId) or 0)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Failed to count project protocols from PostgreSQL. projectId=%s",
            projectId,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to count project protocols from PostgreSQL: {e}",
        )


def getProjectDiskUsageFromFilesystem(
        storedProjectPath: Any,
        manager,
        getProjectSizeCallback,
) -> str:
    pathText = str(storedProjectPath or "").strip()
    if not pathText:
        return "0.00 GB"

    projectPath = Path(pathText).expanduser()
    if not projectPath.is_absolute():
        projectPath = Path(manager.getProjectPath(str(projectPath)))

    try:
        realProjectPath = projectPath.resolve(strict=True)
    except Exception:
        realProjectPath = projectPath

    try:
        sizeGB = getProjectSizeCallback(str(realProjectPath)) / (1024 ** 3)
    except Exception:
        sizeGB = 0.0

    return f"{sizeGB:.2f} GB"


def buildProjectOutFromPostgresqlRow(
        mapper,
        dbProj: Dict[str, Any],
        currentUser: dict,
        manager,
        getProjectSizeCallback,
        includeDiskUsage: bool = True,
) -> Dict[str, Any]:
    projectId = int(dbProj["id"])
    storedProjectPath = dbProj.get("name")
    displayName = getProjectDisplayNameFromPostgresqlPath(storedProjectPath)

    protocolsCount = countProjectProtocolsFromPostgresql(
        mapper=mapper,
        projectId=projectId,
    )

    currentUserId = currentUser["id"]
    isOwner = dbProj.get("isOwner", dbProj.get("ownerId") == currentUserId)
    isShared = dbProj.get("isShared", False)
    permission = dbProj.get("permission", "owner" if isOwner else "full")
    projectOwnerId = dbProj.get("ownerId")
    updatedAt = dbProj.get("updatedAt")

    thumbnailVersion = "%s:%s:%s:postgresql" % (
        projectId,
        updatedAt or "",
        protocolsCount,
    )

    diskUsage = (
        getProjectDiskUsageFromFilesystem(storedProjectPath, manager, getProjectSizeCallback)
        if includeDiskUsage
        else "0.00 GB"
    )

    return {
        "id": projectId,
        "name": displayName,
        "description": dbProj.get("description", ""),
        "createdAt": dbProj.get("createdAt"),
        "status": dbProj.get("status", "active"),
        "protocolsCount": protocolsCount,
        "diskUsage": diskUsage,
        "isOwner": bool(isOwner),
        "isShared": bool(isShared),
        "permission": permission,
        "projectOwnerId": projectOwnerId,
        "updatedAt": updatedAt,
        "thumbnailUrl": buildProjectThumbnailUrl(projectId),
        "thumbnailRebuildUrl": buildProjectThumbnailRebuildUrl(projectId),
        "thumbnailItemsUrl": buildProjectThumbnailItemsUrl(projectId),
        "thumbnailVersion": thumbnailVersion,
    }
