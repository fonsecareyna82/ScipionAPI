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
import json
from types import SimpleNamespace

import app.backend.runtime.project_relation_sync_service as relationSyncModule

from app.backend.runtime.project_relation_sync_service import (
    RuntimeProjectRelationSyncService,
)
from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)
from pyworkflow.object import Object as ScipionObject


class FakeProtocol:
    def __init__(self, relations):
        self.relations = relations
        self.outputParticles = object()

    def getRelations(self):
        return list(self.relations)


class FakeOutput(ScipionObject):
    def __init__(self, objectId):
        super().__init__()
        self.setObjId(objectId)


class FakeRelationEndpoint:
    def __init__(
            self,
            producerProtocolId,
            objectName,
    ):
        self.producerProtocolId = (
            producerProtocolId
        )

        self.objectName = objectName

    def getObjParentId(self):
        return self.producerProtocolId

    def getObjName(self):
        return self.objectName


class FakeRelationMapper:
    def __init__(
            self,
            objectsById,
    ):
        self.objectsById = dict(
            objectsById
        )

    def selectById(
            self,
            objectId,
    ):
        return self.objectsById.get(
            int(objectId)
        )


class FinalOutputProtocol(FakeProtocol):
    def __init__(
            self,
            relations,
            outputs,
    ):
        super().__init__(
            relations
        )

        self.outputs = list(
            outputs
        )

    def isFinished(self):
        return True

    def iterOutputAttributes(self):
        return list(
            self.outputs
        )

def buildOutputObject(
        objectId,
        protocolDbId=200,
        protocolId="20",
        outputName=None,
):
    return {
        "objectId": int(
            objectId
        ) + 10000,
        "protocolDbId": (
            protocolDbId
        ),
        "protocolId": str(
            protocolId
        ),
        "outputName": (
            outputName
            or "output%s"
            % objectId
        ),
    }


class FakeRepository:
    def __init__(self, persistedObjects):
        self.persistedObjects = persistedObjects
        self.cleanupCalls = []
        self.insertCalls = []

    def getPersistedOutputObjectByRuntimeId(
            self,
            mapper,
            projectId,
            runtimeObjectId,
            extended=None,
    ):
        return self.persistedObjects.get(int(runtimeObjectId))

    def deleteImportedOutputRelationsForCreator(
            self,
            mapper,
            projectId,
            creatorProtocolDbId,
            creatorProtocolId,
    ):
        self.cleanupCalls.append({
            "projectId": projectId,
            "creatorProtocolDbId": creatorProtocolDbId,
            "creatorProtocolId": creatorProtocolId,
        })

        return {
            "relationsDeleted": 1,
        }

    def insertImportedOutputRelation(self, **kwargs):
        self.insertCalls.append(kwargs)

        return {
            "saved": True,
            "relationName": kwargs["relationName"],
        }

    def replaceImportedOutputRelationsForCreator(
            self,
            mapper,
            projectId,
            creatorProtocolDbId,
            creatorProtocolId,
            relations,
    ):
        cleanupReport = (
            self.deleteImportedOutputRelationsForCreator(
                mapper=mapper,
                projectId=projectId,
                creatorProtocolDbId=(
                    creatorProtocolDbId
                ),
                creatorProtocolId=creatorProtocolId,
            )
        )

        persistedRelations = []

        for relation in relations:
            result = self.insertImportedOutputRelation(
                mapper=mapper,
                projectId=projectId,
                creatorProtocolDbId=(
                    creatorProtocolDbId
                ),
                creatorProtocolId=relation[
                    "creatorProtocolId"
                ],
                relationName=relation[
                    "relationName"
                ],
                parentRuntimeObjectId=relation[
                    "parentRuntimeObjectId"
                ],
                childRuntimeObjectId=relation[
                    "childRuntimeObjectId"
                ],
                parentExtended=relation[
                    "parentExtended"
                ],
                childExtended=relation[
                    "childExtended"
                ],
                metadata=relation[
                    "metadata"
                ],
            )

            persistedRelations.append(
                result
            )

        return {
            "saved": True,
            "cleanup": cleanupReport,
            "relations": persistedRelations,
            "snapshotSynchronized": True,
        }


