import logging
from typing import Any, Dict, Literal, Optional, Union

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.services.project_service import ProjectService
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.utils.volume_surface_mesh import buildVolumeSurfaceMesh
from app.backend.utils.volume_utils import readVolumeArray3d

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


def getProjectService() -> ProjectService:
    return ProjectService()


def _strideDownsampleVolume(volume: np.ndarray, maxDim: int) -> np.ndarray:
    z, y, x = volume.shape
    largestDim = max(z, y, x)
    if largestDim <= maxDim:
        return volume.astype(np.float32, copy=False)

    step = max(1, int(np.ceil(largestDim / float(maxDim))))
    return volume[::step, ::step, ::step].astype(np.float32, copy=False)


def _downsampleVolumeForSurface(
    service: ProjectService,
    volume: np.ndarray,
    *,
    maxDim: int,
    method: str,
) -> np.ndarray:
    methodLower = (method or "stride").lower()

    if methodLower == "none":
        return volume.astype(np.float32, copy=False)

    if methodLower == "stride":
        return _strideDownsampleVolume(volume, maxDim=maxDim)

    return service._downsampleVolumePreview(volume, maxDim=maxDim, method=methodLower)


@router.get(
    "/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/surface",
    response_model=Any,
    status_code=status.HTTP_200_OK,
    summary="Get a real marching-cubes surface mesh for a volume",
)
def getVolumeSurfaceMesh(
    projectId: int,
    protocolId: int,
    outputName: str,
    volumeId: Union[int, str],
    level: Optional[float] = Query(None, description="Absolute iso level. If omitted, an automatic level is used."),
    maxDim: int = Query(192, ge=32, le=512, alias="maxDim"),
    method: Literal["binning", "stride", "linear", "fourier", "none"] = Query("stride"),
    maxTriangles: int = Query(350000, ge=1000, le=1500000, alias="maxTriangles"),
    currentUser: Dict[str, Any] = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
):
    project = service.getProjectById(mapper, projectId, currentUser, refresh=False, checkPid=False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        _protocol, output = service._resolveOutputForVolumes(protocolId, outputName)
        volumePath = service._getVolumePathFromOutput(output, volumeId)

        volume, _props = readVolumeArray3d(volumePath)
        volumeSmall = _downsampleVolumeForSurface(
            service,
            volume,
            maxDim=maxDim,
            method=method,
        )

        mesh = buildVolumeSurfaceMesh(
            volumeSmall,
            level=level,
            maxTriangles=maxTriangles,
        )

        mesh["sourceDims"] = [int(volume.shape[0]), int(volume.shape[1]), int(volume.shape[2])]
        mesh["maxDim"] = int(maxDim)
        mesh["method"] = method
        mesh["volumeId"] = str(volumeId)
        mesh["outputName"] = outputName

        response = JSONResponse(mesh)
        response.headers["X-Debug-Auth"] = "ok"
        response.headers["X-Debug-UserId"] = str(getattr(currentUser, "id", currentUser.get("id", "")))
        response.headers["Vary"] = "Authorization"
        return response

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to generate volume surface mesh")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate volume surface mesh: {exc}",
        )
