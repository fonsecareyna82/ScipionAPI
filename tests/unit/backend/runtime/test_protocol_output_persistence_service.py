# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
import inspect

import pytest
import app.backend.mapper as backendMapperModule
from app.backend.mapper.scipion_set_mapper import (
    ScipionSetPostgresqlMapper,
)

from app.backend.runtime.protocol_output_persistence_service import (
    RuntimeProtocolOutputPersistenceService,
)
from app.backend.runtime import (
    protocol_output_persistence_service as outputPersistenceModule,
)

class FakeDb:
    def __init__(self):
        self.queries = []

    def fetchAll(self, query, params=None):
        normalizedQuery = " ".join(
            str(query).split()
        )

        self.queries.append(
            {
                "query": normalizedQuery,
                "params": params,
            }
        )

        return []


class FakeMapper:
    def __init__(self):
        self.db = FakeDb()


def test_PersistedOutputReadersExcludeReservedRuntimeSets():
    mapper = FakeMapper()
    service = RuntimeProtocolOutputPersistenceService()

    assert service.loadPersistedOutputsByProtocolId(
        mapper=mapper,
        projectId=7,
    ) == {}

    assert service.loadPersistedOutputSummariesByProtocolId(
        mapper=mapper,
        projectId=7,
    ) == {}

    setQueries = [
        call["query"]
        for call in mapper.db.queries
        if (
            'FROM scipion_sets s JOIN protocols p '
            'ON p.id = s."protocolDbId"'
        ) in call["query"]
    ]

    assert len(setQueries) == 2

    for query in setQueries:
        assert (
            "COALESCE( "
            "s.properties ->> 'runtimeReserved', "
            "'false' ) <> 'true'"
        ) in query


def test_DetachedSetMetadataPersistenceDoesNotExecuteDirectQueries():
    source = inspect.getsource(
        RuntimeProtocolOutputPersistenceService._storeDetachedSetOutput
    )

    assert "objectMapper.mergeStoredObjectMetadata(" in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source


def test_StoreDetachedSetOutputDelegatesMetadataPersistence():
    class DetachedSetStub:
        def getFileName(self):
            return "Runs/000010_Test/extra/output.sqlite"

        def getSize(self):
            return 24

    class ObjectMapperStub:
        def __init__(self):
            self.registerCalls = []
            self.storeCalls = []
            self.metadataCalls = []

        def registerObjectTypeFromObject(
                self,
                outputObj,
                **kwargs,
        ):
            self.registerCalls.append({
                "outputObj": outputObj,
                **kwargs,
            })

        def storeObjectTree(
                self,
                **kwargs,
        ):
            self.storeCalls.append(
                kwargs
            )

            return {
                "rootObjectId": 81,
                "storedObjectsCount": 1,
            }

        def mergeStoredObjectMetadata(
                self,
                **kwargs,
        ):
            self.metadataCalls.append(
                kwargs
            )

            return 1

    outputSet = DetachedSetStub()
    objectMapper = ObjectMapperStub()
    artifactError = FileNotFoundError(
        "missing output.sqlite"
    )

    result = (
        RuntimeProtocolOutputPersistenceService()
        ._storeDetachedSetOutput(
            objectMapper=objectMapper,
            projectId=7,
            protocolDbId=31,
            outputName="outputParticles",
            outputObj=outputSet,
            projectPaths=[
                "/tmp/project",
            ],
            artifactError=artifactError,
        )
    )

    assert len(objectMapper.registerCalls) == 1
    assert len(objectMapper.storeCalls) == 1

    assert objectMapper.metadataCalls == [
        {
            "projectId": 7,
            "protocolDbId": 31,
            "objectDbId": 81,
            "metadata": {
                "mapperKind": "detached_set",
                "storage": "object_tree",
                "artifactMissing": True,
                "artifactFileName": (
                    "Runs/000010_Test/extra/output.sqlite"
                ),
                "artifactError": (
                    "missing output.sqlite"
                ),
                "projectPathsChecked": [
                    "/tmp/project",
                ],
                "itemsCount": 24,
            },
        },
    ]

    assert result == {
        "rootObjectId": 81,
        "storedObjectsCount": 1,
        "artifactMissing": True,
        "artifactFileName": (
            "Runs/000010_Test/extra/output.sqlite"
        ),
        "itemsCount": 24,
        "projectPathsChecked": [
            "/tmp/project",
        ],
    }


