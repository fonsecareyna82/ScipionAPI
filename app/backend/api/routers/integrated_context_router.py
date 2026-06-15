import logging
from collections import deque
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.services.project_service import ProjectService
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


def getProjectService() -> ProjectService:
    return ProjectService()


def _normalizedKind(value: Optional[str]) -> str:
    return "".join(str(value or "").split()).lower()


def _isVolumeKind(value: Optional[str]) -> bool:
    kind = _normalizedKind(value)
    return kind in {"volume", "volumemask", "setofvolumes", "setoftomograms"}


def _isCoords3dKind(value: Optional[str]) -> bool:
    return "setofcoordinates3d" in _normalizedKind(value)


def _isTiltSeriesKind(value: Optional[str]) -> bool:
    kind = _normalizedKind(value)
    return "setoftiltseries" in kind and kind != "setoftiltseriesm"


def _isCTFTomoKind(value: Optional[str]) -> bool:
    return "setofctftomoseries" in _normalizedKind(value)


def _safeStr(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def _toInt(value: Any) -> Any:
    try:
        return int(value)
    except Exception:
        return value


def _nodeOutputs(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    outputs = node.get("outputs") or []
    return [item for item in outputs if isinstance(item, dict)]


def _outputClass(output: Dict[str, Any]) -> str:
    return _safeStr(
        output.get("pointerClass")
        or output.get("outputClassName")
        or output.get("className")
        or output.get("type")
    )


def _outputName(output: Dict[str, Any]) -> str:
    return _safeStr(output.get("name") or output.get("outputName"))


def _findOutput(node: Dict[str, Any], outputName: str) -> Optional[Dict[str, Any]]:
    wanted = _safeStr(outputName).strip()
    for output in _nodeOutputs(node):
        if _outputName(output) == wanted:
            return output
    return None


def _ancestorProtocolIds(protocols: Dict[str, Any], protocolId: int) -> List[str]:
    ordered: List[str] = []
    seen: Set[str] = set()
    queue = deque([str(protocolId)])

    while queue:
        currentId = queue.popleft()
        if currentId in seen:
            continue

        seen.add(currentId)
        ordered.append(currentId)

        node = protocols.get(currentId) or {}
        for parentId in node.get("parents") or []:
            parentText = _safeStr(parentId).strip()
            if parentText and parentText != "PROJECT" and parentText not in seen:
                queue.append(parentText)

    return ordered


def _buildLink(
    protocols: Dict[str, Any],
    protocolIds: Iterable[str],
    matcher: Callable[[str], bool],
) -> Optional[Dict[str, Any]]:
    for nodeId in protocolIds:
        node = protocols.get(str(nodeId)) or {}
        for output in _nodeOutputs(node):
            outputClass = _outputClass(output)
            outputName = _outputName(output)
            if not outputName or not matcher(outputClass):
                continue

            return {
                "protocolId": _toInt(nodeId),
                "outputName": outputName,
                "label": output.get("info") or outputName,
                "status": "inferred",
            }

    return None


def _missingLink() -> Dict[str, Any]:
    return {"status": "missing"}


def _buildSummary(link: Optional[Dict[str, Any]], protocols: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not link or link.get("status") == "missing":
        return None

    node = protocols.get(str(link.get("protocolId"))) or {}
    return {
        "protocolId": link.get("protocolId"),
        "outputName": link.get("outputName"),
        "label": node.get("label") or node.get("runName"),
        "status": node.get("status"),
    }


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
    project = service.getProjectById(
        mapper,
        projectId,
        currentUser,
        refresh=False,
        checkPid=False,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    protocols = project.get("protocols") or {}
    if not isinstance(protocols, dict):
        protocols = {}

    node = protocols.get(str(protocolId))
    if not isinstance(node, dict):
        raise HTTPException(status_code=404, detail="Protocol not found")

    rootOutput = _findOutput(node, outputName) or {}
    rootClass = _outputClass(rootOutput)
    protocolIds = _ancestorProtocolIds(protocols, protocolId)

    links = {
        "tiltSeries": _buildLink(protocols, protocolIds, _isTiltSeriesKind) or _missingLink(),
        "ctf": _buildLink(protocols, protocolIds, _isCTFTomoKind) or _missingLink(),
        "tomogram": _buildLink(protocols, protocolIds, _isVolumeKind) or _missingLink(),
        "coordinates3d": _buildLink(protocols, protocolIds, _isCoords3dKind) or _missingLink(),
    }

    payload = {
        "root": {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "outputClass": rootClass or None,
        },
        "links": links,
        "summaries": {
            key: _buildSummary(link, protocols)
            for key, link in links.items()
        },
    }

    response = JSONResponse(payload)
    response.headers["X-Debug-Auth"] = "ok"
    response.headers["X-Debug-UserId"] = _safeStr(getattr(currentUser, "id", currentUser.get("id", "")))
    response.headers["Vary"] = "Authorization"
    return response
