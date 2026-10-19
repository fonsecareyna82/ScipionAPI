"""The project overview, disk usage and tmp cleaning routes."""
import importlib
import json

import pytest
from fastapi import HTTPException

from app.backend.api.services import project_overview


class Db:
    def __init__(self, rows):
        self.rows = rows

    def fetchAll(self, query, params):
        return self.rows


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


def test_cleaning_tmp_empties_a_finished_protocol_and_refuses_others(authTestEnv, tmp_path, monkeypatch):
    router = importlib.import_module("app.backend.api.routers.project_router")
    monkeypatch.setattr(project_overview, "diskUsageCache", project_overview.DiskUsageCache())
    tmp = project_overview.protocolFolder(str(tmp_path), 3, "ProtA") / "tmp"
    tmp.mkdir(parents=True)
    (tmp / "a").write_bytes(b"x" * 12)

    running = {"protocolId": "3", "protocolClassName": "ProtA", "status": "running"}
    with pytest.raises(HTTPException) as error:
        router.cleanProtocolTmp(projectId=4, protocolId=3, currentUser={"id": 1},
                                mapper=Mapper(running), service=Service(tmp_path))
    assert error.value.status_code == 409 and (tmp / "a").exists()

    finished = dict(running, status="finished")
    result = router.cleanProtocolTmp(projectId=4, protocolId=3, currentUser={"id": 1},
                                     mapper=Mapper(finished), service=Service(tmp_path))
    assert result == {"freedBytes": 12, "removedFiles": 1}

    with pytest.raises(HTTPException) as error:
        router.cleanProtocolTmp(projectId=4, protocolId=9, currentUser={"id": 1},
                                mapper=Mapper(None), service=Service(tmp_path))
    assert error.value.status_code == 404
