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
        self.executeCalls = []

    def fetchAll(self, query, values):
        self.calls.append({
            "query": query,
            "values": values,
        })

        return list(self.rows)

    def execute(self, query, values, commit=True):
        self.executeCalls.append({
            "query": " ".join(str(query).split()),
            "values": values,
            "commit": commit,
        })


def buildRuntimeMapper(rows=None):
    mapper = PostgresqlRuntimeMapper.__new__(PostgresqlRuntimeMapper)

    mapper.projectId = 7
    mapper.db = FakeDatabase(rows=rows)
    mapper.writeFallbackMapper = None
    mapper._runtimeProtocolsById = {}

    return mapper


def test_GetRelationsByCreatorUsesOnlyPostgresql():
    postgresqlRows = [{
        "id": 10,
        "parent_id": 101,
        "name": "source",
        "object_parent_id": 201,
        "object_child_id": 301,
        "object_parent_extended": None,
        "object_child_extended": None,
    }]


    mapper = buildRuntimeMapper(
        rows=postgresqlRows,
    )

    creator = FakeObject(
        101
    )

    result = mapper.getRelationsByCreator(
        creator
    )

    assert result == postgresqlRows

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


def test_GetRelationsByCreatorReturnsEmptyWhenPostgresqlIsEmpty():

    mapper = buildRuntimeMapper(
        rows=[],
    )

    creator = FakeObject(101)

    result = mapper.getRelationsByCreator(creator)

    assert result == []


def test_GetRelationsByNameUsesOnlyPostgresql():
    postgresqlRows = [{
        "id": 20,
        "parent_id": 102,
        "name": "transform",
        "object_parent_id": 202,
        "object_child_id": 302,
        "object_parent_extended": "outputA",
        "object_child_extended": "outputB",
    }]

    mapper = buildRuntimeMapper(
        rows=postgresqlRows,
    )

    result = mapper.getRelationsByName(
        "transform"
    )

    assert result == postgresqlRows

    call = mapper.db.calls[0]

    assert call["values"] == (
        7,
        "transform",
    )

    assert (
        'name = %s'
        in call["query"]
    )


def test_GetRelationsByNameReturnsEmptyWhenPostgresqlIsEmpty():

    mapper = buildRuntimeMapper(
        rows=[],
    )

    result = mapper.getRelationsByName(
        "legacyNamedRelation"
    )

    assert result == []


def test_GetRelationChildsUsesOnlyPostgresqlRelations():
    postgresqlRows = [
        {
            "object_child_id": 301,
        },
        {
            "object_child_id": 302,
        },
    ]

    mapper = buildRuntimeMapper(
        rows=postgresqlRows,
    )

    selectedIds = []

    def selectRelationObjectById(objId):
        selectedIds.append(
            objId
        )

        return FakeObject(
            objId
        )

    mapper._selectRelationObjectById = (
        selectRelationObjectById
    )

    parentObj = FakeObject(
        201
    )

    result = mapper.getRelationChilds(
        "source",
        parentObj,
    )

    assert [
        obj.getObjId()
        for obj in result
    ] == [
        301,
        302,
    ]

    assert selectedIds == [
        301,
        302,
    ]

    call = mapper.db.calls[0]

    assert call["values"] == (
        7,
        "source",
        201,
    )

    assert (
        '"parentObjId" = %s'
        in call["query"]
    )


def test_GetRelationParentsUsesOnlyPostgresqlRelations():
    postgresqlRows = [
        {
            "object_parent_id": 401,
        },
        {
            "object_parent_id": 402,
        },
    ]

    mapper = buildRuntimeMapper(
        rows=postgresqlRows,
    )

    selectedIds = []

    def selectRelationObjectById(objId):
        selectedIds.append(
            objId
        )

        return FakeObject(
            objId
        )

    mapper._selectRelationObjectById = (
        selectRelationObjectById
    )

    childObj = FakeObject(
        501
    )

    result = mapper.getRelationParents(
        "source",
        childObj,
    )

    assert [
        obj.getObjId()
        for obj in result
    ] == [
        401,
        402,
    ]

    assert selectedIds == [
        401,
        402,
    ]

    call = mapper.db.calls[0]

    assert call["values"] == (
        7,
        "source",
        501,
    )

    assert (
        '"childObjId" = %s'
        in call["query"]
    )


def test_GetRelationChildsReturnsEmptyWhenPostgresqlIsEmpty():

    mapper = buildRuntimeMapper(
        rows=[],
    )

    selectedIds = []
    mapper._selectRelationObjectById = lambda objId: selectedIds.append(objId)

    result = mapper.getRelationChilds(
        "legacyRelation",
        FakeObject(201),
    )

    assert result == []
    assert selectedIds == []


def test_GetRelationParentsReturnsEmptyWhenPostgresqlIsEmpty():

    mapper = buildRuntimeMapper(
        rows=[],
    )

    selectedIds = []
    mapper._selectRelationObjectById = lambda objId: selectedIds.append(objId)

    result = mapper.getRelationParents(
        "legacyRelation",
        FakeObject(501),
    )

    assert result == []
    assert selectedIds == []


