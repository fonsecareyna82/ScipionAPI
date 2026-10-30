"""Uploading files from the user's computer into a project's Uploads folder (see project_upload_service).

Work access to the project and the files.upload permission are checked by the router's guard
(project_access) before each route runs.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.backend.api.audit import recordAudit
from app.backend.api.dependencies import getCurrentUser
from app.backend.api.project_access import projectRouteAccess
from app.backend.api.services import project_upload_service as uploads
from app.backend.api.services.project_service import ProjectService
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["uploads"], dependencies=[Depends(projectRouteAccess(getMapper))])


def getProjectService() -> ProjectService:
    return ProjectService()


class UploadStartRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=uploads.MAX_NAME_LENGTH)
    size: int = Field(..., ge=0)


def _projectRoot(projectId: int, currentUser: dict, mapper: PostgresqlFlatMapper, service: ProjectService) -> Path:
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return Path(project["name"]).expanduser().resolve()


def _refused(error: uploads.UploadError) -> HTTPException:
    detail = {"message": error.message}
    if error.received is not None:
        detail["received"] = error.received
    return HTTPException(status_code=error.status, detail=detail if error.received is not None else error.message)


@router.post("/{projectId}/uploads")
def startUpload(projectId: int, payload: UploadStartRequest, currentUser=Depends(getCurrentUser),
                mapper: PostgresqlFlatMapper = Depends(getMapper),
                service: ProjectService = Depends(getProjectService)):
    """Open an upload of one file into Uploads/; its chunks follow."""
    root = _projectRoot(projectId, currentUser, mapper, service)
    try:
        upload = uploads.startUpload(root, int(currentUser["id"]), payload.name, payload.size)
    except uploads.UploadError as error:
        raise _refused(error)
    return {**upload.toDict(), "chunkLimit": uploads.MAX_CHUNK_BYTES}


@router.get("/{projectId}/uploads/{uploadId}")
def uploadStatus(projectId: int, uploadId: str, currentUser=Depends(getCurrentUser),
                 mapper: PostgresqlFlatMapper = Depends(getMapper),
                 service: ProjectService = Depends(getProjectService)):
    """How much of an upload has arrived (to resume it after a dropped connection)."""
    root = _projectRoot(projectId, currentUser, mapper, service)
    try:
        return uploads.uploadStatus(root, int(currentUser["id"]), uploadId).toDict()
    except uploads.UploadError as error:
        raise _refused(error)


@router.put("/{projectId}/uploads/{uploadId}")
async def writeUploadChunk(projectId: int, uploadId: str, request: Request,
                           offset: int = Query(..., ge=0, description="Where this chunk starts in the file"),
                           currentUser=Depends(getCurrentUser),
                           mapper: PostgresqlFlatMapper = Depends(getMapper),
                           service: ProjectService = Depends(getProjectService)):
    """Append one chunk (the raw request body) at offset."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > uploads.MAX_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail="Chunks may be up to %d bytes" % uploads.MAX_CHUNK_BYTES)
    root = await run_in_threadpool(_projectRoot, projectId, currentUser, mapper, service)
    chunk = await request.body()
    try:
        upload = await run_in_threadpool(uploads.writeChunk, root, int(currentUser["id"]), uploadId, offset, chunk)
    except uploads.UploadError as error:
        raise _refused(error)
    return upload.toDict()


@router.post("/{projectId}/uploads/{uploadId}/complete")
def completeUpload(projectId: int, uploadId: str, currentUser=Depends(getCurrentUser),
                   mapper: PostgresqlFlatMapper = Depends(getMapper),
                   service: ProjectService = Depends(getProjectService)):
    """Give the uploaded file its name in Uploads/ (never over an existing file)."""
    root = _projectRoot(projectId, currentUser, mapper, service)
    try:
        upload = uploads.completeUpload(root, int(currentUser["id"]), uploadId)
    except uploads.UploadError as error:
        raise _refused(error)
    recordAudit(mapper, currentUser, "projects.fileUploaded", "project", projectId, root.name,
                {"file": "%s/%s" % (uploads.UPLOADS_FOLDER, upload.name), "bytes": upload.size})
    return {**upload.toDict(), "absPath": (uploads.uploadsFolder(root) / upload.name).as_posix()}


@router.delete("/{projectId}/uploads/{uploadId}")
def cancelUpload(projectId: int, uploadId: str, currentUser=Depends(getCurrentUser),
                 mapper: PostgresqlFlatMapper = Depends(getMapper),
                 service: ProjectService = Depends(getProjectService)):
    """Drop an unfinished upload."""
    root = _projectRoot(projectId, currentUser, mapper, service)
    try:
        uploads.cancelUpload(root, int(currentUser["id"]), uploadId)
    except uploads.UploadError as error:
        raise _refused(error)
    return {"cancelled": True}
