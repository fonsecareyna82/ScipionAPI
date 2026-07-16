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
from types import SimpleNamespace

import app.backend.runtime.project_relation_sync_service as relationSyncModule

from app.backend.runtime.project_relation_sync_service import (
    RuntimeProjectRelationSyncService,
)
from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)


class FakeProtocol:
    def __init__(self, relations):
        self.relations = relations
        self.outputParticles = object()

    def getRelations(self):
        return list(self.relations)


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
            "legacyRelationsDeleted": 1,
            "canonicalRelationsDeleted": 1,
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

    def __exit__(self, excType, excValue, traceback):
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
    def __init__(self, db):
        self.db = db
        self.snapshot = None

    def __enter__(self):
        self.snapshot = list(
            self.db.rows
        )

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
                "legacy",
                "old",
            ),
            (
                "canonical",
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
                if row[0] != "legacy"
            ]

            self.cursor.rowcount = (
                previousCount
                - len(
                    self.rows
                )
            )

            return self.cursor

        if normalizedQuery.startswith(
                "DELETE FROM scipion_object_relations"
        ):
            previousCount = len(
                self.rows
            )

            self.rows = [
                row
                for row in self.rows
                if row[0] != "canonical"
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
                "legacy",
                tuple(
                    params
                ),
            ))

            self.cursor.rowcount = 1

            return self.cursor

        if normalizedQuery.startswith(
                "INSERT INTO scipion_object_relations"
        ):
            self.rows.append((
                "canonical",
                tuple(
                    params
                ),
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


def test_DeleteImportedOutputRelationsClearsBothRepresentations():
    db = FakeDb()
    mapper = SimpleNamespace(db=db)

    report = (
        ProtocolGraphRepository()
        .deleteImportedOutputRelationsForCreator(
            mapper=mapper,
            projectId=4,
            creatorProtocolDbId=200,
            creatorProtocolId=20,
        )
    )

    assert len(db.calls) == 2

    assert "DELETE FROM scipion_relations" in db.calls[0]["query"]
    assert db.calls[0]["params"] == (4, 20)
    assert db.calls[0]["commit"] is False

    assert "DELETE FROM scipion_object_relations" in db.calls[1]["query"]
    assert db.calls[1]["params"] == (4, "200")
    assert db.calls[1]["commit"] is False

    assert report == {
        "legacyRelationsDeleted": 1,
        "canonicalRelationsDeleted": 2,
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

    assert result["relations"] == [
        firstRelation,
        secondRelation,
    ]

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

    assert result["relations"] == [
        runtimeRelation,
    ]

    assert result["sources"] == [
        {
            "source": "runtime_db",
            "relations": 1,
        },
    ]

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

    persistedObjects = {
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
    }

    repository.getPersistedOutputObjectByRuntimeId = (
        lambda **kwargs: persistedObjects.get(
            int(
                kwargs["runtimeObjectId"]
            )
        )
    )

    result = repository.insertImportedOutputRelation(
        mapper=mapper,
        projectId=4,
        creatorProtocolDbId=200,
        creatorProtocolId=20,
        relationName="relation_datasource",
        parentRuntimeObjectId=101,
        childRuntimeObjectId=202,
        parentExtended="TiltSeries",
        childExtended=None,
        metadata={
            "source": "test",
        },
    )

    assert result["saved"] is True
    assert len(db.calls) == 2

    assert (
        "ON CONFLICT DO NOTHING"
        in db.calls[0]["query"]
    )

    assert (
        "ON CONFLICT DO NOTHING"
        in db.calls[1]["query"]
    )


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
            "legacyRelationsDeleted": 1,
            "canonicalRelationsDeleted": 1,
        },
        "relations": [],
        "snapshotSynchronized": True,
    }

    assert db.rows == []
    assert db.relationsSynchronized is True

    assert db.transactionCalls == 1
    assert db.commitCalls == 1
    assert db.rollbackCalls == 0

    assert len(db.calls) == 3

    assert (
        db.calls[2]["query"]
        .startswith(
            'UPDATE protocols SET "relationsSynchronized" = TRUE'
        )
    )

    assert db.calls[2]["params"] == (
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



