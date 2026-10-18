import numpy as np

from app.backend.utils.volume_surface_mesh import (
    SURFACE_MESH_BINARY_MAGIC,
    buildVolumeSurfaceMesh,
    decodeSurfaceMeshBinary,
    encodeSurfaceMeshBinary,
)


def _sphere(size=24, radius=7.0):
    zz, yy, xx = np.indices((size, size, size)) - (size - 1) / 2
    return (radius - np.sqrt(zz ** 2 + yy ** 2 + xx ** 2)).astype(np.float32)


def test_TheBinaryMeshHoldsTheSameMeshAsTheJsonOne():
    asLists = buildVolumeSurfaceMesh(_sphere(), level=0.0)
    asArrays = buildVolumeSurfaceMesh(_sphere(), level=0.0, asArrays=True)

    data = encodeSurfaceMeshBinary(asArrays)
    mesh = decodeSurfaceMeshBinary(data)

    assert data[:4] == SURFACE_MESH_BINARY_MAGIC
    for name in ("vertices", "normals", "indices", "values"):
        assert np.allclose(mesh[name], asLists[name])
    assert mesh["indices"].dtype == np.dtype("<u4")
    assert mesh["triangleCount"] == asLists["triangleCount"]
    assert mesh["center"] == asLists["center"]
    assert len(mesh["vertices"]) == 3 * mesh["vertexCount"]


def test_EveryBinaryArrayStartsAtAMultipleOfFourBytes():
    mesh = {"kind": "surfaceMesh", "level": 1.5, "vertices": [1.0, 2.0, 3.0], "normals": [0.0, 0.0, 1.0],
            "indices": [0, 0, 0], "values": [1.5]}
    for padding in range(4):
        data = encodeSurfaceMeshBinary({**mesh, "outputName": "x" * padding})
        headerLength = int.from_bytes(data[4:8], "little")
        assert (8 + headerLength) % 4 == 0
        assert decodeSurfaceMeshBinary(data)["vertices"].tolist() == [1.0, 2.0, 3.0]


def test_SmoothingKeepsTheNormalsPointingOutOfTheDensity():
    for smoothingIterations in (0, 2):
        mesh = buildVolumeSurfaceMesh(_sphere(32, 9.0), level=0.0, smoothingIterations=smoothingIterations,
                                      asArrays=True)
        vertices = mesh["vertices"].reshape(-1, 3)
        outward = vertices - vertices.mean(axis=0)

        assert np.mean((mesh["normals"].reshape(-1, 3) * outward).sum(axis=1) > 0) > 0.99
