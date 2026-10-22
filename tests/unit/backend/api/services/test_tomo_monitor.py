"""The tomography monitor: the chain it follows and what it tells of each tilt series."""
from datetime import datetime, timezone

import pytest

from app.backend.api.services import streaming_monitor as spa
from app.backend.api.services import tomo_monitor as tomo
from app.backend.mapper import streaming_monitor_mapper as queries

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def noCache():
    tomo._cache.clear()
    tomo._alertCache.clear()
    yield
    tomo._cache.clear()
    tomo._alertCache.clear()


def output(setId, protocolId, outputName, setClassName, items):
    return {"setId": setId, "protocolId": protocolId, "protocolClassName": "Prot%s" % protocolId,
            "status": "running", "label": "run %s" % protocolId, "outputName": outputName,
            "setClassName": setClassName, "itemClassName": "",
            "properties": {"itemsCount": items, "maxItemId": items, "streamState": 1}, "updatedAt": NOW}


def ref(protocolId, parentProtocolId, parentOutputName):
    return {"protocolId": protocolId, "parentProtocolId": parentProtocolId, "parentOutputName": parentOutputName}


def tilt(order, angle, enabled=True, dose=None, matrix=None, index=None):
    values = {"_acqOrder": order, "_tiltAngle": angle, "_index": index or order}
    if dose is not None:
        values["_acquisition._accumDose"] = dose
    if matrix is not None:
        values["_transform._matrix"] = matrix
    return {"itemId": order, "enabled": enabled, "values": values}


def ctfTilt(order, defocusU, defocusV=None, resolution=None, enabled=True):
    values = {"_acqOrder": order, "_defocusU": defocusU, "_defocusV": defocusV if defocusV is not None else defocusU}
    if resolution is not None:
        values["_resolution"] = resolution
    return {"itemId": order, "enabled": enabled, "values": values}


class Db:
    """Sets: setId -> list of root rows {itemId, tsId, size, updatedAt, ..., children: [tilt rows]}."""

    def __init__(self, outputs, refs, sets, aligned=(), settings=None):
        self.outputs, self.refs, self.sets = outputs, refs, sets
        self.alignedSets = set(aligned)
        self.settings = settings
        self.queries = []

    def fetchOne(self, query, params):
        if query == queries.GET_SETTINGS_SQL:
            return {"settings": self.settings} if self.settings else None
        raise AssertionError("Unexpected query")

    def fetchAll(self, query, params):
        self.queries.append(query)
        if query == queries.OUTPUT_SETS_SQL:
            return self.outputs
        if query == queries.INPUT_REFS_SQL:
            return self.refs
        if query in (queries.DEPENDENCIES_SQL, queries.SET_RATES_SQL):
            return []
        if query == queries.ALIGNED_SQL:
            return [{"aligned": 1}] if params[0] in self.alignedSets else []
        if query == queries.TILT_SERIES_SQL:
            return [{"itemId": r["itemId"], "enabled": True, "updatedAt": r.get("updatedAt", NOW), "time": NOW,
                     "tsId": r["tsId"], "size": r.get("size"), "samplingRate": 1.0, "hasAlignment": None,
                     "tilts": len(r["children"]), "tiltsUpdatedAt": NOW} for r in self.sets[params[0]]]
        if query == queries.ROOT_ROWS_SQL:
            return [{"itemId": r["itemId"], "enabled": True, "updatedAt": r.get("updatedAt", NOW), "tsId": r["tsId"],
                     "fileName": r.get("fileName"), "filename": r.get("filename"), "hasResidualInfo": None}
                    for r in self.sets[params[0]]]
        if query == queries.TILT_IMAGES_SQL:
            setId, itemIds = params
            result = []
            for r in self.sets[setId]:
                if r["itemId"] not in itemIds:
                    continue
                kept = [c for c in r["children"] if c["enabled"]]
                angles = [c["values"]["_tiltAngle"] for c in kept]
                doses = [c["values"].get("_acquisition._accumDose") for c in r["children"]
                         if c["values"].get("_acquisition._accumDose") is not None]
                result.append({"itemId": r["itemId"], "tilts": len(r["children"]), "enabled": len(kept),
                               "angleMin": min(angles, default=None), "angleMax": max(angles, default=None),
                               "dose": max(doses, default=None)})
            return result
        if query == queries.CTF_TILTS_SQL:
            setId, itemIds = params
            result = []
            for r in self.sets[setId]:
                if r["itemId"] not in itemIds:
                    continue
                good = [c["values"] for c in r["children"] if c["enabled"] and c["values"]["_defocusU"] > 0]
                failed = [c for c in r["children"] if not c["enabled"] or c["values"]["_defocusU"] <= -998]
                resolutions = [v["_resolution"] for v in good if v.get("_resolution")]
                result.append({
                    "itemId": r["itemId"], "tilts": len(r["children"]), "failed": len(failed),
                    "defocusU": sum(v["_defocusU"] for v in good) / len(good) if good else None,
                    "defocusV": sum(v["_defocusV"] for v in good) / len(good) if good else None,
                    "astigmatism": sum(abs(v["_defocusU"] - v["_defocusV"]) for v in good) / len(good) if good else None,
                    "resolution": max(resolutions, default=None)})
            return result
        if query == queries.TILTS_OF_SQL:
            setId, itemId = params
            return next(r["children"] for r in self.sets[setId] if r["itemId"] == itemId)
        raise AssertionError("Unexpected query")


