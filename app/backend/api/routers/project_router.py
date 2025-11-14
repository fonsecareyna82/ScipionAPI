from fastapi import APIRouter, Depends, HTTPException, status, Path as PathParam, Query, Request
from typing import List, Any, Union, Optional

from app.backend.api.dependencies import getCurrentUser
from app.backend.database import getMapper
from app.backend.api.schemas.project_schema import ProjectCreate, ProjectOut, ProjectUpdate
from app.backend.api.services.project_service import ProjectService
from app.backend.models.protocol_model import (
    ProtocolRequest,
    ProtocolRenameIn,
    DuplicatePayload,
    DeletePayload,
)
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
    return service.updateProject(mapper, projectId, currentUser, projectData)


@router.delete("/{projectId}", status_code=status.HTTP_200_OK)
def deleteProject(
    projectId: int,
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Delete a project owned by the authenticated user.
    """
    return service.deleteProject(mapper, currentUser, projectId)


@router.get(
    "/{projectId}/protocols",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def loadProtocols(
    projectId: int = PathParam(..., ge=1, title="Numeric project ID"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    protocols = service.getProtocols(mapper, projectId, currentUser)
    if not protocols:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Protocols not found"
        )
    return protocols


@router.get("/{projectId}/protocols/{protocolId}", response_model=Any)
async def loadProtocol(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return service.getProtocolParams(projectId, protocolId)


@router.get("/{projectId}/protclass/{protClassName}", response_model=Any)
async def loadNewProtocol(
    projectId: int,
    protClassName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return service.getNewProtocolParams(projectId, protClassName)


@router.post("/launch", response_model=Any)
async def launchProtocol(request: ProtocolRequest,
                         mapper: PostgresqlFlatMapper = Depends(getMapper)):
    try:
        protocolId = request.getProtocolId()
        protocolClassName = request.getProtocolClassName()
        params = request.getParams()
        service.launchProtocol(mapper, protocolId, protocolClassName, params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save", response_model=Any)
async def saveProtocol(request: ProtocolRequest,
                       mapper: PostgresqlFlatMapper = Depends(getMapper)):
    try:
        protocolId = request.getProtocolId()
        protocolClassName = request.getProtocolClassName()
        params = request.getParams()
        service.saveProtocol(mapper, protocolId, protocolClassName, params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{projectId}/protocols/{protocolId}/rename", response_model=Any, status_code=status.HTTP_200_OK)
def renameProtocol(
    projectId: int,
    protocolId: int,
    payload: ProtocolRenameIn,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        return service.renameProtocol(protocolId, payload.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{projectId}/protocols/duplicate", response_model=Any, status_code=status.HTTP_201_CREATED)
def duplicateProtocol(
    projectId: int,
    payload: DuplicatePayload = None,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        return service.duplicateProtocol(payload.items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{projectId}/protocols/delete", response_model=Any, status_code=status.HTTP_200_OK)
def deleteProtocol(
    projectId: int,
    payload: DeletePayload = None,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        service.deleteProtocol(payload.ids)
        return {"status": "ok", "message": "Protocol deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{projectId}/protocols/{protocolId}/restart-all", response_model=Any, status_code=status.HTTP_200_OK)
def restartProtocolAll(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        errorList = service.restartProtocolAll(protocolId)
        if errorList:
            return {"status": "failed", "details": errorList}
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{projectId}/protocols/{protocolId}/continue-all", response_model=Any, status_code=status.HTTP_200_OK)
def continueProtocolAll(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        service.continueProtocolAll(mapper, projectId, protocolId, currentUser)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{projectId}/protocols/{protocolId}/reset-from", response_model=Any, status_code=status.HTTP_200_OK)
def resetProtocolFrom(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        service.resetProtocolFrom(protocolId)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{projectId}/protocols/stop", response_model=Any, status_code=status.HTTP_200_OK)
def stopProtocol(
    projectId: int,
    payload: DeletePayload = None,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        service.stopProtocol(payload.ids)
        return {"status": "ok", "message": "Protocol stoped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{projectId}/protocols/{protocolId}/fs/start-path", response_model=Any)
async def getProtocolPath(
    projectId: int,
    protocolId: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return service.getProtocolPath(protocolId)


# ======================================================================
#                FS REMOTE: list / preview / download
# ======================================================================

@router.get("/{projectId}/protocols/{protocolId}/fs/list", response_model=Any)
async def listProtocolDir(
    projectId: int,
    protocolId: Union[int, str],
    path: str = Query("", description="Relative path inside the protocol root"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.listProtocolDir(protocolId, path)


@router.get("/{projectId}/protocols/{protocolId}/fs/preview", response_model=None)
async def previewProtocolText(
    projectId: int,
    protocolId: Union[int, str],
    path: str = Query(..., description="Relative file path inside protocol root"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.previewProtocolTextFile(protocolId, path)


@router.get("/{projectId}/protocols/{protocolId}/fs/download", response_model=None)
async def previewProtocolImageFile(
    projectId: int,
    protocolId: Union[int, str],
    path: str = Query(..., description="Relative file path inside protocol root"),
    inline: bool = Query(False, description="If true, send Content-Disposition inline"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.previewProtocolImageFile(protocolId, path, inline)


@router.get("/{projectId}/protocols/{protocolId}/outputpreview/{outputName}", response_model=None)
async def previewOutput(
    projectId: int,
    protocolId: Union[int, str],
    outputName: str,
    request: Request,
    currentUser=Depends(getCurrentUser),
    mapper=Depends(getMapper),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Prefer header; fallback to query param (?cmap=viridis or ?colormap=viridis)
    cmapHeader = (
        request.headers.get("x-scipion-colormap")
        or request.headers.get("x-preview-colormap")
        or request.headers.get("x-colormap")
        or request.headers.get("scipion-colormap")
        or request.headers.get("colormap")
    )
    cmapQuery = request.query_params.get("cmap") or request.query_params.get("colormap")

    return service.outputPreview(
        protocolId=protocolId,
        outputName=outputName,
        requestHeaders=dict(request.headers),
        colormap=cmapHeader or cmapQuery,
    )


# ==============================================================================
#                ANALYZE RESULTS: VOLUMES (Volume / VolumeMask / SetOfVolumes)
# ==============================================================================

@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes", response_model=Any, status_code=status.HTTP_200_OK)
def listOutputVolumes(
    projectId: int,
    protocolId: int,
    outputName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    return service.listOutputVolumesService(projectId, protocolId, outputName)


@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/info",
            response_model=Any, status_code=status.HTTP_200_OK)
def getVolumeInfo(
    projectId: int,
    protocolId: int,
    outputName: str,
    volumeId: Union[int, str],  # <-- aceptar string o int
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    return service.getVolumeInfoService(projectId, protocolId, outputName, volumeId)


@router.get("/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/slice",
            response_model=None)
def renderVolumeSlice(
    projectId: int,
    protocolId: int,
    outputName: str,
    volumeId: Union[int, str],  # <-- aceptar string o int
    index: int = Query(0, ge=0),  # 0-based
    axis: str = Query("z", pattern="^(x|y|z)$"),
    # Aceptar BOTH pero resolvemos a 'cmap' (front ya solo manda cmap)
    cmapParam: Optional[str] = Query(None, alias="cmap"),
    colormapParam: Optional[str] = Query(None, alias="colormap"),
    # Aceptar BOTH pero resolvemos a 'fmt'
    formatParam: Optional[str] = Query(None, alias="format"),
    fmtParam: Optional[str] = Query(None, alias="fmt"),
    normalize: Optional[str] = Query(None),
    scale: float = Query(1.0, gt=0),
    inline: bool = Query(True),
    thumb: Optional[int] = Query(None, ge=32, le=2048),
    fast: bool = Query(False),
    quality: int = Query(75, ge=1, le=100),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    cmap = cmapParam or colormapParam or "viridis"
    fmt = fmtParam or formatParam or "webp"

    return service.renderVolumeSliceService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        volumeId=volumeId,
        sliceIndex=index,
        axis=axis,
        colormap=cmap,
        normalize=normalize,
        scale=scale,
        inline=inline,
        fmt=fmt,
        thumb=thumb,
        fast=fast,
        quality=quality,
    )