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
import pytest
from datetime import datetime
from unittest.mock import Mock

from pyworkflow.object import (
    CsvList,
    Float,
    Integer,
    Object,
    Pointer,
    String,
)

from pwem.objects import Volume

from app.backend.mapper.scipion_object_mapper import (
    ScipionObjectPostgresqlMapper,
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


def test_ObjectTreePersistenceExcludesRuntimeParentReference():
    outputObject = FakeComposite()
    parentObject = FakeComposite()

    outputObject._objParent = parentObject

    mapper = ScipionObjectPostgresqlMapper.__new__(
        ScipionObjectPostgresqlMapper
    )

    attributes = mapper._getAttributesToStore(
        outputObject
    )

    attributeNames = {
        name
        for name, _ in attributes
    }

    assert "title" in attributeNames
    assert "count" in attributeNames
    assert "_objParent" not in attributeNames


def test_ObjectPointerReferencePreservesBaseTargetAndExtended():
    mapper = ScipionObjectPostgresqlMapper.__new__(
        ScipionObjectPostgresqlMapper
    )

    parentProtocol = Object()
    parentProtocol.setObjId(101)
    parentProtocol.setObjName("protocol")

    pointer = Pointer(
        parentProtocol,
        extended="outputParticles",
    )

    reference = mapper._serializePointerReference(
        pointer
    )

    assert reference == {
        "version": 1,
        "kind": "pointer",
        "targetObjectId": 101,
        "targetClassName": "Object",
        "targetObjectName": "protocol",
        "targetParentObjectId": None,
        "targetParentClassName": None,
        "extended": "outputParticles",
        "uniqueId": "101.outputParticles",
    }


def test_ObjectPointerReferencePreservesDirectTargetParentIdentity():
    mapper = ScipionObjectPostgresqlMapper.__new__(
        ScipionObjectPostgresqlMapper
    )

    targetSet = Object()
    targetSet.setObjId(300)

    targetObject = Object()
    targetObject.setObjId(7)
    targetObject._objParent = targetSet
    targetObject._objParentId = 300

    pointer = Pointer(
        targetObject
    )

    reference = mapper._serializePointerReference(
        pointer
    )

    assert reference["targetObjectId"] == 7
    assert reference["targetClassName"] == "Object"
    assert reference["targetParentObjectId"] == 300
    assert reference["targetParentClassName"] == "Object"
    assert reference["extended"] == ""


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


def test_SelectRuntimeInputVolumeIgnoresLegacyParentReference():
    rows = [
        {
            "id": 10,
            "scipionObjId": 700,
            "parentObjectId": None,
            "name": "outputVolume",
            "path": "outputVolume",
            "className": "Volume",
            "value": None,
            "label": "Output volume",
            "comment": None,
            "creation": None,
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
            "name": "_filename",
            "path": "outputVolume._filename",
            "className": "String",
            "value": "/tmp/output-volume.mrc",
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
            "name": "_samplingRate",
            "path": "outputVolume._samplingRate",
            "className": "Float",
            "value": "1.5",
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
            "id": 13,
            "scipionObjId": 703,
            "parentObjectId": 10,
            "name": "_halfMapFilenames",
            "path": "outputVolume._halfMapFilenames",
            "className": "CsvList",
            "value": (
                "/tmp/half-map-1.mrc,"
                "/tmp/half-map-2.mrc"
            ),
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
            "id": 14,
            "scipionObjId": 704,
            "parentObjectId": 10,
            "name": "_sourcePointer",
            "path": (
                "outputVolume."
                "_sourcePointer"
            ),
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
        },
        {
            "id": 15,
            "scipionObjId": 705,
            "parentObjectId": 14,
            "name": "_extended",
            "path": (
                "outputVolume."
                "_sourcePointer._extended"
            ),
            "className": "String",
            "value": "outputParticles",
            "label": None,
            "comment": None,
            "creation": None,
            "metadata": {
                "isPointer": False,
            },
            "ownerProtocolId": "101",
            "depth": 2,
        },
        {
            "id": 16,
            "scipionObjId": 706,
            "parentObjectId": 10,
            "name": "_pluginRuntimeState",
            "path": (
                "outputVolume."
                "_pluginRuntimeState"
            ),
            "className": (
                "MissingPluginRuntimeState"
            ),
            "value": None,
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
            "id": 20,
            "scipionObjId": 101,
            "parentObjectId": 10,
            "name": "_objParent",
            "path": "outputVolume._objParent",
            "className": (
                "ProtCryosparcNonUniformRefine"
            ),
            "value": None,
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
            "id": 21,
            "scipionObjId": 704,
            "parentObjectId": 20,
            "name": "status",
            "path": (
                "outputVolume."
                "_objParent.status"
            ),
            "className": "String",
            "value": "finished",
            "label": None,
            "comment": None,
            "creation": None,
            "metadata": {
                "isPointer": False,
            },
            "ownerProtocolId": "101",
            "depth": 2,
        },
    ]

    mapper = buildRuntimeMapper(rows)

    mapper.dictClasses.update({
        "Volume": Volume,
        "CsvList": CsvList,
        "Float": Float,
    })

    mapper._selectSetByIdFromPostgresql = (
        lambda *args, **kwargs: None
    )

    result = (
        mapper
        .selectRuntimeInputObjectById(
            700
        )
    )

    assert isinstance(result, Volume)

    assert result.getObjId() == 700
    assert result.getObjParentId() == 101

    assert result.getFileName() == (
        "/tmp/output-volume.mrc"
    )

    assert result.getSamplingRate() == 1.5

    assert list(
        result.getHalfMaps(
            asList=True
        )
    ) == [
        "/tmp/half-map-1.mrc",
        "/tmp/half-map-2.mrc",
    ]

    assert result._objParent is None
    assert not hasattr(
        result,
        "_sourcePointer",
    )

    assert not hasattr(
        result,
        "_pluginRuntimeState",
    )


def test_SelectByIdUsesGenericPostgresqlObject():
    mapper = buildRuntimeMapper(buildRows())

    mapper._selectProtocolByIdFromPostgresql = lambda objId: None
    mapper._selectSetByIdFromPostgresql = lambda objId: None

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


def test_ExistsUsesCanonicalGenericPostgresqlObject():
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

    assert mapper.exists("700") is True

    mapper._resolveCanonicalScipionObjectRowId.assert_called_once_with(
        700
    )


def test_SelectByClassUsesGenericPostgresqlObjects():
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


def test_DeduplicateRuntimeObjectsKeepsFirstObjectForEachRuntimeId():
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    firstObject = FakeComposite()
    firstObject.setObjId(700)

    duplicatedObject = FakeComposite()
    duplicatedObject.setObjId(700)

    objectWithoutId = FakeComposite()

    result = mapper._deduplicateRuntimeObjects([
        firstObject,
        duplicatedObject,
        objectWithoutId,
    ])

    assert result == [
        firstObject,
        objectWithoutId,
    ]


def test_SelectByUsesGenericPostgresqlRuntimeId():
    mapper = buildRuntimeMapper(
        buildRows()
    )

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


def test_SelectByReturnsEmptyWhenNoPostgresqlObjectMatches():
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
        classname="String",
    )

    assert result == []


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


