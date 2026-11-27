"""A new project with its data imported, proposed by the assistant ("make a project with the movies of this
folder") and made when the user applies the card.

The folder must be one the user may browse (fs_browser: the data folders, or anywhere with files.browseServer);
the files are found with the pattern given, or with the first usual one that finds any (movies straight in the
folder, EPU's grid squares, one folder down). The import is added to the project saved, not launched: the user
reviews it in its form (with its acquisition values, those given filled in) and launches it.
"""
import glob
import itertools
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.backend.api.services.assistant_actions import ProposalError

IMPORT_CLASSES = {"movies": "ProtImportMovies", "micrographs": "ProtImportMicrographs"}
KIND_TITLES = {"movies": "Import movies", "micrographs": "Import micrographs"}
EXTENSIONS = {"movies": ("tif", "tiff", "eer", "mrc", "mrcs"), "micrographs": ("mrc", "tif", "tiff")}
# Where the files usually are under the folder given
LAYOUTS = ("*.{ext}", "Images-Disc*/GridSquare_*/Data/*_Fractions.{ext}", "Images-Disc*/GridSquare_*/Data/*.{ext}",
           "*/*.{ext}")
MAX_COUNTED = 100000
EXAMPLES = 3
MAX_NAME = 120
# The acquisition values: (name, label, lowest, highest, kinds)
ACQUISITION = (
    ("samplingRate", "Pixel size (Å)", 0.05, 20.0, ("movies", "micrographs")),
    ("voltage", "Voltage (kV)", 60.0, 400.0, ("movies", "micrographs")),
    ("sphericalAberration", "Spherical aberration (mm)", 0.0, 10.0, ("movies", "micrographs")),
    ("amplitudeContrast", "Amplitude contrast", 0.0, 1.0, ("movies", "micrographs")),
    ("dosePerFrame", "Dose per frame (e/Å²)", 0.0, 50.0, ("movies",)),
)
NEEDED = ("samplingRate", "voltage")


def kindOf(value: Any) -> str:
    kind = str(value or "movies").strip().lower()
    if kind in ("movie", "movies", "frames"):
        return "movies"
    if kind in ("micrograph", "micrographs", "mics"):
        return "micrographs"
    raise ProposalError("From the chat a project can import movies or micrographs; for tilt-series or other data "
                        "make the project and use the import form")


def projectName(value: Any) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise ProposalError("Say the project's name")
    if len(name) > MAX_NAME:
        raise ProposalError("A project's name has at most %d characters" % MAX_NAME)
    return name