class FakeFlatMapper:
    def __init__(self, protocolRow=None):
        self.protocolRow = protocolRow

    def getProjectProtocolByProtocolId(
            self,
            projectId,
            protocolId,
    ):
        if self.protocolRow is None:
            return None

        return dict(
            self.protocolRow
        )


def test_SelectRelationObjectKeepsCachedProtocolUnchanged():
    mapper = buildRuntimeMapper(
        rows=[],
    )

    cachedProtocol = FakeObject(
        401
    )
    cachedProtocol.status = "running"

    mapper._runtimeProtocolsById[
        401
    ] = cachedProtocol

    mapper.flatMapper = FakeFlatMapper({
        "protocolId": "401",
        "status": "finished",
        "params": {
            "someParam": {
                "value": "changed",
            },
        },
    })

    def failIfProtocolIsRefreshed(row):
        raise AssertionError(
            "Cached parent protocol must not be refreshed "
            "during relation resolution"
        )

    mapper._getOrBuildProtocolFromPostgresqlRow = (
        failIfProtocolIsRefreshed
    )

    result = mapper._selectRelationObjectById(
        401
    )

    assert result is cachedProtocol
    assert cachedProtocol.status == "running"


def test_SelectRelationSetDisablesParentProtocolRefresh():
    mapper = buildRuntimeMapper(
        rows=[],
    )

    protocolCalls = []
    setCalls = []

    def selectProtocol(
            objId,
            refreshCached=True,
    ):
        protocolCalls.append((
            objId,
            refreshCached,
        ))

        return None

    def selectSet(
            objId,
            refreshParentProtocol=True,
    ):
        setCalls.append((
            objId,
            refreshParentProtocol,
        ))

        return FakeObject(
            objId
        )

    mapper._selectProtocolByIdFromPostgresql = (
        selectProtocol
    )
    mapper._selectSetByIdFromPostgresql = (
        selectSet
    )

    def failIfGenericObjectIsSelected(objId):
        raise AssertionError(
            "Generic object lookup must not run after resolving a Set"
        )

    mapper._selectGenericObjectByIdFromPostgresql = (
        failIfGenericObjectIsSelected
    )

    result = mapper._selectRelationObjectById(
        301
    )

    assert result.getObjId() == 301

    assert protocolCalls == [
        (
            301,
            False,
        ),
    ]

    assert setCalls == [
        (
            301,
            False,
        ),
    ]


def test_SelectRelationObjectUsesGenericPostgresqlObject():
    mapper = buildRuntimeMapper(rows=[])

    protocolCalls = []
    setCalls = []
    genericCalls = []
    genericObject = FakeObject(701)

    def selectProtocol(objId, refreshCached=True):
        protocolCalls.append((
            objId,
            refreshCached,
        ))
        return None

    def selectSet(objId, refreshParentProtocol=True):
        setCalls.append((
            objId,
            refreshParentProtocol,
        ))
        return None

    def selectGenericObject(objId):
        genericCalls.append(objId)
        return genericObject

    mapper._selectProtocolByIdFromPostgresql = selectProtocol
    mapper._selectSetByIdFromPostgresql = selectSet
    mapper._selectGenericObjectByIdFromPostgresql = selectGenericObject

    result = mapper._selectRelationObjectById(701)

    assert result is genericObject

    assert protocolCalls == [
        (
            701,
            False,
        ),
    ]

    assert setCalls == [
        (
            701,
            False,
        ),
    ]

    assert genericCalls == [701]


def test_SelectRelationObjectReturnsNoneForMissingObject():
    mapper = buildRuntimeMapper(rows=[])

    mapper._selectProtocolByIdFromPostgresql = (
        lambda objId, refreshCached=True: None
    )

    mapper._selectSetByIdFromPostgresql = (
        lambda objId, refreshParentProtocol=True: None
    )

    genericCalls = []

    def selectGenericObject(objId):
        genericCalls.append(objId)
        return None

    mapper._selectGenericObjectByIdFromPostgresql = selectGenericObject
    result = mapper._selectRelationObjectById(701)

    assert result is None
    assert genericCalls == [701]


def test_InsertRelationDataWritesOnlyRuntimeRelationTable():
    mapper = buildRuntimeMapper()

    mapper.insertRelationData(
        relName="source",
        creatorId=101,
        parentId=201,
        childId=301,
        parentExtended="outputParent",
        childExtended="outputChild",
    )

    assert len(mapper.db.executeCalls) == 1

    call = mapper.db.executeCalls[0]

    assert call["query"].startswith(
        "INSERT INTO scipion_relations"
    )

    assert call["values"] == (
        7,
        "source",
        101,
        201,
        301,
        "outputParent",
        "outputChild",
    )

    assert "scipion_object_relations" not in call["query"]


def test_DeleteRelationsDeletesOnlyRuntimeRelations():
    mapper = buildRuntimeMapper()
    creator = FakeObject(101)

    mapper.deleteRelations(creator)

    assert len(mapper.db.executeCalls) == 1

    call = mapper.db.executeCalls[0]

    assert call["query"].startswith(
        "DELETE FROM scipion_relations"
    )

    assert call["values"] == (
        7,
        101,
    )

    assert "scipion_object_relations" not in call["query"]


