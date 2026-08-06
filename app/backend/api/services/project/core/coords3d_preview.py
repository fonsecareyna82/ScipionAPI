"""Iterating tomograms referenced by a SetOfCoordinates3D, and constructing
the PostgreSQL Coordinates3D reader when available.
"""
from fastapi import HTTPException, status


def iterCoordinates3dTomograms(setOfCoordinates3D):
    def asIterator(value):
        iterItems = getattr(value, "iterItems", None)

        if callable(iterItems):
            try:
                return iterItems(iterate=False)
            except TypeError:
                return iterItems()

        return iter(value)

    for methodName in ("iterTomograms", "iterVolumes"):
        method = getattr(setOfCoordinates3D, methodName, None)

        if not callable(method):
            continue

        try:
            return asIterator(method())
        except Exception:
            continue

    getTomograms = getattr(setOfCoordinates3D, "getTomograms", None)

    if callable(getTomograms):
        try:
            return asIterator(getTomograms())
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to iterate Coordinates3D tomograms: {error}",
            )

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="SetOfCoordinates3D does not expose tomograms iterator",
    )


def buildPostgresqlCoords3dReader(mapper, projectId: int, protocolId, outputName: str):
    """protocolId here is expected to already be resolved for reader use
    (see ProjectService._resolvePostgresqlReaderProtocolId)."""
    from app.backend.viewers.postgresql_coords3d_reader import PostgresqlCoords3dReader

    reader = PostgresqlCoords3dReader(
        db=mapper.db,
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
    )

    if reader.hasOutput():
        return reader

    return None
