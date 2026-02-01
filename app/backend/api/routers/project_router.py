import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Path as PathParam,
    Query,
    Request,
)
from typing import List, Any, Union, Optional, Literal, Dict
from fastapi.responses import JSONResponse

from pydantic import BaseModel

from app.backend.api.dependencies import getCurrentUser
from app.backend.database import getMapper
from app.backend.api.schemas.project_schema import (ProjectCreate, ProjectOut, ProjectUpdate, ProjectShareCreate,
                                                    ApplyWorkflowToProjectRequest, TiltSeriesNewSetRequest)
from app.backend.api.services.project_service import ProjectService
from app.backend.models.data_model import AnalyzeViewerResolveDecisionOut, AnalyzeViewerResolveContextIn, \
    RemoteListResultModel
from app.backend.models.protocol_model import (
    ProtocolRequest,
    ProtocolRenameIn,
    DuplicatePayload,
    DeletePayload,
)
from app.backend.mapper.postgresql import PostgresqlFlatMapper
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


def getProjectService() -> ProjectService:
    """Return a fresh ProjectService per request to avoid shared state."""
    return ProjectService()

# ======================================================================
#                           PROJECT WORKFLOWS
# ======================================================================

@router.get(
    "/workflows",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listProjectWorkflows(
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Return the list of predefined workflows available for the current user.
    """
    try:
        workflows = service.listProjectWorkflows()
        return workflows or []
    except Exception as e:
        logger.exception("Error in listProjectWorkflows: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load workflows: {e}",
        )

@router.post(
    "/{projectId}/workflows/load",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def applyWorkflowToProject(
    projectId: int,
    payload: ApplyWorkflowToProjectRequest,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Apply a predefined workflow to an existing project.
    """
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=True,
        checkPid=False,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        result = service.applyWorkflowToProject(
            mapper=mapper,
            projectId=projectId,
            workflowId=payload.workflowId,
            currentUser=currentUser,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in applyWorkflowToProject: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to apply workflow to project {projectId}: {e}",
        )


# ======================================================================
#                            PROJECTS CRUD
# ======================================================================
@router.get("/", response_model=List[ProjectOut])
def listProjects(
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    return service.listProjects(mapper, currentUser)


@router.post("/", response_model=ProjectOut)
def createProject(
    projectData: ProjectCreate,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    return service.createProject(mapper, projectData, currentUser)


@router.get("/{projectId}", response_model=Any)
def getProject(
    projectId: int,  # id in the DB
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser, refresh=True, checkPid=True)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.put("/{projectId}", response_model=ProjectOut, status_code=status.HTTP_200_OK)
def updateProject(
    projectId: int,
    projectData: ProjectUpdate,
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    return service.updateProject(mapper, projectId, currentUser, projectData)


@router.delete("/{projectId}", status_code=status.HTTP_200_OK)
def deleteProject(
    projectId: int,
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Delete a project owned by the authenticated user.
    """
    return service.deleteProject(mapper, currentUser, projectId)


# ======================================================================
#                            PROJECT SHARING
# ======================================================================

@router.post("/{projectId}/share", status_code=status.HTTP_201_CREATED)
def shareProject(
    projectId: int,
    payload: ProjectShareCreate,
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    projectService: ProjectService = Depends(getProjectService),
    currentUser: dict = Depends(getCurrentUser),
):
    """
    Share a project with another users.
    """
    return projectService.shareProjectWithUser(
        mapper=mapper,
        projectId=projectId,
        currentUser=currentUser,
        targetUserIds=payload.userIds,
        permission=payload.permission,
    )

@router.delete(
    "/{projectId}/share/{targetUserId}",
    status_code=status.HTTP_200_OK,
)
def revokeProjectShare(
    projectId: int,
    targetUserId: int,
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    projectService: ProjectService = Depends(getProjectService),
    currentUser: dict = Depends(getCurrentUser),
) -> Dict[str, bool]:
    """
    Revoke sharing of a project for a specific user.

    Only the project owner is allowed to revoke access.
    """
    projectService.revokeProjectShareForUser(
        mapper=mapper,
        projectId=projectId,
        currentUser=currentUser,
        targetUserId=targetUserId,
    )
    return {"success": True}


@router.get("/{projectId}/shares")
def listProjectShares(
    projectId: int,
        mapper: PostgresqlFlatMapper = Depends(getMapper),
        projectService: ProjectService = Depends(getProjectService),
        currentUser: dict = Depends(getCurrentUser),
):
    """
    Return the list of users the project is shared with.
    """
    return projectService.listProjectShares(
        mapper=mapper,
        projectId=projectId,
        currentUser=currentUser,
    )

# ======================================================================
#                    PROTOCOLS: LOAD / PARAMS / GRAPH
# ======================================================================

@router.get(
    "/{projectId}/protocols",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def loadProtocols(
    projectId: int = PathParam(..., ge=1, title="Numeric project ID"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser, refresh=True, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    protocols = service.getProtocols(mapper, projectId, currentUser)
    if not protocols:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Protocols not found",
        )
    return protocols


@router.get("/{projectId}/protocols/{protocolId}", response_model=Any)
async def loadProtocol(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
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
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return service.getNewProtocolParams(projectId, protClassName)


# ======================================================================
#                        PROTOCOL SAVE / LAUNCH
# ======================================================================

def _normalizeErrors(detail: Any) -> List[str]:
    if detail is None:
        return ["Unknown error"]
    if isinstance(detail, list):
        return [str(item) for item in detail]
    return [str(detail)]


@router.post("/{projectId}/launch", response_model=Any)
async def launchProtocol(
    projectId: int,
    request: ProtocolRequest,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Launch a protocol in a given project.
    """
    try:
        project = service.getProjectById(mapper, projectId, currentUser)
        if not project:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"status": 0,
                         "errors": ["Project not found"],
                         "workflow": []},
            )

        protocolId = request.getProtocolId()
        protocolClassName = request.getProtocolClassName()
        params = request.getParams()
        executeMode = request.getMode()
        service.launchProtocol(mapper, protocolId, protocolClassName, params, executeMode)

        return {"status": 0,
                "errors": [],
                "workflow": []}

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"status": 0,
                     "errors": _normalizeErrors(e.detail),
                     "workflow": []},
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": 0,
                     "errors": [str(e)],
                     "workflow": []},
        )


@router.post("/{projectId}/save", response_model=Any)
async def saveProtocol(
    projectId: int,
    request: ProtocolRequest,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Save protocol parameters in a given project.
    """
    try:
        project = service.getProjectById(mapper, projectId, currentUser)
        if not project:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"status": 1,
                         "errors": ["Project not found"],
                         "workflow": []},
            )

        protocolId = request.getProtocolId()
        protocolClassName = request.getProtocolClassName()
        params = request.getParams()

        protocol, errors = service.saveProtocol(mapper, protocolId, protocolClassName, params)
        errors = errors or []

        return {"status": 0 if not errors else 1,
                "errors": [str(err) for err in errors],
                "workflow": []}

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"status": 1,
                     "errors": _normalizeErrors(e.detail),
                     "workflow": []},
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": 1,
                     "errors": [str(e)],
                     "workflow": []},
        )


# ======================================================================
#                   PROTOCOL OPERATIONS (RENAME / COPY / ETC.)
# ======================================================================

@router.put("/{projectId}/protocols/{protocolId}/rename", response_model=Any, status_code=status.HTTP_200_OK)
def renameProtocol(
    projectId: int,
    protocolId: int,
    payload: ProtocolRenameIn,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"status": 1,
                     "errors": ["Project not found"],
                     "workflow": []},
        )

    try:
        # Basic payload validation for semantic HTTP
        newName = getattr(payload, "name", None)
        if not newName or not str(newName).strip():
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"status": 1,
                         "errors": ["Missing name"],
                         "workflow": []},
            )

        service.renameProtocol(protocolId, str(newName).strip())
        return {"status": 0,
                "errors": [],
                "workflow": []}

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"status": 1,
                     "errors": _normalizeErrors(e.detail),
                     "workflow": []},
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": 1,
                     "errors": [str(e)],
                     "workflow": []},
        )


@router.post("/{projectId}/protocols/duplicate", response_model=Any, status_code=status.HTTP_201_CREATED)
def duplicateProtocol(
    projectId: int,
    payload: DuplicatePayload = None,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"status": 1,
                     "errors": ["Project not found"],
                     "workflow": []},
        )

    try:
        items = getattr(payload, "items", None) if payload is not None else None
        if not items:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"status": 1,
                         "errors": ["Missing items"],
                         "workflow": []},
            )

        service.duplicateProtocol(items)
        # Keep 201 on success, but still return unified schema
        return {"status": 0,
                "errors": [],
                "workflow": []}

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"status": 1,
                     "errors": _normalizeErrors(e.detail),
                     "workflow": []},
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": 1,
                     "errors": [str(e)],
                     "workflow": []},
        )

@router.post("/{projectId}/protocols/delete", response_model=Any, status_code=status.HTTP_200_OK)
def deleteProtocol(
    projectId: int,
    payload: DeletePayload = None,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    try:
        project = service.getProjectById(mapper, projectId, currentUser)
        if not project:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"status": 1,
                         "errors": ["Project not found"],
                         "workflow": []},
            )

        protocolIds = getattr(payload, "protocolIds", None) if payload is not None else None
        if not protocolIds:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"status": 1,
                         "errors": ["Missing protocolIds"],
                         "workflow": []},
            )

        service.deleteProtocol(protocolIds)

        return {"status": 0,
                "errors": [],
                "workflow": []}

    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": 1,
                     "errors": _normalizeErrors(str(e)),
                     "workflow": []},
        )


@router.post(
    "/{projectId}/protocols/{protocolId}/restart-all",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def restartProtocolAll(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"status": 1,
                     "errors": ["Project not found"],
                     "workflow": []},
        )

    try:
        errorList = service.restartProtocolAll(protocolId)
        errors = [str(e) for e in (errorList or [])]

        if errors:
            return {"status": 1,
                    "errors": errors,
                    "workflow": []}

        return {"status": 0,
                "errors": [],
                "workflow": []}

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"status": 1,
                     "errors": _normalizeErrors(e.detail),
                     "workflow": []},
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": 1,
                     "errors": [str(e)],
                     "workflow": []},
        )


@router.post(
    "/{projectId}/protocols/{protocolId}/continue-all",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def continueProtocolAll(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"status": 1, "errors": ["Project not found"], "workflow": []},
        )

    try:
        service.continueProtocolAll(mapper, projectId, protocolId, currentUser)
        return {"status": 0, "errors": [], "workflow": []}

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"status": 1, "errors": _normalizeErrors(e.detail), "workflow": []},
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": 1, "errors": [str(e)], "workflow": []},
        )


@router.post(
    "/{projectId}/protocols/{protocolId}/reset-from",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def resetProtocolFrom(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"status": 1, "errors": ["Project not found"], "workflow": []},
        )

    try:
        service.resetProtocolFrom(protocolId)
        return {"status": 0, "errors": [], "workflow": []}

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"status": 1, "errors": _normalizeErrors(e.detail), "workflow": []},
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": 1, "errors": [str(e)], "workflow": []},
        )


@router.post("/{projectId}/protocols/stop", response_model=Any, status_code=status.HTTP_200_OK)
def stopProtocol(
    projectId: int,
    payload: DeletePayload = None,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"status": 1,
                     "errors": ["Project not found"],
                     "workflow": []},
        )

    try:
        protocolIds = getattr(payload, "protocolIds", None) if payload is not None else None
        if not protocolIds:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"status": 1,
                         "errors": ["Missing protocolIds"],
                         "workflow": []},
            )

        service.stopProtocol(protocolIds)
        return {"status": 0,
                "errors": [],
                "workflow": []}

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"status": 1,
                     "errors": _normalizeErrors(e.detail),
                     "workflow": []},
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": 1,
                     "errors": [str(e)],
                     "workflow": []},
        )


# ======================================================================
#                FS REMOTE: list / preview / download
# ======================================================================

@router.get("/{projectId}/protocols/{protocolId}/fs/start-path", response_model=Any)
async def getProtocolPath(
    projectId: int,
    protocolId: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return service.getProtocolPath(protocolId)


@router.get("/{projectId}/protocols/{protocolId}/fs/list", response_model=RemoteListResultModel)
async def listProtocolDir(
    projectId: int,
    protocolId: Union[int, str],
    path: str = Query(
        "",
        description=(
            "Path relative to the browser root (rootAbs). "
            "Empty string lists root. Absolute paths are accepted only for legacy clients "
            "and must be under rootAbs."
        ),
    ),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
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
    service: ProjectService = Depends(getProjectService),
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
    service: ProjectService = Depends(getProjectService),
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
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

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
#                ANALYZE RESULTS: Resolve viewer
# ==============================================================================

from fastapi import Body

@router.post(
    "/{projectId}/protocols/{protocolId}/viewer/resolve",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def resolveAnalyzeViewer(
    projectId: int,
    protocolId: int,
    payload: Dict[str, Any] = Body(...),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    # resolveAnalyzeViewer
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    ctx = payload.get("ctx") if isinstance(payload, dict) else None
    if isinstance(ctx, dict):
        payload = ctx  # unwrapCtx

    try:
        decision = service.resolveAnalyzeViewerDecision(
            projectId=projectId,
            protocolId=protocolId,
            ctx=payload,

        )
        return decision or {"handled": False}
    except Exception as e:
        logger.exception("Error in resolveAnalyzeViewer: %s", e)
        return {"handled": False, "message": str(e)}


# ==============================================================================
#                ANALYZE RESULTS: VOLUMES (Volume / VolumeMask / SetOfVolumes)
# ==============================================================================

@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listOutputVolumes(
    projectId: int,
    protocolId: int,
    outputName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    items = service.listOutputVolumesService(projectId, protocolId, outputName)
    from fastapi.responses import JSONResponse

    resp = JSONResponse(items)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["X-Debug-VolumeCount"] = str(len(items or []))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/info",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getVolumeInfo(
    projectId: int,
    protocolId: int,
    outputName: str,
    volumeId: Union[int, str],
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    info = service.getVolumeInfoService(projectId, protocolId, outputName, volumeId)
    from fastapi.responses import JSONResponse

    resp = JSONResponse(info)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/histogram",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getVolumeHistogram(
    projectId: int,
    protocolId: int,
    outputName: str,
    volumeId: Union[int, str],
    bins: int = Query(
        128,
        ge=4,
        le=8192,
        description="Number of histogram bins",
    ),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Return intensity histogram for one volume.
    """
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    hist = service.getVolumeHistogramService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        volumeId=volumeId,
        bins=bins,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(hist or {"binEdges": [], "counts": []})
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/slice",
    response_model=None,
)
def renderVolumeSlice(
    projectId: int,
    protocolId: int,
    outputName: str,
    volumeId: Union[int, str],
    index: int = Query(0, ge=0),
    axis: str = Query("z", pattern="^(x|y|z)$"),
    cmapParam: Optional[str] = Query(None, alias="cmap"),
    colormapParam: Optional[str] = Query(None, alias="colormap"),
    formatParam: Optional[str] = Query(None, alias="format"),
    fmtParam: Optional[str] = Query(None, alias="fmt"),
    normalize: Optional[str] = Query(None),
    scale: float = Query(1.0, gt=0),
    inline: bool = Query(True),
    thumb: Optional[int] = Query(None, ge=32, le=2048),
    fast: bool = Query(True),
    quality: int = Query(75, ge=1, le=100),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    cmap = cmapParam or colormapParam or "viridis"
    fmt = fmtParam or formatParam or "webp"

    resp = service.renderVolumeSliceService(
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
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/data3d",
    summary="Get downsampled 3D volume data for Plotly preview",
)
def getVolumeData3d(
    projectId: int,
    protocolId: int,
    outputName: str,
    volumeId: Union[int, str],
    maxDim: int = Query(160, ge=32, le=512, alias="maxDim"),
    method: Literal["binning", "stride", "none"] = Query("binning"),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    currentUser: Dict[str, Any] = Depends(getCurrentUser),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.getVolumeData3dService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        volumeId=volumeId,
        maxDim=maxDim,
        method=method,
    )
# ==============================================================================
#        ANALYZE RESULTS: TILT SERIES (SetOfTiltSeries)
# ==============================================================================

@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/tiltseries",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listOutputTiltSeries(
    projectId: int,
    protocolId: int,
    outputName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    List tilt series for a SetOfTiltSeries-like output.
    """
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    items = service.listOutputTiltSeriesService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(items or [])
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/tiltseries/{tiltSeriesId}/frames",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getTiltSeriesFrames(
    projectId: int,
    protocolId: int,
    outputName: str,
    tiltSeriesId: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Return metadata for all tilt images in one tilt series.
    """
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        payload = service.getTiltSeriesFramesService(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            tiltSeriesId=tiltSeriesId,
        )

        from fastapi.responses import JSONResponse

        resp = JSONResponse(payload or {})
        resp.headers["X-Debug-Auth"] = "ok"
        resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
        resp.headers["Vary"] = "Authorization"
        return resp
    except Exception as e:
        logger.exception("Error in get_tiltseries_frames: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load frames for tiltseries {tiltSeriesId}: {e}",
        )


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/tiltseries/{tiltSeriesId}/tilt",
    response_model=None,
)
def renderTiltSeriesImage(
    projectId: int,
    protocolId: int,
    outputName: str,
    tiltSeriesId: str,
    index: int = Query(
        0,
        ge=0,
        description="0-based tilt index inside the tilt series",
    ),
    size: int = Query(
        1024,
        ge=16,
        le=4096,
        description="Target thumbnail size (longest side) in pixels",
    ),
    fmt: str = Query(
        "png",
        alias="fmt",
        description="Output image format: png | webp | jpeg",
    ),
    applyTransform: bool = Query(
        False,
        description="If true, apply geometric transformation if available (alignment)",
    ),
    inline: bool = Query(
        True,
        description="If true, send Content-Disposition inline",
    ),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Render one tilt image from a tilt series.
    """
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        resp = service.renderTiltSeriesImageService(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            tiltSeriesId=tiltSeriesId,
            index=index,
            size=size,
            fmt=fmt,
            applyTransform=applyTransform,
            inline=inline,
        )

        resp.headers["X-Debug-Auth"] = "ok"
        resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
        resp.headers["Vary"] = "Authorization"
        return resp
    except Exception as e:
        logger.exception("Error in get_tiltseries_frames: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load frames for tiltseries {tiltSeriesId}: {e}",
        )

@router.post(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/tiltseries/new-set",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def createNewSetOfTiltSeries(
    projectId: int,
    protocolId: int,
    outputName: str,
    payload: TiltSeriesNewSetRequest,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Create a new tilt-series output applying the given exclusions.
    The backend is expected to duplicate the SetOfTiltSeries and
    remove excluded views, optionally restacking files on disk.
    """
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=False,
        checkPid=False,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        result = service.createNewSetOfTiltSeriesService(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            exclusions=payload.exclusions,
            restack=payload.restack,
        )

        from fastapi.responses import JSONResponse

        resp = JSONResponse(result or {})
        resp.headers["X-Debug-Auth"] = "ok"
        resp.headers["X-Debug-UserId"] = str(
            getattr(currentUser, "id", currentUser.get("id", ""))
        )
        resp.headers["Vary"] = "Authorization"
        return resp
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in createNewSetOfTiltSeries: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create new tilt-series set: {e}",
        )


# ==============================================================================
#        ANALYZE RESULTS: CTF TOMOGRAPHY (SetOfCTFTomoSeries)
# ==============================================================================
class CtftomoNewSetRequest(BaseModel):
    """
    Request payload for creating a new SetOfCTFTomoSeries based on exclusions.
    The exact shape of 'exclusions' will be interpreted by the service layer.
    """
    exclusions: Dict[str, Any]
    restack: bool = False


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/ctftomo",
    status_code=status.HTTP_200_OK,
)
def listCtftomoSeries(
    projectId: int,
    protocolId: int,
    outputName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    List CTFTomoSeries entries for a CTFTomo output.
    """
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.listOutputCtftomoSeriesService(projectId, protocolId, outputName)


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/ctftomo/{tiltSeriesId}/views",
    status_code=status.HTTP_200_OK,
)
def getCtftomoSeriesViews(
    projectId: int,
    protocolId: int,
    outputName: str,
    tiltSeriesId: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Return all CTF measurements for one tilt-series (identified by tiltSeriesId).
    """
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.getCtftomoSeriesViewsService(projectId, protocolId, outputName, tiltSeriesId)


@router.post(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/ctftomo/new-set",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def createNewSetOfCtftomoSeries(
    projectId: int,
    protocolId: int,
    outputName: str,
    payload: CtftomoNewSetRequest,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Create a new CTF-tomography output applying the given exclusions.
    The backend is expected to duplicate the SetOfCTFTomoSeries and
    update excluded tilts per series.
    """
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=False,
        checkPid=False,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        result = service.createNewSetOfCtftomoSeriesService(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            exclusions=payload.exclusions,
            restack=payload.restack,
        )

        from fastapi.responses import JSONResponse

        resp = JSONResponse(result or {})
        resp.headers["X-Debug-Auth"] = "ok"
        resp.headers["X-Debug-UserId"] = str(
            getattr(currentUser, "id", currentUser.get("id", ""))
        )
        resp.headers["Vary"] = "Authorization"
        return resp
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in createNewSetOfCtftomoSeries: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create new CTF-tomography set: {e}",
        )


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/ctftomo/psd",
    response_model=None,
)
def renderCtftomoPsdImage(
    projectId: int,
    protocolId: int,
    outputName: str,
    spec: str = Query(
        ...,
        description="Stack spec string such as '3@/path/to/file.mrc'",
    ),
    size: int = Query(
        512,
        ge=16,
        le=4096,
        description="Target thumbnail size (longest side) in pixels",
    ),
    fmt: str = Query(
        "png",
        alias="fmt",
        description="Output image format: png | webp | jpeg",
    ),
    applyTransform: bool = Query(
        False,
        description="If true, apply geometric transformation if available.",
    ),
    inline: bool = Query(
        True,
        description="If true, send Content-Disposition inline",
    ),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Render a PSD image for a CTF-tomography view, given a stack spec
    (for example '3@/path/to/TS_1.mrc').
    """
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=False,
        checkPid=False,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        resp = service.renderCtfTomoPsdImageService(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            psdPath=spec,
            size=size,
            fmt=fmt,
            applyTransform=applyTransform,
            inline=inline,
        )
        resp.headers["X-Debug-Auth"] = "ok"
        resp.headers["X-Debug-UserId"] = str(
            getattr(currentUser, "id", currentUser.get("id", ""))
        )
        resp.headers["Vary"] = "Authorization"
        return resp
    except Exception as e:
        logger.exception("Error in renderCtftomoPsdImage: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to render CTF-tomography PSD image: {e}",
        )


# ==============================================================================
#        ANALYZE RESULTS: COORDINATES3D (SetOfCoordinates3D)
# ==============================================================================

@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords3d/tomograms",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listCoordinates3dTomograms(
    projectId: int,
    protocolId: int,
    outputName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    List tomograms referenced by a SetOfCoordinates3D output.
    """
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    items = service.listCoordinates3dTomogramsService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(items or [])
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(
        getattr(currentUser, "id", currentUser.get("id", ""))
    )
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords3d/tomograms/{tomogramId}",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getCoordinates3dPoints(
    projectId: int,
    protocolId: int,
    outputName: str,
    tomogramId: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Return all 3D coordinates for one tomogram inside a SetOfCoordinates3D.
    """
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pts = service.getCoordinates3dPointsService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tomogramId=tomogramId,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(pts or [])
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(
        getattr(currentUser, "id", currentUser.get("id", ""))
    )
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords3d/tomograms/{tomogramId}/slice",
    status_code=status.HTTP_200_OK,
)
def renderCoords3dTomogramSlice(
    projectId: int,
    protocolId: int,
    outputName: str,
    tomogramId: str,
    index: int = Query(
        ...,
        ge=0,
        description="0-based slice index along the selected axis",
    ),
    axis: str = Query(
        "z",
        description="Axis along which to slice the tomogram: x, y or z",
    ),
    cmap: Optional[str] = Query(
        None,
        alias="cmap",
        description="Optional colormap name (e.g. 'gray', 'viridis')",
    ),
    normalize: Optional[str] = Query(
        "minmax",
        description="Normalization mode: 'minmax' or 'zscore'",
    ),
    scale: float = Query(
        1.0,
        description="Optional scaling factor applied to the 2D slice",
    ),
    inline: bool = Query(
        True,
        description="If true, returns the image as inline preview",
    ),
    fmt: str = Query(
        "webp",
        alias="format",
        description="Output image format: png | webp | jpeg",
    ),
    thumb: Optional[int] = Query(
        None,
        description="If set, max thumbnail size (pixels) for the longest dimension",
    ),
    fast: bool = Query(
        True,
        description="Reserved flag for potential faster/approximate rendering",
    ),
    quality: int = Query(
        75,
        description="JPEG/WEBP quality (1–100) when applicable",
    ),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Render a 2D slice from a tomogram referenced by a SetOfCoordinates3D.
    """
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    resp = service.renderCoords3dTomogramSliceService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tomogramId=tomogramId,
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

    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(
        getattr(currentUser, "id", currentUser.get("id", ""))
    )
    resp.headers["Vary"] = "Authorization"
    return resp


# ==============================================================================
#            ANALYZE RESULTS: METADATA TABLES (.sqlite / .star / etc.)
# ==============================================================================

@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listOutputMetadataTables(
    projectId: int,
    protocolId: int,
    outputName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    List logical metadata tables (blocks) associated with a given output.
    """
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    items = service.listOutputMetadataTablesService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(items)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/schema",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getMetadataTableSchema(
    projectId: int,
    protocolId: int,
    outputName: str,
    tableName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Return logical schema for one metadata table: columns, renderers, flags.
    """
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    schema = service.getMetadataTableSchemaService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tableName=tableName,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(schema)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/page",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getMetadataTablePage(
    projectId: int,
    protocolId: int,
    outputName: str,
    tableName: str,
    page: int = Query(1, ge=1, description="1-based page number"),
    pageSize: int = Query(100, ge=1, le=5000),
    sortBy: str = Query("id", description="Column name used for sorting"),
    asc: bool = Query(True, description="Sort ascending if true"),
    selectionOnly: bool = Query(
        False,
        description="If true, return only rows currently selected in this table (if implemented)",
    ),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Return one logical page of rows for a metadata table.
    """
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pageData = service.getMetadataTablePageService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tableName=tableName,
        page=page,
        pageSize=pageSize,
        sortBy=sortBy,
        asc=asc,
        selectionOnly=selectionOnly,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(pageData)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/export",
    response_model=None,
)
def exportMetadataTable(
    projectId: int,
    protocolId: int,
    outputName: str,
    tableName: str,
    fmt: str = Query(
        "csv",
        alias="format",
        pattern="^(csv|xlsx)$",
        description="Export format: csv or xlsx",
    ),
    selectionOnly: bool = Query(
        False,
        description="If true, export only selected rows (server-side selection, if implemented).",
    ),
    ids: Optional[str] = Query(
        None,
        description=(
            "Optional comma-separated row ids to export; "
            "if provided, takes precedence over selectionOnly."
        ),
    ),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Export a metadata table (full or subset) as CSV/XLSX.
    """
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    idList: Optional[List[int]] = None
    if ids:
        try:
            idList = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid 'ids' parameter. Expected comma-separated integers.",
            )

    resp = service.exportMetadataTableService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tableName=tableName,
        fmt=fmt,
        selectionOnly=selectionOnly,
        ids=idList,
    )
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/image",
    response_model=None,
)
def renderMetadataImageCell(
    projectId: int,
    protocolId: int,
    outputName: str,
    tableName: str,
    rowId: Optional[Union[int, str]] = Query(
        None,
        description=(
            "Logical row id (for selection/export workflows; "
            "optional in virtual scroll)."
        ),
    ),
    rowIndex: Optional[int] = Query(
        None,
        ge=0,
        description=(
            "0-based row index in the current table order "
            "(preferred for virtual scroll)."
        ),
    ),
    column: str = Query(
        ...,
        description="Column name that contains the image path or reference.",
    ),
    size: int = Query(
        256,
        ge=16,
        le=2048,
        description="Target thumbnail size in pixels.",
    ),
    applyTransform: bool = Query(
        False,
        description="If true, apply geometric transformation (rotation) if available.",
    ),
    inline: bool = Query(
        True,
        description="If true, send Content-Disposition inline (for browser display).",
    ),
    fmt: str = Query(
        "png",
        description=(
            "Image format to generate (png, jpeg, webp, etc.), "
            "implementation-dependent."
        ),
    ),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Render one image cell from a metadata table using the same logic as ImageRenderer.
    """
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    resp = service.renderMetadataImageCellService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tableName=tableName,
        rowId=rowId,
        rowIndex=rowIndex,
        columnName=column,
        size=size,
        applyTransform=applyTransform,
        inline=inline,
        fmt=fmt,
    )
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp



@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/rows",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getMetadataTableWindow(
    projectId: int,
    protocolId: int,
    outputName: str,
    tableName: str,
    offset: int = Query(
        0,
        ge=0,
        description="0-based starting row index in the current table order",
    ),
    limit: int = Query(
        2000,
        ge=1,
        le=10000,
        description="Maximum number of rows to return in this window",
    ),
    selectionOnly: bool = Query(
        False,
        description="If true, use server-side selection instead of the full table",
    ),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Return a window (offset + limit) of rows for a metadata table.
    """
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    windowData = service.getMetadataTableWindowService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tableName=tableName,
        offset=offset,
        limit=limit,
        selectionOnly=selectionOnly,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(windowData)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp
