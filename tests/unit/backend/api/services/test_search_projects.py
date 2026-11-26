import datetime as dt

import pytest

from app.backend.api.services.search_projects import MAX_PROTOCOLS, search
from app.backend.mapper.assistant_mapper import AssistantPostgresqlMapper


class FakeMapper:
    def __init__(self, protocols=(), projects=()):
        self.protocols, self.projects, self.asked = list(protocols), list(projects), []

    def searchProtocols(self, projectIds, words, since, until, status, limit):
        self.asked.append(("protocols", projectIds, words, since, until, status, limit))
        return self.protocols[:limit]

    def searchProjects(self, projectIds, words, limit):
        self.asked.append(("projects", projectIds, words, limit))
        return self.projects


ROW = {"projectId": 7, "projectPath": "/data/projects/SPA", "protocolId": 106, "label": "initial model",
       "className": "ProtCryoSparcInitialModel", "status": "finished",
       "startedAt": dt.datetime(2026, 11, 12, 9, 0, tzinfo=dt.timezone.utc), "endedAt": None,
       "createdAt": dt.datetime(2026, 10, 14, tzinfo=dt.timezone.utc)}


def test_SearchesOnlyTheGivenProjectsWithTheWordsAndDays():
    mapper = FakeMapper([ROW], [{"projectId": 7, "projectPath": "/data/projects/SPA", "description": "apoferritin",
                                 "protocols": 31, "createdAt": None, "updatedAt": None}])
    found = search(mapper, [7, 9], "cryosparc  initial,model", "2026-10-01", "2026-10-31", "finished")
    assert mapper.asked[0] == ("protocols", [7, 9], ["cryosparc", "initial", "model"], "2026-10-01", "2026-11-01",
                               "finished", MAX_PROTOCOLS + 1)
    assert found["protocols"][0] == {"projectId": 7, "project": "SPA", "protocolId": "106", "label": "initial model",
                                     "className": "ProtCryoSparcInitialModel", "status": "finished",
                                     "lastRunStarted": "2026-11-12T09:00:00+00:00", "lastRunEnded": None,
                                     "created": "2026-10-14T00:00:00+00:00"}
    assert found["projects"][0]["name"] == "SPA" and found["more"] is False


def test_TooManyIsSaid():
    found = search(FakeMapper([ROW] * (MAX_PROTOCOLS + 5)), [7], "x")
    assert len(found["protocols"]) == MAX_PROTOCOLS and found["more"] is True


def test_BadDatesAreSaid():
    with pytest.raises(ValueError) as error:
        search(FakeMapper(), [7], "x", "October")
    assert "YYYY-MM-DD" in str(error.value)


def test_WordsAreMatchedLiterally():
    condition, values = AssistantPostgresqlMapper._wordsCondition("t", ["50%", "a_b"])
    assert condition == "t ILIKE %s AND t ILIKE %s"
    assert values == ["%50\\%%", "%a\\_b%"]
    assert AssistantPostgresqlMapper._wordsCondition("t", []) == ("TRUE", [])


def test_NoProjectsNoQuery():
    class Db:
        def fetchAll(self, *args):
            raise AssertionError("no query")

    mapper = AssistantPostgresqlMapper(Db())
    assert mapper.searchProtocols([], ["x"], None, None, "", 5) == []
    assert mapper.searchProjects([7], [], 5) == []