class Mapper:
    def __init__(self, db):
        self.db = db


def tiltSeries(tsId, itemId, angles, enabled=None, size=None, **kwargs):
    enabled = enabled if enabled is not None else [True] * len(angles)
    children = [tilt(order + 1, angle, enabled=on, dose=3.0 * (order + 1))
                for order, (angle, on) in enumerate(zip(angles, enabled))]
    return dict({"itemId": itemId, "tsId": tsId, "size": size if size is not None else len(angles),
                 "children": children}, **kwargs)


ANGLES = list(range(-60, 61, 3))  # 41 tilts


def tomography(sets=None, residualFile=None):
    """Compose (1) -> IMOD CTF (2); xcorr (3) -> fiducial alignment (4, with its landmarks) -> reconstruction (5)."""
    outputs = [output(10, "1", "tiltSeries", "SetOfTiltSeries", 2),
               output(20, "2", "CTFTomoSeries", "SetOfCTFTomoSeries", 2),
               output(30, "3", "TiltSeries", "SetOfTiltSeries", 2),
               output(40, "4", "TiltSeries", "SetOfTiltSeries", 2),
               output(41, "4", "FiducialModelNoGaps", "SetOfLandmarkModels", 2),
               output(50, "5", "Tomograms", "SetOfTomograms", 1)]
    refs = [ref("2", "1", "tiltSeries"), ref("3", "1", "tiltSeries"), ref("4", "3", "TiltSeries"),
            ref("5", "4", "TiltSeries")]
    base = {
        10: [tiltSeries("TS_01", 1, ANGLES), tiltSeries("TS_02", 2, ANGLES[:20], size=41)],
        20: [{"itemId": 1, "tsId": "TS_01", "children": [ctfTilt(1, 30000.0, 29000.0, 5.0), ctfTilt(2, -999.0, -1.0),
                                                          ctfTilt(3, 32000.0, 31000.0, 7.0)]}],
        30: [tiltSeries("TS_01", 1, ANGLES)],
        40: [tiltSeries("TS_01", 1, ANGLES)],
        41: [{"itemId": 1, "tsId": "TS_01", "fileName": residualFile, "children": []}],
        50: [{"itemId": 7, "tsId": "TS_01", "filename": "Runs/000005/extra/TS_01.mrc", "children": []}],
    }
    base.update(sets or {})
    return Db(outputs, refs, base, aligned={30, 40})


def test_the_chain_follows_the_acquired_tilt_series_to_their_tomograms():
    payload = tomo.tomoMonitor(Mapper(tomography()), 7, now=NOW)

    assert [(s["stage"], s["setId"]) for s in payload["stages"]] == [
        ("tiltseries", 10), ("ctftomo", 20), ("aligned", 40), ("tomograms", 50)]
    behind = {s["stage"]: s["behind"] for s in payload["stages"]}
    # 2 acquired; 2 with CTF; 2 aligned; 1 tomogram of the 2 aligned
    assert behind == {"tiltseries": None, "ctftomo": 0, "aligned": 0, "tomograms": 1}
    assert payload["tomograms"] == {"setId": 50, "protocolId": "5", "outputName": "Tomograms"}


