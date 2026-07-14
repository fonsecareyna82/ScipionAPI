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
from pyworkflow.protocol.protocol import Protocol

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class ExampleProtocol(Protocol):
    pass


class ExampleChildProtocol(ExampleProtocol):
    pass


class OtherProtocol(Protocol):
    pass


class FakeDb:
    pass


class FakeFlatMapper:
    def __init__(self, rows=None):
        self.db = FakeDb()
        self.rows = list(rows or [])
        self.calls = []

    def getProtocols(self, projectId):
        self.calls.append(projectId)
        return list(self.rows)

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        return None


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


def buildMapper(rows=None, fallback=None):
    return PostgresqlRuntimeMapper(
        flatMapper=FakeFlatMapper(rows),
        projectId=4,
        dictClasses={
            "ExampleProtocol": ExampleProtocol,
            "ExampleChildProtocol": ExampleChildProtocol,
            "OtherProtocol": OtherProtocol,
        },
        readFallbackMapper=fallback,
    )


def buildRow(protocolId, className):
    return {
        "id": protocolId + 1000,
        "projectId": 4,
        "protocolId": str(protocolId),
        "protocolClassName": className,
        "status": "finished",
        "params": {},
        "parentIds": [],
        "childIds": [],
    }


def buildProtocol(protocolClass, protocolId):
    protocol = protocolClass()
    protocol.setObjId(protocolId)
    return protocol


def configureProtocolBuilder(mapper, protocolsById):
    def buildProtocol(row):
        protocolId = int(row["protocolId"])
        return protocolsById.get(protocolId)

    mapper._buildProtocolFromPostgresqlRow = buildProtocol


def test_SelectByClassReturnsPostgresqlProtocolSubclasses():
    mapper = buildMapper([
        buildRow(100, "ExampleProtocol"),
        buildRow(101, "ExampleChildProtocol"),
        buildRow(102, "OtherProtocol"),
    ])

    baseProtocol = buildProtocol(ExampleProtocol, 100)
    childProtocol = buildProtocol(ExampleChildProtocol, 101)
    otherProtocol = buildProtocol(OtherProtocol, 102)

    configureProtocolBuilder(mapper, {
        100: baseProtocol,
        101: childProtocol,
        102: otherProtocol,
    })

    result = mapper.selectByClass(
        "ExampleProtocol",
        includeSubclasses=True,
    )

    assert result == [
        baseProtocol,
        childProtocol,
    ]

    assert mapper.flatMapper.calls == [4]


def test_SelectByClassSupportsExactProtocolClass():
    mapper = buildMapper([
        buildRow(100, "ExampleProtocol"),
        buildRow(101, "ExampleChildProtocol"),
    ])

    baseProtocol = buildProtocol(ExampleProtocol, 100)
    childProtocol = buildProtocol(ExampleChildProtocol, 101)

    configureProtocolBuilder(mapper, {
        100: baseProtocol,
        101: childProtocol,
    })

    result = mapper.selectByClass(
        "ExampleProtocol",
        includeSubclasses=False,
    )

    assert result == [baseProtocol]


def test_SelectByClassSupportsGenericProtocolClass():
    mapper = buildMapper([
        buildRow(100, "ExampleProtocol"),
        buildRow(102, "OtherProtocol"),
    ])

    exampleProtocol = buildProtocol(ExampleProtocol, 100)
    otherProtocol = buildProtocol(OtherProtocol, 102)

    configureProtocolBuilder(mapper, {
        100: exampleProtocol,
        102: otherProtocol,
    })

    result = mapper.selectByClass("Protocol")

    assert result == [
        exampleProtocol,
        otherProtocol,
    ]


def test_SelectByClassMergesProtocolFallbackWithoutDuplicates():
    postgresqlProtocol = buildProtocol(ExampleProtocol, 100)
    duplicatedFallbackProtocol = buildProtocol(ExampleProtocol, 100)
    legacyProtocol = buildProtocol(ExampleProtocol, 200)

    fallback = FakeFallbackMapper([
        duplicatedFallbackProtocol,
        legacyProtocol,
    ])

    mapper = buildMapper(
        rows=[
            buildRow(100, "ExampleProtocol"),
        ],
        fallback=fallback,
    )

    configureProtocolBuilder(mapper, {
        100: postgresqlProtocol,
    })

    result = mapper.selectByClass("ExampleProtocol")

    assert result == [
        postgresqlProtocol,
        legacyProtocol,
    ]


def test_SelectByClassAppliesProtocolObjectFilter():
    mapper = buildMapper([
        buildRow(100, "ExampleProtocol"),
        buildRow(101, "ExampleProtocol"),
    ])

    firstProtocol = buildProtocol(ExampleProtocol, 100)
    secondProtocol = buildProtocol(ExampleProtocol, 101)

    configureProtocolBuilder(mapper, {
        100: firstProtocol,
        101: secondProtocol,
    })

    result = mapper.selectByClass(
        "ExampleProtocol",
        objectFilter=lambda protocol: protocol.getObjId() == 101,
    )

    assert result == [secondProtocol]


def test_SelectByClassReturnsProtocolIterator():
    mapper = buildMapper([
        buildRow(100, "ExampleProtocol"),
    ])

    protocol = buildProtocol(ExampleProtocol, 100)

    configureProtocolBuilder(mapper, {
        100: protocol,
    })

    result = mapper.selectByClass(
        "ExampleProtocol",
        iterate=True,
    )

    assert list(result) == [protocol]