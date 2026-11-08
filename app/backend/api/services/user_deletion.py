"""Deleting an account, with everything it owns.

A user's projects go with them: a project needs its owner. What they did elsewhere stays without them (their
facility sessions, bookings and samples, protocol runs and the audit log keep the rest, their user set to none);
their roles, group memberships, shares, settings and notifications go.

Deleting is refused for oneself, for the last active administrator and while a protocol of theirs runs. The
account stops at once (it cannot sign in, the lists no longer show it); its projects are deleted as any project
(moved to the trash at once, their rows in the background) and its row is removed after them, in the same
background queue. An API stopped meanwhile finishes it at the next start (``resumePendingUserDeletions``).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.api.permissions import hasPermission
from app.backend.mapper.access_mapper import AccessPostgresqlMapper
from app.backend.mapper.user_deletion_mapper import UserDeletionPostgresqlMapper

logger = logging.getLogger(__name__)


def _projectName(path: Any) -> str:
    return str(path or "").rstrip("/").split("/")[-1]


def deletionPreview(mapper, admin: Dict[str, Any], userId: int) -> Dict[str, Any]:
    """What deleting the account takes with it, and what stops it (blockers: none means it can go)."""
    user = mapper.getUserById(int(userId))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    queries = UserDeletionPostgresqlMapper(mapper.db)
    projects = [{"id": int(row["id"]), "name": _projectName(row["name"]), "bytes": row.get("bytes"),
                 "shares": int(row.get("shares") or 0), "running": int(row.get("running") or 0)}
                for row in queries.ownedProjects(userId)]
    blockers: List[str] = []
    if int(userId) == int(admin["id"]):
        blockers.append("You cannot delete your own account.")
    if AccessPostgresqlMapper(mapper.db).listActiveSystemUserIds() == [int(userId)]:
        blockers.append("It is the only active administrator: make another one first.")
    running = [project["name"] for project in projects if project["running"]]
    if running:
        blockers.append("Protocols are running in %s: stop them first." % ", ".join(running))
    if projects and not hasPermission(admin, "projects.manageAll"):
        blockers.append("Its projects go with it: that needs the permission to manage every project.")
    return {"user": {"id": int(user["id"]), "email": user.get("email"), "firstName": user.get("firstName"),
                     "lastName": user.get("lastName")},
            "projects": projects, "facility": queries.facilityTraces(userId), "blockers": blockers,
            "deleting": queries.deletingAt(userId) is not None}


def deleteUser(mapper, admin: Dict[str, Any], userId: int, confirmEmail: str) -> Dict[str, Any]:
    """Delete the account and its projects; confirmEmail must be its address. Answers what went and what could
    not (a project that could not go keeps the account being deleted: deleting again tries the rest)."""
    from app.backend.api.services.project_service import ProjectService

    preview = deletionPreview(mapper, admin, userId)
    if preview["blockers"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=" ".join(preview["blockers"]))
    if str(confirmEmail or "").strip().lower() != str(preview["user"]["email"] or "").strip().lower():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Type the account's address to confirm")
    queries = UserDeletionPostgresqlMapper(mapper.db)
    queries.markDeleting(userId)
    service = ProjectService()
    deleted, failed = [], []
    for project in preview["projects"]:
        try:
            service.deleteProject(mapper, admin, project["id"])
            deleted.append(project)
        except HTTPException as error:
            failed.append(dict(project, detail=str(error.detail)))
        except Exception as error:
            logger.exception("Could not delete project %s of user %s", project["id"], userId)
            failed.append(dict(project, detail=str(error)))
    folder = _projectsFolder(mapper, userId)
    # After the projects' rows, in the same queue (one thread, in order)
    scheduleUserRowDeletion(int(userId), folder)
    return {"user": preview["user"], "deleted": deleted, "failed": failed, "deletingInBackground": True}


def _projectsFolder(mapper, userId: int) -> Optional[str]:
    """The user's own projects folder (to remove once empty), if they have one."""
    try:
        from app.backend.api.services.project_service import ProjectService
        from app.backend.mapper.storage_mapper import StoragePostgresqlMapper

        name = StoragePostgresqlMapper(mapper.db).projectsFolderOf(int(userId))
        return str(Path(ProjectService().manager.PROJECTS) / name) if name else None
    except Exception:
        logger.warning("Could not find the projects folder of user %s", userId, exc_info=True)
        return None


def _deleteUserRow(userId: int, folder: Optional[str] = None) -> None:
    """Remove a user being deleted once their projects are gone, with its own database connection."""
    from app.backend.database import getMapper
    from app.backend.utils.background_delete import deleteInBackground, isLeftoverFolder

    mapper = None
    try:
        mapper = getMapper()
        if UserDeletionPostgresqlMapper(mapper.db).deleteIfNoProjects(int(userId)):
            logger.info("Deleted user %s", userId)
            if folder and isLeftoverFolder(folder):
                deleteInBackground(folder)
        else:
            logger.warning("User %s still owns projects: removed once they are deleted (at the next start)", userId)
    except Exception:
        logger.exception("Could not delete user %s; retried at the next start", userId)
    finally:
        if mapper is not None:
            try:
                mapper.db.close()
            except Exception:
                pass


def scheduleUserRowDeletion(userId: int, folder: Optional[str] = None) -> None:
    from app.backend.utils.background_delete import _executor

    _executor.submit(_deleteUserRow, int(userId), folder)


def resumePendingUserDeletions(mapper) -> int:
    """Finish the account deletions an earlier run left half done (after the projects', at start-up)."""
    try:
        userIds = UserDeletionPostgresqlMapper(mapper.db).listDeletingUserIds()
    except Exception:
        logger.exception("Could not list the accounts being deleted")
        return 0
    for userId in userIds:
        scheduleUserRowDeletion(userId)
    return len(userIds)