def buildRelation():
    return {
        "id": 7,
        "parent_id": 20,
        "name": "relation",
        "object_parent_id": 101,
        "object_child_id": 202,
        "object_parent_extended": "outputParticles",
        "object_child_extended": "outputClasses",
    }

def stripCollectedRelationEndpoints(relation):
    relation = dict(relation)
    relation.pop("_parentEndpoint", None)
    relation.pop("_childEndpoint", None)
    return relation


def test_SyncProjectRelationsReplacesProtocolSnapshotWithoutMutatingOutputs(
        monkeypatch,
):
    repository = FakeRepository({
        101: {
            "objectId": 1001,
            "protocolDbId": 200,
            "protocolId": "20",
            "outputName": "outputParticles",
        },
        202: {
            "objectId": 2002,
            "protocolDbId": 300,
            "protocolId": "30",
            "outputName": "outputClasses",
        },
    })

    monkeypatch.setattr(
        relationSyncModule,
        "ProtocolGraphRepository",
        lambda: repository,
    )

    protocol = FakeProtocol([buildRelation()])
    originalOutput = protocol.outputParticles

    report = RuntimeProjectRelationSyncService().syncProjectRelations(
        mapper=SimpleNamespace(),
        projectId=4,
        protocolsByScipionId={
            "20": protocol,
        },
        protocolDbIdByScipionId={
            "20": 200,
        },
    )

    assert report["relationsDeclared"] == 1
    assert report["relations"] == 1
    assert report["relationMissing"] == []
    assert report["relationErrors"] == []
    assert report["complete"] is True

    assert repository.cleanupCalls == [{
        "projectId": 4,
        "creatorProtocolDbId": 200,
        "creatorProtocolId": 20,
    }]

    assert len(repository.insertCalls) == 1

    insertCall = repository.insertCalls[0]

    assert insertCall["relationName"] == "relation"
    assert insertCall["parentRuntimeObjectId"] == 101
    assert insertCall["childRuntimeObjectId"] == 202
    assert insertCall["parentExtended"] == "outputParticles"
    assert insertCall["childExtended"] == "outputClasses"
    assert insertCall["metadata"] == {
        "source": "project_relation_sync",
        "sqliteRelationId": 7,
    }

    assert protocol.outputParticles is originalOutput


def test_SyncProjectRelationsPreservesSnapshotWhenOutputIsMissing(
        monkeypatch,
):
    repository = FakeRepository({
        101: {
            "objectId": 1001,
            "protocolDbId": 200,
            "protocolId": "20",
            "outputName": "outputParticles",
        },
    })

    monkeypatch.setattr(
        relationSyncModule,
        "ProtocolGraphRepository",
        lambda: repository,
    )

    report = RuntimeProjectRelationSyncService().syncProjectRelations(
        mapper=SimpleNamespace(),
        projectId=4,
        protocolsByScipionId={
            "20": FakeProtocol([buildRelation()]),
        },
        protocolDbIdByScipionId={
            "20": 200,
        },
    )

    assert report["relationsDeclared"] == 1
    assert report["relations"] == 0
    assert report["complete"] is False

    assert report["relationMissing"] == [{
        "relationId": 7,
        "relationName": "relation",
        "creatorProtocolId": 20,
        "parentRuntimeObjectId": 101,
        "childRuntimeObjectId": 202,
        "parentExtended": "outputParticles",
        "childExtended": "outputClasses",
        "reason": "child_output_not_found",
    }]

    assert repository.cleanupCalls == []
    assert repository.insertCalls == []


class FakeCursor:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(
            self,
            exceptionType,
            exceptionValue,
            traceback,
    ):
        return False


class FakeDb:
    def __init__(self):
        self.calls = []
        self.cursor = FakeCursor(
            0
        )

    def transaction(self):
        return FakeTransaction()

    def execute(
            self,
            query,
            params,
            commit=True,
    ):
        self.calls.append({
            "query": query,
            "params": params,
            "commit": commit,
        })

        self.cursor.rowcount = len(
            self.calls
        )

        return self.cursor


