"""The streaming monitor: the chain it follows, the rates of its stages and the quality points it reads."""
from datetime import datetime, timedelta, timezone

import pytest

from app.backend.api.services import streaming_monitor as monitor
from app.backend.mapper import streaming_monitor_mapper as queries

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def noCaches():
    """The alert runs and micrograph counts are kept per process: every test starts without them."""
    monitor._alertCache.clear()
    monitor._micCounts.clear()
    monitor._doseSets.clear()
    yield
    monitor._alertCache.clear()
    monitor._micCounts.clear()
    monitor._doseSets.clear()


def output(setId, protocolId, outputName, setClassName, items, streamState=1, updatedAt=None, maxItemId=None):
    return {"setId": setId, "protocolId": protocolId, "protocolClassName": "Prot%s" % protocolId,
            "status": "running", "label": "run %s" % protocolId, "outputName": outputName,
            "setClassName": setClassName, "itemClassName": "",
            "properties": {"itemsCount": items, "maxItemId": maxItemId or items, "streamState": streamState},
            "updatedAt": updatedAt or NOW}


def ref(protocolId, parentProtocolId, parentOutputName):
    return {"protocolId": protocolId, "parentProtocolId": parentProtocolId, "parentOutputName": parentOutputName}


def ctfItem(itemId, defocusU=20000.0, defocusV=19500.0, resolution=4.0, minutes=0, extra=None, rowId=None):
    """A CTF row; its row id says when it was written (by default in the order of the item ids)."""
    values = {"_defocusU": defocusU, "_defocusV": defocusV, "_resolution": resolution, "_fitQuality": 0.2}
    values.update(extra or {})
    return {"rowId": rowId if rowId is not None else 100 + itemId, "scipionItemId": itemId, "enabled": True,
            "label": "mic_%03d" % itemId, "time": NOW - timedelta(minutes=minutes), "values": values}


class Db:
    """Answers each monitor query with its rows; the series rows are filtered as the query would."""

    def __init__(self, outputs=(), refs=(), rates=(), items=(), movies=(), settings=None, picks=(), classes=(),
                 dependencies=(), doseRows=None, setRows=None):
        self.setRows = dict(setRows or {})
        self.outputs, self.refs, self.rates = list(outputs), list(refs), list(rates)
        # The rows of the outputs of a dose analysis: setId -> rows
        self.doseRows = dict(doseRows or {})
        # Rows of the coordinates and particles Sets: (setId, rowId, micrograph id)
        self.picks = list(picks)
        self.classes = list(classes)
        # Graph edges (child protocolId, parent protocolId)
        self.dependencies = list(dependencies)
        self.items, self.movies = list(items), list(movies)
        self.settings = settings
        self.calls = []
        self.executed = []
        self.shiftsSetIds = []

    def fetchOne(self, query, params):
        if query == queries.FIRST_ITEM_HAS_VALUE_SQL:
            key, setId = params
            rows = sorted(self.doseRows.get(setId, self.items), key=lambda item: item["rowId"])
            return {"has": key in rows[0]["values"]} if rows else None
        if query == queries.FIRST_ROW_SQL:
            rows = [rowId for setId, rowId, _ in self.picks if setId == params[0]] if any(
                setId == params[0] for setId, _, _ in self.picks) else [item["rowId"] for item in self.items]
            return {"firstRowId": min(rows, default=None)}
        assert query == queries.GET_SETTINGS_SQL
        if isinstance(self.settings, Exception):
            raise self.settings
        return {"settings": self.settings} if self.settings is not None else None

    def execute(self, query, params):
        self.executed.append((query, params))

    def fetchAll(self, query, params):
        self.calls.append((query, params))
        if query == queries.OUTPUT_SETS_SQL:
            return self.outputs
        if query == queries.INPUT_REFS_SQL:
            return self.refs
        if query == queries.DEPENDENCIES_SQL:
            return [{"protocolId": child, "parentProtocolId": parent} for child, parent in self.dependencies]
        if query == queries.SET_RATES_SQL:
            return [row for row in self.rates if row["setId"] in params[3]]
        if query == queries.SERIES_ITEMS_SQL:
            setId, after, limit = params
            rows = self.doseRows.get(setId, self.items)
            return sorted((item for item in rows if item["rowId"] > after), key=lambda item: item["rowId"])[:limit]
        if query == queries.MIC_COUNTS_SQL:
            setId, after, limit = params
            chunk = sorted((row for row in self.picks if row[0] == setId and row[1] > after), key=lambda row: row[1])[:limit]
            grouped = {}
            for _, rowId, mic in chunk:
                count, last = grouped.get(mic, (0, 0))
                grouped[mic] = (count + 1, max(last, rowId))
            return [{"mic": None if mic is None else str(mic), "n": n, "lastRowId": last}
                    for mic, (n, last) in grouped.items()]
        if query == queries.CLASSES_SQL:
            return list(self.classes)
        if query == queries.LATEST_ROWS_SQL:
            setId, limit = params
            rows = self.setRows.get(setId, self.doseRows.get(setId, self.items))
            return sorted(rows, key=lambda item: item["rowId"], reverse=True)[:limit]
        if query == queries.ITEMS_BY_IDS_SQL:
            if params[0] in self.setRows:
                return [row for row in self.setRows[params[0]] if row["scipionItemId"] in params[1]]
            self.shiftsSetIds.append(params[0])
            return [movie for movie in self.movies if movie["scipionItemId"] in params[1]]
        raise AssertionError("Unexpected query")


class Mapper:
    def __init__(self, db):
        self.db = db


def preprocessing(**kwargs):
    """Import movies (1) -> motioncor (2) -> CTF (3) -> picking (4) -> extraction (5)."""
    outputs = [
        output(10, "1", "outputMovies", "SetOfMovies", 100),
        output(20, "2", "outputMicrographsDoseWeighted", "SetOfMicrographs", 90),
        output(21, "2", "outputMovies", "SetOfMovies", 90),
        output(30, "3", "outputCTF", "SetOfCTF", 80),
        output(40, "4", "outputCoordinates", "SetOfCoordinates", 5000),
        output(50, "5", "outputParticles", "SetOfParticles", 4800),
    ]
    refs = [ref("2", "1", "outputMovies"), ref("3", "2", "outputMicrographsDoseWeighted"),
            ref("4", "2", "outputMicrographsDoseWeighted"), ref("5", "4", "outputCoordinates")]
    return Db(outputs=outputs, refs=refs, **kwargs)