def test_each_tilt_series_tells_its_tilts_ctf_alignment_and_tomogram():
    rows = {row["tsId"]: row for row in tomo.tomoMonitor(Mapper(tomography()), 7, now=NOW)["tiltSeries"]}

    first = rows["TS_01"]
    assert (first["tilts"], first["enabledTilts"], first["angleMin"], first["angleMax"], first["dose"]) == (
        41, 41, -60.0, 60.0, 123.0)
    assert first["complete"] is True and first["aligned"] is True and first["tomogramId"] == 7
    assert (first["defocusU"], first["failedCtfTilts"], first["resolution"]) == (31000.0, 1, 7.0)
    assert first["alerts"] == []
    second = rows["TS_02"]
    assert second["complete"] is False and "defocusU" not in second and "tomogramId" not in second
    # Incomplete: its tilts and angles are not judged yet
    assert second["alerts"] == []


def test_a_complete_tilt_series_with_too_few_tilts_or_a_short_range_is_an_alert():
    short = tiltSeries("TS_03", 3, list(range(-40, 41, 4)))  # 21 tilts, up to ±40
    rows = tomo.tomoMonitor(Mapper(tomography(sets={10: [short]})), 7, now=NOW)["tiltSeries"]

    assert rows[0]["alerts"] == ["minTilts", "minAngleSpan"]


def test_excluded_tilts_do_not_count():
    excluded = tiltSeries("TS_04", 4, ANGLES, enabled=[i % 3 != 0 for i in range(41)])
    row = tomo.tomoMonitor(Mapper(tomography(sets={10: [excluded]})), 7, now=NOW)["tiltSeries"][0]

    assert row["enabledTilts"] == 27 and "minTilts" in row["alerts"]


def test_ctf_thresholds_and_failed_tilts_are_alerts_when_the_project_sets_them():
    db = tomography()
    db.settings = {"thresholds": {"maxFailedCtfTilts": 0, "maxResolution": 6}}
    row = next(r for r in tomo.tomoMonitor(Mapper(db), 7, now=NOW)["tiltSeries"] if r["tsId"] == "TS_01")

    assert row["alerts"] == ["maxResolution", "maxFailedCtfTilts"]


def test_tilt_series_are_worked_out_again_only_when_they_change():
    db = tomography()
    tomo.tomoMonitor(Mapper(db), 7, now=NOW)
    db.queries.clear()
    tomo.tomoMonitor(Mapper(db), 7, now=NOW)

    assert queries.TILT_IMAGES_SQL not in db.queries and queries.CTF_TILTS_SQL not in db.queries
    db.sets[10][1] = tiltSeries("TS_02", 2, ANGLES, updatedAt=datetime(2026, 10, 22, 12, 5, tzinfo=timezone.utc))
    db.queries.clear()
    row = next(r for r in tomo.tomoMonitor(Mapper(db), 7, now=NOW)["tiltSeries"] if r["tsId"] == "TS_02")

    assert queries.TILT_IMAGES_SQL in db.queries and row["complete"] is True


def test_the_residual_of_the_fiducial_alignment_comes_from_its_model_file(tmp_path, monkeypatch):
    model = tmp_path / "TS_01_noGaps.sfid"
    model.write_text("10 20 1 1 3.0 4.0\n30 40 1 2 0.0 1.0\n50 60 2 1 nan nan\n70 80 2 2 6.0 8.0\n")
    from app.backend.viewers import postgresql_path_resolver as resolvers
    monkeypatch.setattr(resolvers.PostgresqlProjectPathResolver, "resolveExistingPath", lambda self, name: name)

    db = tomography(residualFile=str(model))
    db.settings = {"thresholds": {"maxResidual": 4}}
    row = next(r for r in tomo.tomoMonitor(Mapper(db), 7, now=NOW)["tiltSeries"] if r["tsId"] == "TS_01")

    # (5 + 1 + 10) / 3 landmarks with a residual
    assert row["residual"] == pytest.approx(16 / 3) and "maxResidual" in row["alerts"]
    assert tomo.landmarkResiduals(str(model))["perTilt"] == {1: 3.0, 2: 10.0}