class AtomicRelationTransaction:
    def __init__(
            self,
            db,
    ):
        self.db = db
        self.snapshot = None

    def __enter__(self):
        self.snapshot = {
            "rows": list(
                self.db.rows
            ),
            "relationsSynchronized": (
                self.db.relationsSynchronized
            ),
        }

        self.db.transactionCalls += 1

        return self

    def __exit__(
            self,
            exceptionType,
            exceptionValue,
            traceback,
    ):
        if exceptionType is not None:
            self.db.rows = list(
                self.snapshot[
                    "rows"
                ]
            )

            self.db.relationsSynchronized = (
                self.snapshot[
                    "relationsSynchronized"
                ]
            )

            self.db.rollbackCalls += 1

            return False

        self.db.commitCalls += 1

        return False


class AtomicRelationDb:
    def __init__(
            self,
            markerRowcount=1,
    ):
        self.rows = [
            (
                "runtime",
                "old",
            ),
        ]
        self.relationsSynchronized = False
        self.markerRowcount = int(
            markerRowcount
        )

        self.calls = []
        self.cursor = FakeCursor(
            0
        )

        self.transactionCalls = 0
        self.commitCalls = 0
        self.rollbackCalls = 0

    def transaction(self):
        return AtomicRelationTransaction(
            self
        )

    def execute(
            self,
            query,
            params,
            commit=True,
    ):
        normalizedQuery = " ".join(
            str(query).split()
        )

        self.calls.append({
            "query": normalizedQuery,
            "params": params,
            "commit": commit,
        })

        if normalizedQuery.startswith(
                "DELETE FROM scipion_relations"
        ):
            previousCount = len(
                self.rows
            )

            self.rows = [
                row
                for row in self.rows
                if row[0] != "runtime"
            ]

            self.cursor.rowcount = (
                previousCount
                - len(
                    self.rows
                )
            )

            return self.cursor

        if normalizedQuery.startswith(
                "INSERT INTO scipion_relations"
        ):
            childRuntimeObjectId = int(
                params[4]
            )

            if childRuntimeObjectId == 303:
                raise RuntimeError(
                    "forced relation insert failure"
                )

            self.rows.append((
                "runtime",
                tuple(params),
            ))

            self.cursor.rowcount = 1

            return self.cursor

        if normalizedQuery.startswith(
                'UPDATE protocols SET "relationsSynchronized" = TRUE'
        ):
            self.cursor.rowcount = (
                self.markerRowcount
            )

            if self.markerRowcount == 1:
                self.relationsSynchronized = (
                    True
                )

            return self.cursor

        raise AssertionError(
            "Unexpected SQL: %s"
            % normalizedQuery
        )


def test_DeleteImportedOutputRelationsClearsAuthoritativeSnapshot():
    db = FakeDb()
    mapper = SimpleNamespace(
        db=db
    )

    report = (
        ProtocolGraphRepository()
        .deleteImportedOutputRelationsForCreator(
            mapper=mapper,
            projectId=4,
            creatorProtocolDbId=200,
            creatorProtocolId=20,
        )
    )

    assert len(db.calls) == 1

    assert (
        "DELETE FROM scipion_relations"
        in db.calls[0]["query"]
    )

    assert db.calls[0]["params"] == (
        4,
        20,
    )

    assert db.calls[0]["commit"] is False

    assert report == {
        "relationsDeleted": 1,
    }


def test_CollectProtocolRelationsMergesRuntimeAndFallbackSnapshots():
    firstRelation = buildRelation()

    secondRelation = {
        **buildRelation(),
        "id": 8,
        "name": "transform",
        "object_child_id": 303,
        "object_child_extended": "outputAverage",
    }

    runtimeProtocol = FakeProtocol([
        firstRelation,
    ])

    fallbackProtocol = FakeProtocol([
        firstRelation,
        secondRelation,
    ])

    service = RuntimeProjectRelationSyncService()

    result = service.collectProtocolRelations([
        (
            "runtime_db",
            runtimeProtocol,
        ),
        (
            "readFallbackMapper",
            fallbackProtocol,
        ),
    ])

    assert [
               stripCollectedRelationEndpoints(relation)
               for relation in result["relations"]
           ] == [
               firstRelation,
               secondRelation,
           ]

    assert all(
        "_parentEndpoint" in relation
        for relation in result["relations"]
    )

    assert all(
        "_childEndpoint" in relation
        for relation in result["relations"]
    )

    assert result["sources"] == [
        {
            "source": "runtime_db",
            "relations": 1,
        },
        {
            "source": "readFallbackMapper",
            "relations": 1,
        },
    ]

    assert result["errors"] == []


