"""Protocol activity over the projects of a user."""
from datetime import datetime, timedelta, timezone

import pytest

from app.backend.api.services import workspace_service as workspace
from app.backend.mapper import protocol_activity_mapper as activityQueries


class Db:
    def __init__(self, rows, live=0):
        self.rows, self.live, self.calls = rows, live, []

    def fetchOne(self, query, params):
        self.calls.append(("one", params))
        return {"live": self.live}

    def fetchAll(self, query, params):
        self.calls.append(("all", params))
        return self.rows


class Mapper:
    def __init__(self, projects, db):
        self.projects, self.db = projects, db

    def listProjects(self, userId):
        return self.projects


NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
PROJECTS = [{"id": 7, "name": "/data/projects/Workflow_2D"}, {"id": 9, "name": "/data/projects/Tomo"}]


def test_a_first_call_reports_nothing_but_the_server_time():
    db = Db(rows=[{"projectId": 7}], live=2)
    payload = workspace.protocolActivity(Mapper(PROJECTS, db), 3, None, now=NOW)
    assert payload == {"now": NOW.isoformat(), "live": 2, "events": []}
    assert [call[0] for call in db.calls] == ["one"]


def test_runs_ended_since_the_previous_call_are_reported_with_their_project():
    ended = NOW - timedelta(seconds=20)
    db = Db(rows=[{"projectId": 7, "projectPath": "/data/projects/Workflow_2D", "protocolId": "4",
                   "protocolClassName": "XmippProtCTFConsensus", "status": "FINISHED",
                   "label": "ctf consensus", "endedAt": ended}])
    payload = workspace.protocolActivity(Mapper(PROJECTS, db), 3, NOW - timedelta(seconds=30), now=NOW)
    assert payload["events"] == [{
        "projectId": 7, "projectName": "Workflow_2D", "protocolId": "4",
        "protocolClassName": "XmippProtCTFConsensus", "label": "ctf consensus",
        "status": "finished", "endedAt": ended.isoformat(),
    }]
    projectIds, statuses, since, limit = db.calls[-1][1]
    assert projectIds == [7, 9] and "failed" in statuses and "interactive" in statuses
    assert since == NOW - timedelta(seconds=30)


def test_an_old_since_is_capped_and_users_without_projects_get_nothing():
    db = Db(rows=[])
    workspace.protocolActivity(Mapper(PROJECTS, db), 3, NOW - timedelta(days=30), now=NOW)
    assert db.calls[-1][1][2] == NOW - workspace.MAX_LOOKBACK
    empty = Db(rows=[{"projectId": 1}])
    assert workspace.protocolActivity(Mapper([], empty), 3, NOW, now=NOW)["events"] == []
    assert empty.calls == []



class StreamingDb(Db):
    """One project (7) streams; its activity has no ended run."""

    def fetchAll(self, query, params):
        self.calls.append(("all", params))
        if query == activityQueries.LIVE_PROJECTS_SQL:
            return [{"projectId": 7}]
        return []


def test_streaming_projects_tell_when_micrographs_go_past_a_monitor_threshold(monkeypatch):
    from app.backend.api.services import streaming_monitor
    started = NOW - timedelta(seconds=10)
    monkeypatch.setattr(streaming_monitor, "alertsSince", lambda mapper, projectId, since: [{
        "kind": "maxAstigmatism", "text": "Astigmatism above 1000 Å", "startedAt": started.isoformat(),
        "micrographName": "mic_012", "count": 3, "ongoing": True, "protocolId": "5",
        "protocolClassName": "CistemProtCTFFind"}])

    payload = workspace.protocolActivity(Mapper(PROJECTS, StreamingDb([], live=1)), 3, NOW - timedelta(seconds=30),
                                         now=NOW)

    assert payload["events"] == [{
        "projectId": 7, "projectName": "Workflow_2D", "protocolId": "5", "protocolClassName": "CistemProtCTFFind",
        "label": "Astigmatism above 1000 Å: mic_012 and 2 more", "status": "alert", "threshold": "maxAstigmatism",
        "endedAt": started.isoformat(),
    }]


def test_a_monitor_that_cannot_be_read_does_not_stop_the_activity(monkeypatch):
    from app.backend.api.services import streaming_monitor

    def broken(mapper, projectId, since):
        raise RuntimeError("no such table")

    monkeypatch.setattr(streaming_monitor, "alertsSince", broken)

    payload = workspace.protocolActivity(Mapper(PROJECTS, StreamingDb([], live=1)), 3, NOW - timedelta(seconds=30),
                                         now=NOW)

    assert payload["events"] == [] and payload["live"] == 1


def test_nothing_running_looks_at_no_monitor(monkeypatch):
    from app.backend.api.services import streaming_monitor
    monkeypatch.setattr(streaming_monitor, "alertsSince", lambda *args: pytest.fail("No monitor to read"))

    workspace.protocolActivity(Mapper(PROJECTS, StreamingDb([], live=0)), 3, NOW - timedelta(seconds=30), now=NOW)



def test_tilt_series_alerts_reach_the_bell_too(monkeypatch):
    from app.backend.api.services import streaming_monitor, tomo_monitor
    started = NOW - timedelta(seconds=5)
    monkeypatch.setattr(streaming_monitor, "alertsSince", lambda mapper, projectId, since: [])
    monkeypatch.setattr(tomo_monitor, "alertsSince", lambda mapper, projectId, since: [{
        "kind": "minTilts", "text": "Fewer than 30 tilts", "startedAt": started.isoformat(), "micrographName": "TS_07",
        "count": 1, "ongoing": True, "protocolId": "1", "protocolClassName": "ProtComposeTS"}])

    payload = workspace.protocolActivity(Mapper(PROJECTS, StreamingDb([], live=1)), 3, NOW - timedelta(seconds=30),
                                         now=NOW)

    assert [(e["label"], e["status"], e["threshold"]) for e in payload["events"]] == [
        ("Fewer than 30 tilts: TS_07", "alert", "minTilts")]
