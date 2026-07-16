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
    def __init__(
            self,
            rows=None,
            ownedCreatorIds=None,
    ):
        self.rows = list(
            rows or []
        )

        self.ownedCreatorIds = {
            int(
                creatorId
            )
            for creatorId
            in (
                ownedCreatorIds
                or []
            )
        }

        self.calls = []
        self.ownershipCalls = []

    def fetchAll(
            self,
            query,
            values,
    ):
        self.calls.append({
            "query": query,
            "values": values,
        })

        return list(
            self.rows
        )

    def fetchOne(
            self,
            query,
            values,
    ):
        self.ownershipCalls.append({
            "query": query,
            "values": values,
        })

        creatorId = int(
            values[1]
        )

        if creatorId in self.ownedCreatorIds:
            return {
                "owned": 1,
            }

        return None


class FakeFallbackMapper:
    def __init__(self):
        self.creatorRows = [{
            "id": 901,
            "parent_id": 101,
            "name": (
                "legacyCreatorRelation"
            ),
            "object_parent_id": 201,
            "object_child_id": 301,
            "object_parent_extended": None,
            "object_child_extended": None,
        }]

        self.nameRows = [{
            "id": 902,
            "parent_id": 901,
            "name": (
                "legacyNamedRelation"
            ),
            "object_parent_id": 202,
            "object_child_id": 302,
            "object_parent_extended": None,
            "object_child_extended": None,
        }]

        self.childObjects = [
            FakeObject(903),
        ]
        self.parentObjects = [
            FakeObject(904),
        ]

        self.creatorCalls = []
        self.nameCalls = []
        self.childCalls = []
        self.parentCalls = []

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

    def getRelationChilds(
            self,
            relationName,
            parentObj,
    ):
        self.childCalls.append((
            relationName,
            parentObj,
        ))

        return list(
            self.childObjects
        )

    def getRelationParents(
            self,
            relationName,
            childObj,
    ):
        self.parentCalls.append((
            relationName,
            childObj,
        ))

        return list(
            self.parentObjects
        )


def buildRuntimeMapper(
        rows=None,
        fallbackMapper=None,
        ownedCreatorIds=None,
):
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 7

    mapper.db = FakeDatabase(
        rows=rows,
        ownedCreatorIds=(
            ownedCreatorIds
        ),
    )

    mapper.readFallbackMapper = (
        fallbackMapper
    )

    mapper._fallbackAuditEnabled = False
    mapper._fallbackAuditCounts = {}
    mapper._fallbackAuditContexts = {}

    mapper._runtimeProtocolsById = {}
    mapper._sqliteProtocolMirrorIds = set()

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

def test_GetRelationsByCreatorDoesNotResurrectOwnedEmptySnapshot():
    fallbackMapper = FakeFallbackMapper()

    mapper = buildRuntimeMapper(
        rows=[],
        fallbackMapper=fallbackMapper,
        ownedCreatorIds={
            101,
        },
    )

    creator = FakeObject(
        101
    )

    result = mapper.getRelationsByCreator(
        creator
    )

    assert result == []

    assert fallbackMapper.creatorCalls == []

    assert len(
        mapper.db.ownershipCalls
    ) == 1

    ownershipCall = (
        mapper.db.ownershipCalls[0]
    )

    assert ownershipCall["values"] == (
        7,
        "101",
        7,
        101,
    )


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


def test_GetRelationsByNameFiltersRowsOwnedByPostgresql():
    fallbackMapper = FakeFallbackMapper()

    staleRelation = {
        "id": 910,
        "parent_id": 101,
        "name": "source",
        "object_parent_id": 201,
        "object_child_id": 301,
        "object_parent_extended": None,
        "object_child_extended": None,
    }

    compatibilityRelation = {
        "id": 911,
        "parent_id": 999,
        "name": "source",
        "object_parent_id": 202,
        "object_child_id": 302,
        "object_parent_extended": None,
        "object_child_extended": None,
    }

    fallbackMapper.nameRows = [
        staleRelation,
        compatibilityRelation,
    ]

    mapper = buildRuntimeMapper(
        rows=[],
        fallbackMapper=fallbackMapper,
        ownedCreatorIds={
            101,
        },
    )

    result = mapper.getRelationsByName(
        "source"
    )

    assert result == [
        compatibilityRelation,
    ]

    assert fallbackMapper.nameCalls == [
        "source",
    ]


