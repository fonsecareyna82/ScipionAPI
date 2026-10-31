"""A facility in ScipionWeb: its mode, microscopes, samples and sessions (see the facility_*_service modules).

Without facility mode every route but the status answers 404, as if it did not exist.
"""
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.backend.api.audit import recordAudit
from app.backend.api.dependencies import getCurrentUser
from app.backend.api.permissions import hasPermission, requirePermission
from app.backend.api.services.facility_service import (
    PHOTO_MAX_UPLOAD_BYTES, FacilityService, facilityStatus, isFacilityStaff, requireFacilityMode,
)
from app.backend.api.services.facility_sample_service import FacilitySampleService
from app.backend.api.services.facility_session_service import ACTIVE_STATUSES, FacilitySessionService
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

router = APIRouter(prefix="/facility", tags=["Facility"])


class PixelSizePayload(BaseModel):
    magnification: int
    pixelSize: float


class DetectorPayload(BaseModel):
    id: Optional[int] = None
    name: str
    metadataName: Optional[str] = ""
    energyFiltered: bool = False
    gainPath: Optional[str] = ""
    gainFlip: str = "none"
    gainRotation: int = 0
    notes: Optional[str] = ""
    pixelSizes: List[PixelSizePayload] = []


class MicroscopePayload(BaseModel):
    name: str
    model: Optional[str] = ""
    status: str = "operational"
    energyFilter: Optional[str] = ""
    acquisitionSoftware: Optional[str] = ""
    voltageKv: Optional[float] = None
    csMm: Optional[float] = None
    offloadPath: Optional[str] = ""
    sessionsEnabled: bool = False
    notes: Optional[str] = ""
    detectors: List[DetectorPayload] = []


def requireFacilityStaff(currentUser: dict = Depends(getCurrentUser)) -> dict:
    """Any facility permission: the staff see the microscopes."""
    if not isFacilityStaff(currentUser):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This is for the facility staff")
    return currentUser


