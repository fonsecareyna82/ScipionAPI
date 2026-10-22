"""A live monitor of one streaming project: its processing chain, how fast each stage goes, and the quality
of what comes out.

The chain follows the outputs a CTF estimation was fed from: the micrographs it read, the movies they were
aligned from, and downstream the coordinates and particles picked or extracted from those micrographs.
With several CTF outputs the most recently updated one is followed unless the caller asks for another.

Counts come from the counters every Set keeps in its properties, so they cost nothing; the rates count the
items of each Set created in the last minutes. The quality series are read incrementally: the caller passes
the last item it has and gets the next ones, so a long session is never read again. A Set that was rebuilt
(another setId, or rows all written again) starts the series again.

The time of an item is when it was written to its Set, that is, when it was processed: Scipion keeps no
acquisition time for movies or micrographs.

Thresholds turn values into alerts per item; the caller decides how to show them. Each project keeps its
own in ``project_monitor_settings``; a project without them, or a database not migrated yet, uses the
defaults.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.backend.mapper.streaming_monitor_mapper import StreamingMonitorPostgresqlMapper

logger = logging.getLogger(__name__)


def _store(mapper) -> StreamingMonitorPostgresqlMapper:
    """The monitor's queries, over the database of the request's mapper."""
    return StreamingMonitorPostgresqlMapper(mapper.db)


STREAM_OPEN = 1
SERIES_BATCH = 2000
RATE_WINDOW_MINUTES = 10
# A rate that moves more than this from the previous window gets a trend arrow, as in the facilities report.
RATE_TREND_THRESHOLD = 0.1

# Defaults of the scipion-em-facilities monitors (CTF, Summary) and of Xmipp's movie max shift filter.
DEFAULT_THRESHOLDS: Dict[str, Optional[float]] = {
    "minDefocus": 1000.0,     # A
    "maxDefocus": 40000.0,    # A
    "maxAstigmatism": 1000.0,  # A, |defocusU - defocusV|
    "maxResolution": None,    # A, the CTF fit resolution; no default alert
    "maxFrameShift": 10.0,    # A, between two consecutive frames
    "maxTotalDrift": 45.0,    # A, the whole path of the movie
    "minParticles": None,     # coordinates picked on a micrograph; depends on the sample, no default alert
    # Tomography, per tilt series (see tomo_monitor)
    "minTilts": 30.0,         # enabled tilt images, as the exclude views filter of tomo
    "minAngleSpan": 50.0,     # degrees: the series should reach at least -50 and +50
    "maxFailedCtfTilts": None,  # tilts whose CTF estimation failed; no default alert
    "maxResidual": None,      # px, mean residual of the fiducial alignment (IMOD); no default alert
}

# alignedMicrographs: what the aligner wrote, when the micrographs the CTF reads come from a later protocol
STAGES = ("movies", "alignedMicrographs", "micrographs", "ctf", "coordinates", "particles", "classes2d")
MICROGRAPH_STAGES = ("alignedMicrographs", "micrographs", "ctf")


# Items of each Set created in the last window and in the one before. Only the newest items of each Set are
# looked at (through its (setId, scipionItemId) index), so a poll costs the same at the start of a session
# and after a million particles.
RATE_SAMPLE = 5000


def _stageOf(setClassName: str, itemClassName: str) -> Optional[str]:
    text = ("%s %s" % (setClassName or "", itemClassName or "")).replace("_", "").lower()
    if "tomo" in text or "tiltseries" in text:
        return None  # The monitor follows single particle streams
    if "setofmovies" in text:
        return "movies"
    if "setofmicrographs" in text:
        return "micrographs"
    if "setofctf" in text:
        return "ctf"
    if "setofcoordinates" in text:
        return "coordinates"
    if "setofparticles" in text:
        return "particles"
    if "setofclasses2d" in text:
        return "classes2d"
    return None


def _aware(value):
    if value is not None and hasattr(value, "tzinfo") and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        if getattr(value, "tzinfo", None) is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _properties(row: Dict[str, Any]) -> Dict[str, Any]:
    properties = row.get("properties") or {}
    if isinstance(properties, str):
        try:
            properties = json.loads(properties)
        except ValueError:
            properties = {}
    return properties if isinstance(properties, dict) else {}


def _toInt(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _outputs(mapper, projectId: int) -> List[Dict[str, Any]]:
    outputs = []
    for row in _store(mapper).listOutputSets(projectId):
        stage = _stageOf(row.get("setClassName"), row.get("itemClassName"))
        if stage is None:
            continue
        properties = _properties(row)
        streamState = _toInt(properties.get("streamState", properties.get("_streamState")))
        outputs.append({
            "stage": stage,
            "setId": int(row["setId"]),
            "protocolId": str(row["protocolId"]),
            "protocolClassName": str(row.get("protocolClassName") or ""),
            "label": str(row.get("label") or ""),
            "status": str(row.get("status") or ""),
            "outputName": str(row.get("outputName") or ""),
            "setClassName": str(row.get("setClassName") or ""),
            "items": _toInt(properties.get("itemsCount")) or 0,
            "maxItemId": _toInt(properties.get("maxItemId")),
            "streaming": streamState == STREAM_OPEN,
            "_updatedAt": row.get("updatedAt"),
        })
    return outputs


def _inputsOf(mapper, projectId: int, outputs: Sequence[Dict[str, Any]] = ()) -> Dict[str, List[tuple]]:
    """protocolId -> the (protocolId, outputName) it reads.

    A protocol the graph says depends on another, with no input ref to it, reads every output of that one:
    without it the stream would stop there (refs are missing, for instance, for runs older than them)."""
    inputs: Dict[str, List[tuple]] = {}
    for row in _store(mapper).listInputRefs(projectId):
        inputs.setdefault(str(row["protocolId"]), []).append(
            (str(row["parentProtocolId"]), str(row.get("parentOutputName") or "")))
    if outputs:
        outputNames: Dict[str, List[str]] = {}
        for output in outputs:
            outputNames.setdefault(output["protocolId"], []).append(output["outputName"])
        try:
            edges = _store(mapper).listDependencies(projectId)
        except Exception:
            logger.warning("The protocol dependencies of project %s could not be read", projectId, exc_info=True)
            edges = []
        for row in edges:
            child, parent = str(row["protocolId"]), str(row["parentProtocolId"])
            refs = inputs.setdefault(child, [])
            if not any(ref[0] == parent for ref in refs):
                refs.extend((parent, name) for name in outputNames.get(parent, []))
    return inputs


def _newest(outputs: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = list(outputs)
    if not candidates:
        return None
    return max(candidates, key=lambda output: (output["_updatedAt"] is not None, output["_updatedAt"] or 0,
                                               output["setId"]))


def _downstream(outputs: List[Dict[str, Any]], inputs: Dict[str, List[tuple]], sources: List[Dict[str, Any]],
                target: str, through: Sequence[str]) -> List[tuple]:
    """Every ``target`` output made from these sources, directly or through any outputs of the ``through``
    stages in between (a CTF consensus or a shift filter between micrographs and picking, a particle screening
    between extraction and classification), with how many steps away it is."""
    reached = {(output["protocolId"], output["outputName"]) for output in sources}
    level = list(reached)
    found: List[tuple] = []
    steps = 0
    while level:
        steps += 1
        readersOf = [candidate for candidate in outputs
                     if any(ref in level for ref in inputs.get(candidate["protocolId"], []))]
        found += [(candidate, steps) for candidate in readersOf if candidate["stage"] == target]
        level = [(candidate["protocolId"], candidate["outputName"]) for candidate in readersOf
                 if candidate["stage"] in through
                 and (candidate["protocolId"], candidate["outputName"]) not in reached]
        reached.update(level)
    return found


def _nearest(found: List[tuple]) -> Optional[Dict[str, Any]]:
    if not found:
        return None
    nearest = min(steps for _, steps in found)
    return _newest(output for output, steps in found if steps == nearest)


def _readInput(outputs: List[Dict[str, Any]], inputs: Dict[str, List[tuple]], output: Dict[str, Any],
               stage: str) -> Optional[Dict[str, Any]]:
    """The ``stage`` output the protocol of ``output`` reads."""
    byKey = {(candidate["protocolId"], candidate["outputName"]): candidate for candidate in outputs}
    read = [byKey[ref] for ref in inputs.get(output["protocolId"], []) if ref in byKey and byKey[ref]["stage"] == stage]
    return _newest(read)


def _pickings(outputs: List[Dict[str, Any]], inputs: Dict[str, List[tuple]],
              sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every picking of the project, with what follows it: its extraction (the nearest particles made from its
    coordinates, through any coordinates filter or picking consensus) and the 2D classes made from those
    particles, through any particle filter or preprocessing. ``steps`` is how far it is from the followed CTF
    and micrographs; None when it is made from another branch."""
    fromStream: Dict[int, int] = {}
    for coordinates, steps in _downstream(outputs, inputs, sources, "coordinates", ("micrographs", "ctf", "coordinates")):
        fromStream[coordinates["setId"]] = min(steps, fromStream.get(coordinates["setId"], steps))
    pickings = []
    for coordinates in (output for output in outputs if output["stage"] == "coordinates"):
        particles = _nearest(_downstream(outputs, inputs, [coordinates], "particles", ("coordinates",)))
        classified = _downstream(outputs, inputs, [particles], "classes2d", ("particles",)) \
            if particles is not None else []
        pickings.append({"coordinates": coordinates, "steps": fromStream.get(coordinates["setId"]),
                         "particles": particles, "classes2d": _nearest(classified),
                         "allClasses": {output["setId"] for output, _ in classified}})
    return pickings


