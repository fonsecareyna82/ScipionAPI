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

from app.backend.runtime.protocol_identity import ProtocolIdentityResolver
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


def test_RegisterOutputPreparesDetachedSetAsCanonicalObjectTree(
        monkeypatch,
):
    class RuntimeObjectStub:
        def __init__(
                self,
                objectId,
                attributes=None,
        ):
            self._objId = objectId
            self._objParentId = None
            self._attributes = list(attributes or [])

        def getObjId(self):
            return self._objId

        def setObjId(self, objectId):
            self._objId = objectId

        def getObjParentId(self):
            return self._objParentId

        def setObjParentId(self, parentObjectId):
            self._objParentId = parentObjectId

        def getAttributesToStore(self):
            return list(self._attributes)

    class DetachedSetStub(RuntimeObjectStub):
        def getClassName(self):
            return "SetOfParticles"

        def getFileName(self):
            return "Runs/000023_Test/extra/output.sqlite"

        def getSize(self):
            return 24

    childObject = RuntimeObjectStub(
        objectId=3_000_000_101
    )

    outputSet = DetachedSetStub(
        objectId=3_000_000_100,
        attributes=[
            (
                "_child",
                childObject,
            ),
        ],
    )

    class ProtocolStub:
        def getObjId(self):
            return 23

        def iterOutputAttributes(self):
            return [
                (
                    "outputParticles",
                    outputSet,
                ),
            ]

    class RuntimeMapperStub:
        def __init__(self):
            self.db = object()
            self.objectIds = iter([
                1_000_100,
                1_000_101,
            ])

        def allocateProjectObjectId(self, projectId):
            assert projectId == 7
            return next(self.objectIds)

    storeCalls = []

    class ObjectMapperStub:
        def __init__(self, db):
            self.db = db

        def getStoredObjectTree(
                self,
                projectId,
                protocolDbId,
                outputName,
        ):
            return []

        def _getAttributesToStore(
                self,
                runtimeObject,
        ):
            return runtimeObject.getAttributesToStore()

        def registerObjectTypeFromObject(
                self,
                *args,
                **kwargs,
        ):
            return {}

        def storeObjectTree(
                self,
                **kwargs,
        ):
            storeCalls.append(kwargs)

            return {
                "rootObjectId": 81,
                "storedObjectsCount": 2,
            }

        def mergeStoredObjectMetadata(
                self,
                **kwargs,
        ):
            return 1

    class SetMapperStub:
        def __init__(self, db):
            self.db = db

        def isPostgresqlNativeSetOutput(
                self,
                projectId,
                protocolDbId,
                outputName,
        ):
            return False

        def storeSet(self, **kwargs):
            pytest.fail(
                "A detached Set must not use flat Set persistence."
            )

    monkeypatch.setattr(
        backendMapperModule,
        "ScipionObjectPostgresqlMapper",
        ObjectMapperStub,
    )

    monkeypatch.setattr(
        backendMapperModule,
        "ScipionSetPostgresqlMapper",
        SetMapperStub,
    )

    service = RuntimeProtocolOutputPersistenceService()

    monkeypatch.setattr(
        service,
        "resolveProtocolDbIdForOutputPersistence",
        lambda **kwargs: 17,
    )

    def failSetArtifactOpen(**kwargs):
        raise FileNotFoundError(
            "missing output.sqlite"
        )

    monkeypatch.setattr(
        service,
        "_openRelativeSetMapperForPersistence",
        failSetArtifactOpen,
    )

    report = service.registerOutput(
        projectId=7,
        protocol=ProtocolStub(),
        mapper=RuntimeMapperStub(),
        returnReport=True,
        allowDetachedSetOutputs=True,
    )

    assert len(storeCalls) == 1

    assert storeCalls[0]["scipionObjectIdsByPath"] == {
        "outputParticles": 1_000_100,
        "outputParticles._child": 1_000_101,
    }

    assert storeCalls[0]["includeNestedProperties"] is True

    assert report["errors"] == []
    assert report["skipped"] == []

    assert len(report["persisted"]) == 1
    assert report["persisted"][0]["mapperKind"] == "detached_set"
    assert report["persisted"][0]["artifactMissing"] is True

    assert outputSet.getObjId() == 3_000_000_100
    assert childObject.getObjId() == 3_000_000_101