def test_SyncProjectRelationsUsesPreloadedRuntimeSnapshot(
        monkeypatch,
):
    repository = FakeRepository({
        101: {
            "objectId": 1001,
            "protocolDbId": 200,
            "protocolId": "20",
            "outputName": "outputParticles",
        },
        202: {
            "objectId": 2002,
            "protocolDbId": 300,
            "protocolId": "30",
            "outputName": "outputClasses",
        },
    })

    monkeypatch.setattr(
        relationSyncModule,
        "ProtocolGraphRepository",
        lambda: repository,
    )

    emptyFallbackProtocol = FakeProtocol([])

    report = RuntimeProjectRelationSyncService().syncProjectRelations(
        mapper=SimpleNamespace(),
        projectId=4,
        protocolsByScipionId={
            "20": emptyFallbackProtocol,
        },
        protocolDbIdByScipionId={
            "20": 200,
        },
        relationsByScipionId={
            "20": [
                buildRelation(),
            ],
        },
    )

    assert report["relationsDeclared"] == 1
    assert report["relations"] == 1
    assert report["relationMissing"] == []
    assert report["relationErrors"] == []
    assert len(repository.insertCalls) == 1


def test_CollectProtocolRelationsDeduplicatesLogicalRelationWithDifferentIds():
    runtimeRelation = {
        **buildRelation(),
        "id": 7,
        "object_child_extended": None,
    }

    fallbackRelation = {
        **runtimeRelation,
        "id": 8,
        "object_child_extended": "",
    }

    service = RuntimeProjectRelationSyncService()

    result = service.collectProtocolRelations([
        (
            "runtime_db",
            FakeProtocol([
                runtimeRelation,
            ]),
        ),
        (
            "readFallbackMapper",
            FakeProtocol([
                fallbackRelation,
            ]),
        ),
    ])

    assert [
               stripCollectedRelationEndpoints(relation)
               for relation in result["relations"]
           ] == [
               runtimeRelation,
           ]

    assert result["sources"] == [
        {
            "source": "runtime_db",
            "relations": 1,
        },
    ]

    assert result["errors"] == []


def test_CollectProtocolRelationsEnrichesDuplicateEndpointsFromFallback():
    relation = {
        "id": 1,
        "parent_id": 79,
        "name": "relation_datasource",
        "object_parent_id": 58,
        "object_child_id": 146,
        "object_parent_extended": "",
        "object_child_extended": None,
    }

    runtimeProtocol = FakeProtocol([
        relation,
    ])

    runtimeProtocol.mapper = FakeRelationMapper(
        {}
    )

    fallbackProtocol = FakeProtocol([
        relation,
    ])

    fallbackProtocol.mapper = FakeRelationMapper({
        58: FakeRelationEndpoint(
            producerProtocolId=2,
            objectName="2.outputParticles",
        ),
        146: FakeRelationEndpoint(
            producerProtocolId=79,
            objectName="79.outputCoordinates",
        ),
    })

    result = (
        RuntimeProjectRelationSyncService()
        .collectProtocolRelations([
            (
                "runtime_db",
                runtimeProtocol,
            ),
            (
                "project_sqlite_isolated",
                fallbackProtocol,
            ),
        ])
    )

    assert len(result["relations"]) == 1

    collectedRelation = result[
        "relations"
    ][0]

    assert collectedRelation[
        "_parentEndpoint"
    ] == {
        "runtimeObjectId": 58,
        "producerProtocolId": 2,
        "outputName": "outputParticles",
        "className": "FakeRelationEndpoint",
    }

    assert collectedRelation[
        "_childEndpoint"
    ] == {
        "runtimeObjectId": 146,
        "producerProtocolId": 79,
        "outputName": "outputCoordinates",
        "className": "FakeRelationEndpoint",
    }

    assert result["sources"] == [{
        "source": "runtime_db",
        "relations": 1,
    }]

    assert result["errors"] == []


