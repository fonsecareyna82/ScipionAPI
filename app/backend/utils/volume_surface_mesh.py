from typing import Any, Dict, Optional, Tuple

import numpy as np
from fastapi import HTTPException


def _cleanVolume(volume: np.ndarray) -> np.ndarray:
    arr = np.asarray(volume, dtype=np.float32)
    if arr.ndim != 3:
        raise HTTPException(status_code=500, detail="Expected a 3D volume")

    finiteMask = np.isfinite(arr)
    if finiteMask.all():
        return arr

    if finiteMask.any():
        fillValue = float(np.nanmedian(arr[finiteMask]))
    else:
        fillValue = 0.0

    return np.where(finiteMask, arr, fillValue).astype(np.float32, copy=False)


def _autoIsoLevel(volume: np.ndarray) -> float:
    values = volume[np.isfinite(volume)]
    if values.size == 0:
        raise HTTPException(status_code=422, detail="Volume does not contain finite values")

    vmin = float(values.min())
    vmax = float(values.max())
    if vmax <= vmin:
        raise HTTPException(status_code=422, detail="Volume has constant values")

    mean = float(values.mean())
    std = float(values.std())
    sigmaLevel = mean + (2.5 * std)
    percentileLevel = float(np.percentile(values, 99.5))

    level = max(sigmaLevel, percentileLevel)
    if not np.isfinite(level) or level <= vmin or level >= vmax:
        level = float(np.percentile(values, 99.0))

    if not np.isfinite(level) or level <= vmin or level >= vmax:
        level = (vmin + vmax) * 0.5

    return float(level)


def _validateIsoLevel(volume: np.ndarray, level: Optional[float]) -> float:
    values = volume[np.isfinite(volume)]
    if values.size == 0:
        raise HTTPException(status_code=422, detail="Volume does not contain finite values")

    vmin = float(values.min())
    vmax = float(values.max())

    if level is None:
        level = _autoIsoLevel(volume)

    level = float(level)
    if not np.isfinite(level):
        raise HTTPException(status_code=422, detail="Invalid iso level")

    if level <= vmin or level >= vmax:
        raise HTTPException(
            status_code=422,
            detail=f"Iso level {level:g} is outside the volume range [{vmin:g}, {vmax:g}]",
        )

    return level


def buildVolumeSurfaceMesh(
    volume: np.ndarray,
    *,
    level: Optional[float] = None,
    spacing: Optional[Tuple[float, float, float]] = None,
    maxTriangles: int = 350000,
) -> Dict[str, Any]:
    arr = _cleanVolume(volume)
    levelValue = _validateIsoLevel(arr, level)

    try:
        from skimage.measure import marching_cubes
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"scikit-image is required to generate volume surface meshes: {exc}",
        )

    zSpacing, ySpacing, xSpacing = spacing or (1.0, 1.0, 1.0)

    try:
        verts, faces, normals, values = marching_cubes(
            arr,
            level=levelValue,
            spacing=(float(zSpacing), float(ySpacing), float(xSpacing)),
            allow_degenerate=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build surface mesh: {exc}")

    if faces.size == 0 or verts.size == 0:
        raise HTTPException(status_code=422, detail="No surface could be generated for this level")

    triangleCount = int(faces.shape[0])
    if triangleCount > maxTriangles:
        step = int(np.ceil(triangleCount / float(maxTriangles)))
        faces = faces[::step]
        triangleCount = int(faces.shape[0])

    # marching_cubes returns coordinates in Z,Y,X. The frontend expects X,Y,Z.
    verticesXyz = verts[:, [2, 1, 0]].astype(np.float32, copy=False)
    normalsXyz = normals[:, [2, 1, 0]].astype(np.float32, copy=False)

    center = verticesXyz.mean(axis=0)
    verticesXyz = verticesXyz - center

    extent = np.ptp(verticesXyz, axis=0)
    maxExtent = float(np.max(extent)) if extent.size else 1.0
    if maxExtent > 0 and np.isfinite(maxExtent):
        verticesXyz = verticesXyz / maxExtent

    return {
        "kind": "surfaceMesh",
        "level": float(levelValue),
        "dims": [int(arr.shape[0]), int(arr.shape[1]), int(arr.shape[2])],
        "order": "zyx",
        "vertexCount": int(verticesXyz.shape[0]),
        "triangleCount": triangleCount,
        "vertices": verticesXyz.reshape(-1).astype(np.float32).tolist(),
        "normals": normalsXyz.reshape(-1).astype(np.float32).tolist(),
        "indices": faces.reshape(-1).astype(np.int32).tolist(),
        "values": np.asarray(values, dtype=np.float32).reshape(-1).tolist(),
        "center": center.astype(np.float32).tolist(),
        "scale": maxExtent,
    }
