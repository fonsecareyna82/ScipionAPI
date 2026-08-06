"""Creating, renaming, and deleting projects on the managed filesystem +
PostgreSQL. `manager` (a pyworkflow Manager) is always taken explicitly.
"""
import logging
import os
from typing import Any, Optional

from fastapi import HTTPException, status

from app.backend.api.services.project.core.project_display import (
    buildProjectOutFromPostgresqlRow,
    getProjectDisplayNameFromPostgresqlPath,
)
from app.backend.api.services.project.core.project_path import (
    isLinkedProjectPath,
    isManagedProjectPath,
    normalizeProjectPath,
    removeCreatedProjectPath,
    sanitizeProjectName,
)
from app.backend.runtime.project_lifecycle_service import RuntimeProjectLifecycleService

logger = logging.getLogger(__name__)


def createProject(
        mapper,
        projectData: Any,
        currentUser,
        manager,
        getProjectSizeCallback,
) -> dict:
    sanitizedName = sanitizeProjectName(projectData.name)
    description = projectData.description or ""
    statusValue = projectData.status or "active"

    projectPath = normalizeProjectPath(
        manager.getProjectPath(sanitizedName), manager,
    )

    existingProjects = mapper.listProjects(
        ownerId=currentUser["id"]
    ) or []

    existingNames = {
        getProjectDisplayNameFromPostgresqlPath(project.get("name"))
        for project in existingProjects
        if project.get("name")
    }

    existingPaths = {
        normalizeProjectPath(project.get("name"), manager)
        for project in existingProjects
        if project.get("name")
    }

    if sanitizedName in existingNames or projectPath in existingPaths:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                    "A project with this name already exists for the current user "
                    "(sanitized name: '%s')" % sanitizedName
            ),
        )

    if os.path.lexists(projectPath):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                    "A project with this name already exists in the file system "
                    "(sanitized name: '%s')" % sanitizedName
            ),
        )

    project = None
    dbProjectId = None
    createAttempted = False
    projectMapperClosed = False

    try:
        createAttempted = True

        project = manager.createProject(sanitizedName)

        projectDbPath = project.getDbPath()

        closeMapper = getattr(project, "closeMapper", None)

        if not callable(closeMapper):
            raise RuntimeError(
                "Created Scipion project does not expose closeMapper()"
            )

        closeMapper()
        projectMapperClosed = True

        lifecycleService = RuntimeProjectLifecycleService()

        lifecycleService.removeLegacyProjectDatabase(
            projectPath=projectPath,
            projectDbPath=projectDbPath,
        )

        dbProjectId = mapper.insertProject(
            ownerId=currentUser["id"],
            name=projectPath,
            description=description,
            status=statusValue,
        )

        dbProject = mapper.getProject(
            projectId=dbProjectId,
            userId=currentUser["id"],
        )

        if not dbProject:
            raise RuntimeError(
                "Project was inserted but could not be read from PostgreSQL"
            )

        return buildProjectOutFromPostgresqlRow(
            mapper,
            dbProject,
            currentUser,
            manager,
            getProjectSizeCallback,
            includeDiskUsage=False,
        )

    except Exception as error:
        rollbackErrors = []

        if dbProjectId is not None:
            try:
                mapper.deleteProject(dbProjectId, currentUser["id"])
            except Exception as rollbackError:
                rollbackErrors.append(
                    "PostgreSQL rollback failed: %s" % rollbackError
                )

        if project is not None and not projectMapperClosed:
            try:
                project.closeMapper()
            except Exception:
                logger.debug(
                    "Could not close project mapper during creation rollback. path=%s",
                    projectPath,
                    exc_info=True,
                )

        if createAttempted:
            try:
                removeCreatedProjectPath(projectPath, manager)
            except Exception as rollbackError:
                rollbackErrors.append(
                    "Filesystem rollback failed: %s" % rollbackError
                )

        logger.exception(
            "Failed to create project. name=%s path=%s rollbackErrors=%s",
            sanitizedName,
            projectPath,
            rollbackErrors,
        )

        detail = "Failed to create project: %s" % error

        if rollbackErrors:
            detail += ". " + "; ".join(rollbackErrors)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )


def updateProject(
        mapper,
        projectId: int,
        currentUser: dict,
        projectData: Any,
        manager,
):
    dbProj = mapper.getProject(projectId=projectId, userId=currentUser["id"])
    if not dbProj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    currentPath = normalizeProjectPath(dbProj["name"], manager)

    if not os.path.lexists(currentPath):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project path not found on disk",
        )

    if not isManagedProjectPath(currentPath, manager):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Renaming external imported projects is not supported",
        )

    newName = sanitizeProjectName(projectData.name)
    newPath = normalizeProjectPath(manager.getProjectPath(newName), manager)

    if currentPath != newPath and os.path.lexists(newPath):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A project with this name already exists: '{newName}'",
        )

    try:
        if isLinkedProjectPath(currentPath, manager):
            os.rename(currentPath, newPath)
        else:
            manager.renameProject(currentPath, newName)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rename project: {e}",
        )

    description = projectData.description
    if description is None:
        description = dbProj.get("description")

    return mapper.updateProject(
        projectId,
        currentUser["id"],
        newPath,
        description,
    )


def deleteProject(
        mapper,
        currentUser,
        projectId: int,
        manager,
) -> Optional[dict]:
    dbProj = mapper.getProject(projectId=projectId, userId=currentUser["id"])
    if not dbProj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    projectPath = normalizeProjectPath(dbProj["name"], manager)
    isManagedEntry = isManagedProjectPath(projectPath, manager)
    isLinkedEntry = isLinkedProjectPath(projectPath, manager)

    deleted = mapper.deleteProject(projectId, currentUser["id"])
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    if isLinkedEntry:
        try:
            if os.path.lexists(projectPath):
                os.unlink(projectPath)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Project was unregistered but the symbolic link could not be removed: {e}",
            )

        return {"message": "Linked project unregistered successfully"}

    if not isManagedEntry:
        return {"message": "Project unregistered successfully"}

    if not os.path.exists(projectPath):
        return {"message": "Project deleted successfully"}

    try:
        cwd = manager.PROJECTS
        manager.deleteProject(projectPath)
        os.chdir(cwd)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Project was unregistered but the managed project folder could not be removed: {e}",
        )

    return {"message": "Project deleted successfully"}
