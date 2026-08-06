"""Creating, finalizing, and discarding new Sets written directly into
PostgreSQL runtime storage - shared by every "create a new derived Set"
endpoint (volumes, tilt-series, ctftomo-series, coordinates3d, ...).
"""
from typing import Any, Dict, Optional, Union
from uuid import uuid4

from fastapi import HTTPException

from app.backend.runtime import RuntimeProtocolOutputPersistenceService
from app.backend.runtime.protocol_identity import ProtocolIdentityResolver


def getGeneratedSetOutputIdentity(
        mapper,
        projectId: int,
        protocolId: Union[int, str],
        protocol,
        outputPrefix: str,
) -> Dict[str, Any]:
    if mapper is None:
        return {
            "outputName": protocol.getNextOutputName(outputPrefix),
            "outputSuffix": str(protocol.getOutputsSize()),
            "protocolDbId": None,
        }

    protocolDbId = ProtocolIdentityResolver(
        mapper=mapper,
        projectId=projectId,
    ).resolvePostgresqlProtocolDbId(protocolId)

    if protocolDbId is None:
        raise HTTPException(
            status_code=404,
            detail=f"Protocol '{protocolId}' not found in PostgreSQL",
        )

    outputNames = RuntimeProtocolOutputPersistenceService().loadPersistedProtocolOutputNames(
        mapper=mapper,
        projectId=projectId,
        protocolDbId=int(protocolDbId),
    )

    maxCounter = -1

    for attributeName in outputNames:
        nameSuffix = str(attributeName).replace(outputPrefix, "")

        try:
            counter = int(nameSuffix)
        except (TypeError, ValueError):
            counter = 1

        maxCounter = max(counter, maxCounter)

    nextNameSuffix = str(maxCounter + 1) if maxCounter > 0 else ""

    return {
        "outputName": outputPrefix + nextNameSuffix,
        "outputSuffix": str(len(outputNames)),
        "protocolDbId": int(protocolDbId),
    }


def createWritableGeneratedPostgresqlSet(
        mapper,
        projectId: int,
        protocolId: Union[int, str],
        protocol,
        outputName: str,
        sourceSet,
) -> Dict[str, Any]:
    if mapper is None:
        raise RuntimeError("Generated Sets require a PostgreSQL mapper")

    db = getattr(mapper, "db", None)

    if db is None:
        raise RuntimeError("Generated Sets require a PostgreSQL database")

    protocolDbId = ProtocolIdentityResolver(
        mapper=mapper,
        projectId=projectId,
    ).resolvePostgresqlProtocolDbId(protocolId)

    if protocolDbId is None:
        raise HTTPException(
            status_code=404,
            detail=f"Protocol '{protocolId}' not found in PostgreSQL",
        )

    allocator = getattr(mapper, "allocateProjectObjectId", None)

    if not callable(allocator):
        raise RuntimeError("PostgreSQL mapper does not expose allocateProjectObjectId()")

    nativeSetClass = sourceSet.getClass()

    if not isinstance(nativeSetClass, type):
        raise RuntimeError(f"Could not resolve native Set class for '{outputName}'")

    seedSet = nativeSetClass()

    copyInfo = getattr(seedSet, "copyInfo", None)

    if callable(copyInfo):
        copyInfo(sourceSet)
    else:
        seedSet.copy(sourceSet, copyId=False)

    runtimeObjectId = int(allocator(int(projectId)))

    seedSet.setObjId(runtimeObjectId)
    seedSet.setName(outputName)
    seedSet.setObjLabel(outputName)

    from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
    from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetFactory

    setMapper = ScipionSetPostgresqlMapper(db)

    reservation = setMapper.reserveRuntimeSet(
        projectId=int(projectId),
        protocolDbId=int(protocolDbId),
        outputName=outputName,
        scipionSet=seedSet,
        reservationToken=str(uuid4()),
    )

    runtimeSetFactory = PostgresqlRuntimeSetFactory()

    try:
        outputInfo = dict(reservation)
        outputInfo["exists"] = True
        outputInfo["itemsCount"] = 0

        outputSet = runtimeSetFactory.build(
            db=db,
            parent=protocol,
            outputName=outputName,
            outputInfo=outputInfo,
        )

        outputSet.enablePostgresqlWrite()

    except Exception:
        setMapper.discardReservedRuntimeSet(
            projectId=int(projectId),
            protocolDbId=int(protocolDbId),
            runtimeObjectId=runtimeObjectId,
        )
        raise

    return {
        "outputSet": outputSet,
        "setMapper": setMapper,
        "runtimeSetFactory": runtimeSetFactory,
        "reservation": reservation,
        "protocolDbId": int(protocolDbId),
        "runtimeObjectId": runtimeObjectId,
    }


def cloneGeneratedNestedSet(sourceSet):
    nativeSetClass = sourceSet.getClass()

    if not isinstance(nativeSetClass, type):
        raise RuntimeError("Could not resolve native nested Set class")

    result = nativeSetClass()
    result.copy(sourceSet, copyId=False)

    return result


def finalizeGeneratedPostgresqlSet(
        context: Dict[str, Any],
        projectId: int,
        outputName: str,
) -> Dict[str, Any]:
    return context["setMapper"].finalizeRuntimeSetOutput(
        projectId=int(projectId),
        protocolDbId=int(context["protocolDbId"]),
        outputName=outputName,
        scipionSet=context["outputSet"],
    )


def discardGeneratedPostgresqlSet(
        context: Optional[Dict[str, Any]],
        projectId: int,
) -> bool:
    if not context:
        return False

    reservation = context.get("reservation") or {}
    runtimeObjectId = reservation.get("runtimeObjectId", context.get("runtimeObjectId"))

    if runtimeObjectId is None:
        return False

    return bool(
        context["setMapper"].discardReservedRuntimeSet(
            projectId=int(projectId),
            protocolDbId=int(context["protocolDbId"]),
            runtimeObjectId=int(runtimeObjectId),
        )
    )


def storeGeneratedSetInPostgresql(
        mapper,
        projectId: Optional[int],
        protocolId: Union[int, str],
        outputName: str,
        scipionSet,
        contextLabel: str,
) -> Dict[str, Any]:
    return RuntimeProtocolOutputPersistenceService().storeGeneratedSetInPostgresql(
        mapper=mapper,
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
        scipionSet=scipionSet,
        contextLabel=contextLabel,
    )