def test_SelectByReturnsOnlyPostgresqlObjectsInRuntimeIdOrder():
    classRows = [{
        "id": 10,
        "runtimeObjectId": 700,
        "className": "FakeComposite",
    }]

    mapper = buildRuntimeMapper(
        buildRows(),
        classRows=classRows,
    )

    result = mapper.selectBy()

    assert [
        obj.getObjId()
        for obj in result
    ] == [
        700,
    ]

    assert isinstance(
        result[0],
        FakeComposite,
    )

    assert result[0].title.get() == (
        "PostgreSQL object"
    )


def test_UpdateFromHydratesExistingGenericObjectFromPostgresql():
    mapper = buildRuntimeMapper(
        buildRows()
    )

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

    assert mapper.objectMapper.calls == [
        (
            7,
            700,
        ),
    ]


def test_UpdateFromRaisesWhenGenericObjectIsMissingFromPostgresql():
    mapper = buildRuntimeMapper([])

    targetObject = FakeComposite()
    targetObject.setObjId(700)

    with pytest.raises(NotImplementedError) as error:
        mapper.updateFrom(targetObject)

    assert str(error.value) == (
        "PostgreSQL updateFrom is only implemented "
        "for protocols, PostgreSQL runtime Sets "
        "and supported generic runtime objects."
    )


def test_UpdateFromClearsStaleParentIdForParentlessGenericObject():
    rows = buildRows()
    rows[0]["ownerProtocolId"] = None
    rows[0]["rootParentScipionObjId"] = None

    mapper = buildRuntimeMapper(
        rows
    )

    targetObject = FakeComposite()
    targetObject.setObjId(700)
    targetObject._objParentId = 999

    result = mapper.updateFrom(
        targetObject
    )

    assert result is None
    assert targetObject.getObjParentId() is None


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

    targetObject = FakeComposite()

    mapper.delete(
        targetObject
    )

    assert mapper.objectMapper.deleteCalls == []


def test_DeleteIgnoresNonPersistedSet():
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
    mapper.runtimeSetFactory.evictRuntimeSet.assert_not_called()