def test_ProtocolFormOutputReaderDelegatesOutputRows(
        monkeypatch,
):
    mapper = FakeMapper()
    service = RuntimeProtocolOutputPersistenceService()
    setReadCalls = []
    treeReadCalls = []

    class SetMapperStub:
        def __init__(self, database):
            assert database is mapper.db

        def listProtocolSetOutputRows(
                self,
                projectId,
                protocolDbId,
        ):
            setReadCalls.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return []

    class ObjectMapperStub:
        def __init__(self, database):
            assert database is mapper.db

        def listProtocolTreeOutputRows(
                self,
                projectId,
                protocolDbId,
        ):
            treeReadCalls.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return []

    monkeypatch.setattr(
        backendMapperModule,
        "ScipionSetPostgresqlMapper",
        SetMapperStub,
    )

    monkeypatch.setattr(
        backendMapperModule,
        "ScipionObjectPostgresqlMapper",
        ObjectMapperStub,
    )

    monkeypatch.setattr(
        outputPersistenceModule.ProtocolIdentityResolver,
        "resolvePostgresqlProtocolDbId",
        lambda self, protocolId: 17,
    )

    assert service.loadPersistedProtocolOutputs(
        mapper=mapper,
        projectId=7,
        protocolId=19,
    ) == {}

    assert setReadCalls == [
        {
            "projectId": 7,
            "protocolDbId": 17,
        },
    ]

    assert treeReadCalls == [
        {
            "projectId": 7,
            "protocolDbId": 17,
        },
    ]

    assert mapper.db.queries == []

    source = inspect.getsource(
        RuntimeProtocolOutputPersistenceService.loadPersistedProtocolOutputs
    )

    assert "setMapper.listProtocolSetOutputRows(" in source
    assert "objectMapper.listProtocolTreeOutputRows(" in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source


def test_ProjectOutputReaderDelegatesOutputRows(monkeypatch):
    mapper = FakeMapper()
    service = RuntimeProtocolOutputPersistenceService()
    setReadCalls = []
    treeReadCalls = []

    class SetMapperStub:
        def __init__(self, database):
            assert database is mapper.db

        def listProjectSetOutputRows(self, projectId):
            setReadCalls.append({"projectId": projectId})
            return []

    class ObjectMapperStub:
        def __init__(self, database):
            assert database is mapper.db

        def listProjectTreeOutputRows(self, projectId):
            treeReadCalls.append({"projectId": projectId})
            return []

    monkeypatch.setattr(backendMapperModule, "ScipionSetPostgresqlMapper", SetMapperStub)
    monkeypatch.setattr(backendMapperModule, "ScipionObjectPostgresqlMapper", ObjectMapperStub)

    assert service.loadPersistedOutputsByProtocolId(mapper=mapper, projectId=7) == {}

    assert setReadCalls == [{"projectId": 7}]
    assert treeReadCalls == [{"projectId": 7}]
    assert mapper.db.queries == []

    source = inspect.getsource(RuntimeProtocolOutputPersistenceService.loadPersistedOutputsByProtocolId)

    assert "setMapper.listProjectSetOutputRows(" in source
    assert "objectMapper.listProjectTreeOutputRows(" in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source


def test_ProjectOutputSummaryReaderDelegatesOutputRows(monkeypatch):
    mapper = FakeMapper()
    service = RuntimeProtocolOutputPersistenceService()
    setReadCalls = []
    treeReadCalls = []

    class SetMapperStub:
        def __init__(self, database):
            assert database is mapper.db

        def listProjectSetOutputSummaryRows(self, projectId):
            setReadCalls.append({"projectId": projectId})
            return []

    class ObjectMapperStub:
        def __init__(self, database):
            assert database is mapper.db

        def listProjectTreeOutputRows(self, projectId):
            treeReadCalls.append({"projectId": projectId})
            return []

    monkeypatch.setattr(backendMapperModule, "ScipionSetPostgresqlMapper", SetMapperStub)
    monkeypatch.setattr(backendMapperModule, "ScipionObjectPostgresqlMapper", ObjectMapperStub)

    assert service.loadPersistedOutputSummariesByProtocolId(mapper=mapper, projectId=7) == {}

    assert setReadCalls == [{"projectId": 7}]
    assert treeReadCalls == [{"projectId": 7}]
    assert mapper.db.queries == []

    source = inspect.getsource(RuntimeProtocolOutputPersistenceService.loadPersistedOutputSummariesByProtocolId)

    assert "setMapper.listProjectSetOutputSummaryRows(" in source
    assert "objectMapper.listProjectTreeOutputRows(" in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source