def test_the_chain_follows_what_the_ctf_read():
    payload = monitor.streamingMonitor(Mapper(preprocessing()), 7, now=NOW)

    assert [(stage["stage"], stage["setId"]) for stage in payload["stages"]] == [
        ("movies", 10), ("micrographs", 20), ("ctf", 30), ("coordinates", 40), ("particles", 50)]
    assert payload["streaming"] is True
    behind = {stage["stage"]: stage["behind"] for stage in payload["stages"]}
    # Nothing picked yet: every micrograph the picker reads (the 90 aligned) waits for picking
    assert behind == {"movies": None, "micrographs": 10, "ctf": 10, "coordinates": 90, "particles": 0}


def test_the_newest_ctf_is_followed_unless_another_is_asked_for():
    db = preprocessing()
    db.outputs.append(output(31, "6", "outputCTF", "SetOfCTF", 3, updatedAt=NOW + timedelta(minutes=1)))
    db.refs.append(ref("6", "2", "outputMicrographsDoseWeighted"))

    newest = monitor.streamingMonitor(Mapper(db), 7, now=NOW)
    asked = monitor.streamingMonitor(Mapper(db), 7, ctfSetId=30, now=NOW)

    assert next(s for s in newest["stages"] if s["stage"] == "ctf")["setId"] == 31
    assert next(s for s in asked["stages"] if s["stage"] == "ctf")["setId"] == 30
    assert [o["setId"] for o in newest["ctfOutputs"]] == [30, 31]


def test_a_stream_without_ctf_is_followed_from_its_micrographs():
    db = preprocessing()
    db.outputs = [o for o in db.outputs if o["setClassName"] != "SetOfCTF"]

    payload = monitor.streamingMonitor(Mapper(db), 7, now=NOW)

    assert [stage["stage"] for stage in payload["stages"]] == ["movies", "micrographs", "coordinates", "particles"]
    assert payload["series"]["kind"] == "micrographs" and payload["series"]["setId"] == 20


def test_tomography_outputs_are_not_followed():
    db = Db(outputs=[output(60, "1", "outputCTF", "SetOfCTFTomoSeries", 4)])

    assert monitor.streamingMonitor(Mapper(db), 7, now=NOW)["stages"] == []


def test_rates_count_the_items_of_the_last_minutes_with_their_trend():
    rates = [{"setId": 30, "lastWindow": 30, "previousWindow": 20, "sampled": 80, "oldest": NOW - timedelta(hours=1)},
             {"setId": 20, "lastWindow": 20, "previousWindow": 20, "sampled": 90, "oldest": NOW - timedelta(hours=1)}]
    payload = monitor.streamingMonitor(Mapper(preprocessing(rates=rates)), 7, now=NOW)

    stages = {stage["stage"]: stage for stage in payload["stages"]}
    assert stages["ctf"]["perMinute"] == 3.0 and stages["ctf"]["trend"] == "up"
    assert stages["micrographs"]["trend"] == "steady"
    assert stages["movies"]["perMinute"] == 0.0


def test_the_series_is_read_after_the_last_point_the_caller_has():
    items = [ctfItem(i) for i in range(1, 6)]
    first = monitor.streamingMonitor(Mapper(preprocessing(items=items)), 7, now=NOW)["series"]
    following = monitor.streamingMonitor(Mapper(preprocessing(items=items)), 7, afterSetId=30, afterRowId=103,
                                         now=NOW)["series"]

    assert [point["id"] for point in first["points"]] == [1, 2, 3, 4, 5]
    assert first["setId"] == 30 and first["lastRowId"] == 105 and first["reset"] is False
    assert [point["id"] for point in following["points"]] == [4, 5]
    point = first["points"][0]
    assert point["defocusU"] == 20000.0 and point["astigmatism"] == 500.0 and point["resolution"] == 4.0
    assert point["micrographName"] == "mic_001" and point["time"] == (NOW).isoformat()


def test_nothing_new_keeps_the_last_point():
    series = monitor.streamingMonitor(Mapper(preprocessing(items=[ctfItem(1)])), 7, afterSetId=30, afterRowId=101,
                                      now=NOW)["series"]

    assert series["points"] == [] and series["lastRowId"] == 101 and series["reset"] is False


@pytest.mark.parametrize("afterSetId, afterRowId", [(99, 103), (30, 50)])
def test_a_rebuilt_ctf_output_starts_the_series_again(afterSetId, afterRowId):
    """Another output, or one whose rows were all written again (all above the cursor)."""
    items = [ctfItem(i) for i in range(1, 4)]
    series = monitor.streamingMonitor(Mapper(preprocessing(items=items)), 7, afterSetId=afterSetId,
                                      afterRowId=afterRowId, now=NOW)["series"]

    assert series["reset"] is True
    assert [point["id"] for point in series["points"]] == [1, 2, 3]


def test_the_drift_comes_from_the_alignment_shifts_of_the_movies():
    movies = [{"scipionItemId": 1, "values": {"_samplingRate": 0.5, "_alignment._xshifts": "0.0,3.0,3.0",
                                              "_alignment._yshifts": "0.0,4.0,4.0"}}]
    db = preprocessing(items=[ctfItem(1)], movies=movies)
    series = monitor.streamingMonitor(Mapper(db), 7, now=NOW)["series"]

    # The shifts are read from the movies motioncor wrote (21), not from the imported ones (10)
    assert db.shiftsSetIds == [21]
    point = series["points"][0]
    # Steps of 5 px and 0 px at 0.5 A/px.
    assert point["totalDrift"] == 2.5 and point["maxFrameShift"] == 2.5


def test_without_shifts_the_accumulated_motion_of_the_micrograph_is_used():
    item = ctfItem(1, extra={"_micObj._rlnAccumMotionTotal": 30.5})
    movies = [{"scipionItemId": 1, "values": {"_samplingRate": 1.0, "_alignment._xshifts": "0,0,0",
                                              "_alignment._yshifts": "0,0,0"}}]
    point = monitor.streamingMonitor(Mapper(preprocessing(items=[item], movies=movies)), 7,
                                     now=NOW)["series"]["points"][0]

    assert point["totalDrift"] == 30.5 and "maxFrameShift" not in point


