"""Where the remote file browser may look, and write.

Three kinds of browsing:

- ``project``: a protocol's files, inside its project folder (symbolic links
  under it may lead elsewhere, as Scipion links its inputs).
- ``filesystem``: the files a protocol form points to. Imports in particular
  need data anywhere (other disks, mounted volumes), so the whole filesystem
  is readable; browsing starts in the protocol (or project) folder. A user
  without the files.browseServer permission only reaches the project folder and
  the data folders of ``SCIPIONWEB_DATA_ROOTS`` (separated by ``:``), and sees
  only the folders leading to them; with no data folders set, nothing is limited.
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
from typing import Iterable, List, Optional, Tuple

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
    # The only folders reachable (absolute), or None for no limit
    allowed: Optional[Tuple[Path, ...]] = None

    def toDict(self) -> dict:
        return {
            "rootAbs": self.root.as_posix(),
            "startPath": self.start,
            "protocolRoot": self.protocolRoot,
            "projectRootAbs": self.projectRoot.as_posix() if self.projectRoot else None,
            "scope": self.kind,
            # The folders the user may browse, when limited, and among them the data folders (shortcuts)
            "allowedRoots": [folder.as_posix() for folder in self.allowed] if self.allowed is not None else None,
            "dataRoots": ([folder.as_posix() for folder in dataRoots() if folder.as_posix() != "/"]
                          if self.allowed is not None else None),
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


def dataRoots() -> Tuple[Path, ...]:
    """The data folders every user may browse (SCIPIONWEB_DATA_ROOTS)."""
    raw = os.environ.get("SCIPIONWEB_DATA_ROOTS") or ""
    return tuple(Path(part).expanduser().absolute() for part in raw.split(os.pathsep) if part.strip())


def _within(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def _real(path: Path) -> Path:
    """Where a path really is: its symbolic links followed (a missing end is kept as written)."""
    return Path(os.path.realpath(str(path)))


def _reaches(path: Path, folders: Iterable[Path]) -> bool:
    """Whether a path is inside one of the folders both as written and where it really is: a symbolic link in a
    reachable folder that leads out of them (to another user's data) does not take the user there."""
    folders = tuple(folders)
    if not any(_within(path, folder) for folder in folders):
        return False
    real = _real(path)
    return any(_within(real, _real(folder)) for folder in folders)


def isAllowed(browser: BrowserRoot, absolutePath: Path) -> bool:
    """Whether a path (absolute) is inside one of the browser's reachable folders, also where it really is."""
    if browser.allowed is None:
        return True
    return _reaches(absolutePath, browser.allowed)


def leadsToAllowed(browser: BrowserRoot, absolutePath: Path) -> bool:
    """Whether a folder is reachable or on the way to a reachable one (to browse down to it)."""
    if browser.allowed is None:
        return True
    if any(_within(absolutePath, folder) for folder in browser.allowed):
        return isAllowed(browser, absolutePath)
    return any(_within(folder, absolutePath) for folder in browser.allowed)


def checkAllowed(browser: BrowserRoot, absolutePath: Path, folder: bool = False) -> None:
    allowed = leadsToAllowed(browser, absolutePath) if folder else isAllowed(browser, absolutePath)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="This folder is out of reach: ask for the files.browseServer permission")


def filterListing(browser: BrowserRoot, folder: Path, entries: Iterable[dict]) -> List[dict]:
    """The entries of a listed folder the browser may reach or go through."""
    entries = list(entries)
    if browser.allowed is None or isAllowed(browser, folder):
        return entries
    return [entry for entry in entries
            if entry.get("isDir") is not False and leadsToAllowed(browser, folder / str(entry.get("name") or ""))]


