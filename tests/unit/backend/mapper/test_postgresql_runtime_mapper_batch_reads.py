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

from pyworkflow.object import Object
from pyworkflow.protocol.protocol import Protocol

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class ExampleProtocol(Protocol):
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
        self.byIdCalls = []

    def getProtocols(self, projectId):
        self.calls.append(projectId)
        return [dict(row) for row in self.rows]

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        self.byIdCalls.append((projectId, protocolId))

        for row in self.rows:
            if int(row["protocolId"]) == int(protocolId):
                return dict(row)

        return None


class FakeFallbackMapper:
    def __init__(self, objects=None):
        self.objects = list(objects or [])
        self.calls = []

    def selectAllBatch(self, objectFilter=None):
        self.calls.append(objectFilter)
        result = list(self.objects)

        if callable(objectFilter):
            result = [obj for obj in result if objectFilter(obj)]

        return result


def buildMapper(rows=None, fallback=None):
    return PostgresqlRuntimeMapper(
        flatMapper=FakeFlatMapper(rows),
        projectId=4,
        dictClasses={
            "ExampleProtocol": ExampleProtocol,
            "OtherProtocol": OtherProtocol,
        },
        readFallbackMapper=fallback,
    )


def buildRow(protocolId, className="ExampleProtocol"):
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


def test_SelectAllBatchPrefersFallbackMirrorAndBuildsPostgresqlOnlyProtocols():
    fallbackProtocol = buildProtocol(ExampleProtocol, 100)
    fallbackOnlyProtocol = buildProtocol(OtherProtocol, 200)
    postgresqlOnlyProtocol = buildProtocol(ExampleProtocol, 101)

    fallback = FakeFallbackMapper([
        fallbackProtocol,
        fallbackOnlyProtocol,
    ])

    mapper = buildMapper(
        rows=[
            buildRow(100),
            buildRow(101),
        ],
        fallback=fallback,
    )

    buildCalls = []

    def buildProtocolFromRow(row):
        protocolId = int(row["protocolId"])
        buildCalls.append(protocolId)

        if protocolId == 101:
            return postgresqlOnlyProtocol

        raise AssertionError(
            "The protocol mirrored in SQLite must not be rebuilt"
        )

    mapper._buildProtocolFromPostgresqlRow = buildProtocolFromRow

    result = mapper.selectAllBatch(
        objectFilter=lambda obj: isinstance(obj, Protocol)
    )

    assert result == [
        fallbackProtocol,
        postgresqlOnlyProtocol,
        fallbackOnlyProtocol,
    ]

    assert buildCalls == [101]
    assert mapper.flatMapper.calls == [4]

    assert len(fallback.calls) == 1
    assert callable(fallback.calls[0])

    assert mapper._runtimeProtocolsById[100] is fallbackProtocol
    assert mapper._runtimeProtocolsById[101] is postgresqlOnlyProtocol

    mapper._refreshProtocolFromPostgresqlRow = (
        lambda protocol, row: protocol
    )

    assert (
        mapper._selectProtocolByIdFromPostgresql(100)
        is fallbackProtocol
    )

    assert mapper.flatMapper.byIdCalls == [
        (4, 100),
    ]


def test_SelectAllBatchWorksWithoutSqliteFallback():
    firstProtocol = buildProtocol(ExampleProtocol, 100)
    secondProtocol = buildProtocol(ExampleProtocol, 101)

    mapper = buildMapper([
        buildRow(100),
        buildRow(101),
    ])

    protocolsById = {
        100: firstProtocol,
        101: secondProtocol,
    }

    buildCalls = []

    def buildProtocolFromRow(row):
        protocolId = int(row["protocolId"])
        buildCalls.append(protocolId)
        return protocolsById[protocolId]

    mapper._buildProtocolFromPostgresqlRow = buildProtocolFromRow

    result = mapper.selectAllBatch(
        objectFilter=lambda protocol: protocol.getObjId() == 101
    )

    assert result == [
        secondProtocol,
    ]

    assert buildCalls == [
        100,
        101,
    ]


def test_SelectAllBatchPreservesFallbackOnlyObjectsWithoutFilter():
    fallbackProtocol = buildProtocol(ExampleProtocol, 100)

    legacyObject = Object()
    legacyObject.setObjId(500)

    fallback = FakeFallbackMapper([
        fallbackProtocol,
        legacyObject,
    ])

    mapper = buildMapper(
        rows=[],
        fallback=fallback,
    )

    result = mapper.selectAllBatch()

    assert result == [
        fallbackProtocol,
        legacyObject,
    ]

    assert mapper.flatMapper.calls == [4]


def test_SelectAllBatchRejectsInvalidObjectFilter():
    mapper = buildMapper()

    with pytest.raises(
            TypeError,
            match="objectFilter must be callable or None",
    ):
        mapper.selectAllBatch(
            objectFilter="Protocol"
        )