def test_each_point_names_the_thresholds_it_goes_past():
    items = [ctfItem(1), ctfItem(2, defocusU=45000.0, defocusV=43500.0),
             ctfItem(3, defocusU=800.0, defocusV=700.0), ctfItem(4, defocusU=-999.0, defocusV=-1.0)]
    points = monitor.streamingMonitor(Mapper(preprocessing(items=items)), 7, now=NOW)["series"]["points"]

    assert [point["alerts"] for point in points] == [[], ["maxDefocus", "maxAstigmatism"], ["minDefocus"], []]
    assert points[3]["failed"] is True


def test_thresholds_can_be_changed_or_switched_off():
    limits = monitor.thresholdsWith({"maxResolution": 6, "maxAstigmatism": None, "unknown": 3})

    assert limits["maxResolution"] == 6.0 and limits["maxAstigmatism"] is None and "unknown" not in limits
    assert monitor.alertsOf({"resolution": 7.0, "astigmatism": 5000.0}, limits) == ["maxResolution"]


def test_drift_needs_two_frames_and_a_pixel_size():
    assert monitor.driftFromShifts("1", "1", 1.0) is None
    assert monitor.driftFromShifts("0,1", "0,0", None) is None
    assert monitor.driftFromShifts([0, 3], [0, 4], 1.0) == {"totalDrift": 5.0, "maxFrameShift": 5.0}


def test_the_thresholds_a_project_keeps_are_used():
    db = preprocessing(items=[ctfItem(1, resolution=7.0)], settings={"thresholds": {"maxResolution": 6.0}})
    payload = monitor.streamingMonitor(Mapper(db), 7, now=NOW)

    assert payload["thresholds"]["maxResolution"] == 6.0 and payload["thresholds"]["maxDefocus"] == 40000.0
    assert payload["series"]["points"][0]["alerts"] == ["maxResolution"]


def test_a_database_without_the_settings_table_uses_the_defaults():
    db = preprocessing(settings=RuntimeError('relation "project_monitor_settings" does not exist'))

    assert monitor.streamingMonitor(Mapper(db), 7, now=NOW)["thresholds"] == monitor.DEFAULT_THRESHOLDS


def test_saved_thresholds_are_checked_and_kept_with_who_changed_them():
    db = Db()
    saved = monitor.saveThresholds(Mapper(db), 7, 3, {"maxResolution": 6, "maxAstigmatism": None})

    assert saved["maxResolution"] == 6.0 and saved["maxAstigmatism"] is None and saved["minDefocus"] == 1000.0
    (query, params), = db.executed
    assert query == queries.SAVE_SETTINGS_SQL and params[0] == 7 and params[2] == 3
    assert params[1].adapted == {"thresholds": {"maxResolution": 6.0, "maxAstigmatism": None}}


@pytest.mark.parametrize("thresholds, message", [
    ({"maxSpeed": 3}, "Unknown thresholds: maxSpeed"),
    ({"maxResolution": "high"}, "maxResolution must be a number"),
    ({"maxResolution": True}, "maxResolution must be a number"),
    ({"maxResolution": -1}, "maxResolution must be a positive number"),
    ({"maxResolution": float("nan")}, "maxResolution must be a positive number"),
    ({"minDefocus": 50000}, "The minimum defocus must be below the maximum one"),
    ([], "The thresholds must be an object"),
])
def test_wrong_thresholds_are_refused(thresholds, message):
    db = Db()
    with pytest.raises(ValueError, match=message):
        monitor.saveThresholds(Mapper(db), 7, 3, thresholds)
    assert db.executed == []


def test_without_aligned_movies_the_drift_is_not_read_from_the_imported_ones():
    db = preprocessing(items=[ctfItem(1)])
    db.outputs = [o for o in db.outputs if o["setId"] != 21]

    point = monitor.streamingMonitor(Mapper(db), 7, now=NOW)["series"]["points"][0]

    assert db.shiftsSetIds == [] and "totalDrift" not in point


def ctfConsensusAndSampler(db):
    """A CTF consensus (6) and a defocus sampler (8) read the estimation (3); they update after it."""
    later = NOW + timedelta(minutes=1)
    db.outputs += [output(60, "6", "outputCTF", "SetOfCTF", 70, updatedAt=later),
                   output(61, "6", "outputCTFDiscarded", "SetOfCTF", 10, updatedAt=later),
                   output(80, "8", "outputCTF", "SetOfCTF", 20, updatedAt=later)]
    db.refs += [ref("6", "3", "outputCTF"), ref("8", "6", "outputCTF")]
    return db


def test_by_default_the_estimation_is_followed_not_what_was_made_from_it():
    payload = monitor.streamingMonitor(Mapper(ctfConsensusAndSampler(preprocessing())), 7, now=NOW)

    assert next(s for s in payload["stages"] if s["stage"] == "ctf")["setId"] == 30
    assert [o["setId"] for o in payload["ctfOutputs"]] == [30, 60, 61, 80]


@pytest.mark.parametrize("ctfSetId", [61, 80])
def test_a_ctf_made_from_another_is_followed_back_to_its_micrographs_and_movies(ctfSetId):
    db = ctfConsensusAndSampler(preprocessing(movies=[{"scipionItemId": 1, "values": {
        "_samplingRate": 1.0, "_alignment._xshifts": "0,3", "_alignment._yshifts": "0,4"}}],
        items=[ctfItem(1)]))
    payload = monitor.streamingMonitor(Mapper(db), 7, ctfSetId=ctfSetId, now=NOW)

    assert [(s["stage"], s["setId"]) for s in payload["stages"]][:3] == [
        ("movies", 10), ("micrographs", 20), ("ctf", ctfSetId)]
    assert db.shiftsSetIds == [21]


