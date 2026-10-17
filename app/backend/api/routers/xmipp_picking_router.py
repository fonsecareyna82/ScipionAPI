"""Routes of the web session of Xmipp's particle picker (one per protocol)."""
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header, Query, status
from pydantic import BaseModel, Field

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.services.xmipp_picking_session_service import XmippPickingSessionService
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

router = APIRouter(prefix="/projects", tags=["xmipp-picking"])


class PickingPointPayload(BaseModel):
    id: Optional[str] = None
    x: float
    y: float


class PickingParticlesPayload(BaseModel):
    coordinates: List[PickingPointPayload] = Field(default_factory=list)
    threshold: Optional[float] = None


class PickingSettingsPayload(BaseModel):
    particleSize: Optional[int] = None


def getPickingService() -> XmippPickingSessionService:
    return XmippPickingSessionService()


@router.get("/{projectId}/protocols/{protocolId}/picking/session", response_model=Any)
def getPickingSession(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: XmippPickingSessionService = Depends(getPickingService),
):
    return service.describeSession(mapper, projectId, protocolId, currentUser)


@router.put("/{projectId}/protocols/{protocolId}/picking/settings", response_model=Any)
def savePickingSettings(
    projectId: int,
    protocolId: int,
    payload: PickingSettingsPayload,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: XmippPickingSessionService = Depends(getPickingService),
):
    return service.saveSettings(mapper, projectId, protocolId, currentUser,
                                particleSize=payload.particleSize)


@router.get("/{projectId}/protocols/{protocolId}/picking/micrographs/{micId}/coordinates",
            response_model=Any)
def getPickingParticles(
    projectId: int,
    protocolId: int,
    micId: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: XmippPickingSessionService = Depends(getPickingService),
):
    return service.listParticles(mapper, projectId, protocolId, currentUser, micId)


@router.put("/{projectId}/protocols/{protocolId}/picking/micrographs/{micId}/coordinates",
            response_model=Any)
def savePickingParticles(
    projectId: int,
    protocolId: int,
    micId: str,
    payload: PickingParticlesPayload,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: XmippPickingSessionService = Depends(getPickingService),
):
    return service.saveParticles(mapper, projectId, protocolId, currentUser, micId,
                                 [point.dict() for point in payload.coordinates],
                                 threshold=payload.threshold)


@router.get("/{projectId}/protocols/{protocolId}/picking/micrographs/{micId}/image")
def getPickingMicrographImage(
    projectId: int,
    protocolId: int,
    micId: str,
    size: int = Query(2200, ge=32, le=8192),
    format: str = Query("png"),
    ifNoneMatch: Optional[str] = Header(None, alias="If-None-Match"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: XmippPickingSessionService = Depends(getPickingService),
):
    return service.renderMicrographImage(mapper, projectId, protocolId, currentUser, micId,
                                         size=size, fmt=format, ifNoneMatch=ifNoneMatch)


@router.post("/{projectId}/protocols/{protocolId}/picking/coordinates", response_model=Any,
             status_code=status.HTTP_200_OK)
def createPickingCoordinates(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: XmippPickingSessionService = Depends(getPickingService),
):
    return service.createCoordinates(mapper, projectId, protocolId, currentUser)


@router.get("/{projectId}/picking/open-sessions", response_model=Any)
def listOpenPickingSessions(
    projectId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: XmippPickingSessionService = Depends(getPickingService),
):
    """Picking protocols waiting for their picker to be opened in the web."""
    return service.listOpenSessions(mapper, projectId, currentUser)


@router.post("/{projectId}/protocols/{protocolId}/picking/close", response_model=Any)
def closePickingSession(
    projectId: int,
    protocolId: int,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: XmippPickingSessionService = Depends(getPickingService),
):
    """The picker was closed: the protocol's interactive step finishes."""
    return service.closeWebSession(mapper, projectId, protocolId, currentUser)


class PickingNextPayload(BaseModel):
    nextMicId: Optional[str] = None


@router.post("/{projectId}/protocols/{protocolId}/picking/micrographs/{micId}/train",
             response_model=Any)
def trainPickingClassifier(
    projectId: int,
    protocolId: int,
    micId: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: XmippPickingSessionService = Depends(getPickingService),
):
    """Train Xmipp's picker with the manual particles and autopick this micrograph."""
    return service.trainAndAutopick(mapper, projectId, protocolId, currentUser, micId)


@router.post("/{projectId}/protocols/{protocolId}/picking/micrographs/{micId}/next",
             response_model=Any)
def correctAndAutopickNext(
    projectId: int,
    protocolId: int,
    micId: str,
    payload: PickingNextPayload,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: XmippPickingSessionService = Depends(getPickingService),
):
    """Learn from this micrograph's corrections and autopick the next one."""
    return service.correctAndAutopick(mapper, projectId, protocolId, currentUser, micId,
                                      payload.nextMicId)