def test_ProtocolOutputNameReaderDelegatesOutputRows(monkeypatch):
    mapper = FakeMapper()
    service = RuntimeProtocolOutputPersistenceService()
    setReadCalls = []
    treeReadCalls = []

    class SetMapperStub:
        def __init__(self, database):
            assert database is mapper.db

        def listProtocolSetOutputNameRows(self, projectId, protocolDbId):
            setReadCalls.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return [
                {
                    "outputName": "outputParticles",
                },
                (
                    "outputVolume",
                ),
            ]

    class ObjectMapperStub:
        def __init__(self, database):
            assert database is mapper.db

        def listProtocolTreeOutputNameRows(self, projectId, protocolDbId):
            treeReadCalls.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return [
                {
                    "outputName": "outputVolume",
                },
                (
                    "outputMask",
                ),
            ]

    monkeypatch.setattr(backendMapperModule, "ScipionSetPostgresqlMapper", SetMapperStub)
    monkeypatch.setattr(backendMapperModule, "ScipionObjectPostgresqlMapper", ObjectMapperStub)

    result = service.loadPersistedProtocolOutputNames(mapper=mapper, projectId=7, protocolDbId=31)

    assert result == {
        "outputParticles",
        "outputVolume",
        "outputMask",
    }

    assert setReadCalls == [
        {
            "projectId": 7,
            "protocolDbId": 31,
        },
    ]

    assert treeReadCalls == [
        {
            "projectId": 7,
            "protocolDbId": 31,
        },
    ]

    assert mapper.db.queries == []

    source = inspect.getsource(RuntimeProtocolOutputPersistenceService.loadPersistedProtocolOutputNames)

    assert "setMapper.listProtocolSetOutputNameRows(" in source
    assert "objectMapper.listProtocolTreeOutputNameRows(" in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source


def test_ProtocolOutputSnapshotDeleteDelegatesPersistence(monkeypatch):
    mapper = FakeMapper()
    service = RuntimeProtocolOutputPersistenceService()
    deleteCalls = []

    expectedResult = [
        {
            "outputName": "outputMask",
            "setsDeleted": 1,
            "objectsDeleted": 2,
        },
        {
            "outputName": "outputParticles",
            "setsDeleted": 0,
            "objectsDeleted": 3,
        },
    ]

    class ObjectMapperStub:
        def __init__(self, database):
            assert database is mapper.db

        def deleteProtocolOutputSnapshots(self, projectId, protocolDbId, outputNames):
            deleteCalls.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "outputNames": outputNames,
            })

            return expectedResult

    monkeypatch.setattr(backendMapperModule, "ScipionObjectPostgresqlMapper", ObjectMapperStub)

    result = service.deletePersistedProtocolOutputSnapshots(
        mapper=mapper,
        projectId=7,
        protocolDbId=31,
        outputNames=[
            " outputParticles ",
            "outputMask",
            "outputParticles",
            "",
            None,
        ],
    )

    assert result == expectedResult
    assert deleteCalls == [
        {
            "projectId": 7,
            "protocolDbId": 31,
            "outputNames": [
                "outputMask",
                "outputParticles",
            ],
        },
    ]

    assert mapper.db.queries == []

    source = inspect.getsource(RuntimeProtocolOutputPersistenceService.deletePersistedProtocolOutputSnapshots)

    assert "objectMapper.deleteProtocolOutputSnapshots(" in source
    assert ".db.transaction(" not in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source


def test_ProtocolOutputSnapshotDeleteSkipsEmptyOutputNames(monkeypatch):
    mapper = FakeMapper()
    service = RuntimeProtocolOutputPersistenceService()

    class ObjectMapperStub:
        def __init__(self, database):
            pytest.fail("The mapper must not be created without valid output names.")

    monkeypatch.setattr(backendMapperModule, "ScipionObjectPostgresqlMapper", ObjectMapperStub)

    result = service.deletePersistedProtocolOutputSnapshots(
        mapper=mapper,
        projectId=7,
        protocolDbId=31,
        outputNames=[
            "",
            "   ",
            None,
        ],
    )

    assert result == []
    assert mapper.db.queries == []


