import base64
import logging
import os
import hashlib
from email.utils import formatdate

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Path as PathParam,
    Query,
    Request, Body,
)
from typing import List, Any, Union, Optional, Literal, Dict
from fastapi.responses import JSONResponse, FileResponse, Response

from pydantic import BaseModel, Field

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.schemas.protocols_schema import (
    ExportProtocolsRequest,
    RemoteFileWriteRequest,
    WorkflowExportRequest,
    WorkflowImportRequest,
)
from app.backend.api.schemas.tags_schema import ProtocolTagCreateIn, ProtocolTagUpdateIn, ProtocolTagsSetIn
from app.backend.database import getMapperDependency as getMapper
from app.backend.api.schemas.project_schema import (ProjectCreate, ProjectOut, ProjectUpdate, ProjectShareCreate,
                                                    ApplyWorkflowToProjectRequest, TiltSeriesNewSetRequest,
                                                    ProjectImportIn, ProtocolWizardExecuteResponse,
                                                    ProtocolWizardExecuteRequest, ProjectImportOut)
from app.backend.api.services.project_service import ProjectService, _thumbnailProjectLock
from app.backend.models.project_model import ExternalViewerLaunchRequest
from app.backend.models.protocol_model import (
    ProtocolRequest,
    ProtocolRenameIn,
    DuplicatePayload,
    DeletePayload, ProtocolOutputThumbnailsRequest,
)
from app.backend.mapper.postgresql import PostgresqlFlatMapper

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


def getProjectService() -> ProjectService:
    """Return a fresh ProjectService per request to avoid shared state."""
    return ProjectService()

def _appendProtocolSyncCounts(response: Dict[str, Any], result: Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return response

    protocolsCount = result.get("protocolsCount", result.get("protocols"))
    dependenciesCount = result.get("dependenciesCount", result.get("dependencies"))

    if protocolsCount is not None:
        response["protocolsCount"] = protocolsCount
    if dependenciesCount is not None:
        response["dependenciesCount"] = dependenciesCount

    return response

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


@router.post("/import", response_model=ProjectImportOut, status_code=status.HTTP_201_CREATED)
def importProject(
    projectData: ProjectImportIn,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    return service.importProject(mapper, projectData, currentUser)


@router.get("/{projectId}", response_model=Any)
def getProject(
    projectId: int,
    validateConsistency: bool = Query(False),
    usePostgresqlRuntimeProject: bool = Query(True),
    syncRuntimeStatuses: bool = Query(True),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=True,
        checkPid=True,
        validateConsistency=validateConsistency,
        loadWorkflowFromPostgresql=not validateConsistency,
        usePostgresqlRuntimeProject=usePostgresqlRuntimeProject,
        syncRuntimeStatuses=syncRuntimeStatuses,
    )

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    return project

@router.get(
    "/{projectId}/summary",
    response_model=ProjectOut,
    status_code=status.HTTP_200_OK,
)
def getProjectSummary(
        projectId: int,
        includeDiskUsage: bool = Query(False),
        currentUser=Depends(getCurrentUser),
        mapper: PostgresqlFlatMapper = Depends(getMapper),
        service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectSummaryFromPostgresql(
        mapper=mapper,
        projectId=projectId,
        currentUser=currentUser,
        includeDiskUsage=includeDiskUsage,
    )

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    return project

@router.get(
    "/{projectId}/effective-settings",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getProjectEffectiveSettings(
    projectId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Return runtime-effective settings for a project.

    This endpoint is read-only and aggregates the relevant settings that
    the frontend may need when opening a project, such as:
    - user settings
    - instance settings
    - host execution settings

    The project must be accessible by the authenticated user.
    """
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    try:
        return service.getProjectEffectiveSettings(
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in getProjectEffectiveSettings: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load project effective settings: {e}",
        )


@router.post(
    "/{projectId}/consistency/check",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def checkProjectPostgresqlConsistency(
    projectId: int,
    refresh: bool = Query(True),
    checkPid: bool = Query(True),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    return service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=projectId,
        currentUser=currentUser,
        refresh=refresh,
        checkPid=checkPid,
    )


@router.put("/{projectId}", response_model=Any, status_code=status.HTTP_200_OK)
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
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
    usePostgresqlRuntimeProject: bool = Query(True),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=False,
        checkPid=False,
        usePostgresqlRuntimeProject=usePostgresqlRuntimeProject,
    )
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return service.getProtocolParams(
        mapper=mapper,
        projectId=projectId,
        protocolId=protocolId,
    )


class ProtocolStepStatusUpdate(BaseModel):
    status: Literal["new", "finished"] = Field(..., description="New status for the selected protocol step")


@router.get("/{projectId}/protocols/{protocolId}/steps", response_model=Any)
def listProtocolSteps(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return service.listProtocolStepsService(mapper, projectId, protocolId)


@router.patch("/{projectId}/protocols/{protocolId}/steps/{stepIndex}/status", response_model=Any)
def updateProtocolStepStatus(
    projectId: int,
    protocolId: int,
    stepIndex: int,
    payload: ProtocolStepStatusUpdate,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return service.updateProtocolStepStatusService(
        mapper=mapper,
        projectId=projectId,
        protocolId=protocolId,
        stepIndex=stepIndex,
        stepStatus=payload.status,
    )


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
    usePostgresqlRuntimeProject: bool = Query(True),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Launch, restart, schedule, or stop a protocol in a given project.
    """
    try:
        if usePostgresqlRuntimeProject:
            project = (
                service
                .loadPostgresqlRuntimeProjectForMutation(
                    mapper=mapper,
                    projectId=projectId,
                    currentUser=currentUser,
                    enableWriteFallback=True,
                )
            )

        else:
            project = service.getProjectById(
                mapper=mapper,
                projectId=projectId,
                currentUser=currentUser,
                refresh=True,
                checkPid=False,
                usePostgresqlRuntimeProject=False,
                usePostgresqlRuntimeWriteFallback=False,
            )
        if not project:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "status": 1,
                    "errors": ["Project not found"],
                    "workflow": [],
                },
            )

        result = service.launchProtocol(
            mapper=mapper,
            projectId=projectId,
            protocolId=request.getProtocolId(),
            protocolClassName=request.getProtocolClassName(),
            params=request.getParams(),
            executeMode=request.getMode(),
        ) or {}

        response = {
            "status": 0,
            "errors": [],
            "workflow": [],
        }

        return _appendProtocolSyncCounts(response, result)

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={
                "status": 1,
                "errors": _normalizeErrors(e.detail),
                "workflow": [],
            },
        )
    except Exception:
        logger.exception("Unexpected error while launching protocol")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": 1,
                "errors": ["Internal server error"],
                "workflow": [],
            },
        )