def test_micrographs_made_from_micrographs_still_find_their_movies():
    """motioncor (2) -> preprocess (9) -> CTF (3); another aligner (4b) also reads the movies."""
    db = preprocessing(items=[ctfItem(1)])
    db.outputs += [output(25, "9", "outputMicrographs", "SetOfMicrographs", 88),
                   output(22, "12", "outputMovies", "SetOfMovies", 5, updatedAt=NOW + timedelta(minutes=5))]
    db.refs = [r for r in db.refs if r["protocolId"] != "3"] + [
        ref("9", "2", "outputMicrographsDoseWeighted"), ref("3", "9", "outputMicrographs"), ref("12", "1", "outputMovies")]

    payload = monitor.streamingMonitor(Mapper(db), 7, now=NOW)

    # The micrographs motioncor aligned show apart, before the preprocessed ones the CTF reads
    assert [(s["stage"], s["setId"]) for s in payload["stages"]][:4] == [
        ("movies", 10), ("alignedMicrographs", 20), ("micrographs", 25), ("ctf", 30)]
    behind = {s["stage"]: s["behind"] for s in payload["stages"]}
    assert (behind["alignedMicrographs"], behind["micrographs"]) == (10, 2)
    monitor.streamingMonitor(Mapper(db), 7, now=NOW)
    assert set(db.shiftsSetIds) == {21}, "The shifts come from motioncor, which made these micrographs"


def test_before_any_alignment_the_imported_movies_are_followed():
    db = Db(outputs=[output(10, "1", "outputMovies", "SetOfMovies", 40)])

    payload = monitor.streamingMonitor(Mapper(db), 7, now=NOW)

    assert [(s["stage"], s["setId"]) for s in payload["stages"]] == [("movies", 10)]
    assert payload["streaming"] is True and payload["series"]["points"] == []


def test_imported_movies_are_followed_rather_than_the_ones_an_aligner_wrote():
    db = Db(outputs=[output(10, "1", "outputMovies", "SetOfMovies", 40),
                     output(21, "2", "outputMovies", "SetOfMovies", 3, updatedAt=NOW + timedelta(minutes=1))],
            refs=[ref("2", "1", "outputMovies")])

    assert [s["setId"] for s in monitor.streamingMonitor(Mapper(db), 7, now=NOW)["stages"]] == [10]


def test_before_the_ctf_the_micrographs_give_their_drift():
    movies = [{"scipionItemId": 1, "values": {"_samplingRate": 1.0, "_alignment._xshifts": "0,3",
                                              "_alignment._yshifts": "0,4"}}]
    db = preprocessing(movies=movies)
    db.outputs = [o for o in db.outputs if o["setClassName"] in ("SetOfMovies", "SetOfMicrographs")]
    db.items = [{"rowId": 1, "scipionItemId": 1, "enabled": True, "label": "mic_001", "time": NOW, "values": {}}]

    series = monitor.streamingMonitor(Mapper(db), 7, now=NOW)["series"]

    assert series["kind"] == "micrographs" and series["setId"] == 20
    point, = series["points"]
    assert point["micrographName"] == "mic_001" and point["totalDrift"] == 5.0 and "defocusU" not in point


def test_the_series_starts_again_from_the_ctf_once_there_is_one():
    series = monitor.streamingMonitor(Mapper(preprocessing(items=[ctfItem(1)])), 7, afterSetId=20, afterRowId=1,
                                      now=NOW)["series"]

    assert series["kind"] == "ctf" and series["reset"] is True and [p["id"] for p in series["points"]] == [1]


def test_an_item_written_after_one_with_a_higher_id_is_still_read():
    """Parallel steps: micrograph 5 is estimated before 3, which is written later."""
    db = preprocessing(items=[ctfItem(5, rowId=101)])
    first = monitor.streamingMonitor(Mapper(db), 7, now=NOW)["series"]
    db.items.append(ctfItem(3, rowId=102))

    following = monitor.streamingMonitor(Mapper(db), 7, afterSetId=30, afterRowId=first["lastRowId"], now=NOW)["series"]

    assert [p["id"] for p in first["points"]] == [5] and first["lastRowId"] == 101
    assert [p["id"] for p in following["points"]] == [3] and following["reset"] is False


def test_a_set_growing_faster_than_the_sample_gets_the_rate_of_the_sample():
    """5000 particles in the last 5 minutes: the sample does not reach the window before."""
    rates = [{"setId": 50, "lastWindow": monitor.RATE_SAMPLE, "previousWindow": 0, "sampled": monitor.RATE_SAMPLE,
              "oldest": NOW - timedelta(minutes=5)}]
    payload = monitor.streamingMonitor(Mapper(preprocessing(rates=rates)), 7, now=NOW)

    particles = next(s for s in payload["stages"] if s["stage"] == "particles")
    assert particles["perMinute"] == 1000.0 and particles["trend"] == "steady"


ASTIGMATIC = dict(defocusU=21500.0, defocusV=20000.0)  # 1500 A, past the 1000 A default


def test_alert_runs_group_consecutive_micrographs_past_a_threshold():
    points = [{"id": 1, "alerts": ["maxAstigmatism"]}, {"id": 2, "alerts": ["maxAstigmatism"]},
              {"id": 3, "alerts": [], "failed": True}, {"id": 4, "alerts": ["maxAstigmatism"]},
              {"id": 5, "alerts": []}, {"id": 6, "alerts": ["maxTotalDrift"]}]

    runs = monitor.alertRuns(points)

    assert [(r["kind"], r["first"]["id"], r["count"], r["ongoing"]) for r in runs] == [
        ("maxAstigmatism", 1, 3, False), ("maxTotalDrift", 6, 1, True)]


def test_the_bell_hears_of_the_runs_that_started_since_its_last_call():
    items = [ctfItem(1, minutes=30), ctfItem(2, minutes=20, **ASTIGMATIC), ctfItem(3, minutes=10, **ASTIGMATIC),
             ctfItem(4, minutes=5), ctfItem(5, minutes=1, defocusU=45000.0, defocusV=44800.0)]
    db = preprocessing(items=items)

    recent = monitor.alertsSince(Mapper(db), 7, NOW - timedelta(minutes=15))
    monitor._alertCache.clear()
    older = monitor.alertsSince(Mapper(db), 7, NOW - timedelta(minutes=25))

    assert [(r["kind"], r["micrographName"], r["count"]) for r in recent] == [("maxDefocus", "mic_005", 1)]
    assert [(r["kind"], r["micrographName"], r["count"]) for r in older] == [
        ("maxAstigmatism", "mic_002", 2), ("maxDefocus", "mic_005", 1)]
    assert recent[0]["text"] == "Defocus above 40000 Å" and recent[0]["protocolId"] == "3"


def test_a_run_that_may_have_started_before_the_window_is_not_announced(monkeypatch):
    monkeypatch.setattr(monitor, "ALERT_WINDOW", 2)
    items = [ctfItem(1, **ASTIGMATIC), ctfItem(2, **ASTIGMATIC), ctfItem(3, **ASTIGMATIC)]

    assert monitor.projectAlertRuns(Mapper(preprocessing(items=items)), 7) == []


