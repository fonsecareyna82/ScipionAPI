import json
import logging
import os
from typing import Any, Dict, List, Optional, Set, Union

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.services.project_service import ProjectService
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


class WorkflowExportRequest(BaseModel):
    protocolIds: List[Union[int, str]] = Field(default_factory=list)
    includeUpstream: bool = False


class WorkflowImportRequest(BaseModel):
    workflow: Any
    mode: str = "append"
    sourceProjectId: Optional[Union[int, str]] = None
    sourceProjectName: Optional[str] = None


def getProjectService() -> ProjectService:
    return ProjectService()


def _sortProtocolIds(protocolIds: Set[str]) -> List[str]:
    def sortKey(value: str):
        try:
            return 0, int(value)
        except Exception:
            return 1, str(value)

    return sorted(protocolIds, key=sortKey)


def _getCurrentWorkflowProtocolIds(service: ProjectService) -> Set[str]:
    try:
        runs = service.currentProject.getRunsGraph(refresh=True, checkPids=False)
        nodesDict = getattr(runs, "_nodesDict", {}) or {}
    except Exception:
        return set()

    return {
        str(nodeId)
        for nodeId in nodesDict.keys()
        if str(nodeId) != "PROJECT"
    }


def _normalizeWorkflowImportErrors(result: Any) -> List[str]:
    if result is None:
        return []

    if isinstance(result, dict):
        rawErrors = result.get("errors") or result.get("error") or result.get("detail")
        if rawErrors is None:
            return []
        if isinstance(rawErrors, list):
            return [str(item) for item in rawErrors if str(item).strip()]
        text = str(rawErrors).strip()
        return [text] if text else []

    if isinstance(result, (list, tuple, set)):
        return [str(item) for item in result if str(item).strip()]

    text = str(result).strip()
    return [text] if text else []


def _unwrapWorkflowImportPayload(service: ProjectService, workflowPayload: Any) -> Any:
    if workflowPayload is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing workflow",
        )

    if isinstance(workflowPayload, dict):
        metadata = workflowPayload.get("scipionWeb")
        if isinstance(metadata, dict):
            requiredPluginNames = [
                str(name).strip()
                for name in metadata.get("requiredPluginNames", []) or []
                if str(name).strip()
            ]
            service._validateWorkflowRequiredPlugins(requiredPluginNames)

        if "workflow" in workflowPayload:
            return workflowPayload.get("workflow")

        if "content" in workflowPayload:
            return workflowPayload.get("content")

    return workflowPayload


def _getProjectDisplayName(service: ProjectService) -> str:
    try:
        projectPath = service.currentProject.getPath()
        if projectPath:
            return os.path.basename(str(projectPath)) or str(projectPath)
    except Exception:
        pass

    return ""


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

    if bool(payload.includeUpstream):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="includeUpstream is not supported yet",
        )

    protocolIds = service._normalizeProtocolIdsForExport(payload.protocolIds)
    if not protocolIds:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing protocolIds",
        )

    try:
        protocolIdInts = [int(protocolId) for protocolId in protocolIds]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="protocolIds must be numeric",
        )

    protocolList = []
    missing: List[str] = []

    for protocolId in protocolIdInts:
        protocol = service.currentProject.getProtocol(protocolId)
        if protocol is None:
            missing.append(str(protocolId))
            continue
        protocolList.append(protocol)

    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Protocol(s) not found: {', '.join(missing)}",
        )

    try:
        rawExport = service.currentProject.getProtocolsJson(protocolList)
        workflow = service._decodeExportJsonPayload(rawExport)
        metadata = service._buildWorkflowPluginMetadata(protocolList)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to export workflow protocols. projectId=%s", projectId)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export workflow protocols: {e}",
        )

    return {
        "sourceProjectId": projectId,
        "sourceProjectName": _getProjectDisplayName(service),
        "protocolIds": protocolIds,
        "workflow": workflow,
        "scipionWeb": metadata,
        "summary": {
            "protocolCount": len(protocolList),
            "requiredPluginNames": metadata.get("requiredPluginNames", []),
        },
    }


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

    mode = str(payload.mode or "append").strip().lower()
    if mode != "append":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported import mode: {mode}",
        )

    workflowContent = _unwrapWorkflowImportPayload(service, payload.workflow)

    if isinstance(workflowContent, str):
        workflowText = service._extractWorkflowJsonText(workflowContent)
        try:
            workflowContent = json.loads(workflowText)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid workflow JSON: {e}",
            )

    if not isinstance(workflowContent, (list, dict)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Workflow must be a JSON list or object",
        )

    beforeIds = _getCurrentWorkflowProtocolIds(service)
    workflowJson = json.dumps(workflowContent, ensure_ascii=False)

    try:
        loadResult = service.currentProject.loadProtocols(jsonStr=workflowJson)
    except Exception as e:
        logger.exception("Failed to import workflow protocols. projectId=%s", projectId)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import workflow protocols: {e}",
        )

    errors = _normalizeWorkflowImportErrors(loadResult)

    try:
        syncInfo = service.syncProjectProtocolsAndDependencies(
            mapper,
            projectId,
            refresh=True,
            checkPid=True,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to sync workflow after import. projectId=%s", projectId)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow was imported but graph sync failed: {e}",
        )

    afterIds = _getCurrentWorkflowProtocolIds(service)
    createdIds = _sortProtocolIds(afterIds - beforeIds)

    return {
        "status": 1 if errors else 0,
        "errors": errors,
        "workflow": [],
        "created": [{"newId": protocolId} for protocolId in createdIds],
        "protocolsCount": int(syncInfo.get("protocols", 0)),
        "dependenciesCount": int(syncInfo.get("dependencies", 0)),
    }
