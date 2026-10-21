"""The streaming monitor: the chain it follows, the rates of its stages and the quality points it reads."""
from datetime import datetime, timedelta, timezone

import pytest

from app.backend.api.services import streaming_monitor as monitor

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def output(setId, protocolId, outputName, setClassName, items, streamState=1, updatedAt=None, maxItemId=None):
    return {"setId": setId, "protocolId": protocolId, "protocolClassName": "Prot%s" % protocolId,
            "status": "running", "label": "run %s" % protocolId, "outputName": outputName,
            "setClassName": setClassName, "itemClassName": "",
            "properties": {"itemsCount": items, "maxItemId": maxItemId or items, "streamState": streamState},
            "updatedAt": updatedAt or NOW}


def ref(protocolId, parentProtocolId, parentOutputName):
    return {"protocolId": protocolId, "parentProtocolId": parentProtocolId, "parentOutputName": parentOutputName}


def ctfItem(itemId, defocusU=20000.0, defocusV=19500.0, resolution=4.0, minutes=0, extra=None):
    values = {"_defocusU": defocusU, "_defocusV": defocusV, "_resolution": resolution, "_fitQuality": 0.2}
    values.update(extra or {})
    return {"scipionItemId": itemId, "enabled": True, "label": "mic_%03d" % itemId,
            "time": NOW - timedelta(minutes=minutes), "values": values}


class Db:
    """Answers each monitor query with its rows; the series rows are filtered as the query would."""

    def __init__(self, outputs=(), refs=(), rates=(), items=(), movies=(), settings=None):
        self.outputs, self.refs, self.rates = list(outputs), list(refs), list(rates)
        self.items, self.movies = list(items), list(movies)
        self.settings = settings
        self.calls = []
        self.executed = []
        self.shiftsSetIds = []

    def fetchOne(self, query, params):
        assert query == monitor.GET_SETTINGS_SQL
        if isinstance(self.settings, Exception):
            raise self.settings
        return {"settings": self.settings} if self.settings is not None else None

    def execute(self, query, params):
        self.executed.append((query, params))

    def fetchAll(self, query, params):
        self.calls.append((query, params))
        if query == monitor.OUTPUT_SETS_SQL:
            return self.outputs
        if query == monitor.INPUT_REFS_SQL:
            return self.refs
        if query == monitor.SET_RATES_SQL:
            return [row for row in self.rates if row["setId"] in params[-1]]
        if query == monitor.SERIES_ITEMS_SQL:
            _, after, limit = params
            return [item for item in self.items if item["scipionItemId"] > after][:limit]
        if query == monitor.MOVIE_SHIFTS_SQL:
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
    assert behind == {"movies": None, "micrographs": 10, "ctf": 10, "coordinates": None, "particles": None}


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
    rates = [{"setId": 30, "lastWindow": 30, "previousWindow": 20, "firstAt": NOW - timedelta(hours=1),
              "lastAt": NOW},
             {"setId": 20, "lastWindow": 20, "previousWindow": 20, "firstAt": None, "lastAt": None}]
    payload = monitor.streamingMonitor(Mapper(preprocessing(rates=rates)), 7, now=NOW)

    stages = {stage["stage"]: stage for stage in payload["stages"]}
    assert stages["ctf"]["perMinute"] == 3.0 and stages["ctf"]["trend"] == "up"
    assert stages["micrographs"]["trend"] == "steady"
    assert stages["movies"]["perMinute"] == 0.0


def test_the_series_is_read_after_the_last_point_the_caller_has():
    items = [ctfItem(i) for i in range(1, 6)]
    first = monitor.streamingMonitor(Mapper(preprocessing(items=items)), 7, now=NOW)["series"]
    following = monitor.streamingMonitor(Mapper(preprocessing(items=items)), 7, afterSetId=30, afterItemId=3,
                                         now=NOW)["series"]

    assert [point["id"] for point in first["points"]] == [1, 2, 3, 4, 5]
    assert first["setId"] == 30 and first["lastItemId"] == 5 and first["reset"] is False
    assert [point["id"] for point in following["points"]] == [4, 5]
    point = first["points"][0]
    assert point["defocusU"] == 20000.0 and point["astigmatism"] == 500.0 and point["resolution"] == 4.0
    assert point["micrographName"] == "mic_001" and point["time"] == (NOW).isoformat()


def test_nothing_new_keeps_the_last_point():
    series = monitor.streamingMonitor(Mapper(preprocessing(items=[ctfItem(1)])), 7, afterSetId=30, afterItemId=1,
                                      now=NOW)["series"]

    assert series["points"] == [] and series["lastItemId"] == 1 and series["reset"] is False


@pytest.mark.parametrize("afterSetId, afterItemId", [(99, 3), (30, 500)])
def test_a_rebuilt_ctf_output_starts_the_series_again(afterSetId, afterItemId):
    items = [ctfItem(i) for i in range(1, 4)]
    series = monitor.streamingMonitor(Mapper(preprocessing(items=items)), 7, afterSetId=afterSetId,
                                      afterItemId=afterItemId, now=NOW)["series"]

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
    assert query == monitor.SAVE_SETTINGS_SQL and params[0] == 7 and params[2] == 3
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

    assert [(s["stage"], s["setId"]) for s in payload["stages"]][:3] == [("movies", 10), ("micrographs", 25), ("ctf", 30)]
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
    db.items = [{"scipionItemId": 1, "enabled": True, "label": "mic_001", "time": NOW, "values": {}}]

    series = monitor.streamingMonitor(Mapper(db), 7, now=NOW)["series"]

    assert series["kind"] == "micrographs" and series["setId"] == 20
    point, = series["points"]
    assert point["micrographName"] == "mic_001" and point["totalDrift"] == 5.0 and "defocusU" not in point


def test_the_series_starts_again_from_the_ctf_once_there_is_one():
    series = monitor.streamingMonitor(Mapper(preprocessing(items=[ctfItem(1)])), 7, afterSetId=20, afterItemId=1,
                                      now=NOW)["series"]

    assert series["kind"] == "ctf" and series["reset"] is True and [p["id"] for p in series["points"]] == [1]
