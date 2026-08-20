from typing import Any, Dict, Optional, Tuple

import numpy as np
from fastapi import HTTPException


def _cleanVolume(volume: np.ndarray) -> np.ndarray:
    arr = np.asarray(volume, dtype=np.float32)

    if arr.ndim != 3:
        raise HTTPException(status_code=500, detail="Expected a 3D volume")

    finiteMask = np.isfinite(arr)

    if finiteMask.all():
        return np.array(arr, dtype=np.float32, copy=True, order="C")

    if finiteMask.any():
        fillValue = float(np.nanmedian(arr[finiteMask]))
    else:
        fillValue = 0.0

    cleaned = np.where(finiteMask, arr, fillValue)
    return np.array(cleaned, dtype=np.float32, copy=True, order="C")


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


def _runMarchingCubes(
    volume: np.ndarray,
    *,
    level: float,
    spacing: Tuple[float, float, float],
    maxTriangles: int,
):
    from skimage.measure import marching_cubes

    maxStep = max(1, min(16, min(volume.shape) - 1))
    stepSize = 1
    lastValid = None

    while True:
        try:
            result = marching_cubes(
                volume,
                level=level,
                spacing=spacing,
                step_size=stepSize,
                allow_degenerate=False,
            )
        except ValueError:
            if lastValid is not None:
                return (*lastValid, stepSize - 1)
            raise

        verts, faces, normals, values = result
        lastValid = result

        triangleCount = int(faces.shape[0])

        if triangleCount <= maxTriangles or stepSize >= maxStep:
            return verts, faces, normals, values, stepSize

        ratio = triangleCount / float(maxTriangles)
        nextStep = max(
            stepSize + 1,
            int(np.ceil(stepSize * np.sqrt(ratio))),
        )

        stepSize = min(maxStep, nextStep)


def _filterSmallMeshComponents(
    verts: np.ndarray,
    faces: np.ndarray,
    normals: np.ndarray,
    values: np.ndarray,
    minComponentTriangles: int,
):
    threshold = max(0, int(minComponentTriangles or 0))

    if threshold <= 0 or faces.size == 0:
        return verts, faces, normals, values, 0

    try:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"scipy is required to filter surface components: {exc}",
        )

    faceArray = np.asarray(faces, dtype=np.int64)

    a = faceArray[:, 0]
    b = faceArray[:, 1]
    c = faceArray[:, 2]

    rows = np.concatenate((a, b, b, c, c, a))
    cols = np.concatenate((b, a, c, b, a, c))

    adjacency = coo_matrix(
        (
            np.ones(rows.shape[0], dtype=np.uint8),
            (rows, cols),
        ),
        shape=(verts.shape[0], verts.shape[0]),
    ).tocsr()

    componentCount, labels = connected_components(
        adjacency,
        directed=False,
        return_labels=True,
    )

    faceLabels = labels[faceArray[:, 0]]
    triangleCounts = np.bincount(
        faceLabels,
        minlength=componentCount,
    )

    keepFaces = triangleCounts[faceLabels] >= threshold

    if not np.any(keepFaces):
        largestComponent = int(np.argmax(triangleCounts))
        keepFaces = faceLabels == largestComponent

    filteredFaces = faceArray[keepFaces]

    usedVertexIds = np.unique(filteredFaces.reshape(-1))

    remap = np.full(
        verts.shape[0],
        -1,
        dtype=np.int64,
    )

    remap[usedVertexIds] = np.arange(
        usedVertexIds.size,
        dtype=np.int64,
    )

    compactFaces = remap[filteredFaces].astype(
        np.int32,
        copy=False,
    )

    removedComponents = int(
        np.count_nonzero(triangleCounts < threshold)
    )

    return (
        verts[usedVertexIds],
        compactFaces,
        normals[usedVertexIds],
        values[usedVertexIds],
        removedComponents,
    )


def buildVolumeSurfaceMesh(
    volume: np.ndarray,
    *,
    level: Optional[float] = None,
    spacing: Optional[Tuple[float, float, float]] = None,
    maxTriangles: int = 350000,
    minComponentTriangles: int = 0,
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
        verts, faces, normals, values, stepSize = _runMarchingCubes(
            arr,
            level=levelValue,
            spacing=(
                float(zSpacing),
                float(ySpacing),
                float(xSpacing),
            ),
            maxTriangles=maxTriangles,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to build surface mesh: {exc}",
        )

    if faces.size == 0 or verts.size == 0:
        raise HTTPException(
            status_code=422,
            detail="No surface could be generated for this level",
        )

    verts, faces, normals, values, removedComponents = _filterSmallMeshComponents(
        verts,
        faces,
        normals,
        values,
        minComponentTriangles,
    )

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
        "rangeMin": float(np.nanmin(arr)),
        "rangeMax": float(np.nanmax(arr)),
        "dims": [int(arr.shape[0]), int(arr.shape[1]), int(arr.shape[2])],
        "order": "zyx",
        "vertexCount": int(verticesXyz.shape[0]),
        "triangleCount": triangleCount,
        "marchingCubesStep": int(stepSize),
        "minComponentTriangles": int(minComponentTriangles),
        "removedComponents": int(removedComponents),
        "vertices": verticesXyz.reshape(-1).astype(np.float32).tolist(),
        "normals": normalsXyz.reshape(-1).astype(np.float32).tolist(),
        "indices": faces.reshape(-1).astype(np.int32).tolist(),
        "values": np.asarray(values, dtype=np.float32).reshape(-1).tolist(),
        "center": center.astype(np.float32).tolist(),
        "scale": maxExtent,
    }
