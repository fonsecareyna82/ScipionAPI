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
from app.backend.api.services.facility_settings_service import FacilitySettingsService
from app.backend.api.services.facility_alerts import FacilityAlerts
from app.backend.api.services.facility_mail import FacilityMail
from app.backend.api.services.facility_room import FacilityRoom
from app.backend.api.services.facility_booking_service import FacilityBookingService, isBookingStaff
from app.backend.api.services import facility_navigation as navigation
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
    # How its sessions name their folders (facility_conventions); None keeps the defaults
    code: Optional[str] = ""
    dataFolderPattern: Optional[str] = None
    atlasFolderPattern: Optional[str] = None
    gridSlots: int = 12
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
    # What the technician tells its user (and the group's PI)
    userNotes: Optional[str] = ""
    # One project for all its DATA (each its own branch) instead of one per DATA
    oneProject: bool = False
    # Its CTF limits (A), written into its DATA's CTF consensus; None keeps the template's
    ctfMinDefocus: Optional[float] = None
    ctfMaxDefocus: Optional[float] = None
    ctfMaxResolution: Optional[float] = None
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


@router.get("/my-sessions", dependencies=[Depends(requireFacilityMode)])
def listMySessions(mapper: PostgresqlFlatMapper = Depends(getMapper),
                   currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    """Any signed-in user's sessions and samples (and those of the groups they are the PI of), read only, with how
    long their data are kept and how to take them home."""
    return FacilitySessionService(mapper.db).sessionsOf(currentUser)


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
    if before["status"] != "finished" and session["status"] == "finished":
        # A tomography session that finishes gets the navigation report of each DATA (when tomo5-mapper is there)
        navigation.reportsWhenFinished(session)
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


# Settings: the facility's own conventions ---------------------------------------------------------------
class SettingsPayload(BaseModel):
    # The pattern of a session's name, e.g. {date:%Y_%m_%d}_{user}_{id:06d}
    sessionNamePattern: Optional[str] = None
    # Days the data are kept once the session finished (0: not said), and how to take them home
    rawRetentionDays: Optional[int] = None
    processedRetentionDays: Optional[int] = None
    downloadInstructions: Optional[str] = None
    # Policies (the CNB's by default): who owns a DATA's project and how its user and group see it, the
    # calibration's tolerance (%), the minutes a DATA may go without movies, the watcher's seconds between looks
    projectOwner: Optional[str] = None
    projectShareLevel: Optional[str] = None
    calibrationTolerancePercent: Optional[float] = None
    stallMinutes: Optional[int] = None
    watchSeconds: Optional[int] = None
    # The CTF limits a new session starts with (A)
    ctfMinDefocus: Optional[float] = None
    ctfMaxDefocus: Optional[float] = None
    ctfMaxResolution: Optional[float] = None


class ConventionsPreviewPayload(BaseModel):
    sessionNamePattern: Optional[str] = None
    dataFolderPattern: Optional[str] = None
    atlasFolderPattern: Optional[str] = None
    microscopeCode: Optional[str] = None


@router.get("/settings", dependencies=[Depends(requireFacilityMode)])
def getFacilitySettings(mapper: PostgresqlFlatMapper = Depends(getMapper),
                        currentUser: dict = Depends(requireFacilityStaff)) -> Dict[str, Any]:
    """The facility's settings (over the defaults), what they make for an example session, and the presets."""
    return FacilitySettingsService(mapper.db).getSettings()


@router.put("/settings", dependencies=[Depends(requireFacilityMode)])
def saveFacilitySettings(payload: SettingsPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                         currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    settings = FacilitySettingsService(mapper.db).saveSettings(payload.dict(), userId=currentUser.get("id"))
    recordAudit(mapper, currentUser, "facility.settingsUpdated", "facility", None, "settings",
                {key: value for key, value in payload.dict().items() if value is not None})
    return settings


@router.post("/settings/preview", dependencies=[Depends(requireFacilityMode)])
def previewFacilityConventions(payload: ConventionsPreviewPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                               currentUser: dict = Depends(requireFacilityStaff)) -> Dict[str, Any]:
    """What patterns make for an example session (the session, its ATLAS and two DATA); 400 for a wrong one."""
    return FacilitySettingsService(mapper.db).preview(payload.dict())


# Alerts: what went wrong in the sessions, and the mail that tells the operators -----------------------------
class MailSettingsPayload(BaseModel):
    host: Optional[str] = ""
    port: Optional[int] = 587
    security: str = "starttls"
    user: Optional[str] = ""
    # None keeps the password there is; "" removes it
    password: Optional[str] = None
    sender: Optional[str] = ""
    # Mail addresses separated by commas; empty: every user who runs sessions
    recipients: Optional[str] = ""


class TestMailPayload(BaseModel):
    to: Optional[str] = ""


@router.get("/alerts", dependencies=[Depends(requireFacilityMode)])
def listFacilityAlerts(all_: bool = Query(False, alias="all", description="Also the resolved ones (the newest 200)"),
                       mapper: PostgresqlFlatMapper = Depends(getMapper),
                       currentUser: dict = Depends(requireFacilityStaff)) -> List[Dict[str, Any]]:
    """The open alerts of the facility's sessions, newest first."""
    return FacilityAlerts(mapper.db).listAlerts(openOnly=not all_)


@router.post("/alerts/{alertId}/acknowledge", dependencies=[Depends(requireFacilityMode)])
def acknowledgeFacilityAlert(alertId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                             currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    """Say who is on an alert."""
    alert = FacilityAlerts(mapper.db).acknowledge(alertId, currentUser.get("id"))
    recordAudit(mapper, currentUser, "facility.alertAcknowledged", "session", alert["sessionId"], alert["sessionName"],
                {"alertId": alertId, "kind": alert["kind"]})
    return alert


@router.get("/settings/mail", dependencies=[Depends(requireFacilityMode)])
def getFacilityMailSettings(mapper: PostgresqlFlatMapper = Depends(getMapper),
                            currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    """The mail server of the alerts (its password only as whether there is one)."""
    return FacilityMail(mapper.db).getSettings()


@router.put("/settings/mail", dependencies=[Depends(requireFacilityMode)])
def saveFacilityMailSettings(payload: MailSettingsPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                             currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    settings = FacilityMail(mapper.db).saveSettings(payload.dict(), userId=currentUser.get("id"))
    recordAudit(mapper, currentUser, "facility.settingsUpdated", "facility", None, "mail",
                {key: value for key, value in payload.dict().items() if key != "password"})
    return settings


@router.post("/settings/mail/test", dependencies=[Depends(requireFacilityMode)])
def sendFacilityTestMail(payload: TestMailPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                         currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    """Send a test mail (to the given address, else to the alerts' recipients); 400 says why it did not go."""
    return FacilityMail(mapper.db).sendTest(payload.to)


# The room's screen: opened with its link's token, no signed-in user -----------------------------------------
@router.get("/room", dependencies=[Depends(requireFacilityMode)])
def getRoomScreen(token: str = Query("", max_length=200), mapper: PostgresqlFlatMapper = Depends(getMapper)
                  ) -> Dict[str, Any]:
    """Each microscope's state and session, and the sessions of the next days (names and states only)."""
    room = FacilityRoom(mapper.db)
    room.checkToken(token)
    return room.view()


@router.get("/room/microscopes/{microscopeId}/photo", dependencies=[Depends(requireFacilityMode)])
def getRoomMicroscopePhoto(microscopeId: int, token: str = Query("", max_length=200),
                           mapper: PostgresqlFlatMapper = Depends(getMapper)) -> Response:
    room = FacilityRoom(mapper.db)
    room.checkToken(token)
    photo = room.photo(microscopeId)
    return Response(content=bytes(photo["data"]), media_type=photo["contentType"],
                    headers={"Cache-Control": "private, max-age=3600"})


@router.get("/settings/room-screen", dependencies=[Depends(requireFacilityMode)])
def getRoomScreenLink(mapper: PostgresqlFlatMapper = Depends(getMapper),
                      currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    """The room screen's link (its token), or that it is off."""
    return FacilityRoom(mapper.db).link()


@router.post("/settings/room-screen", dependencies=[Depends(requireFacilityMode)])
def makeRoomScreenLink(mapper: PostgresqlFlatMapper = Depends(getMapper),
                       currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    """A new link for the room screen; the old one stops working."""
    link = FacilityRoom(mapper.db).newLink(currentUser.get("id"))
    recordAudit(mapper, currentUser, "facility.settingsUpdated", "facility", None, "room screen", {"link": "new"})
    return link


@router.delete("/settings/room-screen", dependencies=[Depends(requireFacilityMode)])
def turnOffRoomScreen(mapper: PostgresqlFlatMapper = Depends(getMapper),
                      currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    link = FacilityRoom(mapper.db).turnOff(currentUser.get("id"))
    recordAudit(mapper, currentUser, "facility.settingsUpdated", "facility", None, "room screen", {"link": "off"})
    return link


# Bookings ------------------------------------------------------------------------------------------
class ResourcePayload(BaseModel):
    name: str
    microscopeId: Optional[int] = None
    color: Optional[str] = ""
    unit: str = "session"
    minHours: Optional[float] = None
    maxHours: Optional[float] = None
    dayStart: str = "09:00"
    requiresAuthorization: bool = False
    active: bool = True
    notes: Optional[str] = ""


class BookingPayload(BaseModel):
    resourceId: Optional[int] = None
    kind: Optional[str] = None
    # With their time zone: 2026-11-05T09:00:00+01:00
    startsAt: Optional[str] = None
    endsAt: Optional[str] = None
    title: Optional[str] = None
    ownerId: Optional[int] = None
    groupId: Optional[int] = None
    operatorId: Optional[int] = None
    technique: Optional[str] = None
    priority: Optional[int] = None
    justification: Optional[str] = None
    notes: Optional[str] = None


class BookingDecisionPayload(BaseModel):
    # confirm, propose (another time: proposedStartsAt/proposedEndsAt) or reject
    action: str
    reason: Optional[str] = ""
    proposedStartsAt: Optional[str] = None
    proposedEndsAt: Optional[str] = None
    priority: Optional[int] = None


class BookingAnswerPayload(BaseModel):
    accept: bool


class BookingCancelPayload(BaseModel):
    reason: Optional[str] = ""


def _bookings(mapper: PostgresqlFlatMapper) -> FacilityBookingService:
    return FacilityBookingService(mapper.db)


def _bookingSummary(booking: Dict[str, Any]) -> Dict[str, Any]:
    """What the audit log keeps of a booking."""
    return {"resource": booking["resourceName"], "kind": booking["kind"], "status": booking["status"],
            "startsAt": str(booking["startsAt"]), "endsAt": str(booking["endsAt"]),
            "owner": booking.get("ownerEmail"), "reason": booking.get("decisionReason") or None,
            "session": booking.get("sessionName")}


def _bookingName(booking: Dict[str, Any]) -> str:
    return "%s, %s" % (booking["resourceName"], str(booking["startsAt"])[:16])


@router.get("/resources", dependencies=[Depends(requireFacilityMode)])
def listResources(mapper: PostgresqlFlatMapper = Depends(getMapper),
                  currentUser: dict = Depends(getCurrentUser)) -> List[Dict[str, Any]]:
    """What can be booked: every resource for the facility, the ones in use for a user."""
    return _bookings(mapper).listResources(currentUser)


@router.post("/resources", status_code=status.HTTP_201_CREATED, dependencies=[Depends(requireFacilityMode)])
def createResource(payload: ResourcePayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                   currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    resource = _bookings(mapper).saveResource(payload.dict())
    recordAudit(mapper, currentUser, "facility.resourceCreated", "resource", resource["id"], resource["name"],
                {"unit": resource["unit"], "minHours": resource["minHours"], "maxHours": resource["maxHours"]})
    return resource


@router.put("/resources/{resourceId}", dependencies=[Depends(requireFacilityMode)])
def updateResource(resourceId: int, payload: ResourcePayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                   currentUser: dict = Depends(requirePermission("facility.manage"))) -> Dict[str, Any]:
    service = _bookings(mapper)
    before = service.getResource(resourceId)
    resource = service.saveResource(payload.dict(), resourceId)
    changes = {key: resource[key] for key in ("name", "unit", "minHours", "maxHours", "dayStart", "active",
                                              "microscopeId", "requiresAuthorization") if before[key] != resource[key]}
    recordAudit(mapper, currentUser, "facility.resourceUpdated", "resource", resourceId, resource["name"], changes)
    return resource


@router.delete("/resources/{resourceId}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(requireFacilityMode)])
def deleteResource(resourceId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                   currentUser: dict = Depends(requirePermission("facility.manage"))) -> Response:
    resource = _bookings(mapper).deleteResource(resourceId)
    recordAudit(mapper, currentUser, "facility.resourceDeleted", "resource", resourceId, resource["name"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/bookings", dependencies=[Depends(requireFacilityMode)])
def listBookings(start: Optional[str] = None, end: Optional[str] = None,
                 resourceId: Optional[List[int]] = Query(None), status_: Optional[List[str]] = Query(None, alias="status"),
                 mapper: PostgresqlFlatMapper = Depends(getMapper),
                 currentUser: dict = Depends(getCurrentUser)) -> List[Dict[str, Any]]:
    """The bookings in a time (the calendar): the facility sees them all; a user, theirs and when the others are."""
    return _bookings(mapper).listBookings(currentUser, start, end, resourceId, status_)


@router.get("/my-bookings", dependencies=[Depends(requireFacilityMode)])
def myBookings(mapper: PostgresqlFlatMapper = Depends(getMapper),
               currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    return _bookings(mapper).myBookings(currentUser)


@router.get("/bookings/{bookingId}", dependencies=[Depends(requireFacilityMode)])
def getBooking(bookingId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
               currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    return _bookings(mapper).bookingFor(bookingId, currentUser)


@router.post("/bookings", status_code=status.HTTP_201_CREATED, dependencies=[Depends(requireFacilityMode)])
def createBooking(payload: BookingPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                  currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    """A user asks for time; the facility books (or blocks) at once."""
    service = _bookings(mapper)
    booking = service.create(payload.dict(exclude_unset=True), currentUser)
    action = "facility.bookingCreated" if isBookingStaff(currentUser) else "facility.bookingRequested"
    recordAudit(mapper, currentUser, action, "booking", booking["id"], _bookingName(booking), _bookingSummary(booking))
    if booking.get("ownerId") is not None and int(booking["ownerId"]) != int(currentUser["id"]):
        service.notify(booking, "was booked for you by the facility")
    return booking


@router.put("/bookings/{bookingId}", dependencies=[Depends(requireFacilityMode)])
def updateBooking(bookingId: int, payload: BookingPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                  currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    service = _bookings(mapper)
    before = service.getBooking(bookingId)
    booking = service.update(bookingId, payload.dict(exclude_unset=True), currentUser)
    changes = {key: str(booking[key]) for key in ("resourceName", "startsAt", "endsAt", "kind", "ownerEmail",
                                                  "groupName", "priority") if booking.get(key) != before.get(key)}
    recordAudit(mapper, currentUser, "facility.bookingUpdated", "booking", bookingId, _bookingName(booking), changes)
    moved = any(key in changes for key in ("resourceName", "startsAt", "endsAt"))
    if moved and booking["status"] == "confirmed" and booking.get("ownerId") is not None \
            and int(booking["ownerId"]) != int(currentUser["id"]):
        service.notify(booking, "was moved by the facility")
    return booking


@router.post("/bookings/{bookingId}/decision", dependencies=[Depends(requireFacilityMode)])
def decideBooking(bookingId: int, payload: BookingDecisionPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                  currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    """The facility confirms a request, offers another time, or rejects it."""
    service = _bookings(mapper)
    booking = service.decide(bookingId, payload.dict(exclude_unset=True), currentUser)
    recordAudit(mapper, currentUser, "facility.booking" + {"confirm": "Confirmed", "propose": "Alternative",
                                                           "reject": "Rejected"}[payload.action],
                "booking", bookingId, _bookingName(booking), _bookingSummary(booking))
    service.notify(booking, {"confirm": "is confirmed", "propose": "cannot be at that time",
                             "reject": "was not accepted"}[payload.action])
    return booking


@router.post("/bookings/{bookingId}/answer", dependencies=[Depends(requireFacilityMode)])
def answerBooking(bookingId: int, payload: BookingAnswerPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                  currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    """The user takes, or not, the other time the facility offered."""
    booking = _bookings(mapper).answer(bookingId, payload.accept, currentUser)
    recordAudit(mapper, currentUser, "facility.booking" + ("AlternativeAccepted" if payload.accept
                                                           else "AlternativeDeclined"),
                "booking", bookingId, _bookingName(booking), _bookingSummary(booking))
    return booking


@router.post("/bookings/{bookingId}/cancel", dependencies=[Depends(requireFacilityMode)])
def cancelBooking(bookingId: int, payload: BookingCancelPayload, mapper: PostgresqlFlatMapper = Depends(getMapper),
                  currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    service = _bookings(mapper)
    booking = service.cancel(bookingId, payload.reason or "", currentUser)
    recordAudit(mapper, currentUser, "facility.bookingCancelled", "booking", bookingId, _bookingName(booking),
                _bookingSummary(booking))
    if booking.get("ownerId") is not None and int(booking["ownerId"]) != int(currentUser["id"]):
        service.notify(booking, "was cancelled by the facility")
    return booking


# Navigation reports (tomo5-mapper) ------------------------------------------------------------------
def _datasetOfSession(mapper: PostgresqlFlatMapper, datasetId: int, currentUser: dict):
    """A DATA and its session, for the facility's staff and for the session's user and its group's PI."""
    service = FacilitySessionService(mapper.db)
    sessionId = service.mapper.sessionIdOf("dataset", datasetId)
    if sessionId is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such DATA")
    session = service.getSession(sessionId)
    if not isFacilityStaff(currentUser):
        own = session.get("userId") is not None and int(session["userId"]) == int(currentUser["id"])
        led = session.get("groupId") is not None and int(session["groupId"]) in service.mapper.piGroupIds(
            int(currentUser["id"]))
        if not (own or led):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such DATA")
    dataset = next(item for item in session["datasets"] if int(item["id"]) == int(datasetId))
    return session, dataset


@router.get("/datasets/{datasetId}/navigation", dependencies=[Depends(requireFacilityMode)])
def getNavigation(datasetId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                  currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    session, dataset = _datasetOfSession(mapper, datasetId, currentUser)
    return navigation.navigationOf(session, dataset)


@router.post("/datasets/{datasetId}/navigation", dependencies=[Depends(requireFacilityMode)])
def makeNavigation(datasetId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                   currentUser: dict = Depends(requireSampleKeeper)) -> Dict[str, Any]:
    """Make (again) a tomography DATA's navigation report, in the background."""
    session, dataset = _datasetOfSession(mapper, datasetId, currentUser)
    made = navigation.startReport(session, dataset)
    recordAudit(mapper, currentUser, "facility.navigationReportRequested", "session", session["id"], session["name"],
                {"folder": dataset["folder"]})
    return made


@router.get("/datasets/{datasetId}/navigation/report", dependencies=[Depends(requireFacilityMode)])
def getNavigationReport(datasetId: int, mapper: PostgresqlFlatMapper = Depends(getMapper),
                        currentUser: dict = Depends(getCurrentUser)) -> Response:
    session, dataset = _datasetOfSession(mapper, datasetId, currentUser)
    report = navigation.reportPath(session, dataset)
    return Response(content=report.read_bytes(), media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "private, no-store",
                             "Content-Disposition": 'inline; filename="%s"' % report.name})

