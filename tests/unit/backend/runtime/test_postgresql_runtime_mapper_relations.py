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
from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class FakeObject:
    def __init__(self, objId):
        self._objId = objId

    def getObjId(self):
        return self._objId


class FakeDatabase:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.calls = []

    def fetchAll(self, query, values):
        self.calls.append({
            "query": query,
            "values": values,
        })

        return list(self.rows)


class FakeFallbackMapper:
    def __init__(self):
        self.creatorRows = [{
            "id": 901,
            "name": "legacyCreatorRelation",
        }]
        self.nameRows = [{
            "id": 902,
            "name": "legacyNamedRelation",
        }]

        self.creatorCalls = []
        self.nameCalls = []

    def getRelationsByCreator(self, creatorObj):
        self.creatorCalls.append(
            creatorObj
        )

        return list(
            self.creatorRows
        )

    def getRelationsByName(self, relationName):
        self.nameCalls.append(
            relationName
        )

        return list(
            self.nameRows
        )


def buildRuntimeMapper(
        rows=None,
        fallbackMapper=None,
):
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 7
    mapper.db = FakeDatabase(
        rows=rows,
    )
    mapper.readFallbackMapper = fallbackMapper

    mapper._fallbackAuditEnabled = False
    mapper._fallbackAuditCounts = {}
    mapper._fallbackAuditContexts = {}

    return mapper


def test_GetRelationsByCreatorUsesPostgresqlBeforeFallback():
    postgresqlRows = [{
        "id": 10,
        "parent_id": 101,
        "name": "source",
        "object_parent_id": 201,
        "object_child_id": 301,
        "object_parent_extended": None,
        "object_child_extended": None,
    }]

    fallbackMapper = FakeFallbackMapper()

    mapper = buildRuntimeMapper(
        rows=postgresqlRows,
        fallbackMapper=fallbackMapper,
    )

    creator = FakeObject(
        101
    )

    result = mapper.getRelationsByCreator(
        creator
    )

    assert result == postgresqlRows
    assert fallbackMapper.creatorCalls == []

    call = mapper.db.calls[0]

    assert call["values"] == (
        7,
        101,
    )

    assert (
        '"creatorObjId" = %s'
        in call["query"]
    )

    assert (
        '"creatorObjId" AS parent_id'
        in call["query"]
    )

    assert (
        '"parentObjId" AS object_parent_id'
        in call["query"]
    )

    assert (
        '"childObjId" AS object_child_id'
        in call["query"]
    )


def test_GetRelationsByCreatorFallsBackWhenPostgresqlIsEmpty():
    fallbackMapper = FakeFallbackMapper()

    mapper = buildRuntimeMapper(
        rows=[],
        fallbackMapper=fallbackMapper,
    )

    creator = FakeObject(
        101
    )

    result = mapper.getRelationsByCreator(
        creator
    )

    assert result == fallbackMapper.creatorRows
    assert fallbackMapper.creatorCalls == [
        creator,
    ]


def test_GetRelationsByNameUsesPostgresqlBeforeFallback():
    postgresqlRows = [{
        "id": 20,
        "parent_id": 102,
        "name": "transform",
        "object_parent_id": 202,
        "object_child_id": 302,
        "object_parent_extended": "outputA",
        "object_child_extended": "outputB",
    }]

    fallbackMapper = FakeFallbackMapper()

    mapper = buildRuntimeMapper(
        rows=postgresqlRows,
        fallbackMapper=fallbackMapper,
    )

    result = mapper.getRelationsByName(
        "transform"
    )

    assert result == postgresqlRows
    assert fallbackMapper.nameCalls == []

    call = mapper.db.calls[0]

    assert call["values"] == (
        7,
        "transform",
    )

    assert (
        'name = %s'
        in call["query"]
    )


def test_GetRelationsByNameFallsBackWhenPostgresqlIsEmpty():
    fallbackMapper = FakeFallbackMapper()

    mapper = buildRuntimeMapper(
        rows=[],
        fallbackMapper=fallbackMapper,
    )

    result = mapper.getRelationsByName(
        "legacyNamedRelation"
    )

    assert result == fallbackMapper.nameRows
    assert fallbackMapper.nameCalls == [
        "legacyNamedRelation",
    ]


def test_EmptyPostgresqlRelationsWithoutFallbackReturnsEmptyList():
    mapper = buildRuntimeMapper(
        rows=[],
        fallbackMapper=None,
    )

    result = mapper.getRelationsByName(
        "missingRelation"
    )

    assert result == []