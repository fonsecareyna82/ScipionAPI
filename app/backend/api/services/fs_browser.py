"""Where the remote file browser may look, and write.

Three kinds of browsing:

- ``project``: a protocol's files, inside its project folder (symbolic links
  under it may lead elsewhere, as Scipion links its inputs).
- ``filesystem``: the files a protocol form points to. Imports in particular
  need data anywhere (other disks, mounted volumes), so the whole filesystem
  is readable; browsing starts in the protocol (or project) folder.
- import (project and protocol ids -1): projects and workflows to import,
  under ``SCIPION_IMPORT_BROWSER_ROOT``, never above
  ``SCIPION_IMPORT_BROWSER_CEILING`` (``/home``): a project elsewhere is copied
  under it first.

The browser root of a protocol comes from the database (its folder is
``<project>/Runs/<id>_<class>``), so browsing does not load the project.
Writing is allowed inside a project, and in the import area only as JSON
files (exported workflows), never into hidden folders or over other files.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

SCOPES = ("project", "filesystem")
IMPORT_ID = "-1"
UNSAVED_PROTOCOL_IDS = {"", "none", "null", "undefined", "fake-protocol-id-for-browser-paths-resolution"}
IMPORT_WRITE_SUFFIXES = {".json"}


@dataclass(frozen=True)
class BrowserRoot:
    """A browsing boundary: every path is relative to ``root``."""
    root: Path
    # Where browsing starts, and the protocol's own folder (relative to root).
    start: str
    protocolRoot: str
    # The project folder, when browsing for a project (absolute).
    projectRoot: Optional[Path]
    kind: str

    def toDict(self) -> dict:
        return {
            "rootAbs": self.root.as_posix(),
            "startPath": self.start,
            "protocolRoot": self.protocolRoot,
            "projectRootAbs": self.projectRoot.as_posix() if self.projectRoot else None,
            "scope": self.kind,
        }


def isImportMode(projectId, protocolId) -> bool:
    return str(projectId).strip() == IMPORT_ID and str(protocolId).strip() == IMPORT_ID


def importCeiling() -> Path:
    return Path(os.environ.get("SCIPION_IMPORT_BROWSER_CEILING", "/home")).expanduser().resolve()


def importRoot() -> Path:
    """Where projects and workflows are imported from: never above the ceiling (/home)."""
    configured = Path(os.environ.get("SCIPION_IMPORT_BROWSER_ROOT", "/home")).expanduser().resolve()
    ceiling = importCeiling()
    if configured == ceiling or ceiling in configured.parents:
        return configured
    logger.warning("SCIPION_IMPORT_BROWSER_ROOT=%s is above %s; using %s", configured, ceiling, ceiling)
    return ceiling


def _relative(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return ""
    return "" if relative == "." else relative


def protocolFolder(projectPath: str, protocolId, protocolClassName: str) -> Path:
    """A protocol's working folder, as Scipion names it."""
    return Path(projectPath) / "Runs" / ("%06d_%s" % (int(protocolId), protocolClassName))


def resolveBrowserRoot(mapper, projectId, protocolId, projectPath: Optional[str], scope: str = "project") -> BrowserRoot:
    """The browsing boundary of a request (see the module docstring)."""
    if isImportMode(projectId, protocolId):
        root = importRoot()
        return BrowserRoot(root=root, start="", protocolRoot="", projectRoot=None, kind="import")
    if scope not in SCOPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown browsing scope")
    if not projectPath:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project folder not found")

    projectRoot = Path(projectPath).expanduser().resolve()
    folder = projectRoot
    token = "" if protocolId is None else str(protocolId).strip()
    if token.lower() not in UNSAVED_PROTOCOL_IDS:
        row = mapper.getProjectProtocolByProtocolId(projectId=int(projectId), protocolId=token)
        if not isinstance(row, dict):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Protocol not found")
        candidate = protocolFolder(str(projectRoot), row["protocolId"], str(row["protocolClassName"]))
        # A protocol never run has no folder yet: browsing starts in the project.
        if candidate.is_dir():
            folder = candidate

    if scope == "filesystem":
        root = Path("/")
        return BrowserRoot(root=root, start=_relative(folder, root), protocolRoot=_relative(folder, root),
                           projectRoot=projectRoot, kind="filesystem")
    return BrowserRoot(root=projectRoot, start=_relative(folder, projectRoot),
                       protocolRoot=_relative(folder, projectRoot), projectRoot=projectRoot, kind="project")


def writableTarget(browser: BrowserRoot, requestedPath: str) -> Path:
    """Where a write may go: inside a project, or a JSON file in the import area."""
    raw = str(requestedPath or "").strip()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing path")
    if browser.kind == "filesystem":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Files can only be written inside the project")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = browser.root / candidate
    candidate = candidate.resolve()
    try:
        relative = candidate.relative_to(browser.root)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Path escapes browser root")
    if browser.kind == "import":
        if candidate.suffix.lower() not in IMPORT_WRITE_SUFFIXES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Only JSON files can be written here")
        if any(part.startswith(".") for part in relative.parts):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Files cannot be written into hidden folders")
    return candidate