def test_RegisterOutputDoesNotRetryTreePersistenceAfterInternalTypeError(
        monkeypatch,
):
    class RuntimeObjectStub:
        def __init__(self, objectId):
            self._objId = objectId
            self._objParentId = None

        def getObjId(self):
            return self._objId

        def setObjId(self, objectId):
            self._objId = objectId

        def getObjParentId(self):
            return self._objParentId

        def setObjParentId(self, parentObjectId):
            self._objParentId = parentObjectId

        def getAttributesToStore(self):
            return []

        def getClassName(self):
            return "Volume"

    outputObject = RuntimeObjectStub(
        objectId=3_000_000_200
    )

    class ProtocolStub:
        def getObjId(self):
            return 23

        def iterOutputAttributes(self):
            return [
                (
                    "outputVolume",
                    outputObject,
                ),
            ]

    class RuntimeMapperStub:
        def __init__(self):
            self.db = object()

        def allocateProjectObjectId(self, projectId):
            assert projectId == 7
            return 1_000_200

    storeCalls = []

    class ObjectMapperStub:
        def __init__(self, db):
            self.db = db

        def getStoredObjectTree(
                self,
                projectId,
                protocolDbId,
                outputName,
        ):
            return []

        def _getAttributesToStore(
                self,
                runtimeObject,
        ):
            return runtimeObject.getAttributesToStore()

        def storeObjectTree(self, **kwargs):
            storeCalls.append(kwargs)
            raise TypeError(
                "internal tree serialization failure"
            )

    class SetMapperStub:
        def __init__(self, db):
            self.db = db

    monkeypatch.setattr(
        backendMapperModule,
        "ScipionObjectPostgresqlMapper",
        ObjectMapperStub,
    )

    monkeypatch.setattr(
        backendMapperModule,
        "ScipionSetPostgresqlMapper",
        SetMapperStub,
    )

    service = RuntimeProtocolOutputPersistenceService()

    monkeypatch.setattr(
        service,
        "resolveProtocolDbIdForOutputPersistence",
        lambda **kwargs: 17,
    )

    monkeypatch.setattr(
        service,
        "isScipionSetLikeOutput",
        lambda outputObj: False,
    )

    monkeypatch.setattr(
        service,
        "isPersistableNonSetOutput",
        lambda outputObj: True,
    )

    report = service.registerOutput(
        projectId=7,
        protocol=ProtocolStub(),
        mapper=RuntimeMapperStub(),
        returnReport=True,
    )

    assert len(storeCalls) == 1

    assert storeCalls[0]["registerType"] is True
    assert storeCalls[0]["includeNestedProperties"] is True
    assert storeCalls[0]["scipionObjectIdsByPath"] == {
        "outputVolume": 1_000_200,
    }

    assert report["persisted"] == []
    assert len(report["errors"]) == 1

    assert outputObject.getObjId() == 3_000_000_200


