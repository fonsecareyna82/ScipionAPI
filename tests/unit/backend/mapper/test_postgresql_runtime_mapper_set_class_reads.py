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
from pyworkflow.object import Object, Set

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class ExampleItem(Object):
    pass


class ExampleSet(Set):
    ITEM_TYPE = ExampleItem


class ExampleChildSet(ExampleSet):
    pass


class ExampleObject(Object):
    pass


class FakeDb:
    pass


class FakeFlatMapper:
    def __init__(self):
        self.db = FakeDb()

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        return None


class FakeRepository:
    def __init__(self, rows=None, fail=False):
        self.rows = list(rows or [])
        self.fail = fail
        self.calls = []

    def listPersistedSetOutputRows(
            self,
            mapper,
            projectId,
            className=None,
    ):
        if self.fail:
            raise AssertionError(
                "PostgreSQL set listing must not be called"
            )

        self.calls.append({
            "mapper": mapper,
            "projectId": projectId,
            "className": className,
        })

        if className:
            return [
                row
                for row in self.rows
                if row["className"] == className
            ]

        return list(self.rows)


class FakeFallbackMapper:
    def __init__(self, objects=None):
        self.objects = list(objects or [])
        self.calls = []

    def selectByClass(
            self,
            className,
            includeSubclasses=True,
            iterate=False,
            objectFilter=None,
    ):
        self.calls.append({
            "className": className,
            "includeSubclasses": includeSubclasses,
            "iterate": iterate,
            "objectFilter": objectFilter,
        })

        result = list(self.objects)

        if callable(objectFilter):
            result = [obj for obj in result if objectFilter(obj)]

        return iter(result) if iterate else result


def buildMapper(fallback=None):
    return PostgresqlRuntimeMapper(
        flatMapper=FakeFlatMapper(),
        projectId=4,
        dictClasses={
            "ExampleItem": ExampleItem,
            "ExampleSet": ExampleSet,
            "ExampleChildSet": ExampleChildSet,
            "ExampleObject": ExampleObject,
        },
        readFallbackMapper=fallback,
    )


def buildRow(runtimeObjectId, className):
    return {
        "setId": runtimeObjectId,
        "projectId": 4,
        "protocolDbId": 20,
        "protocolId": "200",
        "objectId": runtimeObjectId + 1000,
        "runtimeObjectId": runtimeObjectId,
        "outputName": f"output{runtimeObjectId}",
        "className": className,
        "itemClassName": "ExampleItem",
        "properties": {},
    }


def buildSet(setClass, objectId):
    runtimeSet = setClass()
    runtimeSet.setObjId(objectId)
    runtimeSet._postgresqlNativeSetClass = setClass
    return runtimeSet


def test_SelectByClassReturnsPostgresqlSetSubclasses():
    mapper = buildMapper()

    baseSet = buildSet(ExampleSet, 300)
    childSet = buildSet(ExampleChildSet, 301)

    mapper.protocolGraphRepository = FakeRepository([
        buildRow(300, "ExampleSet"),
        buildRow(301, "ExampleChildSet"),
    ])

    setsById = {
        300: baseSet,
        301: childSet,
    }

    mapper._selectSetByIdFromPostgresql = setsById.get

    result = mapper.selectByClass(
        "ExampleSet",
        includeSubclasses=True,
    )

    assert result == [baseSet, childSet]

    assert mapper.protocolGraphRepository.calls == [{
        "mapper": mapper,
        "projectId": 4,
        "className": None,
    }]


def test_SelectByClassSupportsExactSetClass():
    mapper = buildMapper()

    baseSet = buildSet(ExampleSet, 300)
    childSet = buildSet(ExampleChildSet, 301)

    mapper.protocolGraphRepository = FakeRepository([
        buildRow(300, "ExampleSet"),
        buildRow(301, "ExampleChildSet"),
    ])

    setsById = {
        300: baseSet,
        301: childSet,
    }

    mapper._selectSetByIdFromPostgresql = setsById.get

    result = mapper.selectByClass(
        "ExampleSet",
        includeSubclasses=False,
    )

    assert result == [baseSet]

    assert mapper.protocolGraphRepository.calls == [{
        "mapper": mapper,
        "projectId": 4,
        "className": "ExampleSet",
    }]


def test_SelectByClassMergesFallbackWithoutDuplicates():
    postgresqlSet = buildSet(ExampleSet, 300)
    duplicatedFallbackSet = buildSet(ExampleSet, 300)
    legacySet = buildSet(ExampleSet, 400)

    fallback = FakeFallbackMapper([
        duplicatedFallbackSet,
        legacySet,
    ])

    mapper = buildMapper(fallback=fallback)

    mapper.protocolGraphRepository = FakeRepository([
        buildRow(300, "ExampleSet"),
    ])

    mapper._selectSetByIdFromPostgresql = (
        lambda objectId: postgresqlSet
    )

    result = mapper.selectByClass("ExampleSet")

    assert result == [
        postgresqlSet,
        legacySet,
    ]


