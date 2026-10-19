"""The project revision route: a cheap fingerprint of the graph, for the signed-in user's projects."""
import importlib
import json

import pytest
from fastapi import HTTPException


class Mapper:
    def __init__(self):
        self.queries = []

    def getProjectRevision(self, projectId):
        self.queries.append(projectId)
        return {"revision": "abc", "protocols": 3}


class Service:
    def __init__(self, allowed):
        self.allowed = allowed

    def getProjectDbRow(self, mapper, projectId, currentUser):
        return {"id": projectId} if self.allowed else None


def test_the_revision_is_never_cached_and_needs_access(authTestEnv):
    router = importlib.import_module("app.backend.api.routers.project_router")
    mapper = Mapper()
    response = router.getProjectRevision(projectId=4, currentUser={"id": 1}, mapper=mapper,
                                         service=Service(allowed=True))
    assert json.loads(response.body) == {"revision": "abc", "protocols": 3}
    assert response.headers["Cache-Control"] == "no-store"
    with pytest.raises(HTTPException) as error:
        router.getProjectRevision(projectId=5, currentUser={"id": 1}, mapper=mapper,
                                  service=Service(allowed=False))
    assert error.value.status_code == 404
    assert mapper.queries == [4]


def test_the_mapper_reads_one_row_for_the_project(authTestEnv):
    postgresql = importlib.import_module("app.backend.mapper.postgresql")

    class Db:
        def fetchOne(self, query, params):
            self.call = (query, params)
            return {"revision": "f00", "protocols": 2}

    mapper = object.__new__(postgresql.PostgresqlFlatMapper)
    mapper.db = Db()
    assert mapper.getProjectRevision("7") == {"revision": "f00", "protocols": 2}
    assert mapper.db.call == (postgresql.PROJECT_REVISION_SQL, (7,))
