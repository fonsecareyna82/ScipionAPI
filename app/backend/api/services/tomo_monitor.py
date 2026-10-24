"""A live monitor of a tomography stream: its processing chain and the quality of each tilt series.

The chain starts from the tilt series as they are acquired (an output whose protocol reads no tilt series:
a composition from mdoc files, an import) and follows what is made from them, through any protocol in
between that writes tilt series again (normalization, dose filter, exclusion of views...): the CTF of each
tilt, the aligned tilt series (the ones the reconstruction reads, else ones that carry an alignment), the
fiducial models with their residuals and the tomograms.

A tilt series is one row of its Set and its tilt images the rows of a child table, written together; the
row shows up a moment before its tilts, so a tilt series is complete once its child table holds as many
tilt images as it says (``_size``). What each tilt series and its CTF series hold is worked out once per
change of their rows (their ``updatedAt``) and kept per process, so polling reads only the root rows.

Alignment residuals are not stored in the database: IMOD's fiducial alignment writes them per landmark to
the model's text file (``_fileName``, columns x y tiltIm chainId xResid yResid, in pixels). It is read once
per file version.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.backend.api.services import streaming_monitor as spa
from app.backend.api.services.streaming_monitor import _store

logger = logging.getLogger(__name__)

STAGES = ("tiltseries", "ctftomo", "aligned", "tomograms", "coordinates3d")

# A failed CTF estimation of a tilt (tomo's setWrongDefocus, or a failed CTFFIND/AreTomo fit)
FAILED_DEFOCUS = -999.0


_cache: Dict[tuple, tuple] = {}
_cacheLock = threading.Lock()


def _stageOf(setClassName: str, itemClassName: str) -> Optional[str]:
    text = ("%s %s" % (setClassName or "", itemClassName or "")).replace("_", "").lower()
    if "setoftiltseriesm" in text:
        return None  # The movies of the tilts, before motion correction
    if "setoftiltseries" in text:
        return "tiltseries"
    if "setofctftomoseries" in text:
        return "ctftomo"
    if "setoftomograms" in text:
        return "tomograms"
    if "setoflandmarkmodels" in text:
        return "landmarks"
    if "setofcoordinates3d" in text:
        return "coordinates3d"
    return None


def _outputs(mapper, projectId: int) -> List[Dict[str, Any]]:
    outputs = []
    for row in _store(mapper).listOutputSets(projectId):
        stage = _stageOf(row.get("setClassName"), row.get("itemClassName"))
        if stage is None:
            continue
        properties = spa._properties(row)
        streamState = spa._toInt(properties.get("streamState", properties.get("_streamState")))
        outputs.append({
            "stage": stage,
            "setId": int(row["setId"]),
            "protocolId": str(row["protocolId"]),
            "protocolClassName": str(row.get("protocolClassName") or ""),
            "label": str(row.get("label") or ""),
            "status": str(row.get("status") or ""),
            "outputName": str(row.get("outputName") or ""),
            "setClassName": str(row.get("setClassName") or ""),
            "items": spa._toInt(properties.get("itemsCount")) or 0,
            "maxItemId": spa._toInt(properties.get("maxItemId")),
            "streaming": streamState == spa.STREAM_OPEN,
            "_updatedAt": row.get("updatedAt"),
            "_boxSize": spa._toInt(properties.get("_boxSize", properties.get("boxSize"))),
        })
    return outputs


def hasTomography(mapper, projectId: int) -> bool:
    """Whether the project has tilt series: the monitor then shows its tomography view."""
    return any(output["stage"] == "tiltseries" for output in _outputs(mapper, projectId))


def _isAligned(mapper, output: Dict[str, Any]) -> bool:
    return _store(mapper).hasAlignedItem(output["setId"])


def _chain(mapper, outputs: List[Dict[str, Any]], inputs: Dict[str, List[tuple]],
           tsSetId: Optional[int]) -> Dict[str, Dict[str, Any]]:
    """The output of each stage of the followed tomography stream."""
    series = [output for output in outputs if output["stage"] == "tiltseries"]
    acquired = [output for output in series
                if not spa._readInput(outputs, inputs, output, "tiltseries")]
    raw = next((output for output in series if output["setId"] == tsSetId), None) \
        or spa._newest(acquired) or spa._newest(series)
    chain: Dict[str, Dict[str, Any]] = {}
    if raw is None:
        return chain
    chain["tiltseries"] = raw
    through = ("tiltseries", "ctftomo", "landmarks")
    ctf = spa._nearest(spa._downstream(outputs, inputs, [raw], "ctftomo", through))
    if ctf is not None:
        chain["ctftomo"] = ctf
    tomograms = spa._nearest(spa._downstream(outputs, inputs, [raw], "tomograms", through))
    aligned = None
    if tomograms is not None:
        chain["tomograms"] = tomograms
        aligned = spa._readInput(outputs, inputs, tomograms, "tiltseries")
    if aligned is None or aligned["setId"] == raw["setId"]:
        found = spa._downstream(outputs, inputs, [raw], "tiltseries", ("tiltseries", "landmarks"))
        aligned = next((output for output, _ in sorted(found, key=lambda item: item[1])
                        if _isAligned(mapper, output)), None)
    if aligned is not None and aligned["setId"] != raw["setId"]:
        chain["aligned"] = aligned
    landmarks = [output for output, _ in spa._downstream(outputs, inputs, [raw], "landmarks", through)]
    if landmarks:
        chain["landmarks"] = spa._newest(landmarks)
    # The picking nearest to the tilt series, on any tomograms made from them: often not the followed ones
    # but a denoised or corrected reconstruction of another branch
    picking = spa._nearest(spa._downstream(outputs, inputs, [raw], "coordinates3d",
                                           ("tiltseries", "ctftomo", "landmarks", "tomograms", "coordinates3d")))
    if picking is not None:
        chain["coordinates3d"] = picking
        pickedFrom = spa._readInput(outputs, inputs, picking, "tomograms")
        if pickedFrom is not None:
            chain["pickedTomograms"] = pickedFrom
    return chain


def _cached(kind: str, setId: int, rows: List[Dict[str, Any]], compute) -> Dict[int, Dict[str, Any]]:
    """Per row (``itemId``) what ``compute`` gives for the rows that changed since it was last worked out."""
    results: Dict[int, Dict[str, Any]] = {}
    stale = []
    with _cacheLock:
        for row in rows:
            key = (kind, setId, int(row["itemId"]))
            version = (str(row.get("updatedAt")), str(row.get("tiltsUpdatedAt")), row.get("tilts"))
            cached = _cache.get(key)
            if cached is not None and cached[0] == version:
                results[int(row["itemId"])] = cached[1]
            else:
                stale.append((key, version, int(row["itemId"])))
    if stale:
        computed = compute([itemId for _, _, itemId in stale])
        with _cacheLock:
            for key, version, itemId in stale:
                value = computed.get(itemId, {})
                _cache[key] = (version, value)
                results[itemId] = value
    return results


def _float(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _tiltImages(mapper, setId: int, itemIds: List[int]) -> Dict[int, Dict[str, Any]]:
    rows = _store(mapper).summarizeTiltImages(setId, itemIds)
    return {int(row["itemId"]): {
        "tilts": int(row.get("tilts") or 0),
        "enabledTilts": int(row.get("enabled") or 0),
        "angleMin": _float(row.get("angleMin")),
        "angleMax": _float(row.get("angleMax")),
        "dose": _float(row.get("dose")),
    } for row in rows}


def _ctfTilts(mapper, setId: int, itemIds: List[int]) -> Dict[int, Dict[str, Any]]:
    rows = _store(mapper).summarizeCtfTilts(setId, itemIds)
    return {int(row["itemId"]): {
        "ctfTilts": int(row.get("tilts") or 0),
        "failedCtfTilts": int(row.get("failed") or 0),
        "defocusU": _float(row.get("defocusU")),
        "defocusV": _float(row.get("defocusV")),
        "astigmatism": _float(row.get("astigmatism")),
        "resolution": _float(row.get("resolution")),
    } for row in rows}


def _particlesPerTomogram(mapper, picking: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """How many coordinates the followed 3D picking has on each tomogram (by tsId), counted again only when
    the picking output changes."""
    if picking is None:
        return {}
    key = ("coordinates3d", picking["setId"])
    version = (picking["items"], picking["maxItemId"], str(picking["_updatedAt"]))
    with _cacheLock:
        cached = _cache.get(key)
    if cached is not None and cached[0] == version:
        return cached[1]
    counts = {str(row["tomoId"]): int(row["count"]) for row in
              _store(mapper).countCoordinates3dPerTomogram(picking["setId"]) if row.get("tomoId")}
    with _cacheLock:
        _cache[key] = (version, counts)
    return counts


def landmarkResiduals(path: str) -> Optional[Dict[str, Any]]:
    """The mean residual of the landmarks of a fiducial model, overall and per tilt image, in pixels.

    The file has one landmark per line: x y tiltIm chainId xResid yResid; landmarks without residual
    (NaN) are skipped."""
    total, count = 0.0, 0
    perTilt: Dict[int, List[float]] = {}
    try:
        with open(path) as handle:
            for line in handle:
                fields = line.split()
                if len(fields) < 6:
                    continue
                try:
                    tilt = int(float(fields[2]))
                    residual = math.hypot(float(fields[4]), float(fields[5]))
                except ValueError:
                    continue
                if not math.isfinite(residual):
                    continue
                total += residual
                count += 1
                perTilt.setdefault(tilt, []).append(residual)
    except OSError:
        return None
    if not count:
        return None
    return {"mean": total / count,
            "perTilt": {tilt: sum(values) / len(values) for tilt, values in perTilt.items()}}


def _residuals(mapper, projectId: int, landmarks: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """tsId -> the residuals of its fiducial model, read once per version of the file."""
    if landmarks is None:
        return {}
    from app.backend.viewers.postgresql_path_resolver import PostgresqlProjectPathResolver

    resolver = PostgresqlProjectPathResolver(mapper.db, int(projectId))
    results = {}
    for row in _store(mapper).listRootItems(landmarks["setId"]):
        if not row.get("tsId") or not row.get("fileName"):
            continue
        path = resolver.resolveExistingPath(row["fileName"])
        if not path:
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        key = ("residuals", path)
        version = (stat.st_mtime_ns, stat.st_size)
        with _cacheLock:
            cached = _cache.get(key)
        if cached is None or cached[0] != version:
            cached = (version, landmarkResiduals(path))
            with _cacheLock:
                _cache[key] = cached
        if cached[1] is not None:
            results[str(row["tsId"])] = cached[1]
    return results


def tomoAlertsOf(row: Dict[str, Any], thresholds: Dict[str, Optional[float]]) -> List[str]:
    """The thresholds one tilt series goes past. The tilts and the angles count once it is complete."""
    alerts = []

    def limit(name):
        return thresholds.get(name)

    if row.get("complete"):
        if limit("minTilts") is not None and row.get("enabledTilts") is not None \
                and row["enabledTilts"] < limit("minTilts"):
            alerts.append("minTilts")
        span = limit("minAngleSpan")
        if span is not None and row.get("angleMin") is not None and row.get("angleMax") is not None \
                and (row["angleMin"] > -span or row["angleMax"] < span):
            alerts.append("minAngleSpan")
    defocusU, defocusV = row.get("defocusU"), row.get("defocusV")
    if defocusU is not None:
        if limit("maxDefocus") is not None and max(defocusU, defocusV or defocusU) > limit("maxDefocus"):
            alerts.append("maxDefocus")
        if limit("minDefocus") is not None and min(defocusU, defocusV or defocusU) < limit("minDefocus"):
            alerts.append("minDefocus")
    for key, name in (("astigmatism", "maxAstigmatism"), ("resolution", "maxResolution"),
                      ("failedCtfTilts", "maxFailedCtfTilts"), ("residual", "maxResidual")):
        if row.get(key) is not None and limit(name) is not None and row[key] > limit(name):
            alerts.append(name)
    return alerts


def _rows(mapper, projectId: int, chain: Dict[str, Dict[str, Any]],
          thresholds: Dict[str, Optional[float]]) -> List[Dict[str, Any]]:
    raw = chain["tiltseries"]
    store = _store(mapper)
    seriesRows = store.listTiltSeries(raw["setId"])
    tilts = _cached("tilts", raw["setId"], seriesRows,
                    lambda itemIds: _tiltImages(mapper, raw["setId"], itemIds))
    ctfByTs: Dict[str, Dict[str, Any]] = {}
    ctf = chain.get("ctftomo")
    if ctf is not None:
        ctfRows = [dict(row, itemId=row["itemId"]) for row in
                   store.listRootItems(ctf["setId"])]
        computed = _cached("ctf", ctf["setId"], ctfRows, lambda itemIds: _ctfTilts(mapper, ctf["setId"], itemIds))
        for row in ctfRows:
            if row.get("tsId"):
                ctfByTs[str(row["tsId"])] = computed.get(int(row["itemId"]), {})
    alignedTsIds = set()
    if chain.get("aligned") is not None:
        alignedTsIds = {str(row["tsId"]) for row in store.listRootItems(chain["aligned"]["setId"]) if row.get("tsId")}
    tomogramByTs: Dict[str, int] = {}
    if chain.get("tomograms") is not None:
        tomogramByTs = {str(row["tsId"]): int(row["itemId"]) for row in
                        store.listRootItems(chain["tomograms"]["setId"]) if row.get("tsId")}
    residuals = _residuals(mapper, projectId, chain.get("landmarks"))
    particles = _particlesPerTomogram(mapper, chain.get("coordinates3d"))

    rows = []
    for series in seriesRows:
        itemId = int(series["itemId"])
        tsId = str(series.get("tsId") or itemId)
        counted = tilts.get(itemId, {})
        size = spa._toInt(series.get("size"))
        present = spa._toInt(series.get("tilts")) or counted.get("tilts") or 0
        row = {
            "id": itemId,
            "tsId": tsId,
            "time": spa._iso(series.get("time")),
            "enabled": series.get("enabled") is not False,
            "tilts": present,
            "complete": present > 0 and (size is None or present >= size),
        }
        row.update({key: value for key, value in counted.items() if key != "tilts"})
        row.update(ctfByTs.get(tsId, {}))
        row["aligned"] = tsId in alignedTsIds
        if tsId in residuals:
            row["residual"] = residuals[tsId]["mean"]
        if tsId in tomogramByTs:
            row["tomogramId"] = tomogramByTs[tsId]
        if tsId in particles:
            row["particles"] = particles[tsId]
        row["alerts"] = tomoAlertsOf(row, thresholds)
        rows.append({key: value for key, value in row.items() if value is not None})
    return sorted(rows, key=lambda item: item["id"])


def _stages(chain: Dict[str, Dict[str, Any]], rates: Dict[int, Dict[str, Any]],
            particles: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    stages = []
    raw = chain.get("tiltseries")
    for stage in STAGES:
        output = chain.get(stage)
        if output is None:
            continue
        entry = {key: value for key, value in output.items() if not key.startswith("_")}
        entry["stage"] = stage
        entry.update(rates.get(output["setId"], {"perMinute": 0.0, "trend": "steady"}))
        if stage == "coordinates3d":
            # Its items are coordinates: what waits are the tomograms it reads with none yet
            entry["tomogramsPicked"] = len(particles or {})
            pickedFrom = chain.get("pickedTomograms") or chain.get("tomograms")
            entry["behind"] = max(0, pickedFrom["items"] - entry["tomogramsPicked"]) if pickedFrom else None
            if chain.get("pickedTomograms") is not None:
                entry["pickedFrom"] = {key: pickedFrom[key] for key in ("protocolId", "label", "outputName", "items")}
            entry["boxSize"] = output["_boxSize"]
            stages.append(entry)
            continue
        # Tilt series acquired and not processed by this stage yet; tomograms wait on the aligned ones
        before = chain.get("aligned") if stage == "tomograms" and chain.get("aligned") is not None else raw
        entry["behind"] = max(0, before["items"] - output["items"]) if stage != "tiltseries" else None
        stages.append(spa.withEta(entry))
    return stages


def tomoMonitor(mapper, projectId: int, tsSetId: Optional[int] = None,
                now: Optional[datetime] = None) -> Dict[str, Any]:
    """The followed tomography stream of a project: its stages and one row per tilt series."""
    now = now or datetime.now(timezone.utc)
    outputs = _outputs(mapper, projectId)
    chain = _chain(mapper, outputs, spa._inputsOf(mapper, projectId, outputs), tsSetId)
    thresholds = spa.thresholdsWith(spa.storedThresholds(mapper, projectId))
    rates = spa._rates(mapper, [chain[stage]["setId"] for stage in STAGES if stage in chain], now)
    tomograms = chain.get("tomograms")
    return {
        "now": now.isoformat(),
        "streaming": any(chain[stage]["streaming"] for stage in STAGES if stage in chain),
        "stages": _stages(chain, rates, _particlesPerTomogram(mapper, chain.get("coordinates3d"))),
        "tiltSeriesOutputs": [{"setId": output["setId"], "protocolId": output["protocolId"], "label": output["label"],
                               "outputName": output["outputName"]}
                              for output in sorted((o for o in outputs if o["stage"] == "tiltseries"),
                                                   key=lambda o: o["setId"])],
        "tomograms": None if tomograms is None else {"setId": tomograms["setId"],
                                                     "protocolId": tomograms["protocolId"],
                                                     "outputName": tomograms["outputName"]},
        "thresholds": thresholds,
        "tiltSeries": _rows(mapper, projectId, chain, thresholds) if "tiltseries" in chain else [],
    }


# -- alerts for the notification bell -----------------------------------------------

ALERT_CACHE_SECONDS = 10.0

# projectId -> (when it was computed, its alert runs): every open tab polls the bell, the work is done once
_alertCache: Dict[int, tuple] = {}


def projectAlertRuns(mapper, projectId: int) -> List[Dict[str, Any]]:
    """The runs of consecutive tilt series past a threshold, as the tomography view shows them."""
    cached = _alertCache.get(int(projectId))
    if cached is not None and time.monotonic() - cached[0] < ALERT_CACHE_SECONDS:
        return cached[1]
    outputs = _outputs(mapper, projectId)
    runs: List[Dict[str, Any]] = []
    if any(output["stage"] == "tiltseries" for output in outputs):
        chain = _chain(mapper, outputs, spa._inputsOf(mapper, projectId, outputs), None)
        thresholds = spa.thresholdsWith(spa.storedThresholds(mapper, projectId))
        rows = _rows(mapper, projectId, chain, thresholds) if "tiltseries" in chain else []
        points = [{"id": row["id"], "time": row.get("time"), "micrographName": row["tsId"], "alerts": row["alerts"]}
                  for row in rows]
        for run in spa.alertRuns(points):
            runs.append({
                "kind": run["kind"],
                "text": spa._limitText(run["kind"], thresholds),
                "startedAt": run["first"].get("time"),
                "micrographName": run["first"]["micrographName"],
                "count": run["count"],
                "ongoing": run["ongoing"],
                "protocolId": chain["tiltseries"]["protocolId"],
                "protocolClassName": chain["tiltseries"]["protocolClassName"],
            })
    _alertCache[int(projectId)] = (time.monotonic(), runs)
    return runs


def alertsSince(mapper, projectId: int, since: datetime) -> List[Dict[str, Any]]:
    """The tilt series alert runs of a project that started after ``since``."""
    return [run for run in projectAlertRuns(mapper, projectId) if spa._startedAfter(run, since)]


# -- one tilt series --------------------------------------------------------------

def _itemIdOf(mapper, setId: int, tsId: str) -> Optional[int]:
    for row in _store(mapper).listRootItems(setId):
        if str(row.get("tsId")) == str(tsId):
            return int(row["itemId"])
    return None


def _shiftsAndRotation(values: Dict[str, Any]) -> Dict[str, float]:
    matrix = spa._floatList(spa._valueBySuffix(values, "_transform._matrix"))
    if not matrix or len(matrix) < 6:
        return {}
    if len(matrix) == 16:
        a, b, tx, c, d, ty = matrix[0], matrix[1], matrix[3], matrix[4], matrix[5], matrix[7]
    else:
        a, b, tx, c, d, ty = matrix[0], matrix[1], matrix[2], matrix[3], matrix[4], matrix[5]
    return {"shiftX": tx, "shiftY": ty, "rotation": math.degrees(math.atan2(b, a))}


def tiltSeriesDetail(mapper, projectId: int, tsId: str, tsSetId: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Per tilt image of one tilt series: its angle, dose and whether it was kept; its CTF; the shifts and
    rotation of its alignment; and the fiducial residual on it. Matched by acquisition order."""
    outputs = _outputs(mapper, projectId)
    chain = _chain(mapper, outputs, spa._inputsOf(mapper, projectId, outputs), tsSetId)
    raw = chain.get("tiltseries")
    if raw is None:
        return None
    rawItem = _itemIdOf(mapper, raw["setId"], tsId)
    if rawItem is None:
        return None

    def byOrder(setId: int, itemId: Optional[int]) -> Dict[int, Dict[str, Any]]:
        if itemId is None:
            return {}
        found = {}
        for row in _store(mapper).listChildItems(setId, itemId):
            values = spa._values(row)
            order = spa._toInt(spa._valueBySuffix(values, "_acqOrder"))
            found[order if order is not None else int(row["itemId"])] = dict(values, _enabled=row.get("enabled"))
        return found

    tilts = byOrder(raw["setId"], rawItem)
    ctf = chain.get("ctftomo")
    ctfTilts = byOrder(ctf["setId"], _itemIdOf(mapper, ctf["setId"], tsId)) if ctf else {}
    aligned = chain.get("aligned")
    alignedTilts = byOrder(aligned["setId"], _itemIdOf(mapper, aligned["setId"], tsId)) if aligned else {}
    residuals = _residuals(mapper, projectId, chain.get("landmarks")).get(str(tsId), {}).get("perTilt", {})

    detail = []
    for position, (order, values) in enumerate(sorted(tilts.items(), key=lambda item: item[0])):
        tilt = {
            "acqOrder": order,
            "angle": _float(values.get("_tiltAngle")),
            "dose": _float(spa._valueBySuffix(values, "_acquisition._accumDose")),
            "enabled": values.get("_enabled") is not False,
        }
        ctfValues = ctfTilts.get(order)
        if ctfValues is not None:
            defocusU = _float(ctfValues.get("_defocusU"))
            failed = defocusU is not None and defocusU <= FAILED_DEFOCUS + 1
            tilt["ctfFailed"] = failed or ctfValues.get("_enabled") is False
            if not failed:
                tilt.update({"defocusU": defocusU, "defocusV": _float(ctfValues.get("_defocusV")),
                             "resolution": _float(ctfValues.get("_resolution"))})
        alignedValues = alignedTilts.get(order)
        if alignedValues is not None:
            tilt.update(_shiftsAndRotation(alignedValues))
            tilt["alignedEnabled"] = alignedValues.get("_enabled") is not False
        # IMOD numbers the tilt images of a model from 1, in stack order
        index = spa._toInt(values.get("_index")) or position + 1
        if index in residuals:
            tilt["residual"] = residuals[index]
        detail.append({key: value for key, value in tilt.items() if value is not None})
    return {"tsId": str(tsId), "tilts": sorted(detail, key=lambda item: (item.get("angle") is None,
                                                                          item.get("angle") or 0))}


# -- the central slice of a tomogram ----------------------------------------------

def tomogramPath(mapper, projectId: int, setId: int, itemId: int) -> Optional[str]:
    from app.backend.viewers.postgresql_path_resolver import PostgresqlProjectPathResolver

    for row in _store(mapper).listRootItems(setId):
        if int(row["itemId"]) == int(itemId) and row.get("filename"):
            return PostgresqlProjectPathResolver(mapper.db, int(projectId)).resolveExistingPath(row["filename"])
    return None


def centralSlice(volumePath: str) -> int:
    from app.backend.utils.volume_utils import readVolumeArray3d

    volume, _ = readVolumeArray3d(volumePath)
    return max(0, int(volume.shape[0]) // 2)
