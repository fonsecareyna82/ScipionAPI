"""Resolving a protocol's working directory for deletion (with symlink/
path-escape guards) and cleaning up its PostgreSQL runtime artifacts +
on-disk working directory after a protocol delete.
"""
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def resolveProtocolWorkingDirectoryForDelete(
        protocol,
        projectPathValue,
) -> Path:
    if not projectPathValue:
        raise RuntimeError(
            "Current project path is not available"
        )

    projectPath = Path(projectPathValue).expanduser().resolve()

    runsPath = Path(os.path.abspath(str(projectPath / "Runs")))

    rawWorkingDir = getattr(protocol, "getWorkingDir", lambda: None)()

    if not rawWorkingDir:
        raise RuntimeError(
            "Protocol %s does not expose a working directory"
            % getattr(protocol, "getObjId", lambda: None)()
        )

    workingDir = Path(str(rawWorkingDir)).expanduser()

    if not workingDir.is_absolute():
        workingDir = projectPath / workingDir

    workingDir = Path(os.path.abspath(str(workingDir)))

    try:
        workingDir.relative_to(runsPath)
    except ValueError as error:
        raise RuntimeError(
            "Refusing to delete protocol path outside the project Runs directory: %s"
            % workingDir
        ) from error

    if workingDir == runsPath:
        raise RuntimeError(
            "Refusing to delete the complete project Runs directory"
        )

    # Do not follow a protocol-directory symlink.
    if workingDir.is_symlink():
        return workingDir

    resolvedRunsPath = runsPath.resolve(strict=False)
    resolvedWorkingDir = workingDir.resolve(strict=False)

    try:
        resolvedWorkingDir.relative_to(resolvedRunsPath)
    except ValueError as error:
        raise RuntimeError(
            "Refusing to follow protocol path outside the project Runs directory: %s"
            % workingDir
        ) from error

    return workingDir


def cleanupPostgresqlRuntimeProtocolDelete(
        currentProject,
        projectPathValue,
        *,
        projectId: int,
        protocols,
        deleteInfo,
) -> Dict[str, Any]:
    deletedProtocolIds = {
        str(protocolId)
        for protocolId in (deleteInfo.get("deletedProtocolIds") or [])
    }

    cleanupProtocols = []

    for protocol in protocols or []:
        protocolId = getattr(protocol, "getObjId", lambda: None)()

        if str(protocolId) not in deletedProtocolIds:
            continue

        cleanupProtocols.append(protocol)

    runtimeMapper = None

    try:
        runtimeMapper = currentProject.getPostgresqlRuntimeMapper()
    except Exception:
        runtimeMapper = None

    cacheCleanup = None

    if runtimeMapper is not None:
        cacheCleanup = runtimeMapper.evictDeletedRuntimeArtifacts(
            protocolIds=list(deletedProtocolIds),
            runtimeSetObjectIds=deleteInfo.get("runtimeSetObjectIds") or [],
        )

    deletedDirectories = []
    missingDirectories = []
    errors = []

    for protocol in cleanupProtocols:
        protocolId = str(getattr(protocol, "getObjId", lambda: None)())

        try:
            workingDir = resolveProtocolWorkingDirectoryForDelete(
                protocol,
                projectPathValue,
            )

            if workingDir.is_symlink():
                workingDir.unlink()

                deletedDirectories.append({
                    "protocolId": protocolId,
                    "path": str(workingDir),
                    "kind": "symlink",
                })

                continue

            if not workingDir.exists():
                missingDirectories.append({
                    "protocolId": protocolId,
                    "path": str(workingDir),
                })

                continue

            if not workingDir.is_dir():
                raise RuntimeError(
                    "Protocol working path is not a directory: %s"
                    % workingDir
                )

            shutil.rmtree(workingDir)

            deletedDirectories.append({
                "protocolId": protocolId,
                "path": str(workingDir),
                "kind": "directory",
            })

        except Exception as error:
            logger.exception(
                "Could not delete PostgreSQL protocol working directory. "
                "projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )

            errors.append({
                "protocolId": protocolId,
                "error": str(error),
            })

    return {
        "cacheCleanup": cacheCleanup,
        "deletedDirectories": deletedDirectories,
        "missingDirectories": missingDirectories,
        "errors": errors,
    }