def _relative(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return ""
    return "" if relative == "." else relative


def protocolFolder(projectPath: str, protocolId, protocolClassName: str) -> Path:
    """A protocol's working folder, as Scipion names it."""
    return Path(projectPath) / "Runs" / ("%06d_%s" % (int(protocolId), protocolClassName))


def resolveBrowserRoot(mapper, projectId, protocolId, projectPath: Optional[str], scope: str = "project",
                       canBrowseServer: bool = True) -> BrowserRoot:
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
        roots = dataRoots()
        # The project as named and as reached (a linked project is browsed through its target)
        projectFolders = tuple(dict.fromkeys((Path(projectPath).expanduser().absolute(), projectRoot)))
        allowed = None if canBrowseServer or not roots else projectFolders + roots
        return BrowserRoot(root=root, start=_relative(folder, root), protocolRoot=_relative(folder, root),
                           projectRoot=projectRoot, kind="filesystem", allowed=allowed)
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


# Launching: the paths a protocol's form points to ------------------------------------------------

_GLOB_CHARACTERS = set("*?[")


def _beforeGlob(path: str) -> str:
    """The folders of a path up to its first pattern (movies/*.tif reads movies)."""
    parts = []
    for part in Path(path).parts:
        if _GLOB_CHARACTERS & set(part):
            break
        parts.append(part)
    return str(Path(*parts)) if parts else ""


def protocolPaths(protocol) -> List[Tuple[str, str]]:
    """(label, path) of every file or folder the protocol's form points to, among the parameters in use."""
    from pyworkflow.protocol.params import PathParam

    found = []
    definition = getattr(protocol, "_definition", None)
    for name, param in (definition.iterAllParams() if definition is not None else ()):
        if not isinstance(param, PathParam):
            continue
        try:
            if not protocol.evalParamCondition(name):
                continue
        except Exception:
            pass
        value = getattr(protocol, name, None)
        text = value.get() if hasattr(value, "get") else value
        if text not in (None, ""):
            found.append((str(getattr(param, "label", None) or name), str(text)))
    # Imports read the files of a pattern under their folder (the pattern may name folders too)
    pattern = getattr(protocol, "filesPattern", None)
    pattern = pattern.get() if hasattr(pattern, "get") else pattern
    if pattern:
        folder = getattr(protocol, "filesPath", None)
        folder = folder.get() if hasattr(folder, "get") else folder
        found.append(("Pattern", os.path.join(str(folder or ""), str(pattern))))
    return found


def pathsOutOfReach(protocols: Iterable, projectPath: str, canBrowseServer: bool) -> List[str]:
    """The paths of the protocols' forms out of the project and of the data folders, as messages.

    The same reach as browsing: nothing is out of it with files.browseServer or with no data folders set.
    """
    roots = dataRoots()
    if canBrowseServer or not roots:
        return []
    project = Path(projectPath).expanduser()
    allowed = tuple(dict.fromkeys((project.absolute(), project.resolve()))) + roots
    problems = []
    folders = ", ".join(folder.as_posix() for folder in roots)
    for protocol in protocols:
        name = protocol.getObjLabel() if hasattr(protocol, "getObjLabel") else ""
        name = name or (protocol.getClassName() if hasattr(protocol, "getClassName") else "Protocol")
        for label, raw in protocolPaths(protocol):
            reason = _outOfReach(raw, project, allowed)
            if reason:
                problems.append(
                    "%s: %s (%s) %s (the project and %s). Ask for the files.browseServer permission to use it."
                    % (name, label, raw, reason, folders))
    return problems


# How many files of a pattern a launch looks at, each where it really is
PATTERN_MATCHES_CHECKED = 20000


def _outOfReach(raw: str, project: Path, allowed: Tuple[Path, ...]) -> Optional[str]:
    """Why a path (or a folder and pattern) of a form is out of reach, or None.

    '..' is refused anywhere: after a pattern it climbs out of the folder the pattern starts in
    (movies/*/../../other/*.tif). The folder before the pattern, and every file the pattern finds, must be in
    reach where they really are, so a symbolic link does not lead out either.
    """
    if ".." in Path(raw).parts:
        return "climbs folders with '..', which the folders you may use do not allow"
    absolute = Path(os.path.normpath(os.path.join(str(project.absolute()), _beforeGlob(raw))))
    if not _reaches(absolute, allowed):
        return "is out of the folders you may use"
    pattern = os.path.join(str(project.absolute()), raw)
    if _GLOB_CHARACTERS & set(raw):
        import glob as globModule
        import itertools

        for match in itertools.islice(globModule.iglob(pattern), PATTERN_MATCHES_CHECKED):
            if not _reaches(Path(match), allowed):
                return "finds %s, which is out of the folders you may use" % match
    return None


def checkLaunchPaths(mapper, userId, protocols, currentProject) -> None:
    """422 when a protocol launched by userId points to files out of their reach (no user: no check)."""
    roots = dataRoots()
    # No data folders, or the whole server as one (the default "/"): every path is in reach
    if userId is None or not roots or any(folder == Path(folder.anchor) for folder in roots):
        return
    projectPath = currentProject if isinstance(currentProject, str) else currentProject.getPath()
    from app.backend.mapper.access_mapper import AccessPostgresqlMapper

    held = AccessPostgresqlMapper(mapper.db).getUserPermissions(int(userId))
    canBrowseServer = held["isSystem"] or "files.browseServer" in held["permissions"]
    problems = pathsOutOfReach(protocols, projectPath, canBrowseServer)
    if problems:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problems)