def test_SelectByClassAppliesCallableObjectFilter():
    mapper = buildMapper()

    firstSet = buildSet(ExampleSet, 300)
    secondSet = buildSet(ExampleSet, 301)

    mapper.protocolGraphRepository = FakeRepository([
        buildRow(300, "ExampleSet"),
        buildRow(301, "ExampleSet"),
    ])

    setsById = {
        300: firstSet,
        301: secondSet,
    }

    mapper._selectSetByIdFromPostgresql = setsById.get

    result = mapper.selectByClass(
        "ExampleSet",
        objectFilter=lambda obj: obj.getObjId() == 301,
    )

    assert result == [secondSet]


def test_SelectByClassReturnsIteratorWhenRequested():
    mapper = buildMapper()

    runtimeSet = buildSet(ExampleSet, 300)

    mapper.protocolGraphRepository = FakeRepository([
        buildRow(300, "ExampleSet"),
    ])

    mapper._selectSetByIdFromPostgresql = (
        lambda objectId: runtimeSet
    )

    result = mapper.selectByClass(
        "ExampleSet",
        iterate=True,
    )

    assert list(result) == [runtimeSet]


def test_SelectByClassDelegatesNonSetClassesToFallback():
    legacyObject = ExampleObject()
    legacyObject.setObjId(500)

    fallback = FakeFallbackMapper([legacyObject])
    mapper = buildMapper(fallback=fallback)

    mapper.protocolGraphRepository = FakeRepository(fail=True)

    result = mapper.selectByClass("ExampleObject")

    assert result == [legacyObject]

    assert fallback.calls == [{
        "className": "ExampleObject",
        "includeSubclasses": True,
        "iterate": False,
        "objectFilter": None,
    }]


def test_UpdateFromRefreshesProtocolFromPostgresqlWithoutFallback():
    row = buildRow(
        100,
        "ExampleProtocol",
    )

    row["status"] = "running"

    fallbackMapper = Mock()

    mapper = buildMapper(
        rows=[
            row,
        ],
        fallback=fallbackMapper,
    )

    mapper._recordReadFallback = Mock()

    protocol = buildProtocol(
        ExampleProtocol,
        100,
    )

    protocol.runtimeValue = "stale"

    def refreshProtocol(
            currentProtocol,
            currentRow,
    ):
        assert currentProtocol is protocol

        currentProtocol.runtimeValue = (
            currentRow[
                "status"
            ]
        )

        return currentProtocol

    mapper._refreshProtocolFromPostgresqlRow = (
        refreshProtocol
    )

    result = mapper.updateFrom(
        protocol
    )

    assert result is None
    assert protocol.runtimeValue == "running"

    assert mapper._runtimeProtocolsById[
        100
    ] is protocol

    fallbackMapper.updateFrom.assert_not_called()
    mapper._recordReadFallback.assert_not_called()


def test_UpdateFromUsesSafeRefreshForSqliteProtocolMirror():
    mapper = buildMapper([
        buildRow(
            100,
            "ExampleProtocol",
        ),
    ])

    protocol = buildProtocol(
        ExampleProtocol,
        100,
    )

    outputObject = object()

    protocol.outputParticles = (
        outputObject
    )

    mapper._sqliteProtocolMirrorIds.add(
        100
    )

    mirrorCalls = []

    def refreshMirror(
            currentProtocol,
            row,
    ):
        mirrorCalls.append(
            currentProtocol
        )

        currentProtocol.runtimeStatus = (
            row[
                "status"
            ]
        )

        return currentProtocol

    mapper._refreshSqliteProtocolMirrorFromPostgresqlRow = (
        refreshMirror
    )

    mapper._refreshProtocolFromPostgresqlRow = Mock(
        side_effect=AssertionError(
            "SQLite mirrors must not receive "
            "the full PostgreSQL param refresh"
        )
    )

    mapper.updateFrom(
        protocol
    )

    assert mirrorCalls == [
        protocol,
    ]

    assert protocol.outputParticles is (
        outputObject
    )

    assert mapper._runtimeProtocolsById[
        100
    ] is protocol


def test_UpdateFromProtocolRestoresStateWhenRefreshFails():
    mapper = buildMapper([
        buildRow(
            100,
            "ExampleProtocol",
        ),
    ])

    previousCachedProtocol = buildProtocol(
        ExampleProtocol,
        100,
    )

    mapper._runtimeProtocolsById[
        100
    ] = previousCachedProtocol

    protocol = buildProtocol(
        ExampleProtocol,
        100,
    )

    protocol.runtimeValue = "before"

    def failRefresh(
            currentProtocol,
            row,
    ):
        currentProtocol.runtimeValue = (
            "partial"
        )

        raise RuntimeError(
            "forced protocol refresh failure"
        )

    mapper._refreshProtocolFromPostgresqlRow = (
        failRefresh
    )

    with pytest.raises(
            RuntimeError,
            match=(
                "forced protocol refresh failure"
            ),
    ):
        mapper.updateFrom(
            protocol
        )

    assert protocol.runtimeValue == "before"

    assert mapper._runtimeProtocolsById[
        100
    ] is previousCachedProtocol


