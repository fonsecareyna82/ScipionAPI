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
from unittest.mock import Mock

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


class FakeDerivedComposite(FakeComposite):
    pass


class FakeObjectMapper:
    def __init__(
            self,
            rows=None,
            classRows=None,
            deleteResult=None,
    ):
        self.rows = list(rows or [])
        self.classRows = list(classRows or [])
        self.calls = []
        self.classCalls = []
        self.deleteCalls = []

        if deleteResult is None:
            deleteResult = {
                "deletedObjectsCount": 0,
                "deletedRelationsCount": 0,
            }

        self.deleteResult = dict(
            deleteResult
        )

    def getStoredObjectSubtreeByScipionObjId(
            self,
            projectId,
            scipionObjId,
    ):
        self.calls.append((
            projectId,
            scipionObjId,
        ))

        return list(self.rows)

    def listCanonicalStoredObjectRows(
            self,
            projectId,
            className=None,
    ):
        self.classCalls.append((
            projectId,
            className,
        ))

        return list(self.classRows)

    def deleteStoredObjectSubtreesByScipionObjId(
            self,
            projectId,
            scipionObjId,
    ):
        self.deleteCalls.append((
            projectId,
            scipionObjId,
        ))

        return dict(
            self.deleteResult
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


def buildRuntimeMapper(
        rows,
        classRows=None,
        deleteResult=None,
):
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 7
    mapper.project = None
    mapper.readFallbackMapper = None
    mapper.writeFallbackMapper = None
    mapper.flatMapper = Mock()
    mapper.flatMapper.getProtocols.return_value = []
    mapper.flatMapper.getProjectRuntimeMetadata.return_value = None
    mapper.flatMapper.getProjectProtocolByProtocolId.return_value = None

    mapper.protocolGraphRepository = Mock()
    mapper.protocolGraphRepository.listPersistedSetOutputRows.return_value = []
    mapper.protocolGraphRepository.getPersistedSetOutputRowByRuntimeObjectId.return_value = None

    mapper.runtimeSetFactory = Mock()
    mapper.runtimeSetFactory._getCachedRuntimeSet.return_value = None

    mapper._runtimeProtocolsById = {}
    mapper._sqliteProtocolMirrorIds = set()
    mapper._fallbackAuditEnabled = False
    mapper.dictClasses = {
        "FakeComposite": FakeComposite,
        "FakeDerivedComposite": FakeDerivedComposite,
    }

    mapper.objectMapper = FakeObjectMapper(
        rows=rows,
        classRows=classRows,
        deleteResult=deleteResult,
    )

    mapper.setMapper = Mock()

    mapper.setMapper.deleteStoredSetOutput.return_value = {
        "deletedSetsCount": 1,
        "deletedObjectsCount": 1,
        "deletedRelationsCount": 2,
    }

    def failIfRuntimeContextIsAttached(obj):
        raise AssertionError(
            "Generic PostgreSQL objects must remain detached"
        )

    mapper._attachRuntimeContext = failIfRuntimeContextIsAttached

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


def test_SelectByIdUsesGenericPostgresqlObjectBeforeFallback():
    mapper = buildRuntimeMapper(buildRows())

    mapper._selectProtocolByIdFromPostgresql = (
        lambda objId, refreshCached=True: None
    )

    mapper._selectSetByIdFromPostgresql = (
        lambda objId, refreshParentProtocol=True: None
    )

    def failIfFallbackIsUsed(objId, auditOperation="selectById"):
        raise AssertionError(
            "SQLite fallback must not be used"
        )

    mapper._selectByIdFromReadFallback = failIfFallbackIsUsed

    result = mapper.selectById("700")

    assert isinstance(result, FakeComposite)
    assert result.getObjId() == 700
    assert result.getObjParentId() == 101
    assert result.title.get() == "PostgreSQL object"
    assert result.count.get() == 5

    assert mapper.objectMapper.calls == [
        (
            7,
            700,
        ),
    ]


def test_ExistsUsesGenericPostgresqlObjectBeforeFallback():
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 7

    mapper.db = Mock()
    mapper.db.fetchOne.return_value = None

    mapper.runtimeSetFactory = Mock()
    mapper.runtimeSetFactory._getCachedRuntimeSet.return_value = None

    mapper.protocolGraphRepository = Mock()
    getSetOutput = (
        mapper.protocolGraphRepository
        .getPersistedSetOutputRowByRuntimeObjectId
    )
    getSetOutput.return_value = None

    mapper._resolveCanonicalScipionObjectRowId = Mock(
        return_value=10
    )

    mapper.readFallbackMapper = Mock()
    mapper.readFallbackMapper.exists.side_effect = AssertionError(
        "SQLite fallback must not be used"
    )

    mapper._recordReadFallback = Mock()

    assert mapper.exists("700") is True

    mapper._resolveCanonicalScipionObjectRowId.assert_called_once_with(
        700
    )

    mapper._recordReadFallback.assert_not_called()
    mapper.readFallbackMapper.exists.assert_not_called()


def test_SelectByClassUsesGenericPostgresqlObjectsBeforeFallback():
    classRows = [{
        "id": 10,
        "runtimeObjectId": "700",
        "className": "FakeComposite",
    }]

    mapper = buildRuntimeMapper(
        buildRows(),
        classRows=classRows,
    )

    result = mapper.selectByClass(
        FakeComposite,
        includeSubclasses=False,
        objectFilter=lambda obj: obj.count.get() == 5,
    )

    assert len(result) == 1
    assert isinstance(result[0], FakeComposite)
    assert result[0].getObjId() == 700
    assert result[0].getObjParentId() == 101
    assert result[0].title.get() == "PostgreSQL object"
    assert result[0].count.get() == 5

    assert mapper.objectMapper.classCalls == [
        (
            7,
            "FakeComposite",
        ),
    ]

    assert mapper.objectMapper.calls == [
        (
            7,
            700,
        ),
    ]

def test_SelectByClassReturnsIteratorForGenericObjects():
    classRows = [{
        "id": 10,
        "runtimeObjectId": 700,
        "className": "FakeComposite",
    }]

    mapper = buildRuntimeMapper(
        buildRows(),
        classRows=classRows,
    )

    result = mapper.selectByClass(
        "FakeComposite",
        includeSubclasses=False,
        iterate=True,
    )

    objects = list(result)

    assert len(objects) == 1
    assert isinstance(objects[0], FakeComposite)
    assert objects[0].getObjId() == 700


def test_GenericObjectClassRowsIncludeRegisteredSubclasses():
    classRows = [
        {
            "id": 10,
            "runtimeObjectId": 700,
            "className": "FakeComposite",
        },
        {
            "id": 20,
            "runtimeObjectId": 800,
            "className": "FakeDerivedComposite",
        },
        {
            "id": 30,
            "runtimeObjectId": 900,
            "className": "String",
        },
    ]

    mapper = buildRuntimeMapper(
        buildRows(),
        classRows=classRows,
    )

    rows = mapper._getPostgresqlGenericObjectRowsForClass(
        requestedClassName="FakeComposite",
        requestedClass=FakeComposite,
        includeSubclasses=True,
    )

    assert [
        row["runtimeObjectId"]
        for row in rows
    ] == [
        700,
        800,
    ]

    assert mapper.objectMapper.classCalls == [
        (
            7,
            None,
        ),
    ]


def test_SelectByClassMergesGenericPostgresqlAndFallbackObjects():
    classRows = [{
        "id": 10,
        "runtimeObjectId": 700,
        "className": "FakeComposite",
    }]

    mapper = buildRuntimeMapper(
        buildRows(),
        classRows=classRows,
    )

    postgresqlDuplicate = FakeComposite()
    postgresqlDuplicate.setObjId(700)

    fallbackOnly = FakeComposite()
    fallbackOnly.setObjId(900)

    mapper.readFallbackMapper = Mock()
    mapper.readFallbackMapper.selectByClass.return_value = [
        postgresqlDuplicate,
        fallbackOnly,
    ]

    mapper._attachRuntimeContext = lambda obj: obj
    mapper._recordReadFallback = Mock()

    result = mapper.selectByClass(
        FakeComposite,
        includeSubclasses=False,
    )

    assert [
        obj.getObjId()
        for obj in result
    ] == [
        700,
        900,
    ]

    mapper._recordReadFallback.assert_called_once_with(
        "selectByClass.genericCompatibilityMerge",
        className=FakeComposite,
        includeSubclasses=False,
        objectFilter=None,
    )

    mapper.readFallbackMapper.selectByClass.assert_called_once_with(
        FakeComposite,
        includeSubclasses=False,
        iterate=False,
        objectFilter=None,
    )


def test_SelectAllBatchIncludesGenericPostgresqlObjects():
    classRows = [{
        "id": 10,
        "runtimeObjectId": 700,
        "className": "FakeComposite",
    }]

    mapper = buildRuntimeMapper(
        buildRows(),
        classRows=classRows,
    )

    result = mapper.selectAllBatch()

    assert len(result) == 1
    assert isinstance(result[0], FakeComposite)
    assert result[0].getObjId() == 700
    assert result[0].getObjParentId() == 101
    assert result[0].title.get() == "PostgreSQL object"
    assert result[0].count.get() == 5

    assert mapper.objectMapper.classCalls == [
        (
            7,
            None,
        ),
    ]

    assert mapper.objectMapper.calls == [
        (
            7,
            700,
        ),
    ]

    mapper.flatMapper.getProtocols.assert_called_once_with(7)


def test_SelectAllBatchMergesGenericAndFallbackObjectsByRuntimeId():
    classRows = [{
        "id": 10,
        "runtimeObjectId": 700,
        "className": "FakeComposite",
    }]

    mapper = buildRuntimeMapper(
        buildRows(),
        classRows=classRows,
    )

    fallbackDuplicate = FakeComposite()
    fallbackDuplicate.setObjId(700)

    fallbackStaleClass = String()
    fallbackStaleClass.set("Fallback string")
    fallbackStaleClass.setObjId(700)

    fallbackOnly = FakeComposite()
    fallbackOnly.setObjId(900)

    mapper.readFallbackMapper = Mock()
    mapper.readFallbackMapper.selectAllBatch.return_value = [
        fallbackDuplicate,
        fallbackStaleClass,
        fallbackOnly,
    ]

    mapper._attachRuntimeContext = lambda obj: obj
    mapper._recordReadFallback = Mock()

    result = mapper.selectAllBatch()

    assert [
        (
            obj.getClassName(),
            obj.getObjId(),
        )
        for obj in result
    ] == [
        (
            "FakeComposite",
            700,
        ),
        (
            "FakeComposite",
            900,
        ),
    ]

    assert result[0] is not fallbackDuplicate
    assert result[0].title.get() == "PostgreSQL object"
    assert result[0] is not fallbackDuplicate
    assert result[0] is not fallbackStaleClass
    assert result[1] is fallbackOnly

    mapper._recordReadFallback.assert_called_once_with(
        "selectAllBatch.compatibilityMerge",
        objectFilter=None,
    )

    mapper.readFallbackMapper.selectAllBatch.assert_called_once_with(
        objectFilter=None,
    )


def test_SelectAllExcludesProtocolOwnedGenericObjects():
    classRows = [{
        "id": 10,
        "runtimeObjectId": 700,
        "className": "FakeComposite",
    }]

    mapper = buildRuntimeMapper(
        buildRows(),
        classRows=classRows,
    )

    result = mapper.selectAll()

    assert result == []

    assert mapper.objectMapper.calls == [
        (
            7,
            700,
        ),
    ]


def test_SelectAllIncludesParentlessGenericRoot():
    rows = buildRows()
    rows[0]["ownerProtocolId"] = None

    classRows = [{
        "id": 10,
        "runtimeObjectId": 700,
        "className": "FakeComposite",
    }]

    mapper = buildRuntimeMapper(
        rows,
        classRows=classRows,
    )

    result = mapper.selectAll(iterate=True)
    objects = list(result)

    assert len(objects) == 1
    assert isinstance(objects[0], FakeComposite)
    assert objects[0].getObjId() == 700
    assert objects[0].getObjParentId() is None


def test_SelectByMatchesGenericPostgresqlObjectFields():
    classRows = [{
        "id": 10,
        "runtimeObjectId": 700,
        "className": "FakeComposite",
    }]

    mapper = buildRuntimeMapper(
        buildRows(),
        classRows=classRows,
    )

    result = mapper.selectBy(
        name="outputObject",
        classname="FakeComposite",
        parent_id=101,
        label="Output label",
        comment="Output comment",
        creation="2026-07-15 12:30:45.123456",
    )

    assert len(result) == 1
    assert isinstance(result[0], FakeComposite)
    assert result[0].getObjId() == 700
    assert result[0].getObjParentId() == 101
    assert result[0].title.get() == "PostgreSQL object"
    assert result[0].count.get() == 5

    assert mapper.objectMapper.classCalls == [
        (
            7,
            None,
        ),
    ]

    assert mapper.objectMapper.calls == [
        (
            7,
            700,
        ),
    ]


def test_SelectByMatchesGenericPostgresqlScalarValue():
    rows = [{
        "id": 20,
        "scipionObjId": 800,
        "parentObjectId": None,
        "name": "message",
        "path": "message",
        "className": "String",
        "value": "PostgreSQL value",
        "label": "",
        "comment": "",
        "creation": None,
        "metadata": {
            "isPointer": False,
        },
        "ownerProtocolId": "101",
        "depth": 0,
    }]

    classRows = [{
        "id": 20,
        "runtimeObjectId": 800,
        "className": "String",
    }]

    mapper = buildRuntimeMapper(
        rows,
        classRows=classRows,
    )

    result = mapper.selectBy(
        name="message",
        classname="String",
        parent_id="101",
        value="PostgreSQL value",
    )

    assert len(result) == 1
    assert isinstance(result[0], String)
    assert result[0].getObjId() == 800
    assert result[0].getObjParentId() == 101
    assert result[0].get() == "PostgreSQL value"


def test_SelectByUsesGenericPostgresqlRuntimeIdWithoutFallback():
    mapper = buildRuntimeMapper(
        buildRows()
    )

    mapper.readFallbackMapper = Mock()
    mapper.readFallbackMapper.selectBy.side_effect = AssertionError(
        "SQLite fallback must not be used"
    )

    mapper._recordReadFallback = Mock()

    result = mapper.selectBy(
        id="700",
        classname="FakeComposite",
    )

    assert len(result) == 1
    assert isinstance(result[0], FakeComposite)
    assert result[0].getObjId() == 700

    staleResult = mapper.selectBy(
        id=700,
        classname="String",
    )

    assert staleResult == []

    mapper.readFallbackMapper.selectBy.assert_not_called()
    mapper._recordReadFallback.assert_not_called()


def test_SelectBySuppressesStaleFallbackForPostgresqlOwnedId():
    classRows = [{
        "id": 10,
        "runtimeObjectId": 700,
        "className": "FakeComposite",
    }]

    mapper = buildRuntimeMapper(
        buildRows(),
        classRows=classRows,
    )

    fallbackStaleClass = String()
    fallbackStaleClass.setObjId(700)

    fallbackOnly = String()
    fallbackOnly.setObjId(900)

    mapper.readFallbackMapper = Mock()
    mapper.readFallbackMapper.selectBy.return_value = [
        fallbackStaleClass,
        fallbackOnly,
    ]

    mapper._attachRuntimeContext = lambda obj: obj
    mapper._recordReadFallback = Mock()

    result = mapper.selectBy(
        classname="String",
    )

    assert len(result) == 1
    assert result[0] is fallbackOnly
    assert result[0].getObjId() == 900

    mapper._recordReadFallback.assert_called_once_with(
        "selectBy.compatibilityMerge",
        query={
            "classname": "String",
        },
        objectFilter=None,
    )

    mapper.readFallbackMapper.selectBy.assert_called_once_with(
        iterate=False,
        objectFilter=None,
        classname="String",
    )


def test_SelectByReturnsIteratorAndAppliesObjectFilter():
    classRows = [{
        "id": 10,
        "runtimeObjectId": 700,
        "className": "FakeComposite",
    }]

    mapper = buildRuntimeMapper(
        buildRows(),
        classRows=classRows,
    )

    result = mapper.selectBy(
        iterate=True,
        objectFilter=lambda obj: obj.count.get() == 5,
        name="outputObject",
    )

    objects = list(result)

    assert len(objects) == 1
    assert isinstance(objects[0], FakeComposite)
    assert objects[0].getObjId() == 700


def test_SelectByCollectorDoesNotRefreshCachedProtocolsOrSetParents():
    mapper = buildRuntimeMapper(
        [],
        classRows=[],
    )

    cachedProtocol = FakeComposite()
    cachedProtocol.setObjId(100)

    runtimeSet = FakeComposite()
    runtimeSet.setObjId(700)

    genericObject = FakeComposite()
    genericObject.setObjId(800)

    mapper._runtimeProtocolsById = {
        100: cachedProtocol,
    }

    mapper.flatMapper.getProtocols.return_value = [{
        "protocolId": "100",
    }]

    mapper._buildProtocolFromPostgresqlRow = Mock(
        side_effect=AssertionError(
            "Cached protocols must not be rebuilt or refreshed"
        )
    )

    mapper.protocolGraphRepository.listPersistedSetOutputRows.return_value = [{
        "runtimeObjectId": "700",
    }]

    mapper._selectSetByIdFromPostgresql = Mock(
        return_value=runtimeSet
    )

    mapper._selectAllGenericObjectsFromPostgresql = Mock(
        return_value=[
            genericObject,
        ]
    )

    mapper._selectProjectCreationTimeFromPostgresql = Mock(
        return_value=None
    )

    result = mapper._selectAllPostgresqlObjectsForSelectBy()

    assert [
        obj.getObjId()
        for obj in result
    ] == [
        100,
        700,
        800,
    ]

    mapper._selectSetByIdFromPostgresql.assert_called_once_with(
        700,
        refreshParentProtocol=False,
    )

    mapper._buildProtocolFromPostgresqlRow.assert_not_called()


def test_SelectByMergePreservesRuntimeObjectIdOrder():
    classRows = [{
        "id": 10,
        "runtimeObjectId": 700,
        "className": "FakeComposite",
    }]

    mapper = buildRuntimeMapper(
        buildRows(),
        classRows=classRows,
    )

    fallbackOnly = FakeComposite()
    fallbackOnly.setObjId(100)

    mapper.readFallbackMapper = Mock()
    mapper.readFallbackMapper.selectBy.return_value = [
        fallbackOnly,
    ]

    mapper._attachRuntimeContext = lambda obj: obj
    mapper._recordReadFallback = Mock()

    result = mapper.selectBy()

    assert [
        obj.getObjId()
        for obj in result
    ] == [
        100,
        700,
    ]

    assert result[0] is fallbackOnly
    assert isinstance(result[1], FakeComposite)
    assert result[1].title.get() == "PostgreSQL object"

    mapper.readFallbackMapper.selectBy.assert_called_once_with(
        iterate=False,
        objectFilter=None,
    )


def test_UpdateFromHydratesExistingGenericObjectFromPostgresql():
    mapper = buildRuntimeMapper(
        buildRows()
    )

    mapper.readFallbackMapper = Mock()
    mapper._recordReadFallback = Mock()

    targetObject = FakeComposite()
    targetObject.setObjId(700)

    mapper._setObjName(
        targetObject,
        "staleOutput",
    )

    targetObject.setObjLabel("Stale label")
    targetObject.setObjComment("Stale comment")
    targetObject.title.set("Stale title")
    targetObject.count.set(99)

    titleBeforeUpdate = targetObject.title
    countBeforeUpdate = targetObject.count

    ownerProtocol = Mock()
    targetObject._objParent = ownerProtocol

    result = mapper.updateFrom(
        targetObject
    )

    assert result is None

    assert targetObject.getObjId() == 700
    assert targetObject.getObjName() == "outputObject"
    assert targetObject.getObjParentId() == 101
    assert targetObject.getObjLabel() == "Output label"
    assert targetObject.getObjComment() == "Output comment"
    assert targetObject.getObjCreation() == (
        "2026-07-15 12:30:45.123456"
    )

    assert targetObject.title is titleBeforeUpdate
    assert targetObject.title.get() == "PostgreSQL object"
    assert targetObject.title.getObjId() == 701
    assert targetObject.title.getObjParentId() == 700
    assert targetObject.title._objParent is targetObject

    assert targetObject.count is countBeforeUpdate
    assert targetObject.count.get() == 5
    assert targetObject.count.getObjId() == 702
    assert targetObject.count.getObjParentId() == 700
    assert targetObject.count._objParent is targetObject

    assert targetObject._objParent is ownerProtocol
    assert ownerProtocol.mock_calls == []

    mapper.readFallbackMapper.updateFrom.assert_not_called()
    mapper._recordReadFallback.assert_not_called()

    assert mapper.objectMapper.calls == [
        (
            7,
            700,
        ),
    ]


def test_UpdateFromUsesFallbackWhenGenericObjectIsNotInPostgresql():
    mapper = buildRuntimeMapper(
        []
    )

    fallbackResult = object()

    mapper.readFallbackMapper = Mock()
    mapper.readFallbackMapper.updateFrom.return_value = (
        fallbackResult
    )

    mapper._recordReadFallback = Mock()

    targetObject = FakeComposite()
    targetObject.setObjId(700)

    result = mapper.updateFrom(
        targetObject
    )

    assert result is fallbackResult

    mapper._recordReadFallback.assert_called_once_with(
        "updateFrom",
        objectId=700,
        objectClass="FakeComposite",
    )

    mapper.readFallbackMapper.updateFrom.assert_called_once_with(
        targetObject
    )


def test_UpdateFromRaisesWhenObjectIsNotAvailableAnywhere():
    mapper = buildRuntimeMapper(
        []
    )

    targetObject = FakeComposite()
    targetObject.setObjId(700)

    try:
        mapper.updateFrom(targetObject)
    except NotImplementedError as error:
        assert str(error) == (
            "PostgreSQL updateFrom is only implemented "
            "for supported generic runtime objects."
        )
    else:
        raise AssertionError(
            "Expected updateFrom to raise NotImplementedError"
        )


def test_UpdateFromClearsStaleParentIdForParentlessGenericObject():
    rows = buildRows()
    rows[0]["ownerProtocolId"] = None
    rows[0]["rootParentScipionObjId"] = None

    mapper = buildRuntimeMapper(
        rows
    )

    mapper.readFallbackMapper = Mock()
    mapper._recordReadFallback = Mock()

    targetObject = FakeComposite()
    targetObject.setObjId(700)
    targetObject._objParentId = 999

    result = mapper.updateFrom(
        targetObject
    )

    assert result is None
    assert targetObject.getObjParentId() is None

    mapper.readFallbackMapper.updateFrom.assert_not_called()
    mapper._recordReadFallback.assert_not_called()

def test_DeleteRemovesGenericObjectTreeWithoutMutatingOwner():
    mapper = buildRuntimeMapper(
        buildRows(),
        deleteResult={
            "deletedObjectsCount": 3,
            "deletedRelationsCount": 2,
        },
    )

    mapper.writeFallbackMapper = Mock()

    targetObject = FakeComposite()
    targetObject.setObjId(700)

    ownerProtocol = Mock()
    ownerProtocol.outputObject = targetObject
    targetObject._objParent = ownerProtocol

    mapper.delete(
        targetObject
    )

    mapper.writeFallbackMapper.delete.assert_called_once_with(
        targetObject
    )

    assert mapper.objectMapper.deleteCalls == [
        (
            7,
            700,
        ),
    ]

    assert targetObject._objParent is ownerProtocol
    assert ownerProtocol.outputObject is targetObject
    assert ownerProtocol.mock_calls == []


def test_DeleteRemovesPersistedPostgresqlSetWithoutMutatingOwner():
    mapper = buildRuntimeMapper(
        []
    )

    mapper.writeFallbackMapper = Mock()

    mapper.protocolGraphRepository.getPersistedSetOutputRowByRuntimeObjectId.return_value = {
        "setId": 10,
        "objectId": 900,
        "runtimeObjectId": 700,
        "outputName": "outputSet",
    }

    runtimeSet = FakeComposite()
    runtimeSet.setObjId(700)

    ownerProtocol = Mock()
    ownerProtocol.outputSet = runtimeSet
    runtimeSet._objParent = ownerProtocol

    mapper._isSetLike = lambda obj: obj is runtimeSet

    mapper.delete(
        runtimeSet
    )

    mapper.writeFallbackMapper.delete.assert_called_once_with(
        runtimeSet
    )

    mapper.setMapper.deleteStoredSetOutput.assert_called_once_with(
        projectId=7,
        setId=10,
        objectId=900,
        runtimeObjectId=700,
    )

    mapper.runtimeSetFactory.evictRuntimeSet.assert_called_once_with(
        projectId=7,
        runtimeObjectId=700,
        runtimeSet=runtimeSet,
    )

    assert mapper.objectMapper.deleteCalls == []

    assert runtimeSet._objParent is ownerProtocol
    assert ownerProtocol.outputSet is runtimeSet
    assert ownerProtocol.mock_calls == []


def test_DeleteIgnoresUnstoredGenericObject():
    mapper = buildRuntimeMapper(
        []
    )

    mapper.writeFallbackMapper = Mock()

    targetObject = FakeComposite()

    mapper.delete(
        targetObject
    )

    mapper.writeFallbackMapper.delete.assert_not_called()
    assert mapper.objectMapper.deleteCalls == []


def test_DeleteUsesFallbackForNonPersistedSet():
    mapper = buildRuntimeMapper(
        []
    )

    mapper.writeFallbackMapper = Mock()

    mapper.protocolGraphRepository.getPersistedSetOutputRowByRuntimeObjectId.return_value = None

    runtimeSet = FakeComposite()
    runtimeSet.setObjId(700)

    mapper._isSetLike = lambda obj: obj is runtimeSet

    mapper.delete(
        runtimeSet
    )

    mapper.writeFallbackMapper.delete.assert_called_once_with(
        runtimeSet
    )

    assert mapper.objectMapper.deleteCalls == []


def test_DeleteDoesNotPartiallyDeleteUnsupportedObject():
    mapper = buildRuntimeMapper(
        []
    )

    mapper.writeFallbackMapper = Mock()

    unsupportedObject = Mock()
    unsupportedObject.getObjId.return_value = 700

    mapper._isSetLike = lambda obj: False
    mapper.protocolGraphRepository.getPersistedSetOutputRowByRuntimeObjectId.return_value = None

    mapper.delete(
        unsupportedObject
    )

    mapper.writeFallbackMapper.delete.assert_not_called()
    assert mapper.objectMapper.deleteCalls == []

def test_DeleteRejectsPersistedSetWithoutCanonicalIdentity():
    mapper = buildRuntimeMapper(
        []
    )

    mapper.writeFallbackMapper = Mock()

    mapper.protocolGraphRepository.getPersistedSetOutputRowByRuntimeObjectId.return_value = {
        "setId": 10,
        "objectId": None,
        "runtimeObjectId": 700,
    }

    runtimeSet = FakeComposite()
    runtimeSet.setObjId(700)

    mapper._isSetLike = lambda obj: obj is runtimeSet

    try:
        mapper.delete(runtimeSet)
    except RuntimeError as error:
        assert str(error) == (
            "Persisted PostgreSQL Set 700 does not expose "
            "its set or canonical object identity."
        )
    else:
        raise AssertionError(
            "Expected incomplete persisted Set identity "
            "to raise RuntimeError"
        )

    mapper.writeFallbackMapper.delete.assert_not_called()
    mapper.setMapper.deleteStoredSetOutput.assert_not_called()
    mapper.runtimeSetFactory.evictRuntimeSet.assert_not_called()



