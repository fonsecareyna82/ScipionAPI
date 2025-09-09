from fastapi import APIRouter, Depends, HTTPException, status, Path
from typing import List, Any, Dict

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.schemas.protocols import ProtocolOut
from app.backend.database import getMapper
from app.backend.api.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.backend.api.services.project_service import ProjectService
from app.backend.models.protocol_model import ProtocolRequest
from app.backend.mapper.postgresql import PostgresqlFlatMapper

router = APIRouter(prefix="/projects", tags=["projects"])
service = ProjectService()


@router.post("/", response_model=ProjectOut)
def createProject(
    projectData: ProjectCreate,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    return service.createProject(mapper, projectData, currentUser)


@router.get("/", response_model=List[ProjectOut])
def listProjects(
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    return service.listProjects(mapper, currentUser)


@router.get("/{projectId}", response_model=Any)
def getProject(
    projectId: int,  # id in the DB
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.put("/{projectId}", response_model=ProjectOut, status_code=status.HTTP_200_OK)
def updateProject(
    projectId: int,
    projectData: ProjectUpdate,
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Update an existing project owned by the authenticated user.
    """

    # Fetch the project, ensuring ownership
    existing = mapper.getProject(projectId, currentUser["id"])
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    #Collect only the fields that were actually sent
    updateFields = projectData.dict(exclude_unset=True)

    # Apply the updates via the mapper
    mapper.updateProject(
        projectId=projectId,
        ownerId=currentUser["id"],
        name=updateFields.get("name"),
        description=updateFields.get("description"),
        status=updateFields.get("status"),
    )

    # 4) Fetch the fresh copy and return
    updated = mapper.getProject(projectId, currentUser["id"])
    return updated


@router.delete("/{projectId}", status_code=status.HTTP_200_OK)
def deleteProject(
    projectId: int,
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Delete a project owned by the authenticated user.
    """
    deleted = mapper.deleteProject(projectId, currentUser["id"])
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    return {"message": "Project deleted successfully"}


@router.get(
    "/{projectId}/protocols",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def loadProtocols(
    projectId: int = Path(..., ge=1, title="Numeric project ID"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    protocols = service.getProtocols(mapper, projectId, currentUser)
    if not protocols:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Protocols not found"
        )
    return protocols


@router.get("/{projectId}/{protocolId}", response_model=Any)
async def loadProtocol(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    project = service.getProjectById(mapper, projectId, currentUser)
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
