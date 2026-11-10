"""Why a protocol failed, for the web (the Summary of a failed protocol, the failure notice): the cause when it
is a known error, the error and the command, each with where it is in the log. See runtime/failure_reader.py."""
import logging
import os
from typing import Any, Dict, Optional

from app.backend.mapper.protocol_failure_mapper import ProtocolFailurePostgresqlMapper
from app.backend.runtime.failure_reader import explainFailure
from app.backend.runtime.protocol_log_service import RuntimeProtocolLogService

logger = logging.getLogger(__name__)

FAILED_STATUSES = ("failed",)


def explainProtocolFailure(mapper, service, projectId: int, protocolId) -> Dict[str, Any]:
    """{failed, cause, error, command, traceback, ...} of a protocol; failed is False (and nothing else is read)
    for a protocol that did not fail. service resolves the protocol's ids and folder."""
    db = mapper.db
    # The web asks by the protocol's Scipion id, as for its logs
    scipionId = service._resolveScipionProtocolIdStrict(mapper=mapper, projectId=projectId, protocolId=protocolId)
    key = scipionId if scipionId is not None else protocolId
    failures = ProtocolFailurePostgresqlMapper(db)
    protocol = failures.protocol(projectId, key)
    if not protocol or protocol.get("status") not in FAILED_STATUSES:
        return {"failed": False}
    paths: Dict[str, Optional[str]] = {}
    try:
        located = RuntimeProtocolLogService().resolvePostgresqlProtocolLogPaths(
            mapper=mapper, projectId=projectId, protocolId=protocolId,
            resolveScipionProtocolIdCallback=service._resolveScipionProtocolIdStrict,
            resolvePostgresqlProjectPathForFilesystemCallback=service._resolvePostgresqlProjectPathForFilesystem)
        paths = (located or {}).get("paths") or {}
    except Exception:
        logger.warning("Could not find the logs of protocol %s of project %s", protocolId, projectId, exc_info=True)
    explained = explainFailure(paths.get("stdout"), paths.get("stderr"), failures.failedStepErrors(projectId, key))
    return dict(explained, failed=True, protocolId=str(key))


def failureCause(mapper, service, projectId: int, protocolId) -> Optional[Dict[str, Any]]:
    """Only the known cause of a failure (for a notice), never failing."""
    try:
        explained = explainProtocolFailure(mapper, service, projectId, protocolId)
    except Exception:
        logger.warning("Could not explain the failure of protocol %s", protocolId, exc_info=True)
        return None
    return explained.get("cause") if explained.get("failed") else None


def runFolder(projectPath: Optional[str], protocolId, className: Optional[str]) -> Optional[str]:
    """A protocol's folder in its project (Runs/<6-digit id>_<class>)."""
    try:
        return os.path.join(str(projectPath), "Runs", "%06d_%s" % (int(protocolId), className)) \
            if projectPath and className else None
    except (TypeError, ValueError):
        return None


def causeOfRun(db, projectId: Optional[int], projectPath: Optional[str], protocolId,
               className: Optional[str]) -> Optional[Dict[str, Any]]:
    """The known cause of a run that just failed, from its logs (for its notice); None when unknown."""
    folder = runFolder(projectPath, protocolId, className)
    if not folder:
        return None
    try:
        stepErrors = ProtocolFailurePostgresqlMapper(db).failedStepErrors(projectId, protocolId) \
            if projectId is not None else []
        return explainFailure(os.path.join(folder, "logs", "run.stdout"), os.path.join(folder, "logs", "run.stderr"),
                              stepErrors).get("cause")
    except Exception:
        logger.warning("Could not read why protocol %s failed", protocolId, exc_info=True)
        return None
