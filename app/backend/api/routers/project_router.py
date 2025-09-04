from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Any

from app.backend.api.dependencies import getCurrentUser
from app.backend.database import getDb
from app.backend.api.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.backend.api.services.project_service import ProjectService
from app.backend.models.protocol_model import ProtocolRequest

router = APIRouter(prefix="/projects", tags=["projects"])
service = ProjectService()

@router.post("/", response_model=ProjectOut)
def createProject(
    projectData: ProjectCreate,
    db: Session = Depends(getDb),
    currentUser=Depends(getCurrentUser)
):
    return service.createProject(db, projectData, currentUser)


@router.get("/", response_model=List[ProjectOut])
def listProjects(
    db: Session = Depends(getDb),
    currentUser=Depends(getCurrentUser)
):
    return service.listProjects(db, currentUser)


@router.get("/{projectId}", response_model=Any)
def getProject(
    projectId: int,  # id in the DB
    db: Session = Depends(getDb),
    currentUser=Depends(getCurrentUser)
):
    project = service.getProjectById(db, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.put("/{projectId}", response_model=ProjectOut)
def updateProject(
    projectId: int,
    projectData: ProjectUpdate,
    db: Session = Depends(getDb),
    currentUser=Depends(getCurrentUser)
):
    project = service.updateProject(db, projectId, projectData, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.delete("/{projectId}")
def deleteProject(
    projectId: int,
    db: Session = Depends(getDb),
    currentUser=Depends(getCurrentUser)
):
    result = service.deleteProject(db, projectId, currentUser)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return result


@router.get("/{projectId}/{protocolId}", response_model=Any)
async def loadProtocol(projectId: int, protocolId: int,
                       db: Session = Depends(getDb),
                       currentUser=Depends(getCurrentUser)):
    project = service.getProjectById(db, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return service.getProtocolParams(project, protocolId)


@router.post("/launch", response_model=Any)
async def launch_protocol(request: ProtocolRequest):
    try:
        protocolId = request.getProtocolId()
        params = request.getParams()
        if not protocolId:
            raise HTTPException(status_code=400, detail="Protocol Id is required")

        return service.launchProtocol(protocolId, params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