@router.post("/{projectId}/save", response_model=Any)
async def saveProtocol(
    projectId: int,
    request: ProtocolRequest,
    usePostgresqlRuntimeProject: bool = Query(True),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Save protocol parameters in a given project.
    """
    try:
        project = service.getProjectById(
            mapper,
            projectId,
            currentUser,
            refresh=False if usePostgresqlRuntimeProject else True,
            checkPid=False,
            loadWorkflowFromPostgresql=usePostgresqlRuntimeProject,
            usePostgresqlRuntimeProject=usePostgresqlRuntimeProject,
            usePostgresqlRuntimeWriteFallback=usePostgresqlRuntimeProject,
        )
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

        protocol, errors = service.saveProtocol(mapper, projectId, protocolId, protocolClassName, params)
        errors = errors or []

        workflow = []

        if not errors and usePostgresqlRuntimeProject:
            refreshedProject = service.getProjectById(
                mapper,
                projectId,
                currentUser,
                refresh=False,
                checkPid=False,
                loadWorkflowFromPostgresql=True,
                usePostgresqlRuntimeProject=usePostgresqlRuntimeProject,
                usePostgresqlRuntimeWriteFallback=usePostgresqlRuntimeProject,
            )

            if refreshedProject:
                workflow = refreshedProject.get("protocols", [])

        return {
            "status": 0 if not errors else 1,
            "errors": [str(err) for err in errors],
            "workflow": workflow,
        }

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

@router.get("/{projectId}/protocols/{protocolId}/suggestions/next", response_model=Any, status_code=status.HTTP_200_OK)
def suggestionProtocol(
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
        return service.getNextProtocolSuggestions(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={
                "status": 1,
                "errors": _normalizeErrors(e.detail),
                "workflow": [],
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": 1,
                "errors": [str(e)],
                "workflow": [],
            },
        )


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
        newName = getattr(payload, "runName", None)
        newComment = getattr(payload, "comment", "")

        if newName is None:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "status": 1,
                    "errors": ["Missing name"],
                    "workflow": [],
                },
            )

        newNameText = str(newName)

        if newNameText != "" and not newNameText.strip():
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "status": 1,
                    "errors": ["Missing name"],
                    "workflow": [],
                },
            )

        service.renameProtocol(
            mapper,
            projectId,
            protocolId,
            newNameText.strip(),
            str(newComment or "").strip(),
        )
        syncResult = service.syncProjectGraphAfterMutation(
            mapper,
            projectId,
            actionLabel="rename protocol",
            refresh=True,
            checkPid=True,
        ) or {}

        response = {
            "status": 0,
            "errors": [],
            "workflow": [],
        }

        return _appendProtocolSyncCounts(response, syncResult)

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
    usePostgresqlRuntimeProject: bool = Query(True),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=False if usePostgresqlRuntimeProject else True,
        checkPid=False,
        loadWorkflowFromPostgresql=usePostgresqlRuntimeProject,
        usePostgresqlRuntimeProject=usePostgresqlRuntimeProject,
        usePostgresqlRuntimeWriteFallback=usePostgresqlRuntimeProject,
    )
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

        result = service.duplicateProtocol(mapper, projectId, items) or {}
        workflow = []

        if usePostgresqlRuntimeProject:
            refreshedProject = service.getProjectById(
                mapper,
                projectId,
                currentUser,
                refresh=False,
                checkPid=False,
                loadWorkflowFromPostgresql=True,
                usePostgresqlRuntimeProject=True,
                usePostgresqlRuntimeWriteFallback=True,
            )

            if refreshedProject:
                workflow = refreshedProject.get("protocols", [])
        # Keep 201 on success, but still return unified schema
        response = {
            "status": result.get("status", 0),
            "errors": result.get("errors", []),
            "workflow": workflow,
            "duplicated": result.get("duplicated", []),
        }

        return _appendProtocolSyncCounts(response, result)

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
    usePostgresqlRuntimeProject: bool = Query(True),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    try:
        project = service.getProjectById(
            mapper,
            projectId,
            currentUser,
            refresh=False if usePostgresqlRuntimeProject else True,
            checkPid=False,
            loadWorkflowFromPostgresql=usePostgresqlRuntimeProject,
            usePostgresqlRuntimeProject=usePostgresqlRuntimeProject,
            usePostgresqlRuntimeWriteFallback=usePostgresqlRuntimeProject,
        )
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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"status": 1,
                         "errors": ["Missing protocolIds"],
                         "workflow": []},
            )

        result = service.deleteProtocol(mapper, projectId, protocolIds) or {}
        workflow = []

        if usePostgresqlRuntimeProject:
            refreshedProject = service.getProjectById(
                mapper,
                projectId,
                currentUser,
                refresh=False,
                checkPid=False,
                loadWorkflowFromPostgresql=True,
                usePostgresqlRuntimeProject=True,
                usePostgresqlRuntimeWriteFallback=True,
            )

            if refreshedProject:
                workflow = refreshedProject.get("protocols", [])

        response = {
            "status": 0,
            "errors": [],
            "workflow": workflow,
        }

        return _appendProtocolSyncCounts(response, result)

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={
                "status": 1,
                "errors": _normalizeErrors(e.detail),
                "workflow": [],
            },
        )

    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": 1,
                "errors": _normalizeErrors(str(e)),
                "workflow": [],
            },
        )


@router.post(
    "/{projectId}/protocols/{protocolId}/restart-all",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def restartProtocolAll(
    projectId: int,
    protocolId: int,
    usePostgresqlRuntimeProject: bool = Query(True),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=False if usePostgresqlRuntimeProject else True,
        checkPid=False,
        loadWorkflowFromPostgresql=usePostgresqlRuntimeProject,
        usePostgresqlRuntimeProject=usePostgresqlRuntimeProject,
        usePostgresqlRuntimeWriteFallback=usePostgresqlRuntimeProject,
    )
    if not project:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"status": 1,
                     "errors": ["Project not found"],
                     "workflow": []},
        )

    try:
        result = service.restartProtocolAll(mapper, projectId, protocolId)

        workflow = []

        if usePostgresqlRuntimeProject:
            refreshedProject = service.getProjectById(
                mapper,
                projectId,
                currentUser,
                refresh=False,
                checkPid=False,
                loadWorkflowFromPostgresql=True,
                usePostgresqlRuntimeProject=True,
                usePostgresqlRuntimeWriteFallback=True,
            )

            if refreshedProject:
                workflow = refreshedProject.get("protocols", [])

            response = {
                "status": result.get("status", 0),
                "errors": result.get("errors", []),
                "workflow": workflow,
            }

            return _appendProtocolSyncCounts(response, result)

        syncResult = service.syncProjectGraphAfterMutation(
            mapper,
            projectId,
            actionLabel="restart protocol subtree",
            refresh=True,
            checkPid=True,
        ) or {}

        response = {
            "status": 0,
            "errors": [],
            "workflow": [],
        }

        return _appendProtocolSyncCounts(response, syncResult)

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
    usePostgresqlRuntimeProject: bool = Query(True),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=False if usePostgresqlRuntimeProject else True,
        checkPid=False,
        loadWorkflowFromPostgresql=usePostgresqlRuntimeProject,
        usePostgresqlRuntimeProject=usePostgresqlRuntimeProject,
        usePostgresqlRuntimeWriteFallback=usePostgresqlRuntimeProject,
    )
    if not project:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"status": 1, "errors": ["Project not found"], "workflow": []},
        )

    try:
        result = service.continueProtocolAll(mapper, projectId, protocolId, currentUser)
        workflow = []

        if usePostgresqlRuntimeProject:
            refreshedProject = service.getProjectById(
                mapper,
                projectId,
                currentUser,
                refresh=False,
                checkPid=False,
                loadWorkflowFromPostgresql=True,
                usePostgresqlRuntimeProject=True,
                usePostgresqlRuntimeWriteFallback=True,
            )

            if refreshedProject:
                workflow = refreshedProject.get("protocols", [])

            response = {
                "status": result.get("status", 0),
                "errors": result.get("errors", []),
                "workflow": workflow,
            }

            return _appendProtocolSyncCounts(response, result)

        syncResult = service.syncProjectGraphAfterMutation(
            mapper,
            projectId,
            actionLabel="continue protocol subtree",
            refresh=True,
            checkPid=True,
        ) or {}

        response = {
            "status": 0,
            "errors": [],
            "workflow": [],
        }

        return _appendProtocolSyncCounts(response, syncResult)

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
    usePostgresqlRuntimeProject: bool = Query(True),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=False if usePostgresqlRuntimeProject else True,
        checkPid=False,
        loadWorkflowFromPostgresql=usePostgresqlRuntimeProject,
        usePostgresqlRuntimeProject=usePostgresqlRuntimeProject,
        usePostgresqlRuntimeWriteFallback=usePostgresqlRuntimeProject,
    )
    if not project:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"status": 1, "errors": ["Project not found"], "workflow": []},
        )

    try:
        result = service.resetProtocolFrom(mapper, projectId, protocolId)

        workflow = []

        if usePostgresqlRuntimeProject:
            refreshedProject = service.getProjectById(
                mapper,
                projectId,
                currentUser,
                refresh=False,
                checkPid=False,
                loadWorkflowFromPostgresql=True,
                usePostgresqlRuntimeProject=True,
                usePostgresqlRuntimeWriteFallback=True,
            )

            if refreshedProject:
                workflow = refreshedProject.get("protocols", [])

            response = {
                "status": result.get("status", 0),
                "errors": result.get("errors", []),
                "workflow": workflow,
            }

            return _appendProtocolSyncCounts(response, result)

        syncResult = service.syncProjectGraphAfterMutation(
            mapper,
            projectId,
            actionLabel="reset protocol from node",
            refresh=True,
            checkPid=True,
        ) or {}

        response = {
            "status": 0,
            "errors": [],
            "workflow": [],
        }

        return _appendProtocolSyncCounts(response, syncResult)

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
    usePostgresqlRuntimeProject: bool = Query(True),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=False if usePostgresqlRuntimeProject else True,
        checkPid=False,
        loadWorkflowFromPostgresql=usePostgresqlRuntimeProject,
        usePostgresqlRuntimeProject=usePostgresqlRuntimeProject,
        usePostgresqlRuntimeWriteFallback=usePostgresqlRuntimeProject,
    )
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

        result = service.stopProtocol(mapper, projectId, protocolIds)
        if usePostgresqlRuntimeProject:
            refreshedProject = service.getProjectById(
                mapper,
                projectId,
                currentUser,
                refresh=False,
                checkPid=False,
                loadWorkflowFromPostgresql=True,
                usePostgresqlRuntimeProject=True,
                usePostgresqlRuntimeWriteFallback=True,
            )

            if refreshedProject:
                workflow = refreshedProject.get("protocols", [])

            response = {
                "status": result.get("status", 0),
                "errors": result.get("errors", []),
                "workflow": workflow,
            }

            return _appendProtocolSyncCounts(response, result)

        syncResult = service.syncProjectGraphAfterMutation(
            mapper,
            projectId,
            actionLabel="stop protocol",
            refresh=True,
            checkPid=True,
        ) or {}

        response = {
            "status": 0,
            "errors": [],
            "workflow": [],
        }

        return _appendProtocolSyncCounts(response, syncResult)

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
#                            PROTOCOL LOGS
# ======================================================================

class LogChannelOut(BaseModel):
    id: str
    label: Optional[str] = None
    order: Optional[int] = None


class LogChunkOut(BaseModel):
    channelId: str
    text: str
    nextOffset: int
    hasMore: Optional[bool] = None


class LogsPollResponse(BaseModel):
    chunks: List[LogChunkOut]
    done: bool = False


def _ensureDefaultLogChannels(channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # ensureDefaultChannels
    byId = {str(c.get("id")): c for c in (channels or []) if isinstance(c, dict) and c.get("id")}

    defaults = [
        {"id": "stdout", "label": "Output", "order": 10},
        {"id": "stderr", "label": "Errors", "order": 20},
        {"id": "schedule", "label": "Schedule", "order": 30},
    ]

    for d in defaults:
        if d["id"] not in byId:
            byId[d["id"]] = dict(d)
        else:
            # mergeDefaults
            if not byId[d["id"]].get("label"):
                byId[d["id"]]["label"] = d["label"]
            if byId[d["id"]].get("order") is None:
                byId[d["id"]]["order"] = d["order"]

    out = list(byId.values())
    out.sort(key=lambda x: (x.get("order") is None, x.get("order", 10**9), str(x.get("id", ""))))
    return out


def _coerceOffsets(payload: Any) -> Dict[str, int]:
    # coerceOffsets
    if payload is None:
        return {}

    if isinstance(payload, dict):
        raw = payload.get("offsets") or payload.get("channels") or {}
    else:
        raw = getattr(payload, "offsets", None) or getattr(payload, "channels", None) or {}

    offsets: Dict[str, int] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                offsets[str(k)] = int(v)
            except Exception:
                offsets[str(k)] = 0
    return offsets


def _coerceInt(payload: Any, key: str, default: Optional[int] = None) -> Optional[int]:
    # coerceInt
    if payload is None:
        return default
    val = payload.get(key) if isinstance(payload, dict) else getattr(payload, key, None)
    if val is None:
        return default
    try:
        return int(val)
    except Exception:
        return default


@router.get(
    "/{projectId}/protocols/{protocolId}/logs/channels",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listProtocolLogChannels(
    projectId: int,
    protocolId: int,
    includeDefault: bool = Query(True, description="If true, always include stdout/stderr/schedule"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    # listProtocolLogChannels
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        channels = service.listProtocolLogChannelsService(
            projectId=projectId,
            protocolId=protocolId,
            mapper=mapper,
            currentUser=currentUser,
        )

        # normalizeChannels
        if isinstance(channels, dict) and isinstance(channels.get("channels"), list):
            channels = channels.get("channels")
        if channels is None:
            channels = []
        if not isinstance(channels, list):
            channels = []

        channelDicts: List[Dict[str, Any]] = []
        for c in channels:
            if isinstance(c, dict) and c.get("id"):
                channelDicts.append(c)
            elif isinstance(c, str):
                channelDicts.append({"id": c})

        # if includeDefault:
        #     channelDicts = _ensureDefaultLogChannels(channelDicts)

        return {"channels": channelDicts}

    except Exception as e:
        logger.exception("Error in listProtocolLogChannels: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to load log channels: {e}")


@router.post(
    "/{projectId}/protocols/{protocolId}/logs/chunk",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def pollProtocolLogs(
    projectId: int,
    protocolId: int,
    payload: Any = Body(...),
    includeDefault: bool = Query(False, description="If true, always poll stdout/stderr/schedule keys"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    # pollProtocolLogs
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        offsets = _coerceOffsets(payload) or {}

        if includeDefault:
            # ensureDefaultOffsets
            for k in ("stdout", "stderr", "schedule"):
                offsets.setdefault(k, 0)

        maxBytes = _coerceInt(payload, "maxBytes", 65536)
        maxLines = _coerceInt(payload, "maxLines", 2000)

        result = service.pollProtocolLogsService(
            projectId=projectId,
            protocolId=protocolId,
            offsets=offsets,
            maxBytes=maxBytes,
            maxLines=maxLines,
            mapper=mapper,
            currentUser=currentUser,
        )

        # normalizePollResponse
        if not isinstance(result, dict):
            return {"chunks": [], "done": False}

        rawChannels = result.get("channels") or {}

        # normalizeChannelsToDict
        channelsDict: Dict[str, Dict[str, Any]] = {}
        if isinstance(rawChannels, dict):
            for k, v in rawChannels.items():
                if isinstance(v, dict):
                    channelsDict[str(k)] = v
                else:
                    channelsDict[str(k)] = {}
        elif isinstance(rawChannels, list):
            # optionalSupportForListShape: [{"id":"...", ...}]
            for item in rawChannels:
                if isinstance(item, dict):
                    cid = item.get("id") or item.get("channel") or item.get("name")
                    if cid:
                        channelsDict[str(cid)] = item

        # decideWhichChannelsToReturn
        requestedIds = list(offsets.keys())
        if not requestedIds:
            # ifClientDidNotSendOffsetsUseServiceKeys
            requestedIds = list(channelsDict.keys())

        # unionWithServiceKeysSoYouDon’tSilentlyDropDynamicChannels
        # if youOnlyWantRequestedRemoveThisBlock
        for cid in channelsDict.keys():
            if cid not in offsets:
                offsets[cid] = 0
                requestedIds.append(cid)

        chunks = []
        anyTruncated = False

        for channelId in requestedIds:
            ch = channelsDict.get(channelId) or {}
            truncated = bool(ch.get("truncated", False))
            anyTruncated = anyTruncated or truncated

            chunks.append({
                "channel": channelId,
                "content": ch.get("content", "") or "",
                "offset": int(ch.get("offset", offsets.get(channelId, 0)) or 0),
                # "resetOffset": bool(ch.get("resetOffset", False)),
                # "truncated": truncated,
                # "exists": bool(ch.get("exists", False)),
                # "path": ch.get("path", "") or "",
                # "bytesRead": int(ch.get("bytesRead", 0) or 0),
                # "linesRead": int(ch.get("linesRead", 0) or 0),
                # "sizeBytes": int(ch.get("sizeBytes", 0) or 0),
            })

        done = not anyTruncated
        return {"chunks": chunks}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in pollProtocolLogs: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to poll logs: {e}")


# ======================================================================
#                FS REMOTE: list / preview / download
# ======================================================================

def _isGlobalFsBrowserMode(projectId: int, protocolId: Union[int, str]) -> bool:
    return str(projectId).strip() == "-1" and str(protocolId).strip() == "-1"


def _ensureProjectForFsRequest(
    projectId: int,
    protocolId: Union[int, str],
    currentUser,
    mapper: PostgresqlFlatMapper,
    service: ProjectService,
    *,
    refresh: bool = True,
    checkPid: bool = True,
):
    if _isGlobalFsBrowserMode(projectId, protocolId):
        return None

    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=refresh,
        checkPid=checkPid,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return project


@router.get("/{projectId}/protocols/{protocolId}/fs/start-path", response_model=Any)
async def getProtocolPath(
    projectId: int,
    protocolId: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    _ensureProjectForFsRequest(projectId, protocolId, currentUser, mapper, service)
    return service.getProtocolPath(
        protocolId=protocolId,
        mapper=mapper,
        projectId=projectId,
    )


@router.get("/{projectId}/protocols/{protocolId}/fs/list", response_model=Any)
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
    _ensureProjectForFsRequest(projectId, protocolId, currentUser, mapper, service)
    return service.listProtocolDir(
        protocolId=protocolId,
        path=path,
        mapper=mapper,
        projectId=projectId,
    )


@router.get("/{projectId}/protocols/{protocolId}/fs/preview2", response_model=None)
async def previewProtocolText(
    projectId: int,
    protocolId: Union[int, str],
    path: str = Query(..., description="Relative file path inside protocol root"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    _ensureProjectForFsRequest(projectId, protocolId, currentUser, mapper, service)
    return service.previewProtocolTextFile(
        protocolId=protocolId,
        path=path,
        mapper=mapper,
        projectId=projectId,
    )


@router.get("/{projectId}/protocols/{protocolId}/fs/preview", response_model=None)
def previewRemoteEntry(
    projectId: int,
    protocolId: Union[int, str],
    path: str = Query(..., description="Relative file path inside protocol root"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    _ensureProjectForFsRequest(
        projectId,
        protocolId,
        currentUser,
        mapper,
        service,
        refresh=False,
        checkPid=False,
    )
    return service.previewRemoteEntry(
        protocolId=protocolId,
        path=path,
        mapper=mapper,
        projectId=projectId,
    )


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
    _ensureProjectForFsRequest(projectId, protocolId, currentUser, mapper, service)
    return service.previewProtocolImageFile(
        protocolId=protocolId,
        path=path,
        inline=inline,
        mapper=mapper,
        projectId=projectId,
    )


@router.post(
    "/{projectId}/protocols/export",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def exportProtocols(
    projectId: int,
    payload: ExportProtocolsRequest,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=False,
        checkPid=False,
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    try:
        return service.exportProtocolsService(
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
            payload=payload,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in exportProtocols: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export protocols: {e}",
        )


@router.post(
    "/{projectId}/protocols/export-workflow",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def exportWorkflowProtocols(
    projectId: int,
    payload: WorkflowExportRequest,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=False,
        checkPid=False,
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    try:
        return service.exportWorkflowProtocolsService(
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
            payload=payload,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in exportWorkflowProtocols: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export workflow protocols: {e}",
        )


@router.post(
    "/{projectId}/protocols/import-workflow",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def importWorkflowProtocols(
    projectId: int,
    payload: WorkflowImportRequest,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=True,
        checkPid=False,
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    try:
        return service.importWorkflowProtocolsService(
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
            payload=payload,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in importWorkflowProtocols: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import workflow protocols: {e}",
        )

@router.post(
    "/{projectId}/protocols/{protocolId}/fs/write",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
async def writeRemoteFile(
    projectId: int,
    protocolId: Union[int, str],
    payload: RemoteFileWriteRequest,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    _ensureProjectForFsRequest(
        projectId,
        protocolId,
        currentUser,
        mapper,
        service,
        refresh=False,
        checkPid=False,
    )

    try:
        return service.writeRemoteFileService(
            protocolId=protocolId,
            payload=payload,
            mapper=mapper,
            projectId=projectId,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in writeRemoteFile: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write remote file: {e}",
        )


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
        mapper=mapper,
        projectId=projectId,
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
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
            mapper=mapper,
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    items = service.listOutputVolumesService(projectId,
                                             protocolId,
                                             outputName,
                                             mapper=mapper)
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    info = service.getVolumeInfoService(projectId,
                                        protocolId,
                                        outputName,
                                        volumeId,
                                        mapper=mapper,)
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    hist = service.getVolumeHistogramService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        volumeId=volumeId,
        bins=bins,
        mapper=mapper,
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
    normalize: Optional[str] = Query("minmax"),
    scale: float = Query(1.0, gt=0),
    inline: bool = Query(True),
    thumb: Optional[int] = Query(None, ge=32, le=2048),
    fast: bool = Query(True),
    quality: int = Query(75, ge=1, le=100),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    cmap = cmapParam or colormapParam
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
        mapper=mapper,
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.getVolumeData3dService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        volumeId=volumeId,
        maxDim=maxDim,
        method=method,
        mapper=mapper,
    )

@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/surface",
    response_model=Any,
    status_code=status.HTTP_200_OK,
    summary="Get a real marching-cubes surface mesh for a volume",
)
def getVolumeSurfaceMesh(
    projectId: int,
    protocolId: int,
    outputName: str,
    volumeId: Union[int, str],
    level: Optional[float] = Query(None, description="Absolute iso level. If omitted, an automatic level is used."),
    maxDim: int = Query(192, ge=32, le=512, alias="maxDim"),
    method: Literal["binning", "stride", "linear", "fourier", "none"] = Query("stride"),
    maxTriangles: int = Query(350000, ge=1000, le=1500000, alias="maxTriangles"),
    currentUser: Dict[str, Any] = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:

        return service.getVolumeSurfaceMesh(projectId=projectId,
                                            protocolId=protocolId,
                                            outputName=outputName,
                                            volumeId=volumeId,
                                            level=level,
                                            maxDim=maxDim,
                                            method=method,
                                            maxTriangles=maxTriangles,
                                            currentUser=currentUser,
                                            mapper=mapper,)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to generate volume surface mesh")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate volume surface mesh: {exc}",
        )

# ==============================================================================
#        ANALYZE RESULTS: TILT SERIES (SetOfTiltSeries)
# ==============================================================================

class TiltSeriesBatchRenderRequest(BaseModel):
    indices: List[int] = Field(default_factory=list)
    size: int = Field(512, ge=16, le=4096)
    fmt: str = "webp"
    applyTransform: bool = True
    inline: bool = True

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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    items = service.listOutputTiltSeriesService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        mapper=mapper,
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        payload = service.getTiltSeriesFramesService(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            tiltSeriesId=tiltSeriesId,
            mapper=mapper,
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
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
            mapper=mapper,
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
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/tiltseries/{tiltSeriesId}/tilt/batch",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def renderTiltSeriesImagesBatch(
    projectId: int,
    protocolId: int,
    outputName: str,
    tiltSeriesId: str,
    payload: TiltSeriesBatchRenderRequest,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Render several tilt images from the same tilt series in one request.
    This is intended for smooth slider prefetching in the web viewer.
    """
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        result = service.renderTiltSeriesImagesBatchService(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            tiltSeriesId=tiltSeriesId,
            indices=payload.indices,
            size=payload.size,
            fmt=payload.fmt,
            applyTransform=payload.applyTransform,
            inline=payload.inline,
            mapper=mapper
        )

        resp = JSONResponse(result or {})
        resp.headers["X-Debug-Auth"] = "ok"
        resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
        resp.headers["Vary"] = "Authorization"
        return resp

    except Exception as e:
        logger.exception("Error in renderTiltSeriesImagesBatch: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to render tiltseries batch for {tiltSeriesId}: {e}",
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
    The backend duplicates the SetOfTiltSeries and removes excluded views,
    optionally restacking files on disk.
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
        result = service.createNewSetOfTiltSeriesService(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            exclusions=payload.exclusions,
            restack=payload.restack,
            mapper=mapper,
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.listOutputCtftomoSeriesService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        mapper=mapper,
    )


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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.getCtftomoSeriesViewsService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tiltSeriesId=tiltSeriesId,
        mapper=mapper,
    )


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
            mapper=mapper,
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
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
            mapper=mapper,
        )
        resp.headers["X-Debug-Auth"] = "ok"
        resp.headers["X-Debug-UserId"] = str(
            getattr(currentUser, "id", currentUser.get("id", ""))
        )
        resp.headers["Vary"] = "Authorization"
        return resp
    except HTTPException:
        raise
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    items = service.listCoordinates3dTomogramsService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        mapper=mapper,
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pts = service.getCoordinates3dPointsService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tomogramId=tomogramId,
        mapper=mapper,
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
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
        mapper=mapper
    )

    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(
        getattr(currentUser, "id", currentUser.get("id", ""))
    )
    resp.headers["Vary"] = "Authorization"
    return resp

