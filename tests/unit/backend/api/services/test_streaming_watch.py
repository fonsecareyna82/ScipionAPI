import pytest

from app.backend.api.services import streaming_watch as watch
from app.backend.api.services.assistant_actions import ProposalError


def _snapshot(items=40, flow=None, stalled=(), streaming=True, **quality):
    return {"streaming": streaming, "quality": dict({"items": items, "outside": 0.0}, **quality),
            "flow": dict({"acquisition": "active", "items": 500, "unit": "movies"}, **(flow or {})),
            "stalled": list(stalled), "stages": {"movies": 500, "ctf": 480}}


def test_TheReferenceWaitsForEnoughMicrographs():
    start = watch.startingState(_snapshot(items=5), [])
    assert start["reference"] is None
    result = watch.step(dict(start, id=1), _snapshot(resolution=3.5), [])
    assert result["reference"]["quality"]["resolution"] == 3.5 and result["notices"] == []


def test_WorseCtfAndDriftAndFewerParticlesAreToldOnce():
    reference = _snapshot(resolution=3.5, totalDrift=8.0, particles=120)
    now = _snapshot(resolution=5.0, totalDrift=14.0, particles=60)
    result = watch.step({"reference": reference, "state": {}}, now, [])
    titles = [notice["title"] for notice in result["notices"]]
    assert titles == ["The CTF resolution got worse", "The drift went up", "Fewer particles per micrograph"]
    assert "3.5 Å" in result["notices"][0]["body"] and "What to do" in result["notices"][0]["body"]
    again = watch.step({"reference": reference, "state": result["state"]}, now, [])
    assert again["notices"] == []
    # Gone, then back: told again
    fine = watch.step({"reference": reference, "state": again["state"]}, _snapshot(resolution=3.6), [])
    back = watch.step({"reference": reference, "state": fine["state"]}, now, [])
    assert len(back["notices"]) == 3


def test_SmallChangesAreNotProblems():
    reference = _snapshot(resolution=3.0, totalDrift=8.0, particles=120)
    assert watch.problems(reference, _snapshot(resolution=3.4, totalDrift=10.0, particles=100), [], []) == []


def test_FlowAndFailuresNewSinceTheWatchBegan():
    protocols = [{"protocolId": "12", "label": "ctf", "status": "failed"},
                 {"protocolId": "13", "label": "pick", "status": "failed"}]
    snapshot = _snapshot(flow={"acquisition": "paused", "idleMinutes": 14},
                         stalled=[{"protocolId": "13", "label": "pick", "behind": 30, "minutes": 20}])
    keys = [problem["key"] for problem in watch.problems(None, snapshot, ["12"], protocols)]
    assert keys == ["paused", "stalled:13", "failed:13"]


def test_AFinishedSessionEndsTheWatch():
    result = watch.step({"reference": None, "state": {}}, _snapshot(flow={"acquisition": "finished",
                                                                          "complete": True}), [])
    assert result["end"] == "finished"
    assert "every step got to the end" in result["notices"][0]["body"]


def test_WatchCardRefusesWhatDoesNotStream():
    with pytest.raises(ProposalError):
        watch.watchCard(7, "p", _snapshot(streaming=False), 24, None)
    with pytest.raises(ProposalError):
        watch.watchCard(7, "p", _snapshot(), 24, {"until": "tomorrow"})
    card = watch.watchCard(7, "p", _snapshot(resolution=3.2), 500, None)
    assert card["hours"] == 72 and card["now"]["resolution"] == 3.2
    with pytest.raises(ProposalError):
        watch.unwatchCard(7, "p", None)
