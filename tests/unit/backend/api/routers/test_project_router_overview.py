"""The project overview route."""
import importlib
import json

import pytest
from fastapi import HTTPException


class Db:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def fetchAll(self, query, params):
        return self.rows

    def fetchOne(self, query, params):
        return None

    def execute(self, query, params):
        self.executed.append((query, params))


class Mapper:
    def __init__(self, protocol=None, rows=()):
        self.protocol = protocol
        self.db = Db(list(rows))

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        return self.protocol


class Service:
    def __init__(self, path=None):
        self.path = path

    def getProjectDbRow(self, mapper, projectId, currentUser):
        return {"id": projectId, "name": str(self.path)} if self.path else None


def test_the_overview_needs_access_and_is_never_cached(authTestEnv, tmp_path):
    router = importlib.import_module("app.backend.api.routers.project_router")
    response = router.getProjectOverview(projectId=4, currentUser={"id": 1}, mapper=Mapper(), service=Service(tmp_path))
    assert json.loads(response.body)["protocols"] == 0
    assert response.headers["Cache-Control"] == "no-store"
    with pytest.raises(HTTPException) as error:
        router.getProjectOverview(projectId=4, currentUser={"id": 1}, mapper=Mapper(), service=Service())
    assert error.value.status_code == 404


def test_the_streaming_monitor_needs_access_and_is_never_cached(authTestEnv, tmp_path):
    router = importlib.import_module("app.backend.api.routers.project_router")
    response = router.getProjectStreamingMonitor(projectId=4, ctfSetId=None, coordinatesSetId=None, classesSetId=None, afterSetId=None, afterRowId=None, qualityWindowSize=0,
                                                 currentUser={"id": 1}, mapper=Mapper(), service=Service(tmp_path))
    assert json.loads(response.body)["stages"] == []
    assert response.headers["Cache-Control"] == "no-store"
    with pytest.raises(HTTPException) as error:
        router.getProjectStreamingMonitor(projectId=4, ctfSetId=None, coordinatesSetId=None, classesSetId=None, afterSetId=None, afterRowId=None, qualityWindowSize=0,
                                          currentUser={"id": 1}, mapper=Mapper(), service=Service())
    assert error.value.status_code == 404


def test_monitor_thresholds_are_checked_before_they_are_kept(authTestEnv, tmp_path):
    router = importlib.import_module("app.backend.api.routers.project_router")
    mapper = Mapper()
    saved = router.saveProjectMonitorThresholds(projectId=4, thresholds={"maxResolution": 6}, currentUser={"id": 1},
                                                mapper=mapper, service=Service(tmp_path))
    assert saved["thresholds"]["maxResolution"] == 6.0 and len(mapper.db.executed) == 1
    with pytest.raises(HTTPException) as error:
        router.saveProjectMonitorThresholds(projectId=4, thresholds={"maxResolution": -2}, currentUser={"id": 1},
                                            mapper=mapper, service=Service(tmp_path))
    assert error.value.status_code == 422 and len(mapper.db.executed) == 1
    with pytest.raises(HTTPException) as error:
        router.saveProjectMonitorThresholds(projectId=4, thresholds={}, currentUser={"id": 1}, mapper=mapper,
                                            service=Service())
    assert error.value.status_code == 404


def test_thresholds_a_database_cannot_keep_say_why(authTestEnv, tmp_path):
    router = importlib.import_module("app.backend.api.routers.project_router")
    mapper = Mapper()

    def missingTable(query, params):
        raise RuntimeError('relation "project_monitor_settings" does not exist')

    mapper.db.execute = missingTable
    with pytest.raises(HTTPException) as error:
        router.saveProjectMonitorThresholds(projectId=4, thresholds={"maxResolution": 6}, currentUser={"id": 1},
                                            mapper=mapper, service=Service(tmp_path))
    assert error.value.status_code == 503 and "alembic upgrade head" in error.value.detail