class Coords3dPointIn(BaseModel):
    x: float
    y: float
    z: float
    id: Optional[Union[int, str]] = None
    score: Optional[float] = None
    classId: Optional[Union[int, str]] = None
    radius: Optional[float] = None
    tomoId: Optional[Union[int, str]] = None
    class Config: extra = "allow"


class CreateCoords3dOutputFromPointsIn(BaseModel):
    newOutputName: str = Field(..., min_length=1, description="Name for the newly created output")
    tomoId: Union[int, str] = Field(..., description="Tomogram identifier inside the source SetOfCoordinates3D")
    coords: List[Coords3dPointIn] = Field(default_factory=list, description="Full coordinates list for this tomogram")
    dims: Optional[List[int]] = Field( None, description="Optional tomogram dimensions [X, Y, Z] for backend validation", )
    voxelSize: Optional[List[float]] = Field( None, description="Optional voxel size [sx, sy, sz] for backend bookkeeping", )


@router.post( "/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords3d/new-output",
              response_model=Any,
              status_code=status.HTTP_200_OK, )
def createCoords3dOutputFromPoints(projectId: int,
                                   protocolId: int,
                                   outputName: str,
                                   payload: Dict[str, Any] = Body(...),
                                   currentUser=Depends(getCurrentUser),
                                   mapper: PostgresqlFlatMapper = Depends(getMapper),
                                   service: ProjectService = Depends(getProjectService), ):
    """ Create a new SetOfCoordinates3D output from an edited full point list for a given tomogram.
    The backend must interpret `coords` as a full replacement for that tomogram inside `outputName`. """

    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        result = service.createCoords3dOutputFromPointsService(projectId=projectId,
                                                               protocolId=protocolId,
                                                               outputName=outputName,
                                                               payload=payload,
                                                               mapper=mapper,)
        resp = JSONResponse(result or {"success": True, "outputName": result['outputName']})
        resp.headers["X-Debug-Auth"] = "ok"
        resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
        resp.headers["Vary"] = "Authorization"

        return resp
    except HTTPException as e:
        logger.exception("Error in createCoords3dOutputFromPoints: %s", e)
        raise HTTPException( status_code=500, detail=f"Failed to create coords3d output from points: {e}", )


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/integrated-context",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getIntegratedAnalyzeContext(
    projectId: int,
    protocolId: int,
    outputName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    payload = service.getIntegratedAnalyzeContextService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        mapper=mapper,
    )

    resp = JSONResponse(payload)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp

