"""The parameters of every launch of a protocol."""
from datetime import datetime, timezone

from app.backend.api.services import protocol_history as history


class Db:
    def __init__(self, rows=(), fail=False):
        self.rows, self.fail, self.executed = list(rows), fail, []

    def execute(self, query, params):
        if self.fail:
            raise RuntimeError("relation protocol_launches does not exist")
        self.executed.append((query, params))

    def fetchAll(self, query, params):
        if self.fail:
            raise RuntimeError("relation protocol_launches does not exist")
        self.query = (query, params)
        return self.rows


class Mapper:
    def __init__(self, protocol=None, db=None):
        self.protocol, self.db = protocol, db or Db()

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        return self.protocol


PROTOCOL = {"id": 41, "protocolId": "12", "params": {"runName": "ctf", "resolution": 5, "_scipionWebRuntime": {"x": 1}}}


def test_a_launch_keeps_the_protocol_parameters_without_the_bookkeeping():
    mapper = Mapper(PROTOCOL)
    assert history.recordLaunch(mapper, 7, "12", 3, "restart") is True
    (query, params), = mapper.db.executed
    assert params[:5] == (7, 41, "12", 3, "restart")
    assert params[5].adapted == {"runName": "ctf", "resolution": 5}


def test_stops_unsaved_protocols_and_missing_tables_are_not_recorded():
    mapper = Mapper(PROTOCOL)
    assert history.recordLaunch(mapper, 7, "12", 3, "stop") is False
    assert history.recordLaunch(mapper, 7, "", 3, "schedule") is False
    assert history.recordLaunch(mapper, 7, "fake-protocol-id", 3, "launch") is False
    assert history.recordLaunch(Mapper(None), 7, "12", 3, "launch") is False
    assert mapper.db.executed == []
    # A database not migrated yet loses the history, not the launch.
    assert history.recordLaunch(Mapper(PROTOCOL, Db(fail=True)), 7, "12", 3, "launch") is False


def test_launches_are_listed_with_who_launched_them():
    when = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    rows = [
        {"id": 5, "mode": "restart", "params": {"resolution": 4, "_x": 1}, "launchedAt": when, "userId": 3,
         "email": "ana@example.org", "firstName": "Ana", "lastName": "López"},
        {"id": 2, "mode": "launch", "params": {"resolution": 5}, "launchedAt": when, "userId": 4,
         "email": "bo@example.org", "firstName": None, "lastName": None},
        {"id": 1, "mode": "launch", "params": None, "launchedAt": when, "userId": None},
    ]
    db = Db(rows)
    launches = history.listLaunches(Mapper(db=db), 7, 12)
    assert db.query[1] == (7, "12", history.HISTORY_LIMIT)
    assert launches[0] == {"id": 5, "mode": "restart", "launchedAt": when.isoformat(),
                           "user": {"id": 3, "name": "Ana López"}, "params": {"resolution": 4}}
    assert launches[1]["user"] == {"id": 4, "name": "bo@example.org"}
    assert launches[2]["user"] is None and launches[2]["params"] == {}
    assert history.listLaunches(Mapper(db=Db(fail=True)), 7, 12) == []
