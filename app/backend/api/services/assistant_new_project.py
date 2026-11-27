"""A new project proposed by the assistant, made when the user applies the card: empty ("make a project called
X"), or with the import of the data the user speaks of ("… and we import particles from /data/x").

What is imported picks one of the installed import protocols (movies, micrographs, particles, volumes,
tilt-series, tomograms…), never guessed: with nothing said about data the project is made empty. A folder is used
only when the user gave it, and only one the user may browse (fs_browser: the data folders, or anywhere with
files.browseServer); its files are found with the pattern given or the usual ones of that data (EPU's grid
squares for movies). Only the values the user said are filled, and only those the import's form has. The import
is added saved, not launched: its form opens for the user to review and launch it.
"""
import glob
import itertools
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.backend.api.services.assistant_actions import ProposalError

# What the user may call each kind of data, by import protocol
ALIASES = {
    "ProtImportMovies": ("movies", "movie", "frames"),
    "ProtImportMicrographs": ("micrographs", "micrograph", "mics"),
    "ProtImportParticles": ("particles", "particle", "particle stack", "particle stacks"),
    "ProtImportVolumes": ("volumes", "volume", "map", "maps", "3d map", "3d maps", "reference", "references"),
    "ProtImportAverages": ("averages", "2d averages", "class averages", "2d classes", "templates"),
    "ProtImportCTF": ("ctf", "ctfs", "ctf estimations"),
    "ProtImportCoordinates": ("coordinates", "coords", "picks", "2d coordinates"),
    "ProtImportMask": ("mask", "masks"),
    "ProtImportPdb": ("atomic structure", "atomic model", "pdb", "model", "mmcif", "cif"),
    "ProtImportSequence": ("sequence", "sequences"),
    "ProtImportTsMovies": ("tilt-series movies", "tilt series movies", "ts movies", "tomo movies",
                           "tilt movies"),
    "ProtImportTs": ("tilt-series", "tilt series", "tiltseries", "ts"),
    "ProtImportTomograms": ("tomograms", "tomogram", "tomos"),
    "ProtImportSubTomograms": ("subtomograms", "subtomogram", "subtomos"),
    "ProtImportCoordinates3D": ("3d coordinates", "coordinates 3d", "tomo coordinates"),
    "ProtImportTomomasks": ("tomomasks", "segmentations", "tomo masks"),
    "ProtImportTsCTF": ("tomo ctf", "tilt-series ctf", "ts ctf"),
}
# The files each kind usually has; EPU's grid squares for movies and micrographs
EXTENSIONS = {
    "ProtImportMovies": ("tif", "tiff", "eer", "mrc", "mrcs"),
    "ProtImportMicrographs": ("mrc", "tif", "tiff"),
    "ProtImportParticles": ("star", "mrcs", "xmd", "sqlite", "hdf", "stk"),
    "ProtImportVolumes": ("mrc", "map", "vol"),
    "ProtImportAverages": ("mrcs", "mrc", "stk"),
    "ProtImportTsMovies": ("mdoc", "tif", "tiff", "eer"),
    "ProtImportTs": ("mdoc", "st", "mrc", "ali"),
    "ProtImportTomograms": ("mrc", "rec"),
    "ProtImportSubTomograms": ("mrc",),
    "ProtImportCoordinates": ("star", "box", "pos", "json"),
}
EPU = ("Images-Disc*/GridSquare_*/Data/*_Fractions.{ext}", "Images-Disc*/GridSquare_*/Data/*.{ext}")
MAX_COUNTED = 100000
EXAMPLES = 3
MAX_NAME = 120
# The values the user may give: (name, label, lowest, highest)
VALUES = (
    ("samplingRate", "Pixel size (Å)", 0.05, 50.0),
    ("voltage", "Voltage (kV)", 60.0, 400.0),
    ("sphericalAberration", "Spherical aberration (mm)", 0.0, 10.0),
    ("amplitudeContrast", "Amplitude contrast", 0.0, 1.0),
    ("dosePerFrame", "Dose per frame (e/Å²)", 0.0, 50.0),
)
NEEDED = ("samplingRate", "voltage")


def _words(text: Any) -> str:
    text = re.sub(r"[_\s]+", " ", str(text or "").strip().lower())
    return re.sub(r"^(import(ing)?\s+)?((the|a|an|some)\s+)?", "", text).strip()