def test_SyncProjectRelationsDeduplicatesLogicalRelationWithDifferentIds(
        monkeypatch,
):
    repository = FakeRepository({
        101: {
            "objectId": 1001,
            "protocolDbId": 200,
            "protocolId": "20",
            "outputName": "outputParticles",
        },
        202: {
            "objectId": 2002,
            "protocolDbId": 300,
            "protocolId": "30",
            "outputName": "outputClasses",
        },
    })

    monkeypatch.setattr(
        relationSyncModule,
        "ProtocolGraphRepository",
        lambda: repository,
    )

    firstRelation = {
        **buildRelation(),
        "id": 7,
        "object_child_extended": None,
    }

    duplicatedRelation = {
        **firstRelation,
        "id": 8,
        "object_child_extended": "",
    }

    report = RuntimeProjectRelationSyncService().syncProjectRelations(
        mapper=SimpleNamespace(),
        projectId=4,
        protocolsByScipionId={
            "20": FakeProtocol([
                firstRelation,
                duplicatedRelation,
            ]),
        },
        protocolDbIdByScipionId={
            "20": 200,
        },
    )

    assert report["relationsDeclared"] == 1
    assert report["relations"] == 1
    assert report["relationErrors"] == []
    assert report["complete"] is True

    assert len(
        repository.insertCalls
    ) == 1

    assert repository.insertCalls[0][
        "metadata"
    ] == {
        "source": "project_relation_sync",
        "sqliteRelationId": 7,
    }


def test_InsertImportedOutputRelationUsesIdempotentPostgresqlInserts():
    db = FakeDb()

    mapper = SimpleNamespace(
        db=db
    )

    repository = ProtocolGraphRepository()

    sourceParentRuntimeObjectId = (
        3_000_000_101
    )

    sourceChildRuntimeObjectId = (
        3_000_000_202
    )

    canonicalParentRuntimeObjectId = (
        1_000_101
    )

    canonicalChildRuntimeObjectId = (
        1_000_202
    )

    persistedObjects = {
        sourceParentRuntimeObjectId: {
            "objectId": 1001,
            "runtimeObjectId": (
                canonicalParentRuntimeObjectId
            ),
            "protocolDbId": 200,
            "protocolId": "20",
            "outputName": "outputParticles",
        },
        sourceChildRuntimeObjectId: {
            "objectId": 2002,
            "runtimeObjectId": (
                canonicalChildRuntimeObjectId
            ),
            "protocolDbId": 300,
            "protocolId": "30",
            "outputName": "outputClasses",
        },
    }

    repository.getPersistedOutputObjectByRuntimeId = (
        lambda **kwargs: persistedObjects.get(
            int(
                kwargs[
                    "runtimeObjectId"
                ]
            )
        )
    )

    result = (
        repository
        .insertImportedOutputRelation(
            mapper=mapper,
            projectId=4,
            creatorProtocolDbId=200,
            creatorProtocolId=20,
            relationName=(
                "relation_datasource"
            ),
            parentRuntimeObjectId=(
                sourceParentRuntimeObjectId
            ),
            childRuntimeObjectId=(
                sourceChildRuntimeObjectId
            ),
            parentExtended="TiltSeries",
            childExtended=None,
            metadata={
                "source": "test",
            },
        )
    )

    assert result["saved"] is True

    assert (
        result[
            "parentRuntimeObjectId"
        ]
        == canonicalParentRuntimeObjectId
    )

    assert (
        result[
            "childRuntimeObjectId"
        ]
        == canonicalChildRuntimeObjectId
    )

    assert (
        result[
            "sourceParentRuntimeObjectId"
        ]
        == sourceParentRuntimeObjectId
    )

    assert (
        result[
            "sourceChildRuntimeObjectId"
        ]
        == sourceChildRuntimeObjectId
    )

    assert len(db.calls) == 1

    relationCall = db.calls[0]

    normalizedQuery = " ".join(
        relationCall["query"].split()
    )

    assert (
            "ON CONFLICT ON CONSTRAINT "
            "ux_scipion_relations_unique_relation"
            in normalizedQuery
    )

    assert (
            "DO UPDATE SET "
            "metadata = EXCLUDED.metadata"
            in normalizedQuery
    )

    assert (
            "scipion_object_relations"
            not in normalizedQuery
    )

    relationParams = (
        relationCall["params"]
    )

    assert relationParams[0] == 4
    assert relationParams[1] == (
        "relation_datasource"
    )
    assert relationParams[2] == 20

    assert (
        relationParams[3]
        == canonicalParentRuntimeObjectId
    )

    assert (
        relationParams[4]
        == canonicalChildRuntimeObjectId
    )

    assert relationParams[5] == (
        "TiltSeries"
    )

    assert relationParams[6] == ""

    relationMetadata = json.loads(
        relationParams[7]
    )

    assert relationMetadata[
        "source"
    ] == "test"

    assert relationMetadata[
        "sourceParentRuntimeObjectId"
    ] == sourceParentRuntimeObjectId

    assert relationMetadata[
        "sourceChildRuntimeObjectId"
    ] == sourceChildRuntimeObjectId

    assert relationMetadata[
        "parentOutputName"
    ] == "outputParticles"

    assert relationMetadata[
        "childOutputName"
    ] == "outputClasses"


