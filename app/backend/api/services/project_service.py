# app/backend/api/services/project_service.py

import os
from pathlib import Path
from typing import List, Union
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.backend.models.project import Project
from app.backend.api.schemas.project import ProjectOut

# Define the root folder where all Scipion projects are stored
PROJECTS_ROOT = Path("/home/ScipionUserdata/projects")


class ProjectService:
    """Service class to manage projects."""

    @staticmethod
    def getProjectPath(projectName: str) -> Path:
        """Return the filesystem path of a project."""
        return PROJECTS_ROOT / projectName

    @staticmethod
    def createProject(db: Session, projectData, currentUser) -> ProjectOut:
        """Create a new project for the current user, ensuring unique name."""
        # Check if a project with the same name already exists
        existing = db.query(Project).filter(Project.name == projectData.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Project with name '{projectData.name}' already exists."
            )

        # Create the project in the database
        newProject = Project(
            name=projectData.name,
            description=projectData.description or "",
            ownerId=currentUser.id,
            status="active"
        )
        db.add(newProject)
        db.commit()
        db.refresh(newProject)

        # Create project folder on disk
        projPath = ProjectService.getProjectPath(newProject.name)
        os.makedirs(projPath, exist_ok=True)

        return ProjectOut(
            id=newProject.id,
            name=newProject.name,
            description=newProject.description,
            status=newProject.status,
            createdAt=newProject.createdAt,
            updatedAt=newProject.updatedAt,
        )

    @staticmethod
    def listProjects(db: Session, currentUser) -> List[ProjectOut]:
        """List all projects of the current user with basic info."""
        projects = db.query(Project).filter(Project.ownerId == currentUser.id).all()
        result = []
        for project in projects:
            projPath = ProjectService.getProjectPath(project.name)
            # diskUsage and protocolsCount can be calculated later
            result.append(ProjectOut(
                id=project.id,
                name=project.name,
                description=project.description,
                status=project.status,
                createdAt=project.createdAt,
                updatedAt=project.updatedAt,
            ))
        return result

    @staticmethod
    def getProjectById(db: Session, projectId: int, currentUser) -> Union[ProjectOut, None]:
        """Retrieve a project by ID only if it belongs to the current user."""
        project = db.query(Project).filter(
            Project.id == projectId, Project.ownerId == currentUser.id
        ).first()
        if not project:
            return None
        return ProjectOut(
            id=project.id,
            name=project.name,
            description=project.description,
            status=project.status,
            createdAt=project.createdAt,
            updatedAt=project.updatedAt,
        )

    @staticmethod
    def updateProject(db: Session, projectId: int, projectData, currentUser) -> Union[ProjectOut, None]:
        """Update project name and description for the current user."""
        project = db.query(Project).filter(
            Project.id == projectId, Project.ownerId == currentUser.id
        ).first()
        if not project:
            return None

        # Check if the new name conflicts with another project
        if project.name != projectData.name:
            existing = db.query(Project).filter(Project.name == projectData.name).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Project with name '{projectData.name}' already exists."
                )
            # Rename folder on disk
            oldPath = ProjectService.getProjectPath(project.name)
            newPath = ProjectService.getProjectPath(projectData.name)
            if oldPath.exists():
                os.rename(oldPath, newPath)

        project.name = projectData.name
        project.description = projectData.description or project.description
        db.commit()
        db.refresh(project)

        return ProjectOut(
            id=project.id,
            name=project.name,
            description=project.description,
            status=project.status,
            createdAt=project.createdAt,
            updatedAt=project.updatedAt,
        )

    @staticmethod
    def deleteProject(db: Session, projectId: int, currentUser) -> dict:
        """Delete a project and its folder from disk if it belongs to the current user."""
        project = db.query(Project).filter(
            Project.id == projectId, Project.ownerId == currentUser.id
        ).first()
        if not project:
            return None

        # Remove project folder from disk
        projPath = ProjectService.getProjectPath(project.name)
        if projPath.exists():
            for root, dirs, files in os.walk(projPath, topdown=False):
                for f in files:
                    os.remove(os.path.join(root, f))
                for d in dirs:
                    os.rmdir(os.path.join(root, d))
            os.rmdir(projPath)

        db.delete(project)
        db.commit()

        return {"message": "Project deleted successfully"}
