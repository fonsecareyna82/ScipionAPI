from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.backend.api.dependencies import getCurrentUser
from app.backend.database import getDb
from app.backend.api.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.backend.api.services.project_service import ProjectService


router = APIRouter(prefix="/projects", tags=["projects"])
service = ProjectService()

@router.post("/", response_model=ProjectOut)
def createProject(projectData: ProjectCreate, db: Session = Depends(getDb), currentUser=Depends(getCurrentUser)):
    return service.createProject(db, projectData, currentUser)


@router.get("/", response_model=List[ProjectOut])
def listProjects(db: Session = Depends(getDb), currentUser=Depends(getCurrentUser)):
    return service.listProjects(db, currentUser)


@router.get("/{projectId}", response_model=ProjectOut)
def getProject(projectId: int, db: Session = Depends(getDb), currentUser=Depends(getCurrentUser)):
    project = service.getProjectById(db, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.put("/{projectId}", response_model=ProjectOut)
def updateProject(projectId: int, projectData: ProjectUpdate, db: Session = Depends(getDb), currentUser=Depends(getCurrentUser)):
    project = service.updateProject(db, projectId, projectData, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.delete("/{projectId}")
def deleteProject(projectId: int, db: Session = Depends(getDb), currentUser=Depends(getCurrentUser)):
    project = service.deleteProject(db, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {"message": "Project deleted successfully"}
