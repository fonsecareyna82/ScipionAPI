import importlib
from types import SimpleNamespace

import pytest


@pytest.fixture
def projectServiceModule(authTestEnv):
    return importlib.import_module(
        "app.backend.api.services.project_service"
    )


@pytest.fixture
def service(projectServiceModule):
    instance = object.__new__(
        projectServiceModule.ProjectService
    )
    instance.currentProject = None
    return instance


def test_PostgresqlReaderProtocolIdUsesScipionIdWhenRouteIdentityIsExplicit(
        service,
        monkeypatch,
):
    strictCalls = []

    def strictResolver(
            mapper,
            projectId,
            protocolId,
    ):
        strictCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
        })
        return 500

    def failCompatibilityResolver(**kwargs):
        raise AssertionError(
            "Strict route identity must not use the "
            "DB-id compatibility resolver."
        )

    monkeypatch.setattr(
        service,
        "_resolvePostgresqlProtocolDbIdFromScipionProtocolId",
        strictResolver,
    )
    monkeypatch.setattr(
        service,
        "_resolvePostgresqlProtocolDbId",
        failCompatibilityResolver,
    )

    mapper = SimpleNamespace(db=object())

    resolved = service._resolvePostgresqlReaderProtocolId(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        protocolIdIsScipionId=True,
    )

    assert resolved == 500
    assert strictCalls == [{
        "mapper": mapper,
        "projectId": 1,
        "protocolId": 10,
    }]


@pytest.mark.parametrize(
    (
        "serviceMethodName",
        "readerHelperName",
        "readerMethodName",
        "payload",
    ),
    [
        (
            "listOutputCtfService",
            "_getPostgresqlCtfReaderIfAvailable",
            "listCtfs",
            {"items": ["ctf"]},
        ),
        (
            "listOutputTiltSeriesService",
            "_getPostgresqlTiltSeriesReaderIfAvailable",
            "listTiltSeries",
            [{"tiltSeriesId": "TS_01"}],
        ),
        (
            "listOutputCtftomoSeriesService",
            "_getPostgresqlCtftomoReaderIfAvailable",
            "listCtftomoSeries",
            [{"tiltSeriesId": "TS_01"}],
        ),
        (
            "listOutputVolumesService",
            "_getPostgresqlVolumeReaderIfAvailable",
            "listVolumes",
            [{"id": 1, "name": "selected-volume"}],
        ),
        (
            "listCoordinates3dTomogramsService",
            "_getPostgresqlCoords3dReaderIfAvailable",
            "listTomograms",
            [{"id": "tomo-1", "name": "selected-tomogram"}],
        ),
        (
            "getFscRowsService",
            "_getPostgresqlFscReaderIfAvailable",
            "getFscRows",
            {
                "threshold": 0.143,
                "rows": [{
                    "label": "selected-fsc",
                    "x": [0.01],
                    "y": [0.9],
                }],
            },
        ),
    ],
)
def test_ViewerServicesPropagateScipionIdWhenRouteIdentityIsExplicit(
        service,
        monkeypatch,
        serviceMethodName,
        readerHelperName,
        readerMethodName,
        payload,
):
    readerCalls = []

    class FakeReader:
        lastSkipReason = None

        def __getattr__(self, name):
            if name != readerMethodName:
                raise AttributeError(name)

            return lambda *args, **kwargs: payload

    def fakeReaderHelper(**kwargs):
        readerCalls.append(kwargs)
        return FakeReader()

    monkeypatch.setattr(
        service,
        readerHelperName,
        fakeReaderHelper,
    )

    mapper = SimpleNamespace(db=object())

    result = getattr(
        service,
        serviceMethodName,
    )(
        projectId=1,
        protocolId=10,
        outputName="selectedOutput",
        mapper=mapper,
        protocolIdIsScipionId=True,
    )

    assert result == payload
    assert readerCalls == [{
        "mapper": mapper,
        "projectId": 1,
        "protocolId": 10,
        "outputName": "selectedOutput",
        "protocolIdIsScipionId": True,
    }]


def test_ProtocolFilesystemUsesScipionIdWhenRouteIdentityIsExplicit(
        service,
        monkeypatch,
        tmp_path,
):
    selectedPath = (
        tmp_path
        / "DemoProject"
        / "Runs"
        / "000010_Selected"
    )

    class SelectedProtocol:
        def getPath(self):
            return str(selectedPath)

    strictCalls = []

    def strictLoader(**kwargs):
        strictCalls.append(kwargs)
        return SelectedProtocol()

    def failCompatibilityLoader(**kwargs):
        raise AssertionError(
            "Protocol filesystem route must not use "
            "DB-id compatibility resolution."
        )

    monkeypatch.setattr(
        service,
        "_getScipionProtocolByScipionId",
        strictLoader,
    )
    monkeypatch.setattr(
        service,
        "_getScipionProtocolForRuntime",
        failCompatibilityLoader,
    )

    result = service.getProtocolPath(
        protocolId=10,
        mapper=SimpleNamespace(db=object()),
        projectId=1,
        protocolIdIsScipionId=True,
    )

    assert result["protocolRoot"] == (
        "Runs/000010_Selected"
    )
    assert strictCalls[0]["protocolId"] == 10