def test_the_alerts_of_a_project_are_worked_out_once_for_every_open_tab():
    db = preprocessing(items=[ctfItem(1, **ASTIGMATIC)])

    first = monitor.projectAlertRuns(Mapper(db), 7)
    calls = len(db.calls)
    again = monitor.projectAlertRuns(Mapper(db), 7)

    assert again == first and len(db.calls) == calls


def picks(setId, micsAndCounts, firstRow=1):
    """Rows of a coordinates or particles Set: ``count`` rows for each micrograph, in this order."""
    rows, rowId = [], firstRow
    for mic, count in micsAndCounts:
        for _ in range(count):
            rows.append((setId, rowId, mic))
            rowId += 1
    return rows


def test_the_picking_says_where_its_coordinates_are_and_their_box_size():
    db = preprocessing(items=[ctfItem(1)], picks=picks(40, [(1, 3)]))
    next(row for row in db.outputs if row["setId"] == 40)["properties"]["_boxSize"] = 180

    picking = monitor.streamingMonitor(Mapper(db), 7, now=NOW)["picking"]

    assert (picking["protocolId"], picking["outputName"], picking["boxSize"]) == ("4", "outputCoordinates", 180)


def test_the_coordinates_of_each_micrograph_are_counted_and_only_the_changes_sent_again():
    db = preprocessing(items=[ctfItem(1), ctfItem(2)], picks=picks(40, [(1, 3), (2, 2)]))
    first = monitor.streamingMonitor(Mapper(db), 7, now=NOW)["picking"]
    db.picks += picks(40, [(2, 4), (3, 1)], firstRow=6)
    following = monitor.streamingMonitor(Mapper(db), 7, afterPickSetId=40, afterPickRowId=first["lastRowId"],
                                         now=NOW)["picking"]

    assert first == {"setId": 40, "reset": False, "lastRowId": 5, "complete": True, "counts": {"1": 3, "2": 2},
                     "protocolId": "4", "outputName": "outputCoordinates", "boxSize": None}
    assert following["counts"] == {"2": 6, "3": 1} and following["lastRowId"] == 10


def test_the_backlog_of_picking_and_extraction_is_in_micrographs():
    """The picker reads the 90 aligned micrographs; 3 picked; 2 of them extracted."""
    db = preprocessing(picks=picks(40, [(1, 3), (2, 2), (3, 1)]) + picks(50, [(1, 3), (2, 2)], firstRow=100))
    stages = {s["stage"]: s for s in monitor.streamingMonitor(Mapper(db), 7, now=NOW)["stages"]}

    assert (stages["coordinates"]["micrographs"], stages["coordinates"]["behind"]) == (3, 87)
    assert (stages["particles"]["micrographs"], stages["particles"]["behind"]) == (2, 1)
    assert stages["coordinates"]["counting"] is False


def test_a_long_session_is_counted_in_chunks_and_has_no_backlog_until_counted(monkeypatch):
    monkeypatch.setattr(monitor, "MIC_COUNT_CHUNK", 4)
    db = preprocessing(picks=picks(40, [(1, 3), (2, 3)]))

    first = {s["stage"]: s for s in monitor.streamingMonitor(Mapper(db), 7, now=NOW)["stages"]}
    second = {s["stage"]: s for s in monitor.streamingMonitor(Mapper(db), 7, now=NOW)["stages"]}

    assert first["coordinates"]["counting"] is True and first["coordinates"]["behind"] is None
    assert second["coordinates"]["counting"] is False and second["coordinates"]["micrographs"] == 2


def test_a_rebuilt_coordinates_output_is_counted_again():
    db = preprocessing(picks=picks(40, [(1, 3)]))
    monitor.countByMicrograph(Mapper(db), 40)
    db.picks = picks(40, [(1, 2)], firstRow=50)

    assert monitor.countByMicrograph(Mapper(db), 40)["counts"] == {1: 2}


def test_too_few_particles_is_an_alert_only_when_the_project_sets_it():
    db = preprocessing(items=[ctfItem(1), ctfItem(2)], picks=picks(40, [(1, 2), (2, 50)]))
    without = monitor.projectAlertRuns(Mapper(db), 7)
    monitor._alertCache.clear()
    db.settings = {"thresholds": {"minParticles": 10}}
    withThreshold = monitor.projectAlertRuns(Mapper(db), 7)

    assert without == []
    assert [(r["kind"], r["micrographName"], r["text"]) for r in withThreshold] == [
        ("minParticles", "mic_001", "Fewer than 10 particles picked")]


def classified(db, classes):
    """alignPCA-2D (9) classifies the extracted particles (5) into classes."""
    db.outputs.append(output(90, "9", "outputClasses", "SetOfClasses2D", len(classes)))
    db.refs.append(ref("9", "5", "outputParticles"))
    db.classes = [{"classId": classId, "enabled": True, "particles": particles} for classId, particles in classes]
    return db


def test_2d_classes_follow_the_particles_with_their_sizes_biggest_first():
    payload = monitor.streamingMonitor(Mapper(classified(preprocessing(), [(1, 1200), (2, 3000), (3, 100)])), 7,
                                       now=NOW)

    stage = payload["stages"][-1]
    assert (stage["stage"], stage["items"], stage["particles"], stage["behind"]) == ("classes2d", 3, 4300, 500)
    assert stage["perMinute"] is None and stage["trend"] is None
    classes = payload["classes"]
    assert [(c["id"], c["particles"]) for c in classes["classes"]] == [(2, 3000), (1, 1200), (3, 100)]
    assert (classes["setId"], classes["protocolId"], classes["outputName"]) == (90, "9", "outputClasses")
    assert classes["version"] == NOW.isoformat()


def test_a_stream_without_2d_classes_has_none():
    payload = monitor.streamingMonitor(Mapper(preprocessing()), 7, now=NOW)

    assert payload["classes"] is None and all(s["stage"] != "classes2d" for s in payload["stages"])


def consensusPicking(db):
    """A CTF consensus (6) reads the CTF (3) and keeps 60 micrographs; the picker (4) reads those."""
    db.outputs += [output(61, "6", "outputMicrographs", "SetOfMicrographs", 60),
                   output(62, "6", "outputCTF", "SetOfCTF", 60)]
    db.refs = [r for r in db.refs if r["protocolId"] != "4"] + [
        ref("6", "3", "outputCTF"), ref("4", "6", "outputMicrographs")]
    return db


