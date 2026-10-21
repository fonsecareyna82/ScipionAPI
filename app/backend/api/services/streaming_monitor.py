"""A live monitor of one streaming project: its processing chain, how fast each stage goes, and the quality
of what comes out.

The chain follows the outputs a CTF estimation was fed from: the micrographs it read, the movies they were
aligned from, and downstream the coordinates and particles picked or extracted from those micrographs.
With several CTF outputs the most recently updated one is followed unless the caller asks for another.

Counts come from the counters every Set keeps in its properties, so they cost nothing; the rates count the
items of each Set created in the last minutes. The quality series are read incrementally: the caller passes
the last item it has and gets the next ones, so a long session is never read again. A Set that was rebuilt
(another setId, or fewer items than the caller has seen) starts the series again.

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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

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
}

STAGES = ("movies", "micrographs", "ctf", "coordinates", "particles")

OUTPUT_SETS_SQL = """
    SELECT s.id AS "setId", p."protocolId", p."protocolClassName",
           LOWER(COALESCE(p.status, '')) AS status,
           COALESCE(NULLIF(p.params->>'runName', ''), p."protocolClassName") AS label,
           s."outputName", s."setClassName", s."itemClassName", s.properties, s."updatedAt"
      FROM scipion_sets s
      JOIN protocols p ON p.id = s."protocolDbId"
     WHERE s."projectId" = %s
       AND COALESCE(s.properties ->> 'runtimeReserved', 'false') <> 'true'
"""

INPUT_REFS_SQL = """
    SELECT "protocolId", "parentProtocolId", "parentOutputName"
      FROM protocol_input_refs
     WHERE "projectId" = %s AND "parentProtocolId" IS NOT NULL
"""

# Items of each Set created in the last window and in the one before, and the first and last item times.
SET_RATES_SQL = """
    SELECT "setId",
           COUNT(*) FILTER (WHERE COALESCE(creation, "createdAt") >= %s) AS "lastWindow",
           COUNT(*) FILTER (WHERE COALESCE(creation, "createdAt") >= %s
                              AND COALESCE(creation, "createdAt") < %s) AS "previousWindow",
           MIN(COALESCE(creation, "createdAt")) AS "firstAt",
           MAX(COALESCE(creation, "createdAt")) AS "lastAt"
      FROM scipion_set_items
     WHERE "setId" = ANY(%s)
     GROUP BY "setId"
"""

SERIES_ITEMS_SQL = """
    SELECT "scipionItemId", enabled, label, COALESCE(creation, "createdAt") AS "time", "values"
      FROM scipion_set_items
     WHERE "setId" = %s AND "scipionItemId" > %s
     ORDER BY "scipionItemId"
     LIMIT %s
"""

GET_SETTINGS_SQL = """
    SELECT settings FROM project_monitor_settings WHERE "projectId" = %s
"""

SAVE_SETTINGS_SQL = """
    INSERT INTO project_monitor_settings ("projectId", settings, "updatedBy", "updatedAt")
    VALUES (%s, %s, %s, NOW())
    ON CONFLICT ("projectId") DO UPDATE
       SET settings = EXCLUDED.settings, "updatedBy" = EXCLUDED."updatedBy", "updatedAt" = NOW()
"""

MOVIE_SHIFTS_SQL = """
    SELECT "scipionItemId", "values"
      FROM scipion_set_items
     WHERE "setId" = %s AND "scipionItemId" = ANY(%s)