def test_the_detail_of_a_tilt_series_matches_ctf_and_alignment_by_acquisition_order(tmp_path, monkeypatch):
    model = tmp_path / "TS_01_noGaps.sfid"
    model.write_text("10 20 2 1 3.0 4.0\n")
    from app.backend.viewers import postgresql_path_resolver as resolvers
    monkeypatch.setattr(resolvers.PostgresqlProjectPathResolver, "resolveExistingPath", lambda self, name: name)
    aligned = tiltSeries("TS_01", 1, ANGLES)
    aligned["children"][0] = tilt(1, -60, matrix="[1.0, 0.0, 12.0, 0.0, 1.0, -3.0, 0.0, 0.0, 1.0]")
    db = tomography(sets={40: [aligned]}, residualFile=str(model))

    detail = tomo.tiltSeriesDetail(Mapper(db), 7, "TS_01")

    tilts = {t["acqOrder"]: t for t in detail["tilts"]}
    assert (tilts[1]["angle"], tilts[1]["defocusU"], tilts[1]["shiftX"], tilts[1]["shiftY"]) == (-60, 30000.0, 12.0, -3.0)
    assert tilts[2]["ctfFailed"] is True and "defocusU" not in tilts[2]
    assert tilts[2]["residual"] == 5.0
    assert [t["angle"] for t in detail["tilts"]][:3] == [-60, -57, -54]
    assert tomo.tiltSeriesDetail(Mapper(db), 7, "TS_99") is None


def test_a_project_without_tilt_series_has_no_tomography():
    db = Db([output(10, "1", "outputMicrographs", "SetOfMicrographs", 3)], [], {})

    assert tomo.hasTomography(Mapper(db), 7) is False
    assert tomo.tomoMonitor(Mapper(db), 7, now=NOW)["stages"] == []
    assert tomo.hasTomography(Mapper(tomography()), 7) is True


def test_tilt_series_movies_are_not_the_acquired_tilt_series():
    db = tomography()
    db.outputs.insert(0, output(5, "9", "outputTiltSeriesM", "SetOfTiltSeriesM", 2))

    assert tomo.tomoMonitor(Mapper(db), 7, now=NOW)["stages"][0]["setId"] == 10


def test_runs_of_tilt_series_past_a_threshold_reach_the_bell():
    late = datetime(2026, 10, 22, 12, 30, tzinfo=timezone.utc)
    short = [tiltSeries("TS_0%d" % i, i, list(range(-40, 41, 4))) for i in (1, 2)]
    db = tomography(sets={10: short})

    runs = tomo.projectAlertRuns(Mapper(db), 7)
    tomo._alertCache.clear()

    assert [(r["kind"], r["micrographName"], r["count"], r["text"]) for r in runs] == [
        ("minAngleSpan", "TS_01", 2, "Tilt range short of ±50°"), ("minTilts", "TS_01", 2, "Fewer than 30 tilts")]
    assert runs[0]["protocolId"] == "1"
    assert len(tomo.alertsSince(Mapper(db), 7, datetime(2026, 10, 22, 11, 0, tzinfo=timezone.utc))) == 2
    assert tomo.alertsSince(Mapper(db), 7, late) == []


def test_the_tomography_stages_carry_their_estimated_time():
    db = tomography()
    db.rates = [{"setId": 50, "lastWindow": 5, "previousWindow": 5, "sampled": 5, "oldest": NOW}]
    original = db.fetchAll

    def fetchAll(query, params):
        if query == queries.SET_RATES_SQL:
            return [row for row in db.rates if row["setId"] in params[3]]
        return original(query, params)

    db.fetchAll = fetchAll
    stages = {s["stage"]: s for s in tomo.tomoMonitor(Mapper(db), 7, now=NOW)["stages"]}

    # 1 tomogram waiting at half a tomogram a minute
    assert stages["tomograms"]["etaMinutes"] == 2.0
