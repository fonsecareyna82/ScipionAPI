from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pyworkflow.object import Float, Object, Set, String

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class TomogramItemStub(Object):
    def __init__(self):
        super().__init__()
        self._score = Float()
        self._code = String()


class TomogramSetStub(Set):
    ITEM_TYPE = TomogramItemStub

    def __init__(self, items):
        super().__init__()
        self._integrationItems = list(items)

    def getClassName(self):
        return "SetOfTomograms"

    def getObjDict(self, includeClass=False):
        if includeClass:
            return {
                "self": (
                    "SetOfTomograms",
                    None,
                ),
            }

        return {}

    def iterItems(self, iterate=False):
        return iter(self._integrationItems)

    def getSize(self):
        return len(self._integrationItems)

    def getFirstItem(self):
        return self._integrationItems[0] if self._integrationItems else None

    def getLastItem(self):
        return self._integrationItems[-1] if self._integrationItems else None

    def getMaxId(self):
        return max(
            (int(item.getObjId()) for item in self._integrationItems),
            default=0,
        )

    def getFileName(self):
        return None


def _buildTomogramItem(itemId):
    item = TomogramItemStub()
    item.setObjId(itemId)
    item._score.set(0.95)
    item._code.set("TOMO_%02d" % itemId)
    return item


def test_TomogramReviewHttpFlowUsesPostgresqlEndToEnd(
        projectRouterModule,
        postgresqlIntegrationDb,
        tmp_path,
):
    mapper = PostgresqlFlatMapper(postgresqlIntegrationDb)
    suffix = uuid4().hex
    userId = None
    projectId = None

    try:
        userId = mapper.insertUser(
            email="tomogram-review-api-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="Tomogram",
            lastName="Review API",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectPath = tmp_path / "tomogram-review-api-project"
        projectPath.mkdir(parents=True, exist_ok=True)

        projectId = mapper.insertProject(
            ownerId=userId,
            name=str(projectPath),
            description="Tomogram review HTTP integration test.",
            status="active",
        )

        scipionProtocolId = 52
        protocolDbId = mapper.saveProtocol({
            "info": {
                "protocolId": scipionProtocolId,
                "projectId": projectId,
                "protocolClassName": "TomogramReviewApiProtocol",
                "status": "finished",
            },
            "values": {},
            "parentIds": [],
            "childIds": [],
        })

        sourceSet = TomogramSetStub([
            _buildTomogramItem(31),
        ])
        sourceSet.setObjId(1_500_001)

        ScipionSetPostgresqlMapper(postgresqlIntegrationDb).storeSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputTomograms",
            scipionSet=sourceSet,
        )

        app = FastAPI()
        app.include_router(projectRouterModule.router)
        app.dependency_overrides[projectRouterModule.getMapper] = lambda: mapper
        app.dependency_overrides[projectRouterModule.getCurrentUser] = lambda: {
            "id": userId,
            "email": "tomogram-review-api-%s@example.com" % suffix,
            "role": "user",
        }

        with TestClient(app) as client:
            baseUrl = (
                "/projects/%s/protocols/%s/outputs/outputTomograms"
                % (projectId, scipionProtocolId)
            )

            initialContext = client.get(baseUrl + "/reviews")

            assert initialContext.status_code == 200
            assert initialContext.json()["progress"] == {
                "total": 1,
                "reviewed": 0,
            }
            assert initialContext.json()["reviews"] == {}

            created = client.patch(
                baseUrl + "/tomograms/31/review",
                json={
                    "reviewed": True,
                    "values": {
                        "quality": "Good",
                        "mito": True,
                    },
                    "comment": "Good membrane contrast",
                    "revision": 0,
                },
            )

            assert created.status_code == 200
            assert created.json()["revision"] == 1
            assert created.json()["scipionItemId"] == 31

            storedContext = client.get(baseUrl + "/reviews")

            assert storedContext.status_code == 200
            assert storedContext.json()["progress"] == {
                "total": 1,
                "reviewed": 1,
            }
            assert storedContext.json()["reviews"]["31"]["comment"] == (
                "Good membrane contrast"
            )

            stale = client.patch(
                baseUrl + "/tomograms/31/review",
                json={
                    "reviewed": True,
                    "values": {
                        "quality": "Bad",
                    },
                    "comment": "Stale update",
                    "revision": 0,
                },
            )

            assert stale.status_code == 409
            assert stale.json()["detail"]["current"]["revision"] == 1
            assert stale.json()["detail"]["current"]["comment"] == (
                "Good membrane contrast"
            )

        app.dependency_overrides.clear()

    finally:
        if projectId is not None and userId is not None:
            mapper.deleteProject(
                projectId=projectId,
                ownerId=userId,
            )

        if userId is not None:
            postgresqlIntegrationDb.execute(
                "DELETE FROM users WHERE id = %s",
                (userId,),
            )
