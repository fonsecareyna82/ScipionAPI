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
from pyworkflow.object import Object

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class FakeDb:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.calls = []

    def fetchAll(self, query, params):
        self.calls.append({
            "query": query,
            "params": params,
        })

        return list(self.rows)


class FakeFlatMapper:
    def __init__(self, rows=None):
        self.db = FakeDb(rows)

    def getProjectProtocolByProtocolId(
            self,
            projectId,
            protocolId,
    ):
        return None


class FakeFallbackMapper:
    def __init__(
            self,
            relationsByCreator=None,
            relationsByName=None,
            childs=None,
            parents=None,
    ):
        self.relationsByCreator = list(
            relationsByCreator or []
        )

        self.relationsByName = list(
            relationsByName or []
        )

        self.childs = list(
            childs or []
        )

        self.parents = list(
            parents or []
        )

        self.calls = []

    def getRelationsByCreator(self, creatorObj):
        self.calls.append(
            (
                "getRelationsByCreator",
                creatorObj,
            )
        )

        return list(
            self.relationsByCreator
        )

    def getRelationsByName(self, relationName):
        self.calls.append(
            (
                "getRelationsByName",
                relationName,
            )
        )

        return list(
            self.relationsByName
        )

    def getRelationChilds(self, relationName, parentObj):
        self.calls.append(
            (
                "getRelationChilds",
                relationName,
                parentObj,
            )
        )

        return list(
            self.childs
        )

    def getRelationParents(self, relationName, childObj):
        self.calls.append(
            (
                "getRelationParents",
                relationName,
                childObj,
            )
        )

        return list(
            self.parents
        )


def buildObject(objId):
    obj = Object()
    obj.setObjId(objId)

    return obj


def buildMapper(
        rows=None,
        fallback=None,
):
    flatMapper = FakeFlatMapper(rows)

    mapper = PostgresqlRuntimeMapper(
        flatMapper=flatMapper,
        projectId=4,
        dictClasses={},
        readFallbackMapper=fallback,
    )

    return mapper, flatMapper.db


def buildRelationRow():
    return {
        "id": 7,
        "projectId": 4,
        "name": "transform",
        "creatorObjId": 20,
        "parentObjId": 101,
        "childObjId": 202,
        "parentExtended": "outputParticles",
        "childExtended": "outputClasses",
    }


def test_GetRelationsByCreatorUsesPostgresqlBeforeFallback():
    fallback = FakeFallbackMapper(
        relationsByCreator=[
            {
                "id": 99,
            },
        ]
    )

    mapper, db = buildMapper(
        rows=[
            buildRelationRow(),
        ],
        fallback=fallback,
    )

    creator = buildObject(20)

    relations = mapper.getRelationsByCreator(
        creator
    )

    assert len(relations) == 1

    relation = relations[0]

    assert relation["creatorObjId"] == 20
    assert relation["parentObjId"] == 101
    assert relation["childObjId"] == 202

    assert relation["parent_id"] == 20
    assert relation["object_parent_id"] == 101
    assert relation["object_child_id"] == 202

    assert relation["object_parent_extended"] == (
        "outputParticles"
    )

    assert relation["object_child_extended"] == (
        "outputClasses"
    )

    assert relation["classname"] is None
    assert relation["value"] is None
    assert relation["label"] is None
    assert relation["comment"] is None
    assert relation["creation"] is None

    assert fallback.calls == []

    assert len(db.calls) == 1
    assert '"creatorObjId" = %s' in db.calls[0]["query"]
    assert db.calls[0]["params"] == (4, 20)


def test_GetRelationsByNameFallsBackWhenPostgresqlIsEmpty():
    fallbackRelations = [
        {
            "id": 8,
            "name": "source",
        },
    ]

    fallback = FakeFallbackMapper(
        relationsByName=fallbackRelations
    )

    mapper, db = buildMapper(
        rows=[],
        fallback=fallback,
    )

    relations = mapper.getRelationsByName(
        "source"
    )

    assert relations == fallbackRelations

    assert fallback.calls == [
        (
            "getRelationsByName",
            "source",
        ),
    ]

    assert len(db.calls) == 1
    assert "name = %s" in db.calls[0]["query"]
    assert db.calls[0]["params"] == (4, "source")


def test_GetRelationChildsReconstructsPostgresqlObjects():
    mapper, db = buildMapper(
        rows=[
            {
                "runtimeObjectId": 202,
            },
        ],
    )

    parent = buildObject(101)
    child = buildObject(202)

    originalOutput = object()
    parent.outputParticles = originalOutput

    selectedIds = []

    def selectById(objId):
        selectedIds.append(objId)

        if objId == 202:
            return child

        return None

    mapper.selectById = selectById

    result = mapper.getRelationChilds(
        "transform",
        parent,
    )

    assert result == [
        child,
    ]

    assert selectedIds == [
        202,
    ]

    assert parent.outputParticles is originalOutput

    assert len(db.calls) == 1
    assert '"parentObjId" = %s' in db.calls[0]["query"]
    assert '"childObjId" AS "runtimeObjectId"' in (
        db.calls[0]["query"]
    )

    assert db.calls[0]["params"] == (
        4,
        "transform",
        101,
    )


def test_GetRelationParentsReconstructsPostgresqlObjects():
    mapper, db = buildMapper(
        rows=[
            {
                "runtimeObjectId": 101,
            },
        ],
    )

    parent = buildObject(101)
    child = buildObject(202)

    mapper.selectById = (
        lambda objId: parent
        if objId == 101
        else None
    )

    result = mapper.getRelationParents(
        "transform",
        child,
    )

    assert result == [
        parent,
    ]

    assert len(db.calls) == 1
    assert '"childObjId" = %s' in db.calls[0]["query"]
    assert '"parentObjId" AS "runtimeObjectId"' in (
        db.calls[0]["query"]
    )

    assert db.calls[0]["params"] == (
        4,
        "transform",
        202,
    )


def test_GetRelationChildsMergesFallbackForUnresolvedObjects():
    resolvedChild = buildObject(202)
    fallbackChild = buildObject(303)

    fallback = FakeFallbackMapper(
        childs=[
            resolvedChild,
            fallbackChild,
        ]
    )

    mapper, db = buildMapper(
        rows=[
            {
                "runtimeObjectId": 202,
            },
            {
                "runtimeObjectId": 303,
            },
        ],
        fallback=fallback,
    )

    parent = buildObject(101)

    mapper.selectById = (
        lambda objId: resolvedChild
        if objId == 202
        else None
    )

    mapper._attachRuntimeContextList = (
        lambda objects: list(objects)
    )

    result = mapper.getRelationChilds(
        "transform",
        parent,
    )

    assert result == [
        resolvedChild,
        fallbackChild,
    ]

    assert fallback.calls == [
        (
            "getRelationChilds",
            "transform",
            parent,
        ),
    ]

    assert len(db.calls) == 1


def test_GetRelationChildsReturnsEmptyWithoutRowsOrFallback():
    mapper, db = buildMapper(
        rows=[],
    )

    parent = buildObject(101)

    result = mapper.getRelationChilds(
        "transform",
        parent,
    )

    assert result == []
    assert len(db.calls) == 1