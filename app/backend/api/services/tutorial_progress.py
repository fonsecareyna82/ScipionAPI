"""Where a project is on the usual road of a processing, for the tutor of the help chat (a new user guided step by
step). Worked out from what the project's protocols made, never asked to the model:

- single particle: movies, aligned micrographs, CTF, picking, particles, 2D classes, initial volume, 3D classes and
  the refined volume;
- tomography: tilt-series movies, motion correction, CTF, alignment, tomograms, 3D picking, subtomograms and the
  average.

A stage is done when a finished protocol (or one still running in streaming) made its kind of output. A protocol
with nothing made yet is placed by the words of its class (e.g. "ctf"), to say that a stage is running, failed or
prepared. A stage left behind while a later one is done was skipped (e.g. micrographs imported without movies).
"""
from typing import Any, Dict, Iterable, List, Optional, Tuple

DONE, RUNNING, WAITING, FAILED, PREPARED, SKIPPED, PENDING = (
    "done", "running", "waiting", "failed", "prepared", "skipped", "pending")
RUNNING_STATES = {"running", "launched", "scheduled"}
FAILED_STATES = {"failed", "aborted"}
PREPARED_STATES = {"saved", "new"}
MAX_PROTOCOLS = 4

# How each stage is recognised: (output classes, words its protocol's class must have, words it must not have)
# for protocols that made something; words for those that made nothing yet; what to search the help for.
Rule = Tuple[Iterable[str], Iterable[str], Iterable[str]]

_INITIAL = ("initial", "abinit", "initvol", "significant")
_REFINE = ("refine", "nonuniform", "homogeneous", "highres")
_ALIGN_TS = ("align", "aretomo", "etomo", "xcorr", "fiducial")

STAGES = {
    "spa": [
        ("movies", "Import the movies", [({"SetOfMovies"}, (), ())], ("importmovies",), "import movies"),
        ("micrographs", "Align the movies", [({"SetOfMicrographs"}, (), ())],
         ("motioncorr", "alignmovies", "flexalign", "motioncor"), "movie alignment"),
        ("ctf", "Estimate the CTF", [({"SetOfCTF"}, (), ())], ("ctf",), "CTF estimation"),
        ("coordinates", "Pick the particles", [({"SetOfCoordinates"}, (), ())], ("pick",), "particle picking"),
        ("particles", "Extract the particles", [({"SetOfParticles"}, (), ())], ("extract",), "extract particles"),
        ("classes2d", "Classify them in 2D", [({"SetOfClasses2D"}, (), ())], ("2d",), "2D classification"),
        ("initial", "Make an initial volume", [({"SetOfVolumes", "Volume", "SetOfClasses3D"}, _INITIAL, ())],
         _INITIAL, "initial volume"),
        ("classes3d", "Classify them in 3D", [({"SetOfClasses3D"}, (), _INITIAL)], ("3dclass", "classify3d"),
         "3D classification"),
        ("refined", "Refine the volume", [({"Volume", "SetOfVolumes"}, _REFINE, ())], _REFINE, "3D refinement"),
    ],
    "tomo": [
        ("movies", "Import the tilt-series", [({"SetOfTiltSeriesM"}, (), ()), ({"SetOfTiltSeries"}, ("import",), ())],
         ("importts", "importtilt"), "import tilt series"),
        ("motion", "Correct the motion", [({"SetOfTiltSeries"}, (), ("import",))], ("motion",),
         "tilt series motion correction"),
        ("ctf", "Estimate the CTF", [({"SetOfCTFTomoSeries"}, (), ())], ("ctf",), "tilt series CTF estimation"),
        ("alignment", "Align the tilt-series", [({"SetOfTiltSeries", "SetOfTomograms"}, _ALIGN_TS, ())], _ALIGN_TS,
         "tilt series alignment"),
        ("tomograms", "Reconstruct the tomograms", [({"SetOfTomograms"}, (), ())],
         ("tomorecon", "reconstructtomo", "tomoreconstruct"),
         "tomogram reconstruction"),
        ("coordinates", "Pick in 3D", [({"SetOfCoordinates3D"}, (), ())], ("pick", "templatematching"),
         "3D particle picking"),
        ("subtomograms", "Extract the subtomograms", [({"SetOfSubTomograms"}, (), ())], ("extract",),
         "extract subtomograms"),
        ("average", "Average them", [({"AverageSubTomogram", "SetOfAverageSubTomograms",
                                       "SetOfClassesSubTomograms"}, (), ())],
         ("average", "reconstructparticle", "subtomorefine", "refinesubtomo"), "subtomogram averaging"),
    ],
}
KIND_TITLES = {"spa": "Single particle", "tomo": "Tomography"}
_TOMO_HINTS = ("TiltSeries", "Tomo", "Coordinates3D", "SubTomo")
_SPA_HINTS = ("SetOfMovies", "SetOfMicrographs", "SetOfParticles", "SetOfCoordinates", "SetOfCTF", "Classes2D")


def _has(name: str, words: Iterable[str]) -> bool:
    return any(word in name for word in words)