def test_StrictScipionProtocolIdentityNeverFallsBackToPostgresqlDbId():
    class ProtocolStub:
        def getObjId(self):
            return 31

    class IdentityMapperStub:
        def __init__(self):
            self.scipionLookups = []
            self.dbLookups = []

        def getProjectProtocolByProtocolId(self, projectId, protocolId):
            self.scipionLookups.append({
                "projectId": projectId,
                "protocolId": protocolId,
            })
            return None

        def getProjectProtocolByDbId(self, projectId, protocolDbId):
            self.dbLookups.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return {
                "id": 31,
                "protocolId": "99",
            }

    mapper = IdentityMapperStub()
    resolver = ProtocolIdentityResolver(mapper=mapper, projectId=7)

    assert resolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(31) is None
    assert mapper.dbLookups == []

    assert resolver.resolveProtocolDbIdsFromProtocols([ProtocolStub()]) == {
        "protocolIds": ["31"],
        "protocolDbIds": [],
        "missingProtocolIds": ["31"],
    }
    assert mapper.dbLookups == []

    assert resolver.resolvePostgresqlProtocolDbId(31) == 31
    assert mapper.dbLookups == [
        {
            "projectId": 7,
            "protocolDbId": 31,
        },
    ]


def test_OutputPersistenceScipionProtocolIdNeverFallsBackToPostgresqlDbId():
    class ProtocolStub:
        def getObjId(self):
            return 31

    class IdentityMapperStub:
        def __init__(self):
            self.db = object()
            self.scipionLookups = []
            self.dbLookups = []

        def getProjectProtocolByProtocolId(self, projectId, protocolId):
            self.scipionLookups.append({
                "projectId": projectId,
                "protocolId": protocolId,
            })
            return None

        def getProjectProtocolByDbId(self, projectId, protocolDbId):
            self.dbLookups.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return {
                "id": 31,
                "protocolId": "99",
            }

    mapper = IdentityMapperStub()
    service = RuntimeProtocolOutputPersistenceService()

    assert service.resolveProtocolDbIdForOutputPersistence(
        mapper=mapper,
        projectId=7,
        protocol=ProtocolStub(),
    ) is None

    assert mapper.scipionLookups == [
        {
            "projectId": 7,
            "protocolId": "31",
        },
    ]
    assert mapper.dbLookups == []


def test_RuntimeProtocolOutputCleanupNeverFallsBackToPostgresqlDbId(
        monkeypatch,
):
    class ProtocolStub:
        def getObjId(self):
            return 31

    class IdentityMapperStub:
        def __init__(self):
            self.db = object()
            self.scipionLookups = []
            self.dbLookups = []

        def getProjectProtocolByProtocolId(self, projectId, protocolId):
            self.scipionLookups.append({
                "projectId": projectId,
                "protocolId": protocolId,
            })

            return None

        def getProjectProtocolByDbId(self, projectId, protocolDbId):
            self.dbLookups.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return {
                "id": 31,
                "protocolId": "99",
            }

    mapper = IdentityMapperStub()
    service = RuntimeProtocolOutputPersistenceService()
    protocol = ProtocolStub()

    monkeypatch.setattr(
        service,
        "collectPersistedProtocolOutputFiles",
        lambda **kwargs: pytest.fail(
            "Runtime protocol cleanup must not fall back to protocols.id"
        ),
    )

    result = service.deletePersistedProtocolOutputs(
        mapper=mapper,
        projectId=7,
        protocolId=protocol.getObjId(),
        protocol=protocol,
    )

    assert result == {
        "protocolDbId": None,
        "setsDeleted": 0,
        "objectsDeleted": 0,
        "filesDeleted": 0,
        "filesSkipped": [],
        "fileErrors": [],
        "skipped": True,
        "reason": "protocol_not_found",
    }

    assert mapper.scipionLookups == [{
        "projectId": 7,
        "protocolId": "31",
    }]

    assert mapper.dbLookups == []


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


