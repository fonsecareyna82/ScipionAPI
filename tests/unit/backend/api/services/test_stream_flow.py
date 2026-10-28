"""Whether a stream flows: the acquisition goes on, paused or finished, and which stages stopped."""
from datetime import datetime, timedelta, timezone

import pytest

from app.backend.api.services import stream_flow as flow
from app.backend.api.services.streaming_monitor import DEFAULT_THRESHOLDS

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


def stage(name, protocolId, items=100, behind=None, streaming=True, lastMinutes=1, status="running"):
    return {"stage": name, "setId": int(protocolId) * 10, "protocolId": protocolId, "protocolClassName": "Prot%s" % protocolId,
            "label": "run %s" % protocolId, "items": items, "behind": behind, "streaming": streaming,
            "status": status, "lastItemAt": None if lastMinutes is None else ago(lastMinutes)}


def stream(**movies):
    return [stage("movies", "1", **movies), stage("micrographs", "2", items=95, behind=5),
            stage("ctf", "3", items=90, behind=5)]


def streamFlow(stages, thresholds=DEFAULT_THRESHOLDS, **kwargs):
    """The flow of a stream whose acquisition fills its first stage."""
    return flow.streamFlow(stages[0], stages, thresholds, NOW, **kwargs)


def test_movies_coming_in_are_an_active_acquisition():
    state = streamFlow(stream(lastMinutes=2))

    assert state["acquisition"] == "active" and state["stalled"] == [] and not state["complete"]


def test_no_new_movies_while_the_import_waits_is_a_pause_with_the_time_it_still_waits():
    state = streamFlow(stream(lastMinutes=12), importTimeoutSeconds=30 * 60)

    assert state["acquisition"] == "paused"
    assert state["idleMinutes"] == pytest.approx(12)
    assert state["importClosesInMinutes"] == pytest.approx(18)


def test_a_closed_import_is_a_finished_acquisition_never_a_pause():
    closedAt = ago(1)
    state = streamFlow(stream(streaming=False, lastMinutes=600), closedAt=closedAt)

    assert state["acquisition"] == "finished" and state["finishedAt"] == closedAt
    # Its micrographs and CTFs still come
    assert not state["complete"]


def test_a_finished_acquisition_whose_stages_all_closed_is_a_complete_session():
    stages = [dict(item, streaming=False, behind=0) for item in stream()]

    assert streamFlow(stages)["complete"] is True


def test_an_open_import_whose_protocol_does_not_run_any_more_stopped():
    state = streamFlow(stream(status="failed", lastMinutes=30))

    assert state["acquisition"] == "stopped" and state["protocolStatus"] == "failed"


def test_a_stage_with_items_waiting_that_gives_nothing_is_stalled_also_after_the_acquisition():
    stages = stream(streaming=False)
    stages[2]["lastItemAt"] = ago(20)
    stages.append(dict(stage("classes2d", "6", behind=500), lastItemAt=ago(60)))
    stages.append(dict(stage("particles", "5", behind=0), lastItemAt=ago(60)))

    state = streamFlow(stages)

    assert [(item["stage"], item["behind"]) for item in state["stalled"]] == [("ctf", 5)]
    assert stages[2]["stalledMinutes"] == pytest.approx(20)
    # Classes come in rounds; nothing waits for the particles
    assert "stalledMinutes" not in stages[3] and "stalledMinutes" not in stages[4]


def test_a_threshold_switched_off_raises_nothing():
    thresholds = dict(DEFAULT_THRESHOLDS, maxMoviePauseMinutes=None, maxStageStallMinutes=None)
    stages = stream(lastMinutes=60)
    stages[2]["lastItemAt"] = ago(60)

    state = streamFlow(stages, thresholds)

    assert state["acquisition"] == "active" and state["stalled"] == []


def test_the_bell_hears_of_each_condition_from_when_it_began():
    stages = stream(lastMinutes=12)
    stages[2]["lastItemAt"] = ago(20)
    runs = flow.flowAlertRuns(streamFlow(stages), stages, DEFAULT_THRESHOLDS)

    assert [(run["kind"], run["text"], run["micrographName"], run["startedAt"]) for run in runs] == [
        ("maxMoviePauseMinutes", "No new movies for over 10 min", "run 1", ago(2)),
        ("maxStageStallMinutes", "No progress for over 15 min", "run 3, 5 waiting", ago(5)),
    ]
    assert runs[1]["protocolClassName"] == "Prot3"


def test_the_bell_hears_of_the_end_of_the_acquisition_when_the_import_closed():
    stages = stream(streaming=False, lastMinutes=720)
    runs = flow.flowAlertRuns(streamFlow(stages, closedAt=ago(1)), stages,
                              DEFAULT_THRESHOLDS)

    assert [(run["kind"], run["micrographName"], run["startedAt"]) for run in runs] == [
        ("acquisitionFinished", "100 movies", ago(1))]


@pytest.mark.parametrize("text, seconds", [
    ("12h", 43200), ("1m 10s", 70), ("22000", 22000), ("1.5h", 5400), ("1d", 86400),
    ("", None), (None, None), ("__import__('os').system('true')", None), ("12 hours", None),
])
def test_import_timeouts_are_read_without_evaluating_them(text, seconds):
    assert flow.durationSeconds(text) == seconds


def test_a_closed_stage_is_never_stalled_what_it_lacks_was_left_out():
    stages = stream()
    # A categorization that finished: 18 micrographs it discarded, not waiting
    stages[1].update(streaming=False, behind=18, lastItemAt=ago(600))

    assert streamFlow(stages)["stalled"] == []
