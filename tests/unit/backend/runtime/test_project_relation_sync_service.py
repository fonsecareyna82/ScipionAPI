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
        return self

    def __exit__(self, excType, excValue, traceback):
        return False


class FakeDb:
    def __init__(self):
        self.calls = []

    def transaction(self):
        return FakeTransaction()

    def execute(self, query, params, commit=True):
        self.calls.append({
            "query": query,
            "params": params,
            "commit": commit,
        })

        return FakeCursor(len(self.calls))


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