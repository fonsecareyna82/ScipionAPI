"""A facility in ScipionWeb: its mode and its microscopes (see facility_service).

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
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

router = APIRouter(prefix="/facility", tags=["Facility"])


class PixelSizePayload(BaseModel):
    magnification: int
    pixelSize: float


class MicroscopePayload(BaseModel):
    name: str
    model: Optional[str] = ""
    status: str = "operational"
    detectors: Optional[str] = ""
    energyFilter: Optional[str] = ""
    acquisitionSoftware: Optional[str] = ""
    voltageKv: Optional[float] = None
    csMm: Optional[float] = None
    gainPath: Optional[str] = ""
    gainFlip: str = "none"
    gainRotation: int = 0
    offloadPath: Optional[str] = ""
    sessionsEnabled: bool = False
    notes: Optional[str] = ""
    pixelSizes: List[PixelSizePayload] = []


def requireFacilityStaff(currentUser: dict = Depends(getCurrentUser)) -> dict:
    """Any facility permission: the staff see the microscopes."""
    if not isFacilityStaff(currentUser):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This is for the facility staff")
    return currentUser


def requireSampleKeeper(currentUser: dict = Depends(getCurrentUser)) -> dict:
    """Who records samples and grids: the staff who run sessions, and the facility managers."""
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


def _sampleSummary(sample: Dict[str, Any]) -> Dict[str, Any]:
    """What the audit log keeps of a sample."""
    boxes = sample.get("boxes") or []
    return {"boxes": len(boxes), "grids": sum(len(box.get("grids") or []) for box in boxes)}


def _service(mapper: PostgresqlFlatMapper) -> FacilityService:
    return FacilityService(mapper.db)


def _summary(microscope: Dict[str, Any]) -> Dict[str, Any]:
    """What the audit log keeps of a microscope."""
    return {"status": microscope["status"], "sessionsEnabled": bool(microscope["sessionsEnabled"]),
            "pixelSizes": {str(row["magnification"]): row["pixelSize"] for row in microscope.get("pixelSizes") or []}}


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
