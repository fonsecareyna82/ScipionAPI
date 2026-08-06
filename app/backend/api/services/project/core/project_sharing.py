"""Sharing a project with other users, listing/revoking shares. Only the
project owner may call these; PostgreSQL is the sole source of truth.
"""
from typing import List

from fastapi import HTTPException, status


def shareProjectWithUser(
        mapper,
        projectId: int,
        currentUser: dict,
        targetUserIds: list,
        permission: str = "full",
) -> dict:
    """Share a project owned by currentUser with another user.

    Only the project owner is allowed to call this method.
    """
    # Ensure project exists and is owned by currentUser
    dbProj = mapper.getProject(projectId=projectId, userId=currentUser["id"])
    if not dbProj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or you are not the owner",
        )

    if targetUserIds == currentUser["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot share a project with yourself",
        )

    for userId in targetUserIds:
        shareRow = mapper.shareProjectWithUser(
            projectId=projectId,
            targetUserId=int(userId),
            permission=permission or "full",
        )

    return {
        "id": shareRow["id"],
        "projectId": shareRow["projectId"],
        "userId": shareRow["userId"],
        "permission": shareRow["permission"],
        "createdAt": shareRow.get("createdAt"),
        "updatedAt": shareRow.get("updatedAt"),
    }


def listProjectShares(
        mapper,
        projectId: int,
        currentUser: dict,
) -> List[dict]:
    """List users that have access to a project.

    Only the project owner is allowed to call this method.
    """
    dbProj = mapper.getProject(projectId=projectId, userId=currentUser["id"])
    if not dbProj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or you are not the owner",
        )

    return mapper.listProjectShares(projectId)


def revokeProjectShareForUser(
        mapper,
        projectId: int,
        targetUserId: int,
        currentUser: dict,
) -> dict:
    """Revoke project access for targetUserId.

    Only the project owner is allowed to perform this action.
    """
    # Ensure currentUser has access and get full project row
    dbProj = mapper.getProject(projectId=projectId, userId=currentUser["id"])
    if not dbProj:
        raise HTTPException(status_code=404, detail="Project not found")

    # Ensure current user is the owner
    if int(dbProj["ownerId"]) != int(currentUser["id"]):
        raise HTTPException(status_code=403, detail="Only project owner can revoke shares")

    # Prevent removing owner from a project
    if int(targetUserId) == int(currentUser["id"]):
        raise HTTPException(status_code=400, detail="Owner cannot be removed from the project")

    deleted = mapper.revokeProjectShare(projectId=projectId, userId=targetUserId)
    if not deleted:
        raise HTTPException(status_code=404, detail="Share entry not found")

    return {"success": True}