def test_a_picker_reading_the_micrographs_a_consensus_kept_is_followed():
    db = consensusPicking(preprocessing(picks=picks(40, [(1, 3), (2, 2)])))

    stages = {s["stage"]: s for s in monitor.streamingMonitor(Mapper(db), 7, now=NOW)["stages"]}

    assert stages["coordinates"]["setId"] == 40 and stages["particles"]["setId"] == 50
    # It waits on the 60 micrographs the consensus kept, not on the 80 with a CTF
    assert stages["coordinates"]["behind"] == 58
    assert stages["coordinates"]["pickedFrom"] == {"protocolId": "6", "label": "run 6",
                                                   "outputName": "outputMicrographs", "items": 60}


def test_the_picker_is_found_through_as_many_filters_as_there_are():
    """CTF (3) -> consensus (6) -> max shift filter (8) -> picker (4)."""
    db = consensusPicking(preprocessing())
    db.outputs.append(output(81, "8", "outputMicrographs", "SetOfMicrographs", 55))
    db.refs = [r for r in db.refs if r["protocolId"] != "4"] + [ref("8", "6", "outputMicrographs"),
                                                                ref("4", "8", "outputMicrographs")]

    stages = {s["stage"]: s for s in monitor.streamingMonitor(Mapper(db), 7, now=NOW)["stages"]}

    assert stages["coordinates"]["setId"] == 40 and stages["coordinates"]["pickedFrom"]["items"] == 55


def test_a_picker_reading_the_chain_micrographs_still_waits_on_them():
    stages = {s["stage"]: s for s in monitor.streamingMonitor(Mapper(preprocessing()), 7, now=NOW)["stages"]}

    assert stages["coordinates"]["pickedFrom"]["outputName"] == "outputMicrographsDoseWeighted"
    assert stages["coordinates"]["behind"] == 90


def twoPickings(db):
    """A second picker (14) reads the same micrographs and is newer, but nothing is extracted from it."""
    db.outputs.append(output(41, "14", "outputCoordinates", "SetOfCoordinates", 9000,
                             updatedAt=NOW + timedelta(minutes=5)))
    db.refs.append(ref("14", "2", "outputMicrographsDoseWeighted"))
    return db


def test_of_several_pickings_the_one_that_goes_furthest_is_followed_unless_another_is_asked_for():
    db = twoPickings(preprocessing())

    default = monitor.streamingMonitor(Mapper(db), 7, now=NOW)
    asked = monitor.streamingMonitor(Mapper(db), 7, coordinatesSetId=41, now=NOW)

    assert next(s for s in default["stages"] if s["stage"] == "coordinates")["setId"] == 40
    assert [o["setId"] for o in default["coordinatesOutputs"]] == [40, 41]
    assert [s["stage"] for s in asked["stages"]][-1] == "coordinates", "Nothing was extracted from picking 41"
    assert next(s for s in asked["stages"] if s["stage"] == "coordinates")["setId"] == 41


def test_2d_classes_behind_a_particle_screening_are_found_and_wait_on_what_it_kept():
    """Extraction (5) -> screening (11, keeps 4000 of 4800) -> alignPCA-2D (9)."""
    db = preprocessing()
    db.outputs += [output(110, "11", "outputParticles", "SetOfParticles", 4000),
                   output(90, "9", "outputClasses", "SetOfClasses2D", 2)]
    db.refs += [ref("11", "5", "outputParticles"), ref("9", "11", "outputParticles")]
    db.classes = [{"classId": 1, "enabled": True, "particles": 3500}]

    stages = {s["stage"]: s for s in monitor.streamingMonitor(Mapper(db), 7, now=NOW)["stages"]}

    assert stages["particles"]["setId"] == 50 and stages["classes2d"]["setId"] == 90
    assert stages["classes2d"]["behind"] == 500
    assert stages["classes2d"]["classifiedFrom"]["items"] == 4000


def test_a_picking_with_2d_classes_wins_over_a_nearer_one_without():
    """Picker 14 reads the motioncor micrographs (nearer); the classified one (4) reads a consensus."""
    db = consensusPicking(classified(twoPickings(preprocessing()), [(1, 100)]))

    stage = next(s for s in monitor.streamingMonitor(Mapper(db), 7, now=NOW)["stages"] if s["stage"] == "coordinates")

    assert stage["setId"] == 40


def test_a_protocol_without_input_refs_reads_the_outputs_of_the_protocols_it_depends_on():
    """The extraction (5) has no input ref; the graph says it depends on the picking (4)."""
    db = preprocessing()
    db.refs = [r for r in db.refs if r["protocolId"] != "5"]
    db.dependencies = [("5", "4")]

    stages = [s["stage"] for s in monitor.streamingMonitor(Mapper(db), 7, now=NOW)["stages"]]

    assert stages[-2:] == ["coordinates", "particles"]


def test_the_picking_that_leads_to_2d_classes_is_followed_even_from_another_branch():
    """Picker 15 reads the motioncor movies' micrographs through another branch the CTF does not see, and its
    extraction (16) feeds alignPCA-2D (9) after a preprocessing (17)."""
    db = preprocessing()
    db.outputs += [output(70, "15", "outputCoordinates", "SetOfCoordinates", 300),
                   output(71, "16", "outputParticles", "SetOfParticles", 290),
                   output(72, "17", "outputParticles", "SetOfParticles", 280),
                   output(90, "9", "outputClasses", "SetOfClasses2D", 2)]
    db.refs += [ref("15", "1", "outputMovies"), ref("16", "15", "outputCoordinates"),
                ref("17", "16", "outputParticles"), ref("9", "17", "outputParticles")]
    db.classes = [{"classId": 1, "enabled": True, "particles": 200}]

    stages = {s["stage"]: s for s in monitor.streamingMonitor(Mapper(db), 7, now=NOW)["stages"]}

    assert (stages["coordinates"]["setId"], stages["particles"]["setId"], stages["classes2d"]["setId"]) == (70, 71, 90)
    assert stages["classes2d"]["classifiedFrom"]["items"] == 280 and stages["classes2d"]["behind"] == 80


