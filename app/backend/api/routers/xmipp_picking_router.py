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
    x: float
    y: float


class PickingParticlesPayload(BaseModel):
    coordinates: List[PickingPointPayload] = Field(default_factory=list)


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
                                 [point.dict() for point in payload.coordinates])


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