def test_ReplaceImportedOutputRelationsRollsBackCompleteSnapshotOnFailure():
    db = AtomicRelationDb()

    mapper = SimpleNamespace(
        db=db
    )

    repository = ProtocolGraphRepository()

    parentObject = {
        "objectId": 1001,
        "protocolDbId": 200,
        "protocolId": "20",
        "outputName": "outputParticles",
    }

    firstChildObject = {
        "objectId": 2002,
        "protocolDbId": 300,
        "protocolId": "30",
        "outputName": "outputClasses",
    }

    secondChildObject = {
        "objectId": 3003,
        "protocolDbId": 400,
        "protocolId": "40",
        "outputName": "outputAverage",
    }

    previousRows = list(
        db.rows
    )

    try:
        repository.replaceImportedOutputRelationsForCreator(
            mapper=mapper,
            projectId=4,
            creatorProtocolDbId=200,
            creatorProtocolId=20,
            relations=[
                {
                    "relationId": 7,
                    "relationName": (
                        "relation_datasource"
                    ),
                    "creatorProtocolId": 20,
                    "parentRuntimeObjectId": 101,
                    "childRuntimeObjectId": 202,
                    "parentExtended": (
                        "outputParticles"
                    ),
                    "childExtended": (
                        "outputClasses"
                    ),
                    "parentObject": parentObject,
                    "childObject": (
                        firstChildObject
                    ),
                    "metadata": {
                        "source": "test",
                    },
                },
                {
                    "relationId": 8,
                    "relationName": (
                        "relation_datasource"
                    ),
                    "creatorProtocolId": 20,
                    "parentRuntimeObjectId": 101,
                    "childRuntimeObjectId": 303,
                    "parentExtended": (
                        "outputParticles"
                    ),
                    "childExtended": (
                        "outputAverage"
                    ),
                    "parentObject": parentObject,
                    "childObject": (
                        secondChildObject
                    ),
                    "metadata": {
                        "source": "test",
                    },
                },
            ],
        )

    except RuntimeError as error:
        assert str(error) == (
            "forced relation insert failure"
        )

    else:
        raise AssertionError(
            "Expected relation replacement "
            "to fail"
        )

    assert db.rows == previousRows

    assert db.transactionCalls == 1
    assert db.commitCalls == 0
    assert db.rollbackCalls == 1

    assert all(
        call["commit"] is False
        for call in db.calls
    )


def test_ReplaceEmptyImportedOutputSnapshotMarksProtocolSynchronized():
    db = AtomicRelationDb()

    mapper = SimpleNamespace(
        db=db
    )

    result = (
        ProtocolGraphRepository()
        .replaceImportedOutputRelationsForCreator(
            mapper=mapper,
            projectId=4,
            creatorProtocolDbId=200,
            creatorProtocolId=20,
            relations=[],
        )
    )

    assert result == {
        "saved": True,
        "cleanup": {
            "relationsDeleted": 1,
        },
        "relations": [],
        "snapshotSynchronized": True,
    }

    assert db.rows == []
    assert db.relationsSynchronized is True

    assert db.transactionCalls == 1
    assert db.commitCalls == 1
    assert db.rollbackCalls == 0

    assert len(db.calls) == 2

    assert (
        db.calls[1]["query"]
        .startswith(
            'UPDATE protocols SET "relationsSynchronized" = TRUE'
        )
    )

    assert db.calls[1]["params"] == (
        4,
        200,
        "20",
    )

    assert all(
        call["commit"] is False
        for call in db.calls
    )