def test_a_picking_consensus_between_picking_and_extraction_is_followed():
    """Picker (4) -> picking consensus (18) -> extraction (19) -> alignPCA-2D (9)."""
    db = preprocessing()
    db.outputs += [output(80, "18", "consensusCoordinates", "SetOfCoordinates", 3000),
                   output(81, "19", "outputParticles", "SetOfParticles", 2900),
                   output(90, "9", "outputClasses", "SetOfClasses2D", 1)]
    db.refs += [ref("18", "4", "outputCoordinates"), ref("19", "18", "consensusCoordinates"),
                ref("9", "19", "outputParticles")]
    db.classes = [{"classId": 1, "enabled": True, "particles": 2900}]

    stages = {s["stage"]: s for s in monitor.streamingMonitor(Mapper(db), 7, now=NOW)["stages"]}

    # The consensus coordinates lead to the classes: they are the picking followed
    assert (stages["coordinates"]["setId"], stages["particles"]["setId"], stages["classes2d"]["setId"]) == (80, 81, 90)


def test_2d_classes_no_picking_leads_to_are_shown_anyway():
    db = preprocessing()
    db.outputs += [output(91, "20", "outputParticles", "SetOfParticles", 1000),
                   output(90, "9", "outputClasses", "SetOfClasses2D", 1)]
    db.refs += [ref("9", "20", "outputParticles")]
    db.classes = [{"classId": 1, "enabled": True, "particles": 900}]

    payload = monitor.streamingMonitor(Mapper(db), 7, now=NOW)

    assert payload["classes"]["setId"] == 90
    classes = next(s for s in payload["stages"] if s["stage"] == "classes2d")
    assert classes["classifiedFrom"]["items"] == 1000 and classes["behind"] == 100


def test_a_backlog_tells_how_long_it_takes_to_clear_at_its_rate():
    assert monitor.withEta({"behind": 30, "perMinute": 2.0})["etaMinutes"] == 15.0
    assert monitor.withEta({"behind": 30, "perMinute": 0.0})["stalled"] is True
    assert "etaMinutes" not in monitor.withEta({"behind": 0, "perMinute": 2.0})
    assert "etaMinutes" not in monitor.withEta({"behind": 10, "perMinute": None})


def test_the_picking_backlog_in_micrographs_clears_at_its_rate_in_micrographs():
    """300 coordinates a minute at 100 per micrograph is 3 micrographs a minute: 12 waiting take 4 minutes."""
    entry = monitor.withEta({"behind": 12, "perMinute": 300.0, "items": 5000, "micrographs": 50})

    assert entry["etaMinutes"] == 4.0


def test_the_stages_of_the_monitor_carry_their_estimated_time():
    rates = [{"setId": 30, "lastWindow": 20, "previousWindow": 20, "sampled": 80, "oldest": NOW - timedelta(hours=1)}]
    stages = {s["stage"]: s for s in monitor.streamingMonitor(Mapper(preprocessing(rates=rates)), 7, now=NOW)["stages"]}

    # 10 micrographs without CTF at 2 CTFs a minute
    assert stages["ctf"]["etaMinutes"] == 5.0
    assert stages["micrographs"]["stalled"] is True


def test_the_aligned_micrographs_are_not_shown_twice_when_the_ctf_reads_them():
    stages = [s["stage"] for s in monitor.streamingMonitor(Mapper(preprocessing()), 7, now=NOW)["stages"]]

    assert "alignedMicrographs" not in stages


def test_of_several_2d_classifications_the_one_asked_for_is_followed_with_its_picking():
    """alignPCA-2D 9 reads the extraction of picking 4; another one (19) reads the extraction (16) of picking 15."""
    db = classified(preprocessing(), [(1, 100)])
    db.outputs += [output(70, "15", "outputCoordinates", "SetOfCoordinates", 300),
                   output(71, "16", "outputParticles", "SetOfParticles", 290),
                   output(91, "19", "outputClasses", "SetOfClasses2D", 1)]
    db.refs += [ref("15", "2", "outputMicrographsDoseWeighted"), ref("16", "15", "outputCoordinates"),
                ref("19", "16", "outputParticles")]

    default = monitor.streamingMonitor(Mapper(db), 7, now=NOW)
    asked = monitor.streamingMonitor(Mapper(db), 7, classesSetId=91, now=NOW)

    assert [o["setId"] for o in default["classesOutputs"]] == [90, 91]
    stages = {s["stage"]: s["setId"] for s in asked["stages"]}
    assert (stages["coordinates"], stages["particles"], stages["classes2d"]) == (70, 71, 91)
    assert asked["classes"]["setId"] == 91


def test_a_3d_picking_is_not_a_picking_of_the_micrographs():
    assert monitor._stageOf("SetOfCoordinates3D", "Coordinate3D") is None
    assert monitor._stageOf("SetOfCoordinates", "Coordinate") == "coordinates"


def doseMovie(itemId, mean=1.2, difference=0.0, rowId=None):
    """A movie of a dose analysis; one whose analysis failed has no dose."""
    values = {"_filename": "Runs/02/movie_%03d.tiff" % itemId}
    if mean is not None:
        values.update({"_MEAN_DOSE_PER_ANGSTROM2": mean, "_DIFF_TO_DOSE_PER_ANGSTROM2": difference})
    return {"rowId": rowId if rowId is not None else 500 + itemId, "scipionItemId": itemId, "enabled": True,
            "label": "", "time": NOW, "values": values}


def withDoseAnalysis(kept, discarded, **kwargs):
    """preprocessing() with a dose analysis (9) of the imported movies: its kept and its discarded movies."""
    db = preprocessing(**kwargs)
    db.outputs += [output(90, "9", "outputMovies", "SetOfMovies", len(kept)),
                   output(91, "9", "outputMoviesDiscarded", "SetOfMovies", len(discarded))]
    db.refs.append(ref("9", "1", "outputMovies"))
    db.doseRows = {90: kept, 91: discarded}
    return db


