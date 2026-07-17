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

from unittest.mock import Mock

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
        self.byIdCalls = []

    def getProtocols(self, projectId):
        self.calls.append(projectId)
        return list(self.rows)

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

def test_SelectByClassReusesProtocolSelectedById():
    mapper = buildMapper([
        buildRow(100, "ExampleProtocol"),
    ])

    protocol = buildProtocol(ExampleProtocol, 100)
    buildCalls = []

    def buildProtocolFromRow(row):
        buildCalls.append(int(row["protocolId"]))
        return protocol

    mapper._buildProtocolFromPostgresqlRow = buildProtocolFromRow

    selectedProtocol = mapper._selectProtocolByIdFromPostgresql(100)
    protocols = mapper.selectByClass("ExampleProtocol")

    assert selectedProtocol is protocol
    assert protocols == [protocol]
    assert protocols[0] is selectedProtocol
    assert buildCalls == [100]
    assert mapper.flatMapper.byIdCalls == [(4, 100)]


def test_ProtocolCacheRefreshesWithoutReplacingInstance():
    mapper = buildMapper([
        buildRow(100, "ExampleProtocol"),
    ])

    protocol = buildProtocol(ExampleProtocol, 100)
    refreshCalls = []

    mapper._buildProtocolFromPostgresqlRow = lambda row: protocol

    firstResult = mapper._selectProtocolByIdFromPostgresql(100)

    def refreshProtocol(cachedProtocol, row):
        refreshCalls.append({
            "protocol": cachedProtocol,
            "status": row["status"],
        })
        return cachedProtocol

    mapper._refreshProtocolFromPostgresqlRow = refreshProtocol
    mapper.flatMapper.rows[0]["status"] = "running"

    secondResult = mapper._selectProtocolByIdFromPostgresql(100)

    assert firstResult is protocol
    assert secondResult is protocol

    assert refreshCalls == [{
        "protocol": protocol,
        "status": "running",
    }]


def test_RefreshProtocolAppliesStoredRuntimeState():
    mapper = buildMapper()

    protocol = buildProtocol(ExampleProtocol, 100)
    statusCalls = []
    paramsCalls = []
    workingDirCalls = []

    mapper._applyStoredProtocolStatus = (
        lambda currentProtocol, status: statusCalls.append(
            (currentProtocol, status)
        )
    )

    mapper._applyStoredProtocolParams = (
        lambda currentProtocol, params: paramsCalls.append(
            (currentProtocol, params)
        )
    )

    mapper._ensureProtocolWorkingDir = (
        lambda currentProtocol: workingDirCalls.append(
            currentProtocol
        )
    )

    row = buildRow(100, "ExampleProtocol")
    row["status"] = "running"
    row["params"] = {
        "threshold": 3,
    }

    result = mapper._refreshProtocolFromPostgresqlRow(
        protocol,
        row,
    )

    assert result is protocol
    assert protocol.getObjId() == 100

    assert statusCalls == [
        (protocol, "running"),
    ]

    assert paramsCalls == [
        (
            protocol,
            {
                "threshold": 3,
            },
        ),
    ]

    assert workingDirCalls == [protocol]


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