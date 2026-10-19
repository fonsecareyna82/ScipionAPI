"""Protocol activity over the projects of a user."""
from datetime import datetime, timedelta, timezone

from app.backend.api.services import workspace_service as workspace


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


def test_search_finds_projects_and_protocols_of_the_user():
    db = Db(rows=[{"projectId": 9, "protocolId": "12", "protocolClassName": "ProtImportTs", "status": "FINISHED",
                   "label": "import tilt series"}])
    found = workspace.search(Mapper(PROJECTS, db), 3, "  tomo  ")
    assert found["projects"] == [{"projectId": 9, "projectName": "Tomo"}]
    assert found["protocols"] == [{"projectId": 9, "projectName": "Tomo", "protocolId": "12",
                                   "protocolClassName": "ProtImportTs", "label": "import tilt series",
                                   "status": "finished"}]
    projectIds, contains, classContains, exactId, exactIdAgain, startsWith, limit = db.calls[-1][1]
    assert (projectIds, contains, startsWith, exactId) == ([7, 9], "%tomo%", "tomo%", "tomo")


def test_search_treats_wildcards_as_text_and_needs_a_query():
    db = Db(rows=[])
    workspace.search(Mapper(PROJECTS, db), 3, "50%_done")
    assert db.calls[-1][1][1] == "%50\\%\\_done%"
    assert workspace.search(Mapper(PROJECTS, Db(rows=[])), 3, "   ") == {"projects": [], "protocols": []}
