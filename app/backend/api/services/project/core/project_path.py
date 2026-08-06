"""Sanitizing project names and resolving/guarding project filesystem
paths against the managed projects root. `manager` (a pyworkflow Manager)
is always taken explicitly rather than cached - callers own it.
"""
import logging
import os
import re
import shutil

logger = logging.getLogger(__name__)


def sanitizeProjectName(rawName: str) -> str:
    """
    Return a filesystem-safe project name.

    Rules:
      - Replace any char not in [A-Za-z0-9_-] with '_'
      - Collapse consecutive underscores
      - Strip leading/trailing underscores and dots
      - Ensure non-empty (fallback to 'project')
    """
    if rawName is None:
        rawName = ""

    # Trim whitespace
    name = rawName.strip()

    # Replace invalid chars with underscore
    name = re.sub(r"[^A-Za-z0-9_\-]", "_", name)

    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)

    # Strip leading/trailing underscores and dots
    name = name.strip("._")

    # Fallback if empty
    if not name:
        name = "project"

    return name


def normalizeProjectPath(projectPath: str, manager) -> str:
    """
    Normalize a stored project path to an absolute filesystem path.

    Important:
    - Do NOT resolve symlinks here.
    - We want the project entry path, not the real target path.
    """
    if not projectPath:
        return ""

    normalized = os.path.expanduser(str(projectPath).strip())

    if not os.path.isabs(normalized):
        normalized = manager.getProjectPath(normalized)

    return os.path.abspath(normalized)


def isManagedProjectPath(projectPath: str, manager) -> bool:
    """
    Return True when the project entry itself lives under the managed
    projects root.

    Important:
    - This checks the lexical path of the entry.
    - It must not resolve symlinks, otherwise linked external projects
      would look "outside" even if their symlink entry is inside the
      workspace.
    """
    try:
        managedRoot = normalizeProjectPath(manager.PROJECTS, manager)
        normalizedPath = normalizeProjectPath(projectPath, manager)

        common = os.path.commonpath([managedRoot, normalizedPath])
        return common == managedRoot
    except Exception:
        return False


def isLinkedProjectPath(projectPath: str, manager) -> bool:
    """Return True if the stored project entry is a symbolic link."""
    normalizedPath = normalizeProjectPath(projectPath, manager)
    return os.path.islink(normalizedPath)


def removeCreatedProjectPath(projectPath: str, manager) -> None:
    normalizedPath = normalizeProjectPath(projectPath, manager)

    if not isManagedProjectPath(normalizedPath, manager):
        raise RuntimeError(
            "Refusing to remove project path outside the managed projects root: %s"
            % normalizedPath
        )

    if not os.path.lexists(normalizedPath):
        return

    try:
        os.chdir(manager.PROJECTS)
    except Exception:
        logger.warning(
            "Could not restore managed projects working directory before cleanup. path=%s",
            normalizedPath,
            exc_info=True,
        )

    if os.path.islink(normalizedPath) or not os.path.isdir(normalizedPath):
        os.unlink(normalizedPath)
    else:
        shutil.rmtree(normalizedPath)