def test_RegisterOutputRecognizesRunDbProjectionOfNativePostgresqlSet(
        monkeypatch,
):
    nativeChecks = []
    finalized = []

    class RunDbSetProjectionStub:
        def getObjId(self):
            return 91

        def getClassName(self):
            return "SetOfParticles"

    class ProtocolStub:
        def __init__(self, outputSet):
            self.outputSet = outputSet

        def getObjId(self):
            return 23

        def iterOutputAttributes(self):
            return [
                (
                    "outputParticles",
                    self.outputSet,
                ),
            ]

    class RuntimeMapperStub:
        def __init__(self):
            self.db = object()

    class SetMapperStub:
        def __init__(self, db):
            self.db = db

        def isPostgresqlNativeSetOutput(
                self,
                projectId,
                protocolDbId,
                outputName,
        ):
            nativeChecks.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "outputName": outputName,
            })

            return True

        def finalizeRuntimeSetOutput(
                self,
                projectId,
                protocolDbId,
                outputName,
                scipionSet,
        ):
            finalized.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "outputName": outputName,
                "runtimeObjectId": (
                    scipionSet.getObjId()
                ),
            })

            return {
                "setId": 71,
                "runtimeObjectId": (
                    scipionSet.getObjId()
                ),
                "outputName": outputName,
            }

        def storeSet(self, **kwargs):
            pytest.fail(
                "A persisted native PostgreSQL "
                "output must not use storeSet()."
            )

    class ObjectMapperStub:
        def __init__(self, db):
            self.db = db

    outputSet = RunDbSetProjectionStub()
    protocol = ProtocolStub(
        outputSet
    )

    service = (
        RuntimeProtocolOutputPersistenceService()
    )

    monkeypatch.setattr(
        backendMapperModule,
        "ScipionSetPostgresqlMapper",
        SetMapperStub,
    )

    monkeypatch.setattr(
        backendMapperModule,
        "ScipionObjectPostgresqlMapper",
        ObjectMapperStub,
    )

    monkeypatch.setattr(
        service,
        "resolveProtocolDbIdForOutputPersistence",
        lambda **kwargs: 17,
    )

    monkeypatch.setattr(
        service,
        "_prepareOutputObjectIdsForPersistence",
        lambda **kwargs: pytest.fail(
            "A persisted native PostgreSQL "
            "output must not prepare ids again."
        ),
    )

    monkeypatch.setattr(
        service,
        "_openRelativeSetMapperForPersistence",
        lambda **kwargs: pytest.fail(
            "A persisted native PostgreSQL output "
            "must not open a SQLite mapper."
        ),
    )

    report = service.registerOutput(
        projectId=7,
        protocol=protocol,
        mapper=RuntimeMapperStub(),
        returnReport=True,
    )

    assert nativeChecks == [
        {
            "projectId": 7,
            "protocolDbId": 17,
            "outputName": "outputParticles",
        },
    ]

    assert finalized == [
        {
            "projectId": 7,
            "protocolDbId": 17,
            "outputName": "outputParticles",
            "runtimeObjectId": 91,
        },
    ]

    assert report["errors"] == []
    assert report["skipped"] == []
    assert len(report["persisted"]) == 1

    assert (
        report["persisted"][0]["setId"]
        == 71
    )

    assert (
        report["persisted"][0][
            "postgresqlNativeOutput"
        ]
        is True
    )

    assert outputSet.getObjId() == 91


def test_StoreSetProtectsNativePostgresqlSnapshotBeforeArtifactRead(
        monkeypatch,
):
    finalized = []

    class RunDbSetProjectionStub:
        def getObjId(self):
            return 91

        def getClassName(self):
            return "SetOfParticles"

    setMapper = object.__new__(
        ScipionSetPostgresqlMapper
    )
    setMapper.db = object()

    monkeypatch.setattr(
        setMapper,
        "_resolveProtocolDbId",
        lambda projectId, protocolDbId: 17,
    )

    monkeypatch.setattr(
        setMapper,
        "_getExistingSet",
        lambda projectId, protocolDbId, outputName: {
            "id": 71,
            "objectId": 81,
            "setClassName": "SetOfParticles",
            "itemClassName": "Particle",
            "properties": {
                "postgresqlNativeOutput": True,
                "itemsCount": 5000,
                "maxItemId": 5000,
            },
        },
    )

    def failArtifactRead(*args, **kwargs):
        pytest.fail(
            "Native PostgreSQL rows must be "
            "protected before artifact inspection."
        )

    for methodName in (
        "_getSetItemsCountHint",
        "_getSetMaxItemIdHint",
        "_getSetSourceMTime",
        "_iterSetItems",
        "_replaceStoredSetSnapshot",
    ):
        monkeypatch.setattr(
            setMapper,
            methodName,
            failArtifactRead,
        )

    def finalizeRuntimeSetOutput(**kwargs):
        finalized.append(
            kwargs
        )

        return {
            "setId": 71,
            "runtimeObjectId": 91,
            "outputName": (
                kwargs["outputName"]
            ),
        }

    monkeypatch.setattr(
        setMapper,
        "finalizeRuntimeSetOutput",
        finalizeRuntimeSetOutput,
    )

    outputSet = RunDbSetProjectionStub()

    result = setMapper.storeSet(
        projectId=7,
        protocolDbId=17,
        outputName="outputParticles",
        scipionSet=outputSet,
    )

    assert len(finalized) == 1

    assert finalized[0] == {
        "projectId": 7,
        "protocolDbId": 17,
        "outputName": "outputParticles",
        "scipionSet": outputSet,
    }

    assert result == {
        "setId": 71,
        "runtimeObjectId": 91,
        "outputName": "outputParticles",
    }