def _size(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def protocolsOf(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per protocol, in the project's order, with the classes of what it made and their sizes."""
    protocols: Dict[Any, Dict[str, Any]] = {}
    for row in rows:
        protocol = protocols.setdefault(row["protocolId"], {
            "id": str(row["protocolId"]), "className": row.get("className") or "", "label": row.get("label") or "",
            "status": row.get("status") or "", "outputs": {}})
        if row.get("outputClass"):
            size = _size(row.get("size"))
            known = protocol["outputs"].get(row["outputClass"])
            protocol["outputs"][row["outputClass"]] = max(filter(None, (known, size)), default=None)
    return list(protocols.values())


def kindOf(protocols: List[Dict[str, Any]]) -> Optional[str]:
    """'spa' or 'tomo' by what the project made (or, with nothing made, by its protocols); None for an empty one."""
    made = [name for protocol in protocols for name in protocol["outputs"]]
    tomo = sum(1 for name in made if _has(name, _TOMO_HINTS))
    spa = sum(1 for name in made if _has(name, _SPA_HINTS) and not _has(name, _TOMO_HINTS))
    if not made:
        classes = [protocol["className"] for protocol in protocols]
        tomo = sum(1 for name in classes if _has(name, ("Tomo", "Ts", "TiltSeries", "Subtomo", "SubTomo")))
        spa = len(classes) - tomo
    if not tomo and not spa:
        return None
    return "tomo" if tomo >= spa else "spa"


def _made(protocol: Dict[str, Any], rules: List[Rule]) -> Optional[int]:
    """How many items the protocol made for a stage (0 when unknown); None when it made nothing of it."""
    name = protocol["className"].lower()
    found = None
    for classes, need, avoid in rules:
        for output, size in protocol["outputs"].items():
            if output in classes and (not need or _has(name, need)) and not _has(name, avoid):
                found = max(found or 0, size or 0)
    return found


def stagesOf(kind: str, protocols: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    stages = []
    for key, title, rules, guess, search in STAGES[kind]:
        matched, items = [], None
        for protocol in protocols:
            made = _made(protocol, rules)
            if made is None and (protocol["outputs"] or not _has(protocol["className"].lower(), guess)):
                continue
            matched.append(dict(protocol, made=made))
            if made is not None and protocol["status"] not in FAILED_STATES:
                items = max(items or 0, made)
        statuses = {protocol["status"] for protocol in matched}
        producing = [protocol for protocol in matched if protocol["made"] is not None
                     and protocol["status"] not in FAILED_STATES]
        if statuses & RUNNING_STATES:
            state = RUNNING
        elif "interactive" in statuses:
            state = WAITING
        elif producing:
            state = DONE
        elif statuses & FAILED_STATES:
            state = FAILED
        elif statuses & PREPARED_STATES:
            state = PREPARED
        else:
            state = PENDING
        stages.append({
            "key": key, "title": title, "state": state, "items": items or None, "search": search,
            "protocols": [{"id": protocol["id"], "label": protocol["label"], "status": protocol["status"]}
                          for protocol in matched[-MAX_PROTOCOLS:]],
        })
    # A stage nobody did while a later one is done was skipped
    reached = False
    for stage in reversed(stages):
        if stage["state"] == DONE:
            reached = True
        elif reached and stage["state"] == PENDING:
            stage["state"] = SKIPPED
    return stages


def _from(stage: Dict[str, Any], protocols: List[Dict[str, Any]]) -> Optional[str]:
    """The protocol to go on from: the last one of the stage that made something and did not fail."""
    ids = {protocol["id"] for protocol in stage["protocols"]}
    usable = [protocol for protocol in protocols if protocol["id"] in ids and protocol["outputs"]
              and protocol["status"] not in FAILED_STATES]
    return usable[-1]["id"] if usable else None


def progress(rows: List[Dict[str, Any]], kind: Optional[str] = None) -> Dict[str, Any]:
    """{kind, title, stages, current, next, fromProtocolId}. current: the stage to look at now (one running, waiting
    for the user or failed, else the next to do); next: the first stage after the last one done."""
    protocols = protocolsOf(rows)
    kind = kind if kind in STAGES else kindOf(protocols)
    if kind is None:
        return {"kind": None, "title": "", "stages": [], "current": None, "next": None, "fromProtocolId": None,
                "empty": not protocols}
    stages = stagesOf(kind, protocols)
    lastDone = max((index for index, stage in enumerate(stages) if stage["state"] == DONE), default=-1)
    following = stages[lastDone + 1] if lastDone + 1 < len(stages) else None
    busy = next((stage for stage in stages if stage["state"] in (RUNNING, WAITING, FAILED)), None)
    current = busy or following
    return {
        "kind": kind, "title": KIND_TITLES[kind], "stages": stages,
        "current": current["key"] if current else None,
        "next": following["key"] if following else None,
        "fromProtocolId": _from(stages[lastDone], protocols) if lastDone >= 0 else None,
        "empty": not protocols,
    }


def card(projectId: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """The progress shown under the tutor's answer."""
    return {"kind": "tutorial", "projectId": int(projectId), "road": data.get("kind"), "title": data.get("title"),
            "current": data.get("current"),
            "stages": [{key: stage[key] for key in ("key", "title", "state", "items", "protocols")}
                       for stage in data.get("stages") or []]}


def describe(data: Dict[str, Any]) -> str:
    """The progress in a few lines, for the tutor's instructions."""
    if not data.get("kind"):
        return ("The project has no protocols yet." if data.get("empty") else
                "The project's protocols do not show yet whether it is single particle or tomography.") + \
            " Ask the user which kind of data they have (movies of single particles, or tilt-series) before guiding."
    lines = ["Road: %s. Stages (state, items made, protocols):" % data["title"]]
    for stage in data["stages"]:
        protocols = ", ".join("#%s %s (%s)" % (item["id"], item["label"], item["status"])
                              for item in stage["protocols"])
        lines.append("- %s [%s]: %s%s%s" % (stage["key"], stage["search"], stage["state"],
                                           ", %s items" % stage["items"] if stage["items"] else "",
                                           "; " + protocols if protocols else ""))
    lines.append("Current stage: %s. Next stage to do: %s. Go on from protocol: %s." % (
        data.get("current") or "none", data.get("next") or "none (the road is finished)",
        data.get("fromProtocolId") or "none"))
    return "\n".join(lines)
