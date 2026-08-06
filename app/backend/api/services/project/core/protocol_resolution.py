"""Resolving protocol identities/objects across the Scipion runtime and
PostgreSQL. All functions here take the state they need (currentProject,
mapper, projectId, protocolId) explicitly rather than caching it - the
caller (ProjectService) owns currentProject and it can be reassigned during
a request, so nothing here should snapshot it at construction time.
"""
import logging
from typing import Optional, Union

from fastapi import HTTPException, status

from app.backend.runtime.protocol_identity import ProtocolIdentityResolver

logger = logging.getLogger(__name__)


def resolveScipionProtocolId(mapper, projectId: int, protocolId) -> Optional[int]:
    return ProtocolIdentityResolver(
        mapper=mapper,
        projectId=projectId,
    ).resolveScipionProtocolId(protocolId)


def resolvePostgresqlProtocolDbId(mapper, projectId: int, protocolId) -> Optional[int]:
    return ProtocolIdentityResolver(
        mapper=mapper,
        projectId=projectId,
    ).resolvePostgresqlProtocolDbId(protocolId)


def resolvePostgresqlReaderProtocolId(
        mapper,
        projectId: Optional[int],
        protocolId: Union[int, str],
) -> Union[int, str]:
    if mapper is None:
        return protocolId

    return resolvePostgresqlProtocolDbId(
        mapper=mapper,
        projectId=projectId,
        protocolId=protocolId,
    ) or protocolId


def getScipionProtocolByRuntimeId(
        currentProject,
        protocolId: Union[int, str],
        logFailure: bool = True,
):
    if currentProject is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No current Scipion project loaded",
        )

    try:
        runtimeMapper = getattr(currentProject, "mapper", None)
        selectRuntimeProtocol = getattr(runtimeMapper, "selectRuntimeProtocolById", None)

        if callable(selectRuntimeProtocol):
            protocol = selectRuntimeProtocol(int(protocolId))
        else:
            protocol = currentProject.getProtocol(int(protocolId))

    except HTTPException:
        raise
    except Exception as e:
        logMessage = (
            "Failed to load protocol from currentProject. "
            "protocolId=%s currentProject=%s mapper=%s"
        )
        logArgs = (
            protocolId,
            type(currentProject),
            type(getattr(currentProject, "mapper", None)),
        )
        if logFailure:
            logger.exception(logMessage, *logArgs)
        else:
            logger.debug(logMessage, *logArgs)

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Protocol not found in Scipion runtime: {protocolId}. {e}",
        )

    if protocol is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Protocol not found in Scipion runtime: {protocolId}",
        )

    return protocol


def tryGetScipionProtocolByRuntimeId(currentProject, protocolId: Union[int, str]):
    try:
        return getScipionProtocolByRuntimeId(
            currentProject,
            protocolId,
            logFailure=False,
        )
    except Exception:
        return None


def getScipionProtocolForRuntime(
        currentProject,
        mapper,
        projectId: Optional[int],
        protocolId: Union[int, str],
):
    scipionProtocolId = resolveScipionProtocolId(
        mapper=mapper,
        projectId=projectId,
        protocolId=protocolId,
    )

    return getScipionProtocolByRuntimeId(currentProject, scipionProtocolId)


def tryGetScipionProtocolForRuntime(
        currentProject,
        mapper,
        projectId: Optional[int],
        protocolId: Union[int, str],
):
    try:
        scipionProtocolId = resolveScipionProtocolId(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        return getScipionProtocolByRuntimeId(
            currentProject,
            scipionProtocolId,
            logFailure=False,
        )

    except Exception:
        return None