def _within(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def reachable(path: str, canBrowseServer: bool) -> Path:
    """The folder (or file) as an absolute path, if the user may use it (as the file browser)."""
    from app.backend.api.services import fs_browser

    raw = str(path or "").strip()
    if not raw or not os.path.isabs(raw):
        raise ProposalError("Give the whole path of the folder, from /")
    if ".." in Path(raw).parts:
        raise ProposalError("The path cannot climb folders with '..'")
    absolute = Path(os.path.normpath(raw))
    roots = fs_browser.dataRoots()
    if not canBrowseServer and roots and not any(folder == Path(folder.anchor) for folder in roots):
        real = Path(os.path.realpath(str(absolute)))
        if not any(_within(absolute, root) and _within(real, Path(os.path.realpath(str(root)))) for root in roots):
            raise ProposalError("%s is out of the folders you may use (%s)" % (
                absolute, ", ".join(root.as_posix() for root in roots)))
    return absolute


def _matches(folder: Path, pattern: str) -> Tuple[int, List[str], bool]:
    found = itertools.islice(glob.iglob(str(folder / pattern)), MAX_COUNTED + 1)
    files = [path for path in found if os.path.isfile(path)]
    capped = len(files) > MAX_COUNTED
    return min(len(files), MAX_COUNTED), [os.path.relpath(path, str(folder)) for path in sorted(files)[:EXAMPLES]], capped


def checkedPattern(value: Any) -> str:
    pattern = str(value or "").strip()
    if pattern.startswith("/") or ".." in Path(pattern).parts:
        raise ProposalError("The pattern goes under the folder: no '/' at the start, no '..'")
    return pattern


def findFiles(folder: Path, kind: str, pattern: str = "") -> Dict[str, Any]:
    """{pattern, count, examples, capped}: with the pattern given, or the first usual one that finds files."""
    if not folder.is_dir():
        raise ProposalError("There is no folder %s (or the server cannot read it)" % folder)
    candidates = [pattern] if pattern else [layout.format(ext=ext) for layout in LAYOUTS for ext in EXTENSIONS[kind]]
    for candidate in candidates:
        count, examples, capped = _matches(folder, candidate)
        if count:
            return {"pattern": candidate, "count": count, "examples": examples, "capped": capped}
    if pattern:
        raise ProposalError("No file of %s matches %s" % (folder, pattern))
    raise ProposalError("No %s found in %s (looked for %s files there, in EPU's grid squares and one folder down): "
                        "say the pattern" % (kind, folder, ", ".join(EXTENSIONS[kind])))


def acquisitionValues(kind: str, given: Dict[str, Any]) -> Tuple[Dict[str, float], List[str]]:
    """(the acquisition values given, checked; the labels of the needed ones missing)."""
    values: Dict[str, float] = {}
    for name, label, lowest, highest, kinds in ACQUISITION:
        raw = (given or {}).get(name)
        if raw in (None, "") or kind not in kinds:
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            raise ProposalError("%s takes a number, not %r" % (label, raw))
        if not lowest <= number <= highest:
            raise ProposalError("%s %s is out of %s–%s" % (label, raw, lowest, highest))
        values[name] = number
    missing = [label for name, label, _, _, _ in ACQUISITION if name in NEEDED and name not in values]
    return values, missing


def gainOf(value: Any, canBrowseServer: bool) -> Optional[str]:
    if not str(value or "").strip():
        return None
    path = reachable(str(value), canBrowseServer)
    if not path.is_file():
        raise ProposalError("There is no gain file %s" % path)
    return str(path)


def plan(name: Any, folder: Any, kind: Any, pattern: Any, given: Dict[str, Any], streaming: Any,
         gain: Any, canBrowseServer: bool) -> Dict[str, Any]:
    """Everything checked: what the card shows and what the apply makes."""
    kind = kindOf(kind)
    name = projectName(name)
    where = reachable(str(folder or ""), canBrowseServer)
    files = findFiles(where, kind, checkedPattern(pattern))
    values, missing = acquisitionValues(kind, given)
    gainFile = gainOf(gain, canBrowseServer) if kind == "movies" else None
    return {"name": name, "folder": str(where), "kind": kind, "importClass": IMPORT_CLASSES[kind],
            "importTitle": KIND_TITLES[kind], "files": files, "values": values, "missing": missing,
            "gainFile": gainFile, "streaming": bool(streaming)}


def card(data: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    labels = {name: label for name, label, _, _, _ in ACQUISITION}
    return {"kind": "action", "action": "newproject", "projectId": 0, "protocolId": "", "label": data["name"],
            "name": data["name"], "folder": data["folder"], "dataKind": data["kind"],
            "importTitle": data["importTitle"], "pattern": data["files"]["pattern"], "count": data["files"]["count"],
            "capped": data["files"]["capped"], "examples": data["files"]["examples"],
            "values": [{"name": key, "label": labels[key], "value": value} for key, value in data["values"].items()],
            "missing": data["missing"], "gainFile": data["gainFile"], "streaming": data["streaming"],
            "reason": str(reason or "")[:500]}


def importProtocol(data: Dict[str, Any]) -> Dict[str, Any]:
    """The import as a one-protocol workflow (as an exported workflow writes it)."""
    protocol = {"object.className": data["importClass"], "object.id": "1",
                "object.label": data["importTitle"].lower(), "importFrom": 0, "samplingRateMode": 0,
                "filesPath": data["folder"], "filesPattern": data["files"]["pattern"],
                "dataStreaming": bool(data["streaming"])}
    protocol.update(data["values"])
    if data.get("gainFile"):
        protocol["gainFile"] = data["gainFile"]
    return protocol
