"""The project overview route."""
import importlib
import json

import pytest
from fastapi import HTTPException


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