def test_the_dose_of_the_kept_and_the_discarded_movies_is_followed_in_the_order_they_were_analysed():
    db = withDoseAnalysis([doseMovie(1, 1.20, 0.5), doseMovie(3, 1.22, 2.0)],
                          [doseMovie(2, 1.40, 16.0), doseMovie(4, None, rowId=499)])

    dose = monitor.streamingMonitor(Mapper(db), 7, now=NOW)["dose"]

    assert (dose["key"], dose["label"], dose["reset"], dose["lastRowId"], dose["more"]) == ("9", "run 9", False, 503, False)
    # The failed analysis (no dose) moves the cursor but is no point
    assert [(p["id"], p["doseDifference"], p["discarded"], p["alerts"]) for p in dose["points"]] == [
        (1, 0.5, False, []), (2, 16.0, True, ["maxDoseDifference"]), (3, 2.0, False, [])]
    assert dose["points"][0]["movieName"] == "movie_001.tiff" and dose["points"][0]["meanDose"] == 1.2


def test_the_dose_is_read_after_the_cursor_and_again_from_scratch_for_another_analysis():
    db = withDoseAnalysis([doseMovie(1), doseMovie(3)], [doseMovie(2, 1.4, 16.0)])

    following = monitor.streamingMonitor(Mapper(db), 7, afterDoseKey="9", afterDoseRowId=502, now=NOW)["dose"]
    other = monitor.streamingMonitor(Mapper(db), 7, afterDoseKey="8", afterDoseRowId=502, now=NOW)["dose"]

    assert [p["id"] for p in following["points"]] == [3] and following["reset"] is False
    assert [p["id"] for p in other["points"]] == [1, 2, 3] and other["reset"] is True


def test_the_dose_cursor_stops_where_an_output_with_more_rows_stopped(monkeypatch):
    monkeypatch.setattr(monitor, "SERIES_BATCH", 2)
    kept = [doseMovie(itemId) for itemId in (1, 2, 3, 4)]
    db = withDoseAnalysis(kept, [doseMovie(5, rowId=502)])

    dose = monitor.streamingMonitor(Mapper(db), 7, now=NOW)["dose"]

    # The kept movies stop at row 502: the discarded one at 502 comes, nothing after it is skipped
    assert dose["lastRowId"] == 502 and dose["more"] is True
    assert [p["id"] for p in dose["points"]] == [1, 2, 5]


def test_a_project_without_a_dose_analysis_has_no_dose_series():
    dose = monitor.streamingMonitor(Mapper(preprocessing(items=[ctfItem(1)])), 7, now=NOW)["dose"]

    assert dose["key"] is None and dose["points"] == []


def test_the_bell_tells_a_run_of_movies_off_the_median_dose():
    db = withDoseAnalysis([doseMovie(1)], [doseMovie(2, 1.4, 16.0), doseMovie(3, 1.4, -12.0)])

    runs = monitor.projectAlertRuns(Mapper(db), 7)

    assert [(run["kind"], run["count"], run["micrographName"], run["protocolId"]) for run in runs] == [
        ("maxDoseDifference", 2, "movie_002.tiff", "9")]
    assert runs[0]["text"] == "Dose off the session median by more than 5 %"


def test_exposure_window_tracks_import_order_and_refreshes_late_ctf():
    movies = [dict(ctfItem(itemId), rowId=rowId) for itemId, rowId in [(99, 1), (3, 2), (1, 3), (2, 4), (4, 5)]]
    db = preprocessing(items=[ctfItem(1)], setRows={10: movies, 20: [ctfItem(1), ctfItem(2)], 30: [ctfItem(1)]})
    first = monitor.streamingMonitor(Mapper(db), 7, qualityWindowSize=2, now=NOW)["exposures"]
    assert first["setId"] == 10
    assert [point["id"] for point in first["points"]] == [3, 1, 2, 4]
    assert [point["ctfReady"] for point in first["points"]] == [False, True, False, False]
    assert [point["aligned"] for point in first["points"]] == [False, True, True, False]
    assert first["points"][-1]["point"] is None
    db.setRows[30].append(ctfItem(2))
    following = monitor.streamingMonitor(Mapper(db), 7, qualityWindowSize=2, afterSetId=30, afterRowId=9999, now=NOW)
    assert following["series"]["points"] == []
    assert following["exposures"]["points"][2]["ctfReady"] is True
    assert following["exposures"]["points"][2]["point"]["resolution"] == 4.0
    assert (queries.LATEST_ROWS_SQL, (10, 4)) in db.calls


def test_exposure_window_follows_the_import_before_movie_filters():
    db = preprocessing(setRows={5: [ctfItem(1)], 10: [], 20: [], 30: []})
    db.outputs.append(output(5, "0", "rawMovies", "SetOfMovies", 1))
    db.refs.append(ref("1", "0", "rawMovies"))
    payload = monitor.streamingMonitor(Mapper(db), 7, qualityWindowSize=2, now=NOW)
    assert payload["exposures"]["setId"] == 5
    assert payload["exposures"]["points"][0]["point"] is None


def test_exposure_window_does_not_guess_movie_identity_across_ambiguous_merges():
    db = preprocessing()
    db.outputs.extend([output(5, "0", "moviesA", "SetOfMovies", 1), output(6, "0b", "moviesB", "SetOfMovies", 1)])
    db.refs.extend([ref("1", "0", "moviesA"), ref("1", "0b", "moviesB")])
    assert monitor.streamingMonitor(Mapper(db), 7, qualityWindowSize=2, now=NOW)["exposures"] is None


def test_imported_movies_are_reported_before_any_alignment():
    db = Db(outputs=[output(10, "1", "movies", "SetOfMovies", 1)], setRows={10: [ctfItem(7)]})
    payload = monitor.streamingMonitor(Mapper(db), 7, qualityWindowSize=2, now=NOW)
    assert payload["series"]["kind"] is None
    assert payload["exposures"]["points"][0]["id"] == 7
    assert payload["exposures"]["points"][0]["aligned"] is False
    assert payload["exposures"]["points"][0]["point"] is None


def test_exposure_window_does_not_join_picking_from_another_branch_by_id():
    db = preprocessing(items=[ctfItem(1)], picks=[(41, 700, 1)],
                       setRows={10: [ctfItem(1)], 20: [ctfItem(1)], 30: [ctfItem(1)]})
    db.outputs.extend([output(80, "8", "otherMicrographs", "SetOfMicrographs", 1),
                       output(41, "9", "otherCoordinates", "SetOfCoordinates", 1)])
    db.refs.append(ref("9", "8", "otherMicrographs"))
    payload = monitor.streamingMonitor(Mapper(db), 7, coordinatesSetId=41, qualityWindowSize=2, now=NOW)
    assert "particles" not in payload["exposures"]["points"][0]["point"]
