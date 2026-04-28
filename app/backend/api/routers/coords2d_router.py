# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, status

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.services.coords2d_service import Coords2dService
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["coordinates2d"])


def getCoords2dService() -> Coords2dService:
    return Coords2dService()


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords2d/micrographs",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def listCoords2dMicrographs(
    projectId: int,
    protocolId: int,
    outputName: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: Coords2dService = Depends(getCoords2dService),
):
    return service.listMicrographs(
        mapper=mapper,
        projectId=projectId,
        currentUser=currentUser,
        protocolId=protocolId,
        outputName=outputName,
    )


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords2d/micrographs/{micId}/coordinates",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getCoords2dMicrographCoordinates(
    projectId: int,
    protocolId: int,
    outputName: str,
    micId: str,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: Coords2dService = Depends(getCoords2dService),
):
    return service.listCoordinatesForMicrograph(
        mapper=mapper,
        projectId=projectId,
        currentUser=currentUser,
        protocolId=protocolId,
        outputName=outputName,
        micId=micId,
    )


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords2d/micrographs/{micId}/image",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getCoords2dMicrographImage(
    projectId: int,
    protocolId: int,
    outputName: str,
    micId: str,
    size: int = Query(2200, ge=64, le=4096),
    format: str = Query("png", pattern="^(png|webp|jpeg|jpg)$"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: Coords2dService = Depends(getCoords2dService),
):
    return service.renderMicrographImage(
        mapper=mapper,
        projectId=projectId,
        currentUser=currentUser,
        protocolId=protocolId,
        outputName=outputName,
        micId=micId,
        size=size,
        fmt=format,
    )


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords2d/micrographs/{micId}/thumbnail",
    response_model=Any,
    status_code=status.HTTP_200_OK,
)
def getCoords2dMicrographThumbnail(
    projectId: int,
    protocolId: int,
    outputName: str,
    micId: str,
    size: int = Query(180, ge=32, le=512),
    format: str = Query("png", pattern="^(png|webp|jpeg|jpg)$"),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: Coords2dService = Depends(getCoords2dService),
):
    return service.renderMicrographImage(
        mapper=mapper,
        projectId=projectId,
        currentUser=currentUser,
        protocolId=protocolId,
        outputName=outputName,
        micId=micId,
        size=size,
        fmt=format,
    )