def requireSampleKeeper(currentUser: dict = Depends(getCurrentUser)) -> dict:
    """Who records samples, grids and sessions: the staff who run sessions, and the facility managers."""
    if not (hasPermission(currentUser, "facility.sessions") or hasPermission(currentUser, "facility.manage")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Permission required: facility.sessions or facility.manage")
    return currentUser


class GridPayload(BaseModel):
    id: Optional[int] = None
    position: int
    gridNumber: Optional[int] = None
    gridType: Optional[str] = ""
    concentration: Optional[str] = ""
    specimen: Optional[str] = ""
    status: str = "stored"
    notes: Optional[str] = ""


class GridBoxPayload(BaseModel):
    id: Optional[int] = None
    label: str
    vitrificationCode: Optional[str] = ""
    vitrifiedOn: Optional[date] = None
    notes: Optional[str] = ""
    grids: List[GridPayload] = []


class SamplePayload(BaseModel):
    code: str
    description: Optional[str] = ""
    groupId: Optional[int] = None
    ownerId: Optional[int] = None
    accessRoute: Optional[str] = ""
    notes: Optional[str] = ""
    boxes: List[GridBoxPayload] = []


class DatasetPayload(BaseModel):
    id: Optional[int] = None
    kind: str = "data"
    number: Optional[int] = None
    gridId: Optional[int] = None
    detectorId: Optional[int] = None
    notes: Optional[str] = ""


class SessionPayload(BaseModel):
    # Empty: the facility's name, YYYY_MM_DD_<Name-Surname>_<id>
    name: Optional[str] = ""
    microscopeId: int
    technique: str = "spa"
    status: str = "planned"
    groupId: Optional[int] = None
    userId: Optional[int] = None
    bookingRef: Optional[str] = ""
    scheduledOn: Optional[date] = None
    notes: Optional[str] = ""
    # An id of GET /projects/workflows: the template each DATA's project is made from
    templateId: Optional[str] = ""
    autoProcess: bool = True
    datasets: List[DatasetPayload] = []


def _sessionSummary(session: Dict[str, Any]) -> Dict[str, Any]:
    """What the audit log keeps of a session."""
    return {"status": session["status"], "microscope": session["microscopeName"],
            "datasets": {dataset["folder"]: dataset.get("gridId") for dataset in session.get("datasets") or []}}


def _sampleSummary(sample: Dict[str, Any]) -> Dict[str, Any]:
    """What the audit log keeps of a sample."""
    boxes = sample.get("boxes") or []
    return {"boxes": len(boxes), "grids": sum(len(box.get("grids") or []) for box in boxes)}


def _service(mapper: PostgresqlFlatMapper) -> FacilityService:
    return FacilityService(mapper.db)


def _summary(microscope: Dict[str, Any]) -> Dict[str, Any]:
    """What the audit log keeps of a microscope."""
    return {"status": microscope["status"], "sessionsEnabled": bool(microscope["sessionsEnabled"]),
            "detectors": {detector["name"]: {str(row["magnification"]): row["pixelSize"]
                                             for row in detector.get("pixelSizes") or []}
                          for detector in microscope.get("detectors") or []}}


@router.get("/status")
def getFacilityStatus(currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    """Whether facility mode is on and the facility permissions the user holds (the web's menu)."""
    return facilityStatus(currentUser)


@router.get("/microscopes", dependencies=[Depends(requireFacilityMode)])
def listMicroscopes(mapper: PostgresqlFlatMapper = Depends(getMapper),
                    currentUser: dict = Depends(requireFacilityStaff)) -> List[Dict[str, Any]]:
    return _service(mapper).listMicroscopes()


@router.post("/microscopes", status_code=status.HTTP_201_CREATED, dependencies=[Depends(requireFacilityMode)])
def createMicroscope(payload: MicroscopePayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                     currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    microscope = _service(mapper).saveMicroscope(payload.dict())
    recordAudit(mapper, currentUser, "facility.microscopeCreated", "microscope", microscope["id"],
                microscope["name"], _summary(microscope))
    return microscope


@router.put("/microscopes/{microscopeId}", dependencies=[Depends(requireFacilityMode)])
def updateMicroscope(microscopeId: int, payload: MicroscopePayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                     currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    service = _service(mapper)
    before = service.getMicroscope(microscopeId)
    microscope = service.saveMicroscope(payload.dict(), microscopeId=microscopeId)
    changes = {key: value for key, value in _summary(microscope).items() if _summary(before).get(key) != value}
    if before["name"] != microscope["name"]:
        changes["renamedFrom"] = before["name"]
    recordAudit(mapper, currentUser, "facility.microscopeUpdated", "microscope", microscopeId, microscope["name"],
                changes)
    return microscope


@router.delete("/microscopes/{microscopeId}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(requireFacilityMode)])
def deleteMicroscope(microscopeId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                     currentUser: dict = Depends(requirePermission("facility.manage"))) -> None:
    microscope = _service(mapper).deleteMicroscope(microscopeId)
    recordAudit(mapper, currentUser, "facility.microscopeDeleted", "microscope", microscopeId, microscope["name"],
                _summary(microscope))


@router.get("/microscopes/{microscopeId}/photo", dependencies=[Depends(requireFacilityMode)])
def getMicroscopePhoto(microscopeId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                       currentUser: dict = Depends(requireFacilityStaff)) -> Response:
    """The microscope's photo; its address carries photoUpdatedAt, so a cached one is never stale."""
    photo = _service(mapper).getPhoto(microscopeId)
    return Response(content=bytes(photo["data"]), media_type=photo["contentType"],
                    headers={"Cache-Control": "private, max-age=86400"})


@router.put("/microscopes/{microscopeId}/photo", dependencies=[Depends(requireFacilityMode)])
async def uploadMicroscopePhoto(microscopeId: int, request: Request,
                                mapper: PostgresqlFlatMapper = Depends(getMapper),
                                currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    """Keep the image of the request body (PNG, JPEG or WebP) as the microscope's photo."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > PHOTO_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Photos may be up to %d MB" % (PHOTO_MAX_UPLOAD_BYTES // (1024 * 1024)))
    data = await request.body()
    microscope = await run_in_threadpool(_service(mapper).savePhoto, microscopeId, data)
    recordAudit(mapper, currentUser, "facility.microscopeUpdated", "microscope", microscopeId, microscope["name"],
                {"photo": "uploaded"})
    return microscope


@router.delete("/microscopes/{microscopeId}/photo", dependencies=[Depends(requireFacilityMode)])
def deleteMicroscopePhoto(microscopeId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                          currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    microscope = _service(mapper).deletePhoto(microscopeId)
    recordAudit(mapper, currentUser, "facility.microscopeUpdated", "microscope", microscopeId, microscope["name"],
                {"photo": "removed"})
    return microscope


@router.get("/samples", dependencies=[Depends(requireFacilityMode)])
def listSamples(q: str = Query("", max_length=100, description="Text in a sample's code or description"),
                mapper: PostgresqlFlatMapper = Depends(getMapper),
                currentUser: dict = Depends(requireFacilityStaff)) -> List[Dict[str, Any]]:
    """The samples, newest first, each with its boxes and grids."""
    return FacilitySampleService(mapper.db).listSamples(q)


@router.post("/samples", status_code=status.HTTP_201_CREATED, dependencies=[Depends(requireFacilityMode)])
def createSample(payload: SamplePayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                 currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    sample = FacilitySampleService(mapper.db).saveSample(payload.dict())
    recordAudit(mapper, currentUser, "facility.sampleCreated", "sample", sample["id"], sample["code"],
                _sampleSummary(sample))
    return sample


@router.put("/samples/{sampleId}", dependencies=[Depends(requireFacilityMode)])
def updateSample(sampleId: int, payload: SamplePayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                 currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    sample = FacilitySampleService(mapper.db).saveSample(payload.dict(), sampleId=sampleId)
    recordAudit(mapper, currentUser, "facility.sampleUpdated", "sample", sampleId, sample["code"],
                _sampleSummary(sample))
    return sample


@router.delete("/samples/{sampleId}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(requireFacilityMode)])
def deleteSample(sampleId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                 currentUser: dict = Depends(requireSampleKeeper)) -> None:
    sample = FacilitySampleService(mapper.db).deleteSample(sampleId)
    recordAudit(mapper, currentUser, "facility.sampleDeleted", "sample", sampleId, sample["code"],
                _sampleSummary(sample))


async def _addImage(ownerKind: str, ownerId: int, request: Request, caption: str, mapper: PostgresqlFlatMapper,
                    currentUser: dict) -> Dict[str, Any]:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > PHOTO_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Images may be up to %d MB" % (PHOTO_MAX_UPLOAD_BYTES // (1024 * 1024)))
    data = await request.body()
    added = await run_in_threadpool(FacilitySampleService(mapper.db).addImage, ownerKind, ownerId, data, caption,
                                    currentUser.get("id"))
    sample = added["sample"]
    recordAudit(mapper, currentUser, "facility.sampleUpdated", "sample", sample["id"], sample["code"],
                {"image": "added", "to": "%s %d" % (ownerKind, ownerId)})
    return added


@router.post("/samples/{sampleId}/images", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(requireFacilityMode)])
async def addSampleImage(sampleId: int, request: Request, caption: str = Query("", max_length=200),
                         mapper: PostgresqlFlatMapper = Depends(getMapper),
                         currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    """Keep the image of the request body (PNG, JPEG or WebP) with the sample."""
    return await _addImage("sample", sampleId, request, caption, mapper, currentUser)


@router.post("/boxes/{boxId}/images", status_code=status.HTTP_201_CREATED, dependencies=[Depends(requireFacilityMode)])
async def addBoxImage(boxId: int, request: Request, caption: str = Query("", max_length=200),
                      mapper: PostgresqlFlatMapper = Depends(getMapper),
                      currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    return await _addImage("box", boxId, request, caption, mapper, currentUser)


@router.post("/grids/{gridId}/images", status_code=status.HTTP_201_CREATED, dependencies=[Depends(requireFacilityMode)])
async def addGridImage(gridId: int, request: Request, caption: str = Query("", max_length=200),
                       mapper: PostgresqlFlatMapper = Depends(getMapper),
                       currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    return await _addImage("grid", gridId, request, caption, mapper, currentUser)


@router.get("/images/{imageId}", dependencies=[Depends(requireFacilityMode)])
def getFacilityImage(imageId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                     currentUser: dict = Depends(requireFacilityStaff)) -> Response:
    """An image of a sample, box or grid; an image never changes, so it is cached for good."""
    image = FacilitySampleService(mapper.db).getImage(imageId)
    return Response(content=bytes(image["data"]), media_type=image["contentType"],
                    headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.delete("/images/{imageId}", dependencies=[Depends(requireFacilityMode)])
def deleteFacilityImage(imageId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                        currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    """Remove an image; answers the sample or the session it was in."""
    image = FacilitySampleService(mapper.db).getImage(imageId)
    if image.get("sessionId") is not None:
        session = FacilitySessionService(mapper.db).deleteImage(imageId)
        recordAudit(mapper, currentUser, "facility.sessionUpdated", "session", session["id"], session["name"],
                    {"image": "removed", "imageId": imageId})
        return session
    sample = FacilitySampleService(mapper.db).deleteImage(imageId)
    recordAudit(mapper, currentUser, "facility.sampleUpdated", "sample", sample["id"], sample["code"],
                {"image": "removed", "imageId": imageId})
    return sample


# Sessions ------------------------------------------------------------------------------------------------
@router.get("/sessions", dependencies=[Depends(requireFacilityMode)])
def listSessions(q: str = Query("", max_length=100, description="Text in a session's name, booking, user or group"),
                 status_: str = Query("active", alias="status",
                                      description="active (planned and acquiring), all, or one status"),
                 mapper: PostgresqlFlatMapper = Depends(getMapper),
                 currentUser: dict = Depends(requireFacilityStaff)) -> List[Dict[str, Any]]:
    """The sessions, newest first, each with its datasets and their grids."""
    statuses = list(ACTIVE_STATUSES) if status_ == "active" else [] if status_ == "all" else [status_]
    return FacilitySessionService(mapper.db).listSessions(statuses, q)


@router.get("/sessions/{sessionId}", dependencies=[Depends(requireFacilityMode)])
def getSession(sessionId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
               currentUser: dict = Depends(requireFacilityStaff)) -> Dict[str, Any]:
    return FacilitySessionService(mapper.db).getSession(sessionId)


@router.post("/sessions", status_code=status.HTTP_201_CREATED, dependencies=[Depends(requireFacilityMode)])
def createSession(payload: SessionPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                  currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    session = FacilitySessionService(mapper.db).saveSession(payload.dict(), userId=currentUser.get("id"))
    recordAudit(mapper, currentUser, "facility.sessionCreated", "session", session["id"], session["name"],
                _sessionSummary(session))
    return session


@router.put("/sessions/{sessionId}", dependencies=[Depends(requireFacilityMode)])
def updateSession(sessionId: int, payload: SessionPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                  currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    service = FacilitySessionService(mapper.db)
    before = service.getSession(sessionId)
    session = service.saveSession(payload.dict(), sessionId=sessionId)
    changes = {key: value for key, value in _sessionSummary(session).items() if _sessionSummary(before).get(key) != value}
    if before["name"] != session["name"]:
        changes["name"] = {"from": before["name"], "to": session["name"]}
    recordAudit(mapper, currentUser, "facility.sessionUpdated", "session", sessionId, session["name"], changes)
    return session


@router.delete("/sessions/{sessionId}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(requireFacilityMode)])
def deleteSession(sessionId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                  currentUser: dict = Depends(requireSampleKeeper)) -> None:
    session = FacilitySessionService(mapper.db).deleteSession(sessionId)
    recordAudit(mapper, currentUser, "facility.sessionDeleted", "session", sessionId, session["name"],
                _sessionSummary(session))


async def _addSessionImage(ownerKind: str, ownerId: int, request: Request, caption: str,
                           mapper: PostgresqlFlatMapper, currentUser: dict) -> Dict[str, Any]:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > PHOTO_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Images may be up to %d MB" % (PHOTO_MAX_UPLOAD_BYTES // (1024 * 1024)))
    data = await request.body()
    added = await run_in_threadpool(FacilitySessionService(mapper.db).addImage, ownerKind, ownerId, data, caption,
                                    currentUser.get("id"))
    session = added["session"]
    recordAudit(mapper, currentUser, "facility.sessionUpdated", "session", session["id"], session["name"],
                {"image": "added", "to": "%s %d" % (ownerKind, ownerId)})
    return added


@router.post("/sessions/{sessionId}/images", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(requireFacilityMode)])
async def addSessionImage(sessionId: int, request: Request, caption: str = Query("", max_length=200),
                          mapper: PostgresqlFlatMapper = Depends(getMapper),
                          currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    """Keep the image of the request body (PNG, JPEG or WebP) with the session."""
    return await _addSessionImage("session", sessionId, request, caption, mapper, currentUser)


@router.post("/datasets/{datasetId}/images", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(requireFacilityMode)])
async def addDatasetImage(datasetId: int, request: Request, caption: str = Query("", max_length=200),
                          mapper: PostgresqlFlatMapper = Depends(getMapper),
                          currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    """Keep the image of the request body with a dataset (the ATLAS or a DATA_NN)."""
    return await _addSessionImage("dataset", datasetId, request, caption, mapper, currentUser)


@router.post("/datasets/{datasetId}/process", dependencies=[Depends(requireFacilityMode)])
def processDataset(datasetId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                   currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    """Make the project of a DATA now (the session processes by itself otherwise, or it failed); answers the session."""
    session = FacilitySessionService(mapper.db).queueProcessing(datasetId)
    recordAudit(mapper, currentUser, "facility.sessionUpdated", "session", session["id"], session["name"],
                {"processing": "queued", "datasetId": datasetId})
    return session