def test_ProtocolOutputFileReaderDelegatesRows(monkeypatch):
    mapper = FakeMapper()
    service = RuntimeProtocolOutputPersistenceService()
    readCalls = []

    class ObjectMapperStub:
        def __init__(self, database):
            assert database is mapper.db

        def listProtocolOutputFileRows(self, projectId, protocolDbId):
            readCalls.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return [
                {
                    "file_name": " Runs/000010_Test/extra/output.sqlite ",
                },
                (
                    "Runs/000010_Test/extra/output.mrc",
                ),
                {
                    "file_name": "Runs/000010_Test/extra/output.sqlite",
                },
                {
                    "file_name": "",
                },
                (
                    None,
                ),
            ]

    monkeypatch.setattr(backendMapperModule, "ScipionObjectPostgresqlMapper", ObjectMapperStub)

    result = service.collectPersistedProtocolOutputFiles(
        mapper=mapper,
        projectId=7,
        protocolDbId=31,
    )

    assert result == [
        "Runs/000010_Test/extra/output.sqlite",
        "Runs/000010_Test/extra/output.mrc",
    ]

    assert readCalls == [
        {
            "projectId": 7,
            "protocolDbId": 31,
        },
    ]

    assert mapper.db.queries == []

    source = inspect.getsource(RuntimeProtocolOutputPersistenceService.collectPersistedProtocolOutputFiles)

    assert "objectMapper.listProtocolOutputFileRows(" in source
    assert ".db.transaction(" not in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source


def test_ProtocolOutputCleanupDelegatesMetadataDeletion(monkeypatch):
    mapper = FakeMapper()
    service = RuntimeProtocolOutputPersistenceService()
    metadataCalls = []
    fileReadCalls = []
    fileDeleteCalls = []

    class ObjectMapperStub:
        def __init__(self, database):
            assert database is mapper.db

        def deleteProtocolOutputMetadata(self, projectId, protocolDbId):
            metadataCalls.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return {
                "setsDeleted": 2,
                "objectsDeleted": 5,
            }

    def collectOutputFiles(**kwargs):
        fileReadCalls.append(kwargs)

        return [
            "Runs/000010_Test/extra/output.sqlite",
        ]

    def deleteOutputFiles(**kwargs):
        fileDeleteCalls.append(kwargs)

        return {
            "filesDeleted": 3,
            "filesSkipped": [
                {
                    "fileName": "outside.sqlite",
                    "reason": "outside_allowed_root",
                },
            ],
            "fileErrors": [],
        }

    monkeypatch.setattr(backendMapperModule, "ScipionObjectPostgresqlMapper", ObjectMapperStub)
    monkeypatch.setattr(outputPersistenceModule.ProtocolIdentityResolver,
                        "resolvePostgresqlProtocolDbIdFromScipionProtocolId", lambda self, protocolId: 31)
    monkeypatch.setattr(service, "collectPersistedProtocolOutputFiles", collectOutputFiles)
    monkeypatch.setattr(service, "deletePersistedProtocolOutputFilesFromFilesystem", deleteOutputFiles)

    protocol = object()

    result = service.deletePersistedProtocolOutputs(
        mapper=mapper,
        projectId=7,
        protocolId=19,
        protocol=protocol,
        getCurrentProjectPathCallback=None,
    )

    assert result == {
        "protocolDbId": 31,
        "setsDeleted": 2,
        "objectsDeleted": 5,
        "filesDeleted": 3,
        "filesSkipped": [
            {
                "fileName": "outside.sqlite",
                "reason": "outside_allowed_root",
            },
        ],
        "fileErrors": [],
        "skipped": False,
    }

    assert fileReadCalls == [
        {
            "mapper": mapper,
            "projectId": 7,
            "protocolDbId": 31,
        },
    ]

    assert fileDeleteCalls == [
        {
            "protocol": protocol,
            "rawFileNames": [
                "Runs/000010_Test/extra/output.sqlite",
            ],
            "getCurrentProjectPathCallback": None,
        },
    ]

    assert metadataCalls == [
        {
            "projectId": 7,
            "protocolDbId": 31,
        },
    ]

    assert mapper.db.queries == []

    source = inspect.getsource(RuntimeProtocolOutputPersistenceService.deletePersistedProtocolOutputs)

    assert "objectMapper.deleteProtocolOutputMetadata(" in source
    assert ".db.transaction(" not in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source


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