# ==============================================================================
#        ANALYZE RESULTS: FSC (SetOfFSCs)
# ==============================================================================

@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/fsc/rows",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getFscRows(
    projectId: int,
    protocolId: int,
    outputName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Return FSC curves for a SetOfFSCs-like output.

    Response shape:
    {
      "curves": [
        {
          "label": "FSC 1",
          "resolution": 3.21,
          "xKind": "frequency",
          "points": [
            {"x": 0.01, "y": 0.95},
            {"x": 0.02, "y": 0.87},
          ],
        },
      ],
      "threshold": 0.143,
    }
    """
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        payload = service.getFscRowsService(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            mapper=mapper,
            currentUser=currentUser,
        )

        resp = JSONResponse(payload or {"curves": [], "threshold": 0.143})
        resp.headers["X-Debug-Auth"] = "ok"
        resp.headers["X-Debug-UserId"] = str(
            getattr(currentUser, "id", currentUser.get("id", ""))
        )
        resp.headers["Vary"] = "Authorization"
        return resp

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in getFscRows: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load FSC rows: {e}",
        )

# ==============================================================================
#            ANALYZE RESULTS: METADATA TABLES (.sqlite / .star / etc.)
# ==============================================================================

class MetadataTableActionRequest(BaseModel):
    action: str = Field(..., description="Action label provided by schema.actions")
    subsetName: Optional[str] = Field(None, description="Subset name for the new output/protocol")
    ids: List[int] = Field(default_factory=list, description="Selected row ids")


class MetadataTableActionResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    errors: Optional[List[str]] = None

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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    items = service.listOutputMetadataTablesService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        mapper=mapper,
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    schema = service.getMetadataTableSchemaService(
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        tableName=tableName,
        mapper=mapper,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(schema)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp

@router.post(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/actions",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def runMetadataTableAction(
    projectId: int,
    protocolId: int,
    outputName: str,
    tableName: str,
    payload: MetadataTableActionRequest = Body(...),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    # runMetadataTableAction
    project = service.getProjectById(mapper, projectId, currentUser, refresh=True, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    actionLabel = (payload.action or "").strip()
    if not actionLabel:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing action")

    rowIds = payload.ids or []
    if not isinstance(rowIds, list) or len(rowIds) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing ids",
        )

    subsetName = (payload.subsetName or "").strip() or "create subset"

    try:
        result = service.runMetadataTableActionService(
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
            tableName=tableName,
            action=actionLabel,
            subsetName=subsetName,
            ids=rowIds,
            currentUser=currentUser,
            mapper=mapper,
        )

        # normalizeServiceResult
        success = True
        message = None
        errors = None

        if isinstance(result, bool):
            success = bool(result)
        elif isinstance(result, dict):
            if "success" in result:
                success = bool(result.get("success"))
            if isinstance(result.get("message"), str):
                message = result.get("message")
            if isinstance(result.get("errors"), list):
                errors = [str(x) for x in result.get("errors") if x is not None]
        elif result is None:
            success = True
        else:
            # treatNonEmptyTruthinessAsSuccess
            success = True

        respPayload: Dict[str, Any] = {"success": success}
        if message:
            respPayload["message"] = message
        if errors:
            respPayload["errors"] = errors

        return JSONResponse(respPayload)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in runMetadataTableAction: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run metadata table action: {e}",
        )


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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
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
        mapper=mapper,
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
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
        mapper=mapper,
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
    project = service.getProjectDbRow(mapper, projectId, currentUser)
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
        mapper=mapper,
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
    sortBy: str = Query(
        'id',
        description="Column used to sort",
    ),
    asc: bool = Query(
        True,
        description="Sort order"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    """
    Return a window (offset + limit) of rows for a metadata table.
    """
    project = service.getProjectDbRow(mapper, projectId, currentUser)
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
        sortBy=sortBy,
        asc=asc,
        mapper=mapper,
    )

    from fastapi.responses import JSONResponse

    resp = JSONResponse(windowData)
    resp.headers["X-Debug-Auth"] = "ok"
    resp.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
    resp.headers["Vary"] = "Authorization"
    return resp

# ======================================================================
#                            ANALYZE RESULTS:  EXTERNAL VIEWERS
# ======================================================================
@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/external-viewers",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listExternalViewers(
    projectId: int,
    protocolId: int,
    outputName: str,
    objectId: Optional[Union[str, int]] = Query(None),
    objectKind: Optional[str] = Query(None),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
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
        viewers = service.listExternalViewers(
            protocolId=protocolId,
            outputName=outputName,
            objectId=objectId,
            objectKind=objectKind,
            mapper=mapper,
            projectId=projectId,
        )

        return {"viewers": viewers or []}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in listExternalViewers: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list external viewers: {e}",
        )


@router.post(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/external-viewers/{viewerId}/launch",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def launchExternalViewer(
    projectId: int,
    protocolId: int,
    outputName: str,
    viewerId: str,
    payload: Optional[ExternalViewerLaunchRequest] = Body(default=None),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=True,
        checkPid=False,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    payload = payload or ExternalViewerLaunchRequest()

    try:
        return service.launchExternalViewer(
            protocolId=protocolId,
            outputName=outputName,
            viewerId=viewerId,
            objectId=payload.objectId,
            objectKind=payload.objectKind,
            params=payload.params or {},
            mapper=mapper,
            projectId=projectId,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in launchExternalViewer: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to launch external viewer: {e}",
        )
# ======================================================================
#                            PROTOCOL TAGS
# ======================================================================


@router.get(
    "/{projectId}/tags",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listProjectTags(
    projectId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    # ensureProjectExists
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.listProjectTags(mapper=mapper, projectId=projectId, currentUser=currentUser)


@router.post(
    "/{projectId}/tags",
    response_model=Any,
    status_code=status.HTTP_201_CREATED,
)
def createProjectTag(
    projectId: int,
    payload: ProtocolTagCreateIn,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    # ensureProjectExists
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        return service.createProjectTag(
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
            payload=payload,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in createProjectTag: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create tag: {e}")


@router.put(
    "/{projectId}/tags/{tagId}",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def updateProjectTag(
    projectId: int,
    tagId: str,
    payload: ProtocolTagUpdateIn,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    # ensureProjectExists
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.updateProjectTag(
        mapper=mapper,
        projectId=projectId,
        tagId=tagId,
        currentUser=currentUser,
        payload=payload,
    )


@router.delete(
    "/{projectId}/tags/{tagId}",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def deleteProjectTag(
    projectId: int,
    tagId: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    # ensureProjectExists
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    ok = service.deleteProjectTag(mapper=mapper, projectId=projectId, tagId=tagId, currentUser=currentUser)
    return {"success": bool(ok)}


@router.get(
    "/{projectId}/protocols/{protocolId}/tags",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listProtocolTags(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    # ensureProjectExists
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.listProtocolTags(
        mapper=mapper,
        projectId=projectId,
        protocolId=protocolId,
        currentUser=currentUser,
    )


@router.put(
    "/{projectId}/protocols/{protocolId}/tags",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def setProtocolTags(
    projectId: int,
    protocolId: int,
    payload: ProtocolTagsSetIn,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    # ensureProjectExists
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return service.setProtocolTags(
        mapper=mapper,
        projectId=projectId,
        protocolId=protocolId,
        tagIds=payload.tagIds or [],
        currentUser=currentUser,
    )


@router.get(
    "/{projectId}/context-menu-visibility",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
async def getContextMenuVisibilityPolicy(
    projectId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return service.getContextMenuVisibilityPolicy()


# ======================================================================
#                            THUMBNAILS
# ======================================================================
def _attachDebugHeaders(response, currentUser):
    # _attachDebugHeaders
    response.headers["X-Debug-Auth"] = "ok"
    response.headers["X-Debug-UserId"] = str(
        getattr(currentUser, "id", currentUser.get("id", ""))
    )
    response.headers["Vary"] = "Authorization"
    return response


def _buildThumbnailEtag(filePath: str) -> str:
    # _buildThumbnailEtag
    statResult = os.stat(filePath)
    payload = f"{filePath}:{int(statResult.st_mtime_ns)}:{int(statResult.st_size)}"
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f'"{digest}"'


def _isNotModified(request: Request, etag: str) -> bool:
    # _isNotModified
    inm = request.headers.get("if-none-match")
    if not inm:
        return False

    tokens = [token.strip() for token in inm.split(",") if token.strip()]
    return etag in tokens


def _buildCachedThumbnailResponse(
    request: Request,
    filePath: str,
    filename: str,
    currentUser,
    maxAge: int = 120,
):
    # _buildCachedThumbnailResponse
    statResult = os.stat(filePath)
    etag = _buildThumbnailEtag(filePath)

    cacheHeaders = {
        "Cache-Control": f"private, max-age={int(maxAge)}, stale-while-revalidate=300",
        "ETag": etag,
        "Last-Modified": formatdate(statResult.st_mtime, usegmt=True),
        "Access-Control-Expose-Headers": "Content-Disposition, ETag, Last-Modified, Cache-Control",
    }

    if _isNotModified(request, etag):
        response = Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=cacheHeaders)
        return _attachDebugHeaders(response, currentUser)

    response = FileResponse(
        path=filePath,
        media_type="image/png",
        headers={
            **cacheHeaders,
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )
    return _attachDebugHeaders(response, currentUser)


def _loadThumbnailProjectContext(
    service: ProjectService,
    mapper: PostgresqlFlatMapper,
    projectId: int,
    currentUser: Dict[str, Any],
) -> dict:
    dbProj = service.getProjectDbRow(mapper, projectId, currentUser)
    if not dbProj:
        raise HTTPException(status_code=404, detail="Project not found")

    service.loadProjectForThumbnails(dbProj)
    return dbProj


def _runThumbnailProjectJob(
    service: ProjectService,
    mapper: PostgresqlFlatMapper,
    projectId: int,
    currentUser: Dict[str, Any],
    job,
):
    with _thumbnailProjectLock:
        try:
            _loadThumbnailProjectContext(service, mapper, projectId, currentUser)
            return job()
        finally:
            _clearThumbnailProjectContext(service)


def _clearThumbnailProjectContext(service: ProjectService) -> None:
    try:
        service.clearCurrentProject()
    except Exception:
        logger.debug("Could not clear thumbnail project context", exc_info=True)


@router.get(
    "/{projectId}/thumbnail",
    response_model=None,
    status_code=status.HTTP_200_OK,
)
def getProjectThumbnail(
    request: Request,
    projectId: int,
    size: int = Query(640, ge=128, le=2048),
    maxProtocols: int = Query(6, ge=1, le=12),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    try:
        with _thumbnailProjectLock:
            try:
                _loadThumbnailProjectContext(service, mapper, projectId, currentUser)

                result = service.buildProjectThumbnail(
                    force=False,
                    size=size,
                    maxProtocols=maxProtocols,
                )
            finally:
                _clearThumbnailProjectContext(service)

        thumbPath = result.get("absolutePath")
        if not thumbPath:
            raise HTTPException(status_code=404, detail="Project thumbnail not found")

        return _buildCachedThumbnailResponse(
            request=request,
            filePath=thumbPath,
            filename="project_thumbnail.png",
            currentUser=currentUser,
            maxAge=900,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in getProjectThumbnail: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load project thumbnail: {e}",
        )


@router.post(
    "/{projectId}/thumbnail/rebuild",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def rebuildProjectThumbnail(
    projectId: int,
    size: int = Query(640, ge=128, le=2048),
    maxProtocols: int = Query(6, ge=1, le=12),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    try:
        with _thumbnailProjectLock:
            try:
                _loadThumbnailProjectContext(service, mapper, projectId, currentUser)

                result = service.buildProjectThumbnail(
                    force=True,
                    size=size,
                    maxProtocols=maxProtocols,
                )
            finally:
                _clearThumbnailProjectContext(service)

        response = JSONResponse(
            {
                "success": True,
                "thumbnail": result,
            }
        )
        return _attachDebugHeaders(response, currentUser)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in rebuildProjectThumbnail: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to rebuild project thumbnail: {e}",
        )


@router.get(
    "/{projectId}/protocols/{protocolId}/thumbnail",
    response_model=None,
    status_code=status.HTTP_200_OK,
)
def getProtocolThumbnail(
    request: Request,
    projectId: int,
    protocolId: int,
    size: int = Query(320, ge=128, le=1024),
    outputName: Optional[str] = Query(None),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    try:
        def buildThumbnail():
            if outputName:
                return service.buildProtocolOutputThumbnail(
                    protocolId=protocolId,
                    outputName=outputName,
                    force=False,
                    size=size,
                    mapper=mapper,
                    projectId=projectId,
                )

            return service.buildProtocolThumbnail(
                protocolId=protocolId,
                force=False,
                size=size,
                mapper=mapper,
                projectId=projectId,
            )

        result = _runThumbnailProjectJob(
            service=service,
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
            job=buildThumbnail,
        )

        thumbPath = result.get("absolutePath")
        if not thumbPath:
            raise HTTPException(status_code=404, detail="Protocol thumbnail not found")

        return _buildCachedThumbnailResponse(
            request=request,
            filePath=thumbPath,
            filename=f"protocol_{protocolId}_thumbnail.png",
            currentUser=currentUser,
            maxAge=900,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in getProtocolThumbnail: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load protocol thumbnail: {e}",
        )


@router.post(
    "/{projectId}/protocols/{protocolId}/thumbnail/rebuild",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def rebuildProtocolThumbnail(
    projectId: int,
    protocolId: int,
    size: int = Query(320, ge=128, le=1024),
    outputName: Optional[str] = Query(None),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    try:
        def buildThumbnail():
            if outputName:
                return service.buildProtocolOutputThumbnail(
                    protocolId=protocolId,
                    outputName=outputName,
                    force=True,
                    size=size,
                    mapper=mapper,
                    projectId=projectId,
                )

            return service.buildProtocolThumbnail(
                protocolId=protocolId,
                force=True,
                size=size,
                mapper=mapper,
                projectId=projectId,
            )

        result = _runThumbnailProjectJob(
            service=service,
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
            job=buildThumbnail,
        )

        response = JSONResponse(
            {
                "success": True,
                "thumbnail": result,
            }
        )
        return _attachDebugHeaders(response, currentUser)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in rebuildProtocolThumbnail: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to rebuild protocol thumbnail: {e}",
        )


@router.get(
    "/{projectId}/thumbnail-items",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listProjectThumbnailItems(
        projectId: int,
        size: int = Query(320, ge=128, le=1024),
        maxProtocols: int = Query(12, ge=1, le=24),
        maxOutputsPerProtocol: int = Query(4, ge=1, le=12),
        inlineImages: bool = Query(False),
        currentUser=Depends(getCurrentUser),
        mapper: PostgresqlFlatMapper = Depends(getMapper),
        service: ProjectService = Depends(getProjectService),
):
    try:
        with _thumbnailProjectLock:
            dbProj = service.getProjectDbRow(mapper, projectId, currentUser)
            if not dbProj:
                raise HTTPException(status_code=404, detail="Project not found")

            service.loadProjectForThumbnails(dbProj)

            items = service.listProjectThumbnailItems(
                projectId=projectId,
                force=False,
                size=size,
                maxProtocols=maxProtocols,
                maxOutputsPerProtocol=maxOutputsPerProtocol,
                inlineImages=inlineImages,
                mapper=mapper,
            )
        response = JSONResponse(items)
        response.headers["Cache-Control"] = "private, max-age=60, stale-while-revalidate=300"
        response.headers["Access-Control-Expose-Headers"] = "Cache-Control"
        return _attachDebugHeaders(response, currentUser)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in listProjectThumbnailItems: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list project thumbnail items: {e}",
        )
    finally:
        _clearThumbnailProjectContext(service)


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/thumbnail",
    response_model=None,
    status_code=status.HTTP_200_OK,
)
def getProtocolOutputThumbnail(
    request: Request,
    projectId: int,
    protocolId: int,
    outputName: str,
    size: int = Query(320, ge=128, le=1024),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    try:
        with _thumbnailProjectLock:
            dbProj = service.getProjectDbRow(mapper, projectId, currentUser)
            if not dbProj:
                raise HTTPException(status_code=404, detail="Project not found")

            service.loadProjectForThumbnails(dbProj)

            result = service.buildProtocolOutputThumbnail(
                protocolId=protocolId,
                outputName=outputName,
                force=False,
                size=size,
                mapper=mapper,
                projectId=projectId,
            )

        thumbPath = result.get("absolutePath")
        if not thumbPath:
            logger.warning(
                "Protocol output thumbnail not found. projectId=%s protocolId=%s outputName=%s result=%s",
                projectId,
                protocolId,
                outputName,
                result,
            )
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "Protocol output thumbnail not found",
                    "projectId": projectId,
                    "protocolId": protocolId,
                    "outputName": outputName,
                    "result": result,
                },
            )

        return _buildCachedThumbnailResponse(
            request=request,
            filePath=thumbPath,
            filename=f"protocol_{protocolId}_{outputName}_thumbnail.png",
            currentUser=currentUser,
            maxAge=900,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in getProtocolOutputThumbnail: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load protocol output thumbnail: {e}",
        )


@router.post(
    "/{projectId}/output-thumbnails",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getProtocolOutputThumbnailsBatch(
        projectId: int,
        payload: ProtocolOutputThumbnailsRequest,
        currentUser=Depends(getCurrentUser),
        mapper: PostgresqlFlatMapper = Depends(getMapper),
        service: ProjectService = Depends(getProjectService),
):
    try:
        requestedOutputs = payload.outputs or []

        if not requestedOutputs:
            return {
                "projectId": projectId,
                "size": payload.size,
                "items": [],
            }

        items = []

        with _thumbnailProjectLock:
            dbProj = service.getProjectDbRow(mapper, projectId, currentUser)
            if not dbProj:
                raise HTTPException(status_code=404, detail="Project not found")

            service.loadProjectForThumbnails(dbProj)

            seen = set()

            for requestedOutput in requestedOutputs:
                requestedProtocolId = int(requestedOutput.protocolId)
                outputName = str(requestedOutput.outputName or "").strip()

                if not outputName:
                    continue

                requestKey = (requestedProtocolId, outputName)
                if requestKey in seen:
                    continue
                seen.add(requestKey)

                item = {
                    "protocolId": requestedProtocolId,
                    "outputName": outputName,
                    "outputClassName": None,
                    "exists": False,
                    "cached": False,
                    "thumbnailUrl": (
                        f"/projects/{int(projectId)}/protocols/{requestedProtocolId}"
                        f"/outputs/{outputName}/thumbnail"
                    ),
                    "thumbnailDataUrl": None,
                    "error": None,
                }

                try:
                    scipionProtocolId = service._resolveScipionProtocolId(
                        mapper=mapper,
                        projectId=projectId,
                        protocolId=requestedProtocolId,
                    )
                    protocol = service.currentProject.getProtocol(int(scipionProtocolId))
                except Exception:
                    item["error"] = "Protocol not found"
                    items.append(item)
                    continue

                try:
                    outputObject = getattr(protocol, outputName)
                    item["outputClassName"] = outputObject.__class__.__name__
                except Exception:
                    item["outputClassName"] = None

                try:
                    result = service.buildProtocolOutputThumbnail(
                        protocolId=requestedProtocolId,
                        outputName=outputName,
                        force=False,
                        size=payload.size,
                        mapper=mapper,
                        projectId=projectId,
                    )
                except Exception as exc:
                    logger.debug(
                        "Failed building batch protocol output thumbnail. projectId=%s protocolId=%s outputName=%s",
                        projectId,
                        requestedProtocolId,
                        outputName,
                        exc_info=True,
                    )
                    item["error"] = str(exc)
                    items.append(item)
                    continue

                thumbPath = result.get("absolutePath")
                if not result.get("exists") or not thumbPath:
                    item["error"] = "Thumbnail not available"
                    items.append(item)
                    continue

                item["exists"] = True
                item["cached"] = bool(result.get("cached"))

                if payload.inlineImages:
                    try:
                        if os.path.exists(str(thumbPath)) and os.path.getsize(str(thumbPath)) > 0:
                            with open(str(thumbPath), "rb") as fh:
                                encoded = base64.b64encode(fh.read()).decode("ascii")
                            item["thumbnailDataUrl"] = f"data:image/png;base64,{encoded}"
                    except Exception:
                        logger.debug(
                            "Could not inline batch thumbnail image. projectId=%s protocolId=%s outputName=%s",
                            projectId,
                            requestedProtocolId,
                            outputName,
                            exc_info=True,
                        )

                items.append(item)

        response = JSONResponse(
            {
                "projectId": projectId,
                "size": payload.size,
                "items": items,
            }
        )
        response.headers["Cache-Control"] = "private, max-age=60, stale-while-revalidate=300"
        response.headers["Access-Control-Expose-Headers"] = "Cache-Control"
        return _attachDebugHeaders(response, currentUser)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in getProtocolOutputThumbnailsBatch: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load protocol output thumbnails: {e}",
        )
    finally:
        _clearThumbnailProjectContext(service)

# *****************************************
# Wizards routers
# *****************************************
@router.post(
    "/{projectId}/wizards/execute",
    response_model=ProtocolWizardExecuteResponse,
)
def executeProtocolWizardRoute(
    projectId: int,
    payload: ProtocolWizardExecuteRequest,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return service.executeProtocolWizard(
        mapper=mapper,
        projectId=projectId,
        currentUser=currentUser,
        payload=payload,
    )