def test_MetadataTablesPropagateScipionIdWhenRouteIdentityIsExplicit(
        service,
        monkeypatch,
):
    managerCalls = []

    class FakeTable:
        def getAlias(self):
            return "Selected table"

        def hasColumnId(self):
            return True

    class FakeManager:
        def getTables(self):
            return {
                "objects": FakeTable(),
            }

        def getTableRowCount(self, name):
            assert name == "objects"
            return 3

    def fakeManager(**kwargs):
        managerCalls.append(kwargs)
        return FakeManager()

    monkeypatch.setattr(
        service,
        "_getMetadataObjectManagerForOutput",
        fakeManager,
    )

    mapper = SimpleNamespace(db=object())

    result = service.listOutputMetadataTablesService(
        projectId=1,
        protocolId=10,
        outputName="selectedOutput",
        mapper=mapper,
        protocolIdIsScipionId=True,
    )

    assert result == [{
        "name": "objects",
        "alias": "Selected table",
        "rowCount": 3,
        "hasColumnId": True,
    }]
    assert managerCalls == [{
        "projectId": 1,
        "protocolId": 10,
        "outputName": "selectedOutput",
        "mapper": mapper,
        "protocolIdIsScipionId": True,
    }]


def test_IntegratedAnalyzeContextPropagatesScipionIdWhenRouteIdentityIsExplicit(
        service,
        monkeypatch,
):
    contextCalls = []

    def fakeContext(**kwargs):
        contextCalls.append(kwargs)
        return {
            "selected": True,
        }

    monkeypatch.setattr(
        service,
        "_getPostgresqlIntegratedAnalyzeContextIfAvailable",
        fakeContext,
    )

    mapper = SimpleNamespace(db=object())

    result = service.getIntegratedAnalyzeContextService(
        projectId=1,
        protocolId=10,
        outputName="selectedOutput",
        mapper=mapper,
        protocolIdIsScipionId=True,
    )

    assert result == {
        "selected": True,
    }
    assert contextCalls == [{
        "mapper": mapper,
        "projectId": 1,
        "protocolId": 10,
        "outputName": "selectedOutput",
        "protocolIdIsScipionId": True,
    }]


def test_ProtocolTagsUseScipionIdWhenRouteIdentityIsExplicit(
        service,
        monkeypatch,
):
    strictCalls = []

    def strictResolver(
            mapper,
            projectId,
            protocolId,
    ):
        strictCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
        })
        return 500

    def failCompatibilityResolver(**kwargs):
        raise AssertionError(
            "Protocol tags must not resolve a UI Scipion "
            "protocol id through DB-id compatibility."
        )

    monkeypatch.setattr(
        service,
        "_resolvePostgresqlProtocolDbIdFromScipionProtocolId",
        strictResolver,
    )
    monkeypatch.setattr(
        service,
        "_resolvePostgresqlProtocolDbId",
        failCompatibilityResolver,
    )
    monkeypatch.setattr(
        service,
        "_touchProjectModificationTime",
        lambda **kwargs: None,
    )

    class FakeMapper:
        def __init__(self):
            self.db = object()
            self.getCalls = []
            self.setCalls = []

        def getProtocolTagIds(
                self,
                projectId,
                protocolDbId,
        ):
            self.getCalls.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })
            return ["quality"]

        def setProtocolTagIdsByProtocolDbId(
                self,
                projectId,
                protocolDbId,
                tagIds,
        ):
            self.setCalls.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "tagIds": list(tagIds),
            })
            return {
                "protocolId": "10",
                "protocolDbId": protocolDbId,
                "tagIds": list(tagIds),
            }

    mapper = FakeMapper()

    listed = service.listProtocolTags(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        currentUser={"id": 1},
        protocolIdIsScipionId=True,
    )

    updated = service.setProtocolTags(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        tagIds=["quality"],
        currentUser={"id": 1},
        protocolIdIsScipionId=True,
    )

    assert listed["protocolDbId"] == 500
    assert updated["protocolDbId"] == 500
    assert mapper.getCalls == [{
        "projectId": 1,
        "protocolDbId": 500,
    }]
    assert mapper.setCalls == [{
        "projectId": 1,
        "protocolDbId": 500,
        "tagIds": ["quality"],
    }]
    assert [call["protocolId"] for call in strictCalls] == [
        10,
        10,
    ]


def test_TomogramReviewUsesScipionIdWhenRouteIdentityIsExplicit(
        projectServiceModule,
        service,
        monkeypatch,
):
    reviewModule = importlib.import_module(
        "app.backend.mapper.tomogram_review_mapper"
    )
    resolveCalls = []

    class FakeReviewMapper:
        def __init__(self, db):
            self.db = db

        def resolveSetId(
                self,
                projectId,
                protocolDbId,
                outputName,
        ):
            resolveCalls.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "outputName": outputName,
            })
            return 47

        def getReviewContext(
                self,
                projectId,
                setId,
        ):
            return {
                "projectId": projectId,
                "setId": setId,
            }

    monkeypatch.setattr(
        reviewModule,
        "TomogramReviewPostgresqlMapper",
        FakeReviewMapper,
    )

    readerCalls = []

    def strictReaderId(**kwargs):
        readerCalls.append(kwargs)
        assert kwargs[
            "protocolIdIsScipionId"
        ] is True
        return 500

    monkeypatch.setattr(
        service,
        "_resolvePostgresqlReaderProtocolId",
        strictReaderId,
    )

    mapper = SimpleNamespace(db=object())

    result = service.getTomogramReviewContextService(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        outputName="outputTomograms",
        protocolIdIsScipionId=True,
    )

    assert result == {
        "projectId": 1,
        "setId": 47,
    }
    assert readerCalls == [{
        "mapper": mapper,
        "projectId": 1,
        "protocolId": 10,
        "protocolIdIsScipionId": True,
    }]
    assert resolveCalls == [{
        "projectId": 1,
        "protocolDbId": 500,
        "outputName": "outputTomograms",
    }]
