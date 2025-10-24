from fastapi import APIRouter, Depends, HTTPException, status, Path as PathParam, Query, Response
from typing import List, Any, Dict, Union
from pathlib import Path as FsPath
import mimetypes

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.schemas.protocols_schema import ProtocolOut
from app.backend.database import getMapper
from app.backend.api.schemas.project_schema import ProjectCreate, ProjectOut, ProjectUpdate
from app.backend.api.services.project_service import ProjectService
from app.backend.models.protocol_model import (
    ProtocolRequest,
    ProtocolRenameIn,
    ProtocolDuplicateIn,
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

def _protocolRoot(protocol_id: Union[int, str]) -> FsPath:
    """
    Resolve the absolute root folder for a protocol, using your service.
    """
    root = service.getProtocolPath(str(protocol_id))
    if not root:
        raise HTTPException(status_code=404, detail="Protocol path not found")
    return FsPath(root).resolve()


def _guardJoin(root: FsPath, rel_path: str) -> FsPath:
    """
    Join root + rel_path, resolve, and ensure it stays inside root.
    """
    # Treat incoming path as relative to the protocol root
    rel = (rel_path or "").strip().lstrip("/\\")
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")
    return target


def _guessMime(p: FsPath) -> str:
    mt, _ = mimetypes.guess_type(str(p))
    return mt or "application/octet-stream"


@router.get("/{projectId}/protocols/{protocolId}/fs/list", response_model=Any)
async def listProtocolDir(
    projectId: int,
    protocolId: Union[int, str],
    path: str = Query("", description="Relative path inside the protocol root"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    # Check project existence
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    root = _protocolRoot(protocolId)
    target = _guardJoin(root, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    items = []
    try:
        for child in target.iterdir():
            is_dir = child.is_dir()
            item = {
                "name": child.name,
                "path": str(child.relative_to(root)).replace("\\", "/"),
                "isDir": is_dir,
            }
            if not is_dir:
                try:
                    item["size"] = child.stat().st_size
                except Exception:
                    item["size"] = None
                item["mime"] = _guessMime(child)
            items.append(item)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Directories first, then files; alpha by name
    items.sort(key=lambda it: (not it["isDir"], it["name"].lower()))

    cwd_rel = str(target.relative_to(root)).replace("\\", "/")
    return {"cwd": cwd_rel, "items": items}


@router.get("/{projectId}/protocols/{protocolId}/fs/preview", response_model=None)
async def previewProtocolText(
    projectId: int,
    protocolId: Union[int, str],
    path: str = Query(..., description="Relative file path inside protocol root"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    # Check project existence
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    root = _protocolRoot(protocolId)
    file_path = _guardJoin(root, path)

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    mime = _guessMime(file_path)
    # Allow common textual types
    textual = (
        mime.startswith("text/")
        or mime in ("application/json", "application/xml", "application/x-yaml", "text/x-log")
    )
    if not textual:
        # Fallback by extension for common text formats
        if file_path.suffix.lower() not in {".txt", ".log", ".json", ".yaml", ".yml", ".md", ".csv", ".tsv", ".xml"}:
            raise HTTPException(status_code=415, detail="Preview not available for this file type")

    # Size guard (e.g., 1MB)
    MAX_BYTES = 1 * 1024 * 1024
    try:
        size = file_path.stat().st_size
        if size > MAX_BYTES:
            raise HTTPException(status_code=413, detail="File too large to preview")
    except Exception:
        pass

    try:
        # Try utf-8 read; ignore errors
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        raise HTTPException(status_code=500, detail="Could not read file")

    return Response(content=text, media_type="text/plain; charset=utf-8")


@router.get("/{projectId}/protocols/{protocolId}/fs/download", response_model=None)
async def downloadProtocolFile(
    projectId: int,
    protocolId: Union[int, str],
    path: str = Query(..., description="Relative file path inside protocol root"),
    inline: bool = Query(False, description="If true, send Content-Disposition inline"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    # Check project existence
    project = service.getProjectById(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    root = _protocolRoot(protocolId)
    file_path = _guardJoin(root, path)

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_type = _guessMime(file_path)
    disposition = "inline" if inline else "attachment"
    headers = {
        "Content-Disposition": f'{disposition}; filename="{file_path.name}"'
    }
    return Response(
        content=file_path.read_bytes(),
        media_type=media_type,
        headers=headers
    )
