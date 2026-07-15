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
from datetime import datetime

from pyworkflow.object import (
    Integer,
    Object,
    Pointer,
    String,
)

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class FakeComposite(Object):
    def __init__(self):
        super().__init__()

        self.title = String()
        self.count = Integer()


class FakeObjectMapper:
    def __init__(self, rows=None):
        self.rows = list(
            rows or []
        )
        self.calls = []

    def getStoredObjectSubtreeByScipionObjId(
            self,
            projectId,
            scipionObjId,
    ):
        self.calls.append((
            projectId,
            scipionObjId,
        ))

        return list(
            self.rows
        )


def buildRows():
    return [
        {
            "id": 10,
            "scipionObjId": 700,
            "parentObjectId": None,
            "name": "outputObject",
            "path": "outputObject",
            "className": "FakeComposite",
            "value": None,
            "label": "Output label",
            "comment": "Output comment",
            "creation": datetime(
                2026,
                7,
                15,
                12,
                30,
                45,
                123456,
            ),
            "metadata": {
                "isPointer": False,
            },
            "ownerProtocolId": "101",
            "depth": 0,
        },
        {
            "id": 11,
            "scipionObjId": 701,
            "parentObjectId": 10,
            "name": "title",
            "path": "outputObject.title",
            "className": "String",
            "value": "PostgreSQL object",
            "label": None,
            "comment": None,
            "creation": None,
            "metadata": {
                "isPointer": False,
            },
            "ownerProtocolId": "101",
            "depth": 1,
        },
        {
            "id": 12,
            "scipionObjId": 702,
            "parentObjectId": 10,
            "name": "count",
            "path": "outputObject.count",
            "className": "Integer",
            "value": "5",
            "label": None,
            "comment": None,
            "creation": None,
            "metadata": {
                "isPointer": False,
            },
            "ownerProtocolId": "101",
            "depth": 1,
        },
    ]


def buildRuntimeMapper(rows):
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 7
    mapper.project = None
    mapper.dictClasses = {
        "FakeComposite": FakeComposite,
    }

    mapper.objectMapper = FakeObjectMapper(
        rows=rows,
    )

    def failIfRuntimeContextIsAttached(obj):
        raise AssertionError(
            "Generic PostgreSQL objects must remain detached"
        )

    mapper._attachRuntimeContext = (
        failIfRuntimeContextIsAttached
    )

    return mapper


def test_SelectGenericObjectHydratesDetachedTree():
    mapper = buildRuntimeMapper(
        buildRows()
    )

    result = (
        mapper
        ._selectGenericObjectByIdFromPostgresql(
            "700"
        )
    )

    assert isinstance(
        result,
        FakeComposite,
    )

    assert result.getObjId() == 700
    assert result.getObjParentId() == 101
    assert result.getObjName() == (
        "outputObject"
    )

    assert result.getObjLabel() == (
        "Output label"
    )

    assert result.getObjComment() == (
        "Output comment"
    )

    assert result.getObjCreation() == (
        "2026-07-15 12:30:45.123456"
    )

    assert result.title.get() == (
        "PostgreSQL object"
    )
    assert result.title.getObjId() == 701
    assert result.title.getObjParentId() == 700
    assert result.title._objParent is result

    assert result.count.get() == 5
    assert result.count.getObjId() == 702
    assert result.count.getObjParentId() == 700
    assert result.count._objParent is result

    assert mapper.objectMapper.calls == [
        (
            7,
            700,
        ),
    ]


def test_SelectGenericObjectRejectsUnknownClass():
    rows = buildRows()
    rows[0]["className"] = (
        "MissingObjectClass"
    )

    mapper = buildRuntimeMapper(
        rows
    )

    result = (
        mapper
        ._selectGenericObjectByIdFromPostgresql(
            700
        )
    )

    assert result is None


def test_SelectGenericObjectRejectsPointerTree():
    rows = buildRows()

    rows.append({
        "id": 13,
        "scipionObjId": 703,
        "parentObjectId": 10,
        "name": "target",
        "path": "outputObject.target",
        "className": "Pointer",
        "value": "900",
        "label": None,
        "comment": None,
        "creation": None,
        "metadata": {
            "isPointer": True,
        },
        "ownerProtocolId": "101",
        "depth": 1,
    })

    mapper = buildRuntimeMapper(
        rows
    )

    result = (
        mapper
        ._selectGenericObjectByIdFromPostgresql(
            700
        )
    )

    assert result is None


def test_RelationResolverUsesGenericPostgresqlObject():
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    genericObject = FakeComposite()
    genericCalls = []

    mapper._selectProtocolByIdFromPostgresql = (
        lambda objId, refreshCached=True: None
    )

    mapper._selectSetByIdFromPostgresql = (
        lambda objId, refreshParentProtocol=True: None
    )

    def selectGenericObject(objId):
        genericCalls.append(
            objId
        )

        return genericObject

    mapper._selectGenericObjectByIdFromPostgresql = (
        selectGenericObject
    )

    def failIfFallbackIsUsed(
            objId,
            auditOperation="selectById",
    ):
        raise AssertionError(
            "SQLite fallback must not be used"
        )

    mapper._selectByIdFromReadFallback = (
        failIfFallbackIsUsed
    )

    result = mapper._selectRelationObjectById(
        700
    )

    assert result is genericObject

    assert genericCalls == [
        700,
    ]


def test_SelectGenericNestedRootPreservesDirectParentId():
    rows = [{
        "id": 11,
        "scipionObjId": 701,
        "parentObjectId": 10,
        "rootParentScipionObjId": 700,
        "name": "title",
        "path": "outputObject.title",
        "className": "String",
        "value": "Nested value",
        "label": None,
        "comment": None,
        "creation": None,
        "metadata": {
            "isPointer": False,
        },
        "ownerProtocolId": "101",
        "depth": 0,
    }]

    mapper = buildRuntimeMapper(rows)

    result = mapper._selectGenericObjectByIdFromPostgresql(701)

    assert isinstance(result, String)
    assert result.get() == "Nested value"
    assert result.getObjId() == 701
    assert result.getObjParentId() == 700


def test_RelationResolverPrefersSetBeforeGenericObject():
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    runtimeSet = object()
    setCalls = []

    mapper._selectProtocolByIdFromPostgresql = (
        lambda objId, refreshCached=True: None
    )

    def selectSet(objId, refreshParentProtocol=True):
        setCalls.append((
            objId,
            refreshParentProtocol,
        ))

        return runtimeSet

    mapper._selectSetByIdFromPostgresql = selectSet

    def failIfGenericReaderIsUsed(objId):
        raise AssertionError(
            "Set reader must run before generic object reader"
        )

    mapper._selectGenericObjectByIdFromPostgresql = (
        failIfGenericReaderIsUsed
    )

    def failIfFallbackIsUsed(
            objId,
            auditOperation="selectById",
    ):
        raise AssertionError(
            "SQLite fallback must not be used"
        )

    mapper._selectByIdFromReadFallback = failIfFallbackIsUsed

    result = mapper._selectRelationObjectById(700)

    assert result is runtimeSet
    assert setCalls == [
        (
            700,
            False,
        ),
    ]