def test_ReplaceImportedOutputRelationsRollsBackWhenMarkerCannotBeStored():
    db = AtomicRelationDb(
        markerRowcount=0
    )

    mapper = SimpleNamespace(
        db=db
    )

    previousRows = list(
        db.rows
    )

    parentObject = {
        "objectId": 1001,
        "protocolDbId": 200,
        "protocolId": "20",
        "outputName": "outputParticles",
    }

    childObject = {
        "objectId": 2002,
        "protocolDbId": 300,
        "protocolId": "30",
        "outputName": "outputClasses",
    }

    try:
        (
            ProtocolGraphRepository()
            .replaceImportedOutputRelationsForCreator(
                mapper=mapper,
                projectId=4,
                creatorProtocolDbId=200,
                creatorProtocolId=20,
                relations=[{
                    "relationId": 7,
                    "relationName": (
                        "relation_datasource"
                    ),
                    "creatorProtocolId": 20,
                    "parentRuntimeObjectId": 101,
                    "childRuntimeObjectId": 202,
                    "parentExtended": (
                        "outputParticles"
                    ),
                    "childExtended": (
                        "outputClasses"
                    ),
                    "parentObject": parentObject,
                    "childObject": childObject,
                    "metadata": {
                        "source": "test",
                    },
                }],
            )
        )

    except RuntimeError as error:
        assert str(error) == (
            "Cannot mark relation snapshot as synchronized "
            "for protocol 20."
        )

    else:
        raise AssertionError(
            "Expected relation snapshot marker "
            "update to fail"
        )

    assert db.rows == previousRows

    assert (
        db.relationsSynchronized
        is False
    )

    assert db.transactionCalls == 1
    assert db.commitCalls == 0
    assert db.rollbackCalls == 1

    assert all(
        call["commit"] is False
        for call in db.calls
    )


def test_SyncProjectRelationsPrunesDeletedOutputGenerations(
        monkeypatch,
):
    oldRelations = [
        {
            "id": 1,
            "parent_id": 20,
            "name": "relation_transform",
            "object_parent_id": 10,
            "object_child_id": 101,
            "object_parent_extended": (
                "outputTiltSeries"
            ),
            "object_child_extended": None,
        },
        {
            "id": 2,
            "parent_id": 20,
            "name": "relation_datasource",
            "object_parent_id": 10,
            "object_child_id": 101,
            "object_parent_extended": (
                "outputTiltSeries"
            ),
            "object_child_extended": None,
        },
        {
            "id": 3,
            "parent_id": 20,
            "name": "relation_datasource",
            "object_parent_id": 10,
            "object_child_id": 102,
            "object_parent_extended": (
                "outputTiltSeries"
            ),
            "object_child_extended": None,
        },
        {
            "id": 4,
            "parent_id": 20,
            "name": "relation_datasource",
            "object_parent_id": 101,
            "object_child_id": 103,
            "object_parent_extended": None,
            "object_child_extended": None,
        },
        {
            "id": 5,
            "parent_id": 20,
            "name": "relation_datasource",
            "object_parent_id": 102,
            "object_child_id": 104,
            "object_parent_extended": None,
            "object_child_extended": None,
        },
    ]

    currentRelations = [
        {
            "id": 6,
            "parent_id": 20,
            "name": "relation_transform",
            "object_parent_id": 10,
            "object_child_id": 301,
            "object_parent_extended": (
                "outputTiltSeries"
            ),
            "object_child_extended": None,
        },
        {
            "id": 7,
            "parent_id": 20,
            "name": "relation_datasource",
            "object_parent_id": 10,
            "object_child_id": 301,
            "object_parent_extended": (
                "outputTiltSeries"
            ),
            "object_child_extended": None,
        },
        {
            "id": 8,
            "parent_id": 20,
            "name": "relation_datasource",
            "object_parent_id": 10,
            "object_child_id": 302,
            "object_parent_extended": (
                "outputTiltSeries"
            ),
            "object_child_extended": None,
        },
        {
            "id": 9,
            "parent_id": 20,
            "name": "relation_datasource",
            "object_parent_id": 301,
            "object_child_id": 303,
            "object_parent_extended": None,
            "object_child_extended": None,
        },
        {
            "id": 10,
            "parent_id": 20,
            "name": "relation_datasource",
            "object_parent_id": 302,
            "object_child_id": 304,
            "object_parent_extended": None,
            "object_child_extended": None,
        },
    ]

    persistedObjects = {
        objectId: buildOutputObject(
            objectId
        )
        for objectId in (
            10,
            101,
            102,
            103,
            104,
            301,
            302,
            303,
            304,
        )
    }

    repository = FakeRepository(
        persistedObjects
    )

    monkeypatch.setattr(
        relationSyncModule,
        "ProtocolGraphRepository",
        lambda: repository,
    )

    protocol = FinalOutputProtocol(
        relations=(
            oldRelations
            + currentRelations
        ),
        outputs=[
            (
                "outputTiltSeries",
                FakeOutput(
                    301
                ),
            ),
            (
                "outputCTFTomoSeries",
                FakeOutput(
                    302
                ),
            ),
            (
                "outputTomograms",
                FakeOutput(
                    303
                ),
            ),
            (
                "outputCoordinates",
                FakeOutput(
                    304
                ),
            ),
        ],
    )

    report = (
        RuntimeProjectRelationSyncService()
        .syncProjectRelations(
            mapper=SimpleNamespace(),
            projectId=4,
            protocolsByScipionId={
                "20": protocol,
            },
            protocolDbIdByScipionId={
                "20": 200,
            },
        )
    )

    assert report[
        "relationsDeclared"
    ] == 10

    assert report[
        "relationsStale"
    ] == 5

    assert [
        relation[
            "relationId"
        ]
        for relation in report[
            "staleRelations"
        ]
    ] == [
        1,
        2,
        3,
        4,
        5,
    ]

    assert report[
        "relations"
    ] == 5

    assert report[
        "relationMissing"
    ] == []

    assert report[
        "relationErrors"
    ] == []

    assert report[
        "complete"
    ] is True

    persistedRelationIds = [
        call[
            "metadata"
        ][
            "sqliteRelationId"
        ]
        for call in repository.insertCalls
    ]

    assert persistedRelationIds == [
        6,
        7,
        8,
        9,
        10,
    ]


def test_SyncProjectRelationsKeepsMissingCurrentOutputFatal(
        monkeypatch,
):
    relation = {
        "id": 7,
        "parent_id": 20,
        "name": "relation_datasource",
        "object_parent_id": 10,
        "object_child_id": 301,
        "object_parent_extended": (
            "outputTiltSeries"
        ),
        "object_child_extended": None,
    }

    repository = FakeRepository({
        10: buildOutputObject(
            10
        ),
    })

    monkeypatch.setattr(
        relationSyncModule,
        "ProtocolGraphRepository",
        lambda: repository,
    )

    protocol = FinalOutputProtocol(
        relations=[
            relation,
        ],
        outputs=[
            (
                "outputTomograms",
                FakeOutput(
                    301
                ),
            ),
        ],
    )

    report = (
        RuntimeProjectRelationSyncService()
        .syncProjectRelations(
            mapper=SimpleNamespace(),
            projectId=4,
            protocolsByScipionId={
                "20": protocol,
            },
            protocolDbIdByScipionId={
                "20": 200,
            },
        )
    )

    assert report[
        "relationsStale"
    ] == 0

    assert report[
        "relations"
    ] == 0

    assert report[
        "relationMissing"
    ] == [{
        "relationId": 7,
        "relationName": (
            "relation_datasource"
        ),
        "creatorProtocolId": 20,
        "parentRuntimeObjectId": 10,
        "childRuntimeObjectId": 301,
        "parentExtended": (
            "outputTiltSeries"
        ),
        "childExtended": None,
        "reason": (
            "child_output_not_found"
        ),
    }]

    assert report[
        "complete"
    ] is False

    assert repository.cleanupCalls == []
    assert repository.insertCalls == []