def _followedPicking(pickings: List[Dict[str, Any]], coordinatesSetId: Optional[int],
                     classesSetId: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The picking asked for; else the one that leads to the 2D classes asked for; else the one that goes
    furthest (to 2D classes, then to particles), then the nearest, then the newest."""
    asked = next((picking for picking in pickings if picking["coordinates"]["setId"] == coordinatesSetId), None)
    if asked is not None or not pickings:
        return asked

    def rank(picking):
        updatedAt = picking["coordinates"]["_updatedAt"]
        steps = picking["steps"]
        return (classesSetId is not None and classesSetId in picking["allClasses"],
                picking["classes2d"] is not None, picking["particles"] is not None, steps is not None,
                -(steps or 0), updatedAt is not None, updatedAt or 0, picking["coordinates"]["setId"])

    return max(pickings, key=rank)


def _chain(outputs: List[Dict[str, Any]], inputs: Dict[str, List[tuple]],
           ctfSetId: Optional[int], coordinatesSetId: Optional[int] = None,
           classesSetId: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
    """The output of each stage of the followed stream. ``pickings`` lists the pickings it could follow."""
    byKey = {(output["protocolId"], output["outputName"]): output for output in outputs}

    def read(protocolId: str, stage: str) -> List[Dict[str, Any]]:
        found = [byKey.get(ref) for ref in inputs.get(protocolId, [])]
        return [output for output in found if output is not None and output["stage"] == stage]

    def source(output: Dict[str, Any], stage: str) -> tuple:
        """The ``stage`` output this one was made from, through any outputs of its own kind in between
        (a CTF consensus reads CTFs, a preprocessing reads micrographs), and the protocol that read it."""
        seen = set()
        current = [output]
        while current:
            found = [(item, reader["protocolId"]) for reader in current for item in read(reader["protocolId"], stage)]
            if found:
                newest = _newest(item for item, _ in found)
                return newest, next(protocolId for item, protocolId in found if item is newest)
            seen.update(item["setId"] for item in current)
            current = [item for candidate in current for item in read(candidate["protocolId"], output["stage"])
                       if item["setId"] not in seen]
        return None, None

    chain: Dict[str, Dict[str, Any]] = {}
    ctfs = [output for output in outputs if output["stage"] == "ctf"]
    # By default the estimation, which sees every micrograph; a consensus or a sampler only keeps some
    estimations = [output for output in ctfs if read(output["protocolId"], "micrographs")]
    ctf = next((output for output in ctfs if output["setId"] == ctfSetId), None) or _newest(estimations) \
        or _newest(ctfs)
    if ctf is not None:
        chain["ctf"] = ctf
        micrographs, _ = source(ctf, "micrographs")
    else:
        micrographs = _newest(output for output in outputs if output["stage"] == "micrographs")
    if micrographs is not None:
        chain["micrographs"] = micrographs
        movies, aligner = source(micrographs, "movies")
        if movies is not None:
            chain["movies"] = movies
        # The alignment shifts are on the movies the aligning protocol writes, not on the ones it read
        aligned = _newest(output for output in outputs if output["stage"] == "movies"
                          and output["protocolId"] == aligner)
        if aligned is not None:
            chain["alignedMovies"] = aligned
        alignedMicrographs = _newest(output for output in outputs if output["stage"] == "micrographs"
                                     and output["protocolId"] == aligner)
        if alignedMicrographs is not None and alignedMicrographs["setId"] != micrographs["setId"]:
            chain["alignedMicrographs"] = alignedMicrographs
        pickings = _pickings(outputs, inputs, [output for output in (micrographs, chain.get("ctf"))
                                               if output is not None])
        chain["pickings"] = pickings
        picking = _followedPicking(pickings, coordinatesSetId, classesSetId)
        if picking is not None:
            coordinates = picking["coordinates"]
            chain["coordinates"] = coordinates
            # The backlogs are counted on what each protocol reads: the micrographs a consensus kept, the
            # particles a screening kept
            pickedFrom = _readInput(outputs, inputs, coordinates, "micrographs")
            if pickedFrom is not None:
                chain["pickedFrom"] = pickedFrom
            if picking["particles"] is not None:
                chain["particles"] = picking["particles"]
            if picking["classes2d"] is not None:
                chain["classes2d"] = picking["classes2d"]
        asked = next((output for output in outputs if output["stage"] == "classes2d"
                      and output["setId"] == classesSetId), None)
        if asked is not None:
            chain["classes2d"] = asked
        if "classes2d" not in chain:
            # 2D classes no picking leads to (particles imported, or from where the graph does not tell)
            classes = _newest(output for output in outputs if output["stage"] == "classes2d")
            if classes is not None:
                chain["classes2d"] = classes
        if "classes2d" in chain:
            classifiedFrom = _readInput(outputs, inputs, chain["classes2d"], "particles")
            if classifiedFrom is not None:
                chain["classifiedFrom"] = classifiedFrom
    else:
        # Nothing aligned yet: the movies as they arrive, from an import rather than from an alignment
        movies = [output for output in outputs if output["stage"] == "movies"]
        imported = [output for output in movies if not read(output["protocolId"], "movies")]
        newest = _newest(imported) or _newest(movies)
        if newest is not None:
            chain["movies"] = newest
    return chain


def _rates(mapper, setIds: Sequence[int], now: datetime) -> Dict[int, Dict[str, Any]]:
    if not setIds:
        return {}
    window = timedelta(minutes=RATE_WINDOW_MINUTES)
    rows = _store(mapper).countRecentItems(setIds, now - window, now - 2 * window, now - window, RATE_SAMPLE)
    rates = {}
    for row in rows:
        last = int(row.get("lastWindow") or 0)
        previous = int(row.get("previousWindow") or 0)
        oldest = _aware(row.get("oldest"))
        if int(row.get("sampled") or 0) >= RATE_SAMPLE and oldest is not None and oldest > now - 2 * window:
            # So many items came that the sample does not reach back two windows: the rate is the sample's
            # own, and there is nothing to compare it with.
            minutes = max((now - oldest).total_seconds() / 60.0, 1.0 / 60)
            rates[int(row["setId"])] = {"perMinute": RATE_SAMPLE / minutes, "trend": "steady"}
            continue
        trend = "steady"
        if previous == 0 and last > 0:
            trend = "up"
        elif previous > 0:
            change = (last - previous) / float(previous)
            trend = "up" if change > RATE_TREND_THRESHOLD else "down" if change < -RATE_TREND_THRESHOLD else "steady"
        rates[int(row["setId"])] = {"perMinute": last / float(RATE_WINDOW_MINUTES), "trend": trend}
    return rates


def withEta(entry: Dict[str, Any]) -> Dict[str, Any]:
    """How long the backlog of a stage takes to clear at its rate of the last minutes (``etaMinutes``), or
    that it does not move (``stalled``). Coordinates and particles count their backlog in micrographs and
    their rate in items: the rate goes to micrographs with their items per micrograph."""
    behind, rate = entry.get("behind"), entry.get("perMinute")
    if not behind or rate is None:
        return entry
    if entry.get("micrographs") is not None:
        items, micrographs = entry.get("items") or 0, entry["micrographs"]
        rate = rate * micrographs / items if items and micrographs else None
    if rate is None:
        return entry
    if rate > 0:
        entry["etaMinutes"] = behind / rate
    else:
        entry["stalled"] = True
    return entry


def _stages(chain: Dict[str, Dict[str, Any]], rates: Dict[int, Dict[str, Any]],
            micCounts: Dict[str, Dict[str, Any]], classes: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The stages and their backlog: what the stage before produced that this one has not yet. Coordinates
    and particles come many per micrograph, so theirs is in micrographs: the ones not picked yet (a
    micrograph where nothing was picked counts as waiting), and the picked ones not extracted yet."""
    stages = []
    previous = None
    previousMicrographs = None
    for stage in STAGES:
        output = chain.get(stage)
        if output is None:
            continue
        entry = {key: value for key, value in output.items() if not key.startswith("_")}
        # The stage of the stream, which for the aligned micrographs is not the kind of their Set
        entry["stage"] = stage
        entry.update(rates.get(output["setId"], {"perMinute": 0.0, "trend": "steady"}))
        counted = micCounts.get(stage)
        entry["behind"] = None
        if stage == "classes2d":
            # Classes are made in rounds: their rows are classes, and the particles waiting for the next round
            # are what was extracted and not classified (particles left out of every class stay waiting).
            entry.update({"perMinute": None, "trend": None})
            classified = (classes or {}).get("particles")
            entry["particles"] = classified
            source = chain.get("classifiedFrom") or (previous if previous is not None
                                                     and previous["stage"] == "particles" else None)
            if source is not None and source is not previous:
                entry["classifiedFrom"] = {"protocolId": source["protocolId"], "label": source["label"],
                                           "outputName": source["outputName"], "items": source["items"]}
            if classified is not None and source is not None:
                entry["behind"] = max(0, source["items"] - classified)
        elif stage in MICROGRAPH_STAGES and previous is not None:
            entry["behind"] = max(0, previous["items"] - output["items"])
        elif counted is not None:
            entry["micrographs"] = len(counted["counts"])
            entry["counting"] = not counted["complete"]
            # Picking waits on the micrographs it reads (those a consensus kept, if it reads them)
            source = chain.get("pickedFrom") if stage == "coordinates" else None
            if source is not None:
                entry["pickedFrom"] = {"protocolId": source["protocolId"], "label": source["label"],
                                       "outputName": source["outputName"], "items": source["items"]}
            waitingOn = source["items"] if source is not None else previousMicrographs
            if waitingOn is not None and counted["complete"]:
                entry["behind"] = max(0, waitingOn - len(counted["counts"]))
        stages.append(withEta(entry))
        previous = output
        if stage in MICROGRAPH_STAGES:
            previousMicrographs = output["items"]
        elif counted is not None:
            previousMicrographs = len(counted["counts"]) if counted["complete"] else None
    return stages


def _classes(mapper, chain: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The 2D classes of the stream, biggest first, and the particles classified so far. ``version`` changes
    when the classes do: their averages are rewritten in place every round, so it keys their images."""
    output = chain.get("classes2d")
    if output is None:
        return None
    rows = _store(mapper).listClasses(output["setId"])
    classes = sorted(({"id": int(row["classId"]), "particles": int(row.get("particles") or 0),
                       "enabled": row.get("enabled") is not False} for row in rows),
                     key=lambda item: (-item["particles"], item["id"]))
    return {
        "setId": output["setId"],
        "protocolId": output["protocolId"],
        "outputName": output["outputName"],
        "version": _iso(output["_updatedAt"]),
        "particles": sum(item["particles"] for item in classes),
        "classes": classes,
    }


# -- quality series -------------------------------------------------------------

def _ctfRowBuilder():
    from app.backend.viewers.postgresql_ctf_reader import PostgresqlCtfReader
    return PostgresqlCtfReader(None, 0, 0, "")


def _floatList(value) -> Optional[List[float]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = [part for part in str(value).replace("[", "").replace("]", "").split(",") if part.strip()]
    try:
        return [float(item) for item in items]
    except (TypeError, ValueError):
        return None


def driftFromShifts(xshifts, yshifts, samplingRate) -> Optional[Dict[str, float]]:
    """The whole path of a movie and its largest step between two frames, in A.

    As Xmipp's movie max shift filter: the frame-to-frame distances of the alignment shifts (in pixels) times
    the pixel size. Shifts that are all zero (aligned movies that were saved) say nothing.
    """
    xs, ys = _floatList(xshifts), _floatList(yshifts)
    try:
        sampling = float(samplingRate)
    except (TypeError, ValueError):
        return None
    if not xs or not ys or len(xs) != len(ys) or len(xs) < 2 or sampling <= 0:
        return None
    if not any(xs) and not any(ys):
        return None
    steps = [math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]) * sampling for i in range(1, len(xs))]
    return {"totalDrift": sum(steps), "maxFrameShift": max(steps)}


def _valueBySuffix(values: Dict[str, Any], suffix: str):
    suffix = suffix.replace("_", "").replace(".", "").lower()
    for key, value in (values or {}).items():
        if str(key).replace("_", "").replace(".", "").lower().endswith(suffix):
            return value
    return None


def _values(item: Dict[str, Any]) -> Dict[str, Any]:
    values = item.get("values") or {}
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except ValueError:
            values = {}
    return values if isinstance(values, dict) else {}


def _movieDrifts(mapper, movies: Optional[Dict[str, Any]], itemIds: List[int]) -> Dict[int, Dict[str, float]]:
    """The drift of the movies with these ids (a movie, its micrograph and its CTF share the id)."""
    if movies is None or not itemIds:
        return {}
    drifts = {}
    for row in _store(mapper).listItemsByIds(movies["setId"], itemIds):
        values = _values(row)
        drift = driftFromShifts(_valueBySuffix(values, "_alignment._xshifts"),
                                _valueBySuffix(values, "_alignment._yshifts"),
                                _valueBySuffix(values, "_samplingRate"))
        if drift is not None:
            drifts[int(row["scipionItemId"])] = drift
    return drifts


def thresholdsWith(overrides: Optional[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    for key, value in (overrides or {}).items():
        if key in thresholds:
            thresholds[key] = None if value is None else float(value)
    return thresholds


class ThresholdsNotKept(RuntimeError):
    """The database could not keep the thresholds, e.g. it is not migrated yet."""


def validThresholds(thresholds: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """The thresholds a caller sends, checked: known names, positive numbers or None (no alert)."""
    if not isinstance(thresholds, dict):
        raise ValueError("The thresholds must be an object")
    unknown = sorted(set(thresholds) - set(DEFAULT_THRESHOLDS))
    if unknown:
        raise ValueError("Unknown thresholds: %s" % ", ".join(unknown))
    checked: Dict[str, Optional[float]] = {}
    for key, value in thresholds.items():
        if value is None:
            checked[key] = None
            continue
        if isinstance(value, bool):
            raise ValueError("%s must be a number" % key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError("%s must be a number" % key)
        if not math.isfinite(number) or number <= 0:
            raise ValueError("%s must be a positive number" % key)
        checked[key] = number
    limits = thresholdsWith(checked)
    if limits["minDefocus"] is not None and limits["maxDefocus"] is not None and \
            limits["minDefocus"] >= limits["maxDefocus"]:
        raise ValueError("The minimum defocus must be below the maximum one")
    return checked


def storedThresholds(mapper, projectId: int) -> Dict[str, Any]:
    """The thresholds a project changed; none if it has not, or the database is not migrated yet."""
    try:
        settings = _store(mapper).getSettings(projectId) or {}
    except Exception:
        logger.warning("The monitor thresholds of project %s could not be read", projectId, exc_info=True)
        return {}
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except ValueError:
            settings = {}
    thresholds = settings.get("thresholds") if isinstance(settings, dict) else None
    return thresholds if isinstance(thresholds, dict) else {}


def saveThresholds(mapper, projectId: int, userId: Optional[int], thresholds: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the thresholds of a project (the ones sent replace the ones it had) and give back all of them."""
    checked = validThresholds(thresholds)
    try:
        _store(mapper).saveSettings(projectId, {"thresholds": checked}, userId)
    except Exception as error:
        logger.warning("The monitor thresholds of project %s were not kept", projectId, exc_info=True)
        raise ThresholdsNotKept("The thresholds could not be kept; if the database was not migrated after the "
                                "last update, run the migrations (alembic upgrade head)") from error
    return thresholdsWith(checked)


def alertsOf(point: Dict[str, Any], thresholds: Dict[str, Optional[float]]) -> List[str]:
    """The thresholds one item goes past."""
    if point.get("failed"):
        return []
    alerts = []

    def above(key, limit):
        value = point.get(key)
        return value is not None and limit is not None and value > limit

    defocusU, defocusV = point.get("defocusU"), point.get("defocusV")
    if defocusU is not None and thresholds["maxDefocus"] is not None and max(defocusU, defocusV or defocusU) > \
            thresholds["maxDefocus"]:
        alerts.append("maxDefocus")
    if defocusV is not None and thresholds["minDefocus"] is not None and min(defocusV, defocusU or defocusV) < \
            thresholds["minDefocus"]:
        alerts.append("minDefocus")
    if point.get("astigmatism") is not None and thresholds["maxAstigmatism"] is not None and \
            abs(point["astigmatism"]) > thresholds["maxAstigmatism"]:
        alerts.append("maxAstigmatism")
    if above("resolution", thresholds["maxResolution"]):
        alerts.append("maxResolution")
    if above("maxFrameShift", thresholds["maxFrameShift"]):
        alerts.append("maxFrameShift")
    if above("totalDrift", thresholds["maxTotalDrift"]):
        alerts.append("maxTotalDrift")
    particles = point.get("particles")
    if particles is not None and thresholds.get("minParticles") is not None and particles < thresholds["minParticles"]:
        alerts.append("minParticles")
    return alerts


def _points(mapper, chain: Dict[str, Dict[str, Any]], base: Dict[str, Any], rows: List[Dict[str, Any]],
            thresholds: Dict[str, Optional[float]],
            picked: Optional[Dict[int, int]] = None) -> List[Dict[str, Any]]:
    """The CTF and drift of these rows of the followed output, and the thresholds each goes past. With the
    coordinates picked per micrograph, the micrographs already picked carry theirs."""
    drifts = _movieDrifts(mapper, chain.get("alignedMovies"), [int(row["scipionItemId"]) for row in rows])
    isCtf = base["stage"] == "ctf"
    builder = _ctfRowBuilder()
    points = []
    for position, row in enumerate(rows):
        itemId = int(row["scipionItemId"])
        if isCtf:
            ctfRow = builder._buildCtfRow(row, position)
            point = {key: ctfRow.get(key) for key in ("micrographName", "defocusU", "defocusV", "astigmatism",
                                                       "resolution", "fitQuality", "phaseShift", "failed")}
            enabled = ctfRow.get("excluded") is False
        else:
            point = {"micrographName": row.get("label") or _valueBySuffix(_values(row), "_micName")}
            enabled = row.get("enabled") is not False
        point.update({"id": itemId, "time": _iso(row.get("time")), "enabled": enabled})
        drift = drifts.get(itemId)
        if drift is None:
            # Motioncor and Relion keep the whole path on the micrograph when they dose weight
            total = _valueBySuffix(_values(row), "_rlnAccumMotionTotal")
            try:
                drift = {"totalDrift": float(total)} if total is not None else None
            except (TypeError, ValueError):
                drift = None
        point.update(drift or {})
        if picked is not None and itemId in picked:
            point["particles"] = picked[itemId]
        point["alerts"] = alertsOf(point, thresholds)
        points.append({key: value for key, value in point.items() if value is not None})
    return points


def _series(mapper, chain: Dict[str, Dict[str, Any]], afterSetId: Optional[int], afterRowId: Optional[int],
            thresholds: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """The points of the CTF output; before there is one, of the micrographs, with their drift only."""
    base = chain.get("ctf") or chain.get("micrographs")
    if base is None:
        return {"setId": None, "kind": None, "reset": afterSetId is not None, "lastRowId": None, "more": False,
                "points": []}
    reset = afterSetId != base["setId"]
    if not reset and afterRowId is not None:
        first = _store(mapper).getFirstRowId(base["setId"])
        reset = first is not None and int(first) > int(afterRowId)
    after = 0 if reset or afterRowId is None else int(afterRowId)
    rows = _store(mapper).listItemsAfterRow(base["setId"], after, SERIES_BATCH)
    return {
        "setId": base["setId"],
        "kind": base["stage"],
        "reset": bool(reset and afterSetId is not None),
        "lastRowId": int(rows[-1]["rowId"]) if rows else (None if reset else afterRowId),
        "more": len(rows) >= SERIES_BATCH,
        "points": _points(mapper, chain, base, rows, thresholds),
    }


def alertRuns(points: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Runs of consecutive micrographs (by id) past the same threshold, oldest first, as the monitor page
    shows them: failed estimations neither start nor end a run."""
    runs: List[Dict[str, Any]] = []
    current: Dict[str, Dict[str, Any]] = {}
    for point in sorted(points, key=lambda item: item["id"]):
        if point.get("failed"):
            continue
        kinds = set(point.get("alerts") or [])
        for kind in [kind for kind in current if kind not in kinds]:
            current.pop(kind)["ongoing"] = False
        for kind in sorted(kinds):
            run = current.get(kind)
            if run is None:
                run = {"kind": kind, "first": point, "last": point, "count": 0, "ongoing": True}
                current[kind] = run
                runs.append(run)
            run["last"] = point
            run["count"] += 1
    return runs


def streamingMonitor(mapper, projectId: int, ctfSetId: Optional[int] = None, afterSetId: Optional[int] = None,
                     afterRowId: Optional[int] = None, thresholds: Optional[Dict[str, Any]] = None,
                     now: Optional[datetime] = None, afterPickSetId: Optional[int] = None,
                     afterPickRowId: Optional[int] = None, coordinatesSetId: Optional[int] = None,
                     classesSetId: Optional[int] = None) -> Dict[str, Any]:
    """The followed stream of a project: its stages, their rates, and the quality points after the given one."""
    now = now or datetime.now(timezone.utc)
    outputs = _outputs(mapper, projectId)
    chain = _chain(outputs, _inputsOf(mapper, projectId, outputs), ctfSetId, coordinatesSetId, classesSetId)
    rates = _rates(mapper, [chain[stage]["setId"] for stage in STAGES if stage in chain and stage != "classes2d"],
                   now)
    limits = thresholdsWith(storedThresholds(mapper, projectId) if thresholds is None else thresholds)
    # Counted once per poll: the stages and the counts sent come from the same chunk
    micCounts = {stage: countByMicrograph(mapper, chain[stage]["setId"])
                 for stage in ("coordinates", "particles") if stage in chain}
    picking = _picking(chain, micCounts, afterPickSetId, afterPickRowId)
    classes = _classes(mapper, chain)
    return {
        "now": now.isoformat(),
        "streaming": any(chain[stage]["streaming"] for stage in STAGES if stage in chain),
        "stages": _stages(chain, rates, micCounts, classes),
        "ctfOutputs": [{"setId": output["setId"], "protocolId": output["protocolId"], "label": output["label"],
                        "outputName": output["outputName"]}
                       for output in sorted((o for o in outputs if o["stage"] == "ctf"), key=lambda o: o["setId"])],
        "coordinatesOutputs": [{"setId": picking["coordinates"]["setId"],
                                "protocolId": picking["coordinates"]["protocolId"],
                                "label": picking["coordinates"]["label"],
                                "outputName": picking["coordinates"]["outputName"]}
                               for picking in sorted(chain.get("pickings", []),
                                                     key=lambda item: item["coordinates"]["setId"])],
        "classesOutputs": [{"setId": output["setId"], "protocolId": output["protocolId"], "label": output["label"],
                            "outputName": output["outputName"]}
                           for output in sorted((o for o in outputs if o["stage"] == "classes2d"),
                                                key=lambda o: o["setId"])],
        "thresholds": limits,
        "series": _series(mapper, chain, afterSetId, afterRowId, limits),
        "picking": picking,
        "classes": classes,
        # Tilt series in the project: the monitor shows its tomography view too
        "tomography": _hasTomography(mapper, projectId),
    }


def _hasTomography(mapper, projectId: int) -> bool:
    from app.backend.api.services import tomo_monitor
    try:
        return tomo_monitor.hasTomography(mapper, projectId)
    except Exception:
        logger.warning("Whether project %s has tilt series could not be read", projectId, exc_info=True)
        return False


# -- coordinates and particles per micrograph --------------------------------------
#
# Coordinates and particles come many per micrograph, and a long session has millions: grouping a whole Set
# by micrograph on every poll is out of the question (its values have no index). Each process keeps a count
# per micrograph of every followed Set and adds to it the rows written since the last poll, through the row
# id; after a restart it counts again in chunks, one per poll. A Set rebuilt with new rows (its first row is
# above the ones counted) is counted from the start.

MIC_COUNT_CHUNK = 50000


_micCounts: Dict[int, Dict[str, Any]] = {}
_micCountsLock = threading.Lock()


def countByMicrograph(mapper, setId: int) -> Dict[str, Any]:
    """How many items of the Set each micrograph has, as far as counted: ``counts`` (micrograph id ->
    items), ``changed`` (micrograph id -> the last row that added to it), ``lastRowId`` and ``complete``."""
    with _micCountsLock:
        state = _micCounts.get(int(setId))
        if state is not None and state["lastRowId"]:
            first = _store(mapper).getFirstRowId(setId)
            if first is not None and int(first) > state["lastRowId"]:
                state = None
        if state is None:
            state = {"lastRowId": 0, "counts": {}, "changed": {}, "complete": False}
            _micCounts[int(setId)] = state
        rows = _store(mapper).countItemsPerMicrograph(setId, state["lastRowId"], MIC_COUNT_CHUNK)
        read = 0
        for row in rows:
            count = int(row.get("n") or 0)
            read += count
            lastRowId = int(row.get("lastRowId") or 0)
            state["lastRowId"] = max(state["lastRowId"], lastRowId)
            micId = _toInt(row.get("mic"))
            if micId is None:
                continue
            state["counts"][micId] = state["counts"].get(micId, 0) + count
            state["changed"][micId] = max(state["changed"].get(micId, 0), lastRowId)
        state["complete"] = read < MIC_COUNT_CHUNK
        return state


def _picking(chain: Dict[str, Dict[str, Any]], micCounts: Dict[str, Dict[str, Any]], afterSetId: Optional[int],
             afterRowId: Optional[int]) -> Dict[str, Any]:
    """The coordinates of each micrograph that changed since the caller's cursor (all of them on a first
    call, or when the coordinates output is another one)."""
    coordinates = chain.get("coordinates")
    if coordinates is None:
        return {"setId": None, "reset": afterSetId is not None, "lastRowId": None, "complete": True, "counts": {}}
    state = micCounts["coordinates"]
    reset = afterSetId != coordinates["setId"] or afterRowId is None or int(afterRowId) > state["lastRowId"]
    after = 0 if reset else int(afterRowId)
    return {
        "setId": coordinates["setId"],
        "reset": bool(reset and afterSetId is not None),
        "lastRowId": state["lastRowId"],
        "complete": state["complete"],
        "counts": {str(micId): state["counts"][micId] for micId, row in state["changed"].items() if row > after},
    }


# -- alerts for the notification bell ---------------------------------------------

ALERT_WINDOW = 300
ALERT_CACHE_SECONDS = 10.0

THRESHOLD_TEXT = {
    "minDefocus": "Defocus below %s Å",
    "maxDefocus": "Defocus above %s Å",
    "maxAstigmatism": "Astigmatism above %s Å",
    "maxResolution": "CTF resolution worse than %s Å",
    "maxFrameShift": "Frame shift above %s Å",
    "maxTotalDrift": "Total drift above %s Å",
    "minParticles": "Fewer than %s particles picked",
    "minTilts": "Fewer than %s tilts",
    "minAngleSpan": "Tilt range short of ±%s°",
    "maxFailedCtfTilts": "More than %s tilts without CTF",
    "maxResidual": "Alignment residual above %s px",
}


# projectId -> (when it was computed, its alert runs): every open tab polls the bell, the work is done once
_alertCache: Dict[int, tuple] = {}


def _limitText(kind: str, thresholds: Dict[str, Optional[float]]) -> str:
    value = thresholds.get(kind)
    shown = "%g" % value if value is not None else "?"
    return THRESHOLD_TEXT.get(kind, kind) % shown


def projectAlertRuns(mapper, projectId: int) -> List[Dict[str, Any]]:
    """The alert runs among the newest micrographs of the project's followed stream, as the bell tells them.

    A run whose first micrograph is the oldest one looked at may have started before: it is left out, so a
    long run is not announced again as it slides out of the window.
    """
    cached = _alertCache.get(int(projectId))
    if cached is not None and time.monotonic() - cached[0] < ALERT_CACHE_SECONDS:
        return cached[1]
    outputs = _outputs(mapper, projectId)
    chain = _chain(outputs, _inputsOf(mapper, projectId, outputs), None)
    base = chain.get("ctf") or chain.get("micrographs")
    runs: List[Dict[str, Any]] = []
    if base is not None:
        rows = list(reversed(_store(mapper).listLatestItems(base["setId"], ALERT_WINDOW)))
        thresholds = thresholdsWith(storedThresholds(mapper, projectId))
        picked = countByMicrograph(mapper, chain["coordinates"]["setId"])["counts"] if "coordinates" in chain \
            else None
        points = _points(mapper, chain, base, rows, thresholds, picked)
        oldest = min((point["id"] for point in points), default=None)
        for run in alertRuns(points):
            if len(rows) >= ALERT_WINDOW and run["first"]["id"] == oldest:
                continue
            runs.append({
                "kind": run["kind"],
                "text": _limitText(run["kind"], thresholds),
                "startedAt": run["first"].get("time"),
                "micrographName": run["first"].get("micrographName") or "Micrograph %s" % run["first"]["id"],
                "count": run["count"],
                "ongoing": run["ongoing"],
                "protocolId": base["protocolId"],
                "protocolClassName": base["protocolClassName"],
            })
    _alertCache[int(projectId)] = (time.monotonic(), runs)
    return runs


def _startedAfter(run: Dict[str, Any], since: datetime) -> bool:
    try:
        started = datetime.fromisoformat(str(run["startedAt"]))
    except (TypeError, ValueError):
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return started > since


def alertsSince(mapper, projectId: int, since: datetime) -> List[Dict[str, Any]]:
    """The alert runs of a project that started after ``since``."""
    return [run for run in projectAlertRuns(mapper, projectId) if _startedAfter(run, since)]