def resolveImport(data: Any, protocols: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The installed import protocol for the data the user spoke of; None when they spoke of none."""
    wanted = _words(data)
    if not wanted:
        return None
    installed = {protocol["className"]: protocol for protocol in protocols
                 if str(protocol.get("className", "")).startswith("ProtImport")}
    if str(data).strip() in installed:
        return installed[str(data).strip()]
    for className, names in ALIASES.items():
        if wanted in names and className in installed:
            return installed[className]
    byLabel = [protocol for protocol in installed.values() if _words(protocol.get("label")) == wanted]
    if not byLabel:
        byLabel = [protocol for protocol in installed.values() if wanted in _words(protocol.get("label"))]
    if len(byLabel) == 1:
        return byLabel[0]
    options = ", ".join(sorted(_words(protocol.get("label")) for protocol in (byLabel or installed.values())))
    raise ProposalError("Which data? The imports there are: %s" % options)


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


def findFiles(folder: Path, className: str, pattern: str = "") -> Dict[str, Any]:
    """{pattern, count, examples, capped}: with the pattern given, or the first usual one that finds files."""
    if not folder.is_dir():
        raise ProposalError("There is no folder %s (or the server cannot read it)" % folder)
    extensions = EXTENSIONS.get(className, ())
    layouts = ("*.{ext}",) + (EPU if className in ("ProtImportMovies", "ProtImportMicrographs") else ()) + ("*/*.{ext}",)
    candidates = [pattern] if pattern else [layout.format(ext=ext) for layout in layouts for ext in extensions]
    for candidate in candidates:
        count, examples, capped = _matches(folder, candidate)
        if count:
            return {"pattern": candidate, "count": count, "examples": examples, "capped": capped}
    if pattern:
        raise ProposalError("No file of %s matches %s" % (folder, pattern))
    raise ProposalError("I found none of the usual files in %s%s: say the pattern of the files" % (
        folder, " (%s)" % ", ".join(extensions) if extensions else ""))


def givenValues(form: set, given: Dict[str, Any]) -> Dict[str, float]:
    """The values the user gave that the import's form has, checked."""
    values: Dict[str, float] = {}
    for name, label, lowest, highest in VALUES:
        raw = (given or {}).get(name)
        if raw in (None, "") or name not in form:
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            raise ProposalError("%s takes a number, not %r" % (label, raw))
        if not lowest <= number <= highest:
            raise ProposalError("%s %s is out of %s–%s" % (label, raw, lowest, highest))
        values[name] = number
    return values


def plan(name: Any, folder: Any, data: Any, pattern: Any, given: Dict[str, Any], streaming: Any,
         gain: Any, canBrowseServer: bool, protocols: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Everything checked: what the card shows and what the apply makes."""
    name = projectName(name)
    chosen = resolveImport(data, protocols)
    if chosen is None:
        if str(folder or "").strip():
            raise ProposalError("Say what data the folder has, to pick its import")
        return {"name": name, "importClass": None}
    form = {param["name"] for param in chosen.get("params") or []}
    files = None
    where = None
    if str(folder or "").strip():
        if "filesPath" not in form:
            raise ProposalError("The %s form does not take a folder: its form asks for the files" % chosen["label"])
        where = reachable(str(folder), canBrowseServer)
        files = findFiles(where, chosen["className"], checkedPattern(pattern))
    gainFile = None
    if str(gain or "").strip() and "gainFile" in form:
        path = reachable(str(gain), canBrowseServer)
        if not path.is_file():
            raise ProposalError("There is no gain file %s" % path)
        gainFile = str(path)
    values = givenValues(form, given)
    labels = {key: label for key, label, _, _ in VALUES}
    missing = [labels[key] for key in NEEDED if key in form and key not in values] if files else []
    return {"name": name, "importClass": chosen["className"], "importTitle": chosen.get("label") or "",
            "form": sorted(form & {"filesPath", "filesPattern", "dataStreaming", "importFrom", "samplingRateMode"}),
            "folder": str(where) if where else None, "files": files, "values": values, "missing": missing,
            "gainFile": gainFile, "streaming": bool(streaming) and "dataStreaming" in form}


def card(data: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    labels = {key: label for key, label, _, _ in VALUES}
    files = data.get("files") or {}
    return {"kind": "action", "action": "newproject", "projectId": 0, "protocolId": "", "label": data["name"],
            "name": data["name"], "importClass": data["importClass"], "importTitle": data.get("importTitle"),
            "folder": data.get("folder"), "pattern": files.get("pattern"), "count": files.get("count"),
            "capped": bool(files.get("capped")), "examples": files.get("examples") or [],
            "values": [{"name": key, "label": labels[key], "value": value}
                       for key, value in (data.get("values") or {}).items()],
            "missing": data.get("missing") or [], "gainFile": data.get("gainFile"),
            "streaming": bool(data.get("streaming")), "reason": str(reason or "")[:500]}


def importProtocol(data: Dict[str, Any]) -> Dict[str, Any]:
    """The import as a one-protocol workflow (as an exported workflow writes it): only what was given."""
    protocol = {"object.className": data["importClass"], "object.id": "1",
                "object.label": str(data.get("importTitle") or data["importClass"])}
    form = set(data.get("form") or [])
    if data.get("files"):
        protocol.update({"filesPath": data["folder"], "filesPattern": data["files"]["pattern"]})
        if data["importClass"] in ("ProtImportMovies", "ProtImportMicrographs"):
            # From files, with the pixel size of the image (not from the magnification)
            protocol.update({key: 0 for key in ("importFrom", "samplingRateMode") if key in form})
    if "dataStreaming" in form:
        protocol["dataStreaming"] = bool(data.get("streaming"))
    protocol.update(data.get("values") or {})
    if data.get("gainFile"):
        protocol["gainFile"] = data["gainFile"]
    return protocol
