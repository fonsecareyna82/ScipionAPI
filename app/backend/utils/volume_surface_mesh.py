import json
import struct
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


def _smoothMeshVertices(
    verts: np.ndarray,
    faces: np.ndarray,
    iterations: int,
) -> np.ndarray:
    effectiveIterations = max(0, min(12, int(iterations or 0)))

    if effectiveIterations <= 0 or verts.size == 0 or faces.size == 0:
        return np.asarray(verts, dtype=np.float32)

    try:
        from scipy.sparse import coo_matrix
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"scipy is required to smooth surface meshes: {exc}",
        )

    faceArray = np.asarray(faces, dtype=np.int64)

    a = faceArray[:, 0]
    b = faceArray[:, 1]
    c = faceArray[:, 2]

    rows = np.concatenate((a, b, b, c, c, a))
    cols = np.concatenate((b, a, c, b, a, c))

    adjacency = coo_matrix(
        (
            np.ones(rows.shape[0], dtype=np.float32),
            (rows, cols),
        ),
        shape=(verts.shape[0], verts.shape[0]),
    ).tocsr()

    adjacency.sum_duplicates()
    adjacency.data[:] = 1.0

    degree = np.asarray(
        adjacency.sum(axis=1),
        dtype=np.float32,
    ).reshape(-1)

    active = degree > 0

    positions = np.asarray(
        verts,
        dtype=np.float32,
    ).copy()

    def smoothStep(
        current: np.ndarray,
        strength: float,
    ) -> np.ndarray:
        neighborSum = adjacency.dot(current)

        neighborMean = current.copy()
        neighborMean[active] = (
            neighborSum[active] /
            degree[active, None]
        )

        result = current.copy()
        result[active] += strength * (
            neighborMean[active] -
            current[active]
        )

        return result

    for _ in range(effectiveIterations):
        positions = smoothStep(positions, 0.45)
        positions = smoothStep(positions, -0.47)

    return positions


def _computeMeshVertexNormals(
    verts: np.ndarray,
    faces: np.ndarray,
) -> np.ndarray:
    faceArray = np.asarray(faces, dtype=np.int64)
    positions = np.asarray(verts, dtype=np.float32)

    triangles = positions[faceArray]

    faceNormals = np.cross(
        triangles[:, 1] - triangles[:, 0],
        triangles[:, 2] - triangles[:, 0],
    )

    normals = np.zeros_like(
        positions,
        dtype=np.float32,
    )

    np.add.at(normals, faceArray[:, 0], faceNormals)
    np.add.at(normals, faceArray[:, 1], faceNormals)
    np.add.at(normals, faceArray[:, 2], faceNormals)

    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 1e-12

    normals[valid] /= lengths[valid, None]
    normals[~valid] = 0.0

    return normals


def buildVolumeSurfaceMesh(
    volume: np.ndarray,
    *,
    level: Optional[float] = None,
    spacing: Optional[Tuple[float, float, float]] = None,
    maxTriangles: int = 350000,
    minComponentTriangles: int = 0,
    smoothingIterations: int = 0,
    asArrays: bool = False,
) -> Dict[str, Any]:
    """The isosurface of the volume. Its arrays are lists, or numpy arrays with asArrays."""
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

    effectiveSmoothingIterations = max(
        0,
        min(12, int(smoothingIterations or 0)),
    )

    if effectiveSmoothingIterations > 0:
        verts = _smoothMeshVertices(
            verts,
            faces,
            effectiveSmoothingIterations,
        )

        smoothedNormals = _computeMeshVertexNormals(
            verts,
            faces,
        )
        # The triangle winding gives the opposite orientation to the
        # marching cubes normals: keep the orientation of the latter.
        if float((smoothedNormals * normals).sum()) < 0:
            smoothedNormals = -smoothedNormals
        normals = smoothedNormals

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

    arrays = {
        "vertices": verticesXyz.reshape(-1).astype(np.float32),
        "normals": normalsXyz.reshape(-1).astype(np.float32),
        "indices": faces.reshape(-1).astype(np.uint32),
        "values": np.asarray(values, dtype=np.float32).reshape(-1),
    }
    if not asArrays:
        arrays = {name: values.tolist() for name, values in arrays.items()}

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
        "smoothingIterations": int(effectiveSmoothingIterations),
        **arrays,
        "center": center.astype(np.float32).tolist(),
        "scale": maxExtent,
    }


SURFACE_MESH_BINARY_MEDIA_TYPE = "application/octet-stream"
SURFACE_MESH_BINARY_MAGIC = b"SMSH"
_SURFACE_MESH_BINARY_ARRAYS = (
    ("vertices", "float32"),
    ("normals", "float32"),
    ("indices", "uint32"),
    ("values", "float32"),
)


def encodeSurfaceMeshBinary(mesh: Dict[str, Any]) -> bytes:
    """A surface mesh as bytes: the magic, the header length (uint32), a JSON header and the arrays.

    The arrays follow the header in the order the header lists them, little
    endian. The header is padded with spaces so every array starts at a
    multiple of 4 bytes and can be read in place.
    """
    arrays = []
    descriptors = []
    for name, dtype in _SURFACE_MESH_BINARY_ARRAYS:
        values = np.ascontiguousarray(np.asarray(mesh.get(name, []), dtype=np.dtype(dtype).newbyteorder("<")).reshape(-1))
        arrays.append(values)
        descriptors.append({"name": name, "type": dtype, "length": int(values.size)})

    header = {key: value for key, value in mesh.items() if key not in dict(_SURFACE_MESH_BINARY_ARRAYS)}
    header["arrays"] = descriptors
    headerBytes = json.dumps(header).encode("utf-8")
    prefixLength = len(SURFACE_MESH_BINARY_MAGIC) + 4
    headerBytes += b" " * (-(prefixLength + len(headerBytes)) % 4)

    return b"".join([
        SURFACE_MESH_BINARY_MAGIC,
        struct.pack("<I", len(headerBytes)),
        headerBytes,
        *(values.tobytes() for values in arrays),
    ])


def decodeSurfaceMeshBinary(data: bytes) -> Dict[str, Any]:
    """The mesh written by encodeSurfaceMeshBinary, with numpy arrays."""
    if data[:4] != SURFACE_MESH_BINARY_MAGIC:
        raise ValueError("Not a binary surface mesh")
    (headerLength,) = struct.unpack("<I", data[4:8])
    offset = 8 + headerLength
    mesh = json.loads(data[8:offset].decode("utf-8"))
    for descriptor in mesh.pop("arrays"):
        dtype = np.dtype(descriptor["type"]).newbyteorder("<")
        size = int(descriptor["length"]) * dtype.itemsize
        mesh[descriptor["name"]] = np.frombuffer(data[offset:offset + size], dtype=dtype)
        offset += size
    return mesh
