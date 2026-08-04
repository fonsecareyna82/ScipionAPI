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


class UnsupportedObject:
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


def buildMapper():
    return PostgresqlRuntimeMapper(
        flatMapper=FakeFlatMapper(),
        projectId=4,
        dictClasses={
            "ExampleItem": ExampleItem,
            "ExampleSet": ExampleSet,
            "ExampleChildSet": ExampleChildSet,
            "UnsupportedObject": UnsupportedObject,
        },
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


def test_SelectByClassReturnsOnlyPostgresqlSets():
    postgresqlSet = buildSet(
        ExampleSet,
        300,
    )

    mapper = buildMapper()

    mapper.protocolGraphRepository = FakeRepository([
        buildRow(
            300,
            "ExampleSet",
        ),
    ])

    mapper._selectSetByIdFromPostgresql = (
        lambda objectId: postgresqlSet
    )

    result = mapper.selectByClass(
        "ExampleSet"
    )

    assert result == [
        postgresqlSet,
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


def test_SelectByClassRejectsUnsupportedClass():
    mapper = buildMapper()

    mapper.protocolGraphRepository = FakeRepository(
        fail=True
    )

    with pytest.raises(
            NotImplementedError,
            match="PostgreSQL selectByClass does not support class",
    ):
        mapper.selectByClass(
            "UnsupportedObject"
        )

class PopulatedRuntimeOutputSet(ExampleSet):
    def __init__(self, events):
        super().__init__()
        self.events = events
        self.postgresqlWritable = False

    def isEmpty(self):
        return False

    def enablePostgresqlWrite(self):
        self.events.append("enable-write")
        self.postgresqlWritable = True


class NativeMapperStub:
    def __init__(self, events):
        self.events = events

    def close(self):
        self.events.append("close-native-mapper")


class RuntimeSetMapperStub:
    def __init__(self, events):
        self.events = events
        self.storeCalls = []
        self.deleteCalls = []

    def storeSet(self, **kwargs):
        self.events.append("store-snapshot")
        self.storeCalls.append(dict(kwargs))

        return {
            "setId": 31,
            "rootTableId": 41,
            "rootObjectId": 51,
            "runtimeObjectId": 91,
            "setClassName": "PopulatedRuntimeOutputSet",
            "itemClassName": "ExampleItem",
            "properties": {
                "runtimeReserved": True,
                "runtimeWritable": True,
                "postgresqlNativeOutput": True,
            },
        }

    def deleteStoredSetOutput(self, **kwargs):
        self.deleteCalls.append(dict(kwargs))


class PopulatedRuntimeSetFactoryStub:
    def __init__(self, events):
        self.events = events
        self.buildCalls = []

    def _promoteRuntimeSetInstance(self, runtimeSet, nativeSetClass):
        self.events.append("promote-runtime-set")
        return runtimeSet

    def build(self, **kwargs):
        self.events.append("build-runtime-set")
        self.buildCalls.append(dict(kwargs))
        return kwargs["runtimeSet"]


class OutputProtocolStub:
    def getObjId(self):
        return 17


def test_CreatePostgresqlOutputSetCopiesPopulatedNativeSetBeforePromotion():
    events = []
    mapper = buildMapper()
    protocol = OutputProtocolStub()

    outputSet = PopulatedRuntimeOutputSet(events)
    outputSet.setObjId(91)
    outputSet._mapper = NativeMapperStub(events)

    setMapper = RuntimeSetMapperStub(events)
    runtimeSetFactory = PopulatedRuntimeSetFactoryStub(events)

    mapper.setMapper = setMapper
    mapper.runtimeSetFactory = runtimeSetFactory
    mapper.getPostgresqlOutputSetCapability = lambda setClass: {
        "supported": True,
        "reason": None,
    }
    mapper._resolveProtocolDbIdFromObject = lambda currentProtocol: 23
    mapper._prepareNativeSetForPostgresqlSnapshot = lambda runtimeSet: events.append("prepare-snapshot")

    result = mapper.createPostgresqlOutputSet(
        protocol=protocol,
        setClass=PopulatedRuntimeOutputSet,
        provisionalOutputName="__postgresql_runtime_output_test",
        constructorKwargs={},
        reservationToken="test-token",
        runtimeSet=outputSet,
    )

    assert result is outputSet
    assert outputSet.postgresqlWritable is True

    assert events == [
        "prepare-snapshot",
        "store-snapshot",
        "close-native-mapper",
        "promote-runtime-set",
        "build-runtime-set",
        "enable-write",
    ]

    assert len(setMapper.storeCalls) == 1

    storeCall = setMapper.storeCalls[0]

    assert storeCall["projectId"] == 4
    assert storeCall["protocolDbId"] == 23
    assert storeCall["scipionSet"] is outputSet
    assert storeCall["runtimeReserved"] is True
    assert storeCall["reservationToken"] == "test-token"

    assert len(runtimeSetFactory.buildCalls) == 1
    assert runtimeSetFactory.buildCalls[0]["runtimeSet"] is outputSet
    assert setMapper.deleteCalls == []