"""


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
    return None


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
    for row in mapper.db.fetchAll(OUTPUT_SETS_SQL, (int(projectId),)) or []:
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


def _inputsOf(mapper, projectId: int) -> Dict[str, List[tuple]]:
    """protocolId -> the (protocolId, outputName) it reads."""
    inputs: Dict[str, List[tuple]] = {}
    for row in mapper.db.fetchAll(INPUT_REFS_SQL, (int(projectId),)) or []:
        inputs.setdefault(str(row["protocolId"]), []).append(
            (str(row["parentProtocolId"]), str(row.get("parentOutputName") or "")))
    return inputs


def _newest(outputs: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = list(outputs)
    if not candidates:
        return None
    return max(candidates, key=lambda output: (output["_updatedAt"] is not None, output["_updatedAt"] or 0,
                                               output["setId"]))


def _chain(outputs: List[Dict[str, Any]], inputs: Dict[str, List[tuple]],
           ctfSetId: Optional[int]) -> Dict[str, Dict[str, Any]]:
    """The output of each stage of the followed stream."""
    byKey = {(output["protocolId"], output["outputName"]): output for output in outputs}

    def read(protocolId: str, stage: str) -> List[Dict[str, Any]]:
        found = [byKey.get(ref) for ref in inputs.get(protocolId, [])]
        return [output for output in found if output is not None and output["stage"] == stage]

    def readers(output: Dict[str, Any], stage: str) -> List[Dict[str, Any]]:
        key = (output["protocolId"], output["outputName"])
        return [candidate for candidate in outputs if candidate["stage"] == stage
                and key in inputs.get(candidate["protocolId"], [])]

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
        coordinates = _newest(readers(micrographs, "coordinates"))
        if coordinates is not None:
            chain["coordinates"] = coordinates
            particles = _newest(readers(coordinates, "particles"))
            if particles is not None:
                chain["particles"] = particles
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
    rows = mapper.db.fetchAll(SET_RATES_SQL, (now - window, now - 2 * window, now - window, list(setIds))) or []
    rates = {}
    for row in rows:
        last = int(row.get("lastWindow") or 0)
        previous = int(row.get("previousWindow") or 0)
        perMinute = last / float(RATE_WINDOW_MINUTES)
        trend = "steady"
        if previous == 0 and last > 0:
            trend = "up"
        elif previous > 0:
            change = (last - previous) / float(previous)
            trend = "up" if change > RATE_TREND_THRESHOLD else "down" if change < -RATE_TREND_THRESHOLD else "steady"
        rates[int(row["setId"])] = {"perMinute": perMinute, "trend": trend,
                                    "firstAt": _iso(row.get("firstAt")), "lastAt": _iso(row.get("lastAt"))}
    return rates


def _stages(chain: Dict[str, Dict[str, Any]], rates: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    stages = []
    previous = None
    for stage in STAGES:
        output = chain.get(stage)
        if output is None:
            continue
        entry = {key: value for key, value in output.items() if not key.startswith("_")}
        entry.update(rates.get(output["setId"], {"perMinute": 0.0, "trend": "steady", "firstAt": None,
                                                 "lastAt": None}))
        # What the stage before produced that this one has not yet: the backlog. Coordinates and particles
        # come many per micrograph, so they are not compared.
        entry["behind"] = (max(0, previous["items"] - output["items"])
                           if previous is not None and stage in ("micrographs", "ctf") else None)
        stages.append(entry)
        previous = output
    return stages


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
    for row in mapper.db.fetchAll(MOVIE_SHIFTS_SQL, (movies["setId"], list(itemIds))) or []:
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
        row = mapper.db.fetchOne(GET_SETTINGS_SQL, (int(projectId),))
    except Exception:
        logger.warning("The monitor thresholds of project %s could not be read", projectId, exc_info=True)
        return {}
    settings = (row or {}).get("settings") or {}
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
    from app.backend.mapper.postgresql import _toJsonParam

    try:
        mapper.db.execute(SAVE_SETTINGS_SQL, (int(projectId), _toJsonParam({"thresholds": checked}),
                                              int(userId) if userId is not None else None))
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
    return alerts


def _series(mapper, chain: Dict[str, Dict[str, Any]], afterSetId: Optional[int], afterItemId: Optional[int],
            thresholds: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """The points of the CTF output; before there is one, of the micrographs, with their drift only."""
    base = chain.get("ctf") or chain.get("micrographs")
    if base is None:
        return {"setId": None, "kind": None, "reset": afterSetId is not None, "lastItemId": None, "more": False,
                "points": []}
    reset = afterSetId != base["setId"] or (afterItemId is not None and base["maxItemId"] is not None
                                            and afterItemId > base["maxItemId"])
    after = 0 if reset or afterItemId is None else int(afterItemId)
    rows = mapper.db.fetchAll(SERIES_ITEMS_SQL, (base["setId"], after, SERIES_BATCH)) or []
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
        point["alerts"] = alertsOf(point, thresholds)
        points.append({key: value for key, value in point.items() if value is not None})
    return {
        "setId": base["setId"],
        "kind": base["stage"],
        "reset": bool(reset and afterSetId is not None),
        "lastItemId": points[-1]["id"] if points else (None if reset else afterItemId),
        "more": len(rows) >= SERIES_BATCH,
        "points": points,
    }


def streamingMonitor(mapper, projectId: int, ctfSetId: Optional[int] = None, afterSetId: Optional[int] = None,
                     afterItemId: Optional[int] = None, thresholds: Optional[Dict[str, Any]] = None,
                     now: Optional[datetime] = None) -> Dict[str, Any]:
    """The followed stream of a project: its stages, their rates, and the quality points after the given one."""
    now = now or datetime.now(timezone.utc)
    outputs = _outputs(mapper, projectId)
    chain = _chain(outputs, _inputsOf(mapper, projectId), ctfSetId)
    rates = _rates(mapper, [chain[stage]["setId"] for stage in STAGES if stage in chain], now)
    limits = thresholdsWith(storedThresholds(mapper, projectId) if thresholds is None else thresholds)
    return {
        "now": now.isoformat(),
        "streaming": any(chain[stage]["streaming"] for stage in STAGES if stage in chain),
        "stages": _stages(chain, rates),
        "ctfOutputs": [{"setId": output["setId"], "protocolId": output["protocolId"], "label": output["label"],
                        "outputName": output["outputName"]}
                       for output in sorted((o for o in outputs if o["stage"] == "ctf"), key=lambda o: o["setId"])],
        "thresholds": limits,
        "series": _series(mapper, chain, afterSetId, afterItemId, limits),
    }