def test_GetRelationChildsUsesPostgresqlBeforeFallback():
    postgresqlRows = [
        {
            "object_child_id": 301,
        },
        {
            "object_child_id": 302,
        },
    ]

    fallbackMapper = FakeFallbackMapper()

    mapper = buildRuntimeMapper(
        rows=postgresqlRows,
        fallbackMapper=fallbackMapper,
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

    assert fallbackMapper.childCalls == []

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


def test_GetRelationParentsUsesPostgresqlBeforeFallback():
    postgresqlRows = [
        {
            "object_parent_id": 401,
        },
        {
            "object_parent_id": 402,
        },
    ]

    fallbackMapper = FakeFallbackMapper()

    mapper = buildRuntimeMapper(
        rows=postgresqlRows,
        fallbackMapper=fallbackMapper,
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

    assert fallbackMapper.parentCalls == []

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


def test_GetRelationChildsUsesCompatibilityRelationRowsWhenPostgresqlIsEmpty():
    fallbackMapper = FakeFallbackMapper()

    fallbackMapper.nameRows = [{
        "id": 920,
        "parent_id": 999,
        "name": "legacyRelation",
        "object_parent_id": 201,
        "object_child_id": 903,
        "object_parent_extended": None,
        "object_child_extended": None,
    }]

    mapper = buildRuntimeMapper(
        rows=[],
        fallbackMapper=fallbackMapper,
    )

    selectedIds = []

    def selectRelationObjectById(
            objId,
    ):
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
        "legacyRelation",
        parentObj,
    )

    assert [
        obj.getObjId()
        for obj in result
    ] == [
        903,
    ]

    assert selectedIds == [
        903,
    ]

    assert fallbackMapper.nameCalls == [
        "legacyRelation",
    ]

    assert fallbackMapper.childCalls == []


def test_GetRelationParentsUsesCompatibilityRelationRowsWhenPostgresqlIsEmpty():
    fallbackMapper = FakeFallbackMapper()

    fallbackMapper.nameRows = [{
        "id": 921,
        "parent_id": 999,
        "name": "legacyRelation",
        "object_parent_id": 904,
        "object_child_id": 501,
        "object_parent_extended": None,
        "object_child_extended": None,
    }]

    mapper = buildRuntimeMapper(
        rows=[],
        fallbackMapper=fallbackMapper,
    )

    selectedIds = []

    def selectRelationObjectById(
            objId,
    ):
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
        "legacyRelation",
        childObj,
    )

    assert [
        obj.getObjId()
        for obj in result
    ] == [
        904,
    ]

    assert selectedIds == [
        904,
    ]

    assert fallbackMapper.nameCalls == [
        "legacyRelation",
    ]

    assert fallbackMapper.parentCalls == []


def test_GetRelationChildsDoesNotResurrectOwnedFallbackRelation():
    fallbackMapper = FakeFallbackMapper()

    fallbackMapper.nameRows = [{
        "id": 930,
        "parent_id": 101,
        "name": "source",
        "object_parent_id": 201,
        "object_child_id": 903,
        "object_parent_extended": None,
        "object_child_extended": None,
    }]

    mapper = buildRuntimeMapper(
        rows=[],
        fallbackMapper=fallbackMapper,
        ownedCreatorIds={
            101,
        },
    )

    selectedIds = []

    mapper._selectRelationObjectById = (
        lambda objId: selectedIds.append(
            objId
        )
    )

    result = mapper.getRelationChilds(
        "source",
        FakeObject(
            201
        ),
    )

    assert result == []
    assert selectedIds == []

    assert fallbackMapper.nameCalls == [
        "source",
    ]

def test_EmptyRelationObjectsWithoutFallbackReturnEmptyLists():
    mapper = buildRuntimeMapper(
        rows=[],
        fallbackMapper=None,
    )

    assert mapper.getRelationChilds(
        "missingRelation",
        FakeObject(201),
    ) == []

    assert mapper.getRelationParents(
        "missingRelation",
        FakeObject(501),
    ) == []


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
        fallbackMapper=None,
    )

    cachedProtocol = FakeObject(
        401
    )
    cachedProtocol.status = "running"

    mapper._runtimeProtocolsById[
        401
    ] = cachedProtocol

    mapper._sqliteProtocolMirrorIds.add(
        401
    )

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
        fallbackMapper=None,
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


def test_SelectRelationObjectFallbackKeepsObjectUnchanged():
    mapper = buildRuntimeMapper(
        rows=[],
        fallbackMapper=None,
    )

    fallbackObject = FakeObject(
        701
    )

    mapper._selectProtocolByIdFromPostgresql = (
        lambda objId, refreshCached=True: None
    )

    mapper._selectSetByIdFromPostgresql = (
        lambda objId, refreshParentProtocol=True: None
    )

    mapper._selectByIdFromReadFallback = (
        lambda objId, auditOperation="selectById":
        fallbackObject
    )

    def failIfRuntimeContextIsAttached(obj):
        raise AssertionError(
            "Fallback relation objects must remain unchanged"
        )

    mapper._attachRuntimeContext = (
        failIfRuntimeContextIsAttached
    )

    result = mapper._selectRelationObjectById(
        701
    )

    assert result is fallbackObject