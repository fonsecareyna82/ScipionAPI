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


class RebuildingFallbackMapper:
    def __init__(self, protocolClass):
        self.protocolClass = protocolClass
        self.calls = []
        self.createdProtocols = []

    def selectById(self, objId):
        self.calls.append(objId)

        protocol = buildProtocol(
            self.protocolClass,
            int(objId),
        )

        self.createdProtocols.append(protocol)

        return protocol


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
    assert mapper._sqliteProtocolMirrorIds == {
        100,
    }

    mapper._refreshSqliteProtocolMirrorFromPostgresqlRow = (
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

def test_SelectAllBatchRefreshesMirrorStatusWithoutReapplyingParams():
    fallbackProtocol = buildProtocol(ExampleProtocol, 100)

    fallback = FakeFallbackMapper([
        fallbackProtocol,
    ])

    row = buildRow(100)
    row["status"] = "running"
    row["params"] = {
        "inputParticles": "99.outputParticles",
    }

    mapper = buildMapper(
        rows=[row],
        fallback=fallback,
    )

    statusCalls = []
    paramCalls = []
    workingDirCalls = []

    mapper._applyStoredProtocolStatus = (
        lambda protocol, status: statusCalls.append(
            (protocol, status)
        )
    )

    mapper._applyStoredProtocolParams = (
        lambda protocol, params: paramCalls.append(
            (protocol, params)
        )
    )

    mapper._ensureProtocolWorkingDir = (
        lambda protocol: workingDirCalls.append(protocol)
    )

    result = mapper.selectAllBatch(
        objectFilter=lambda obj: isinstance(obj, Protocol)
    )

    assert result == [
        fallbackProtocol,
    ]

    assert statusCalls == [
        (fallbackProtocol, "running"),
    ]

    assert paramCalls == []
    assert workingDirCalls == [fallbackProtocol]

    assert mapper._runtimeProtocolsById[100] is fallbackProtocol
    assert mapper._sqliteProtocolMirrorIds == {100}


def test_SelectByIdUsesSafeRefreshForSqliteProtocolMirror():
    protocol = buildProtocol(ExampleProtocol, 100)

    mapper = buildMapper([
        buildRow(100),
    ])

    mapper._runtimeProtocolsById[100] = protocol
    mapper._sqliteProtocolMirrorIds.add(100)

    safeRefreshCalls = []

    def safeRefresh(cachedProtocol, row):
        safeRefreshCalls.append({
            "protocol": cachedProtocol,
            "protocolId": int(row["protocolId"]),
        })
        return cachedProtocol

    def failFullRefresh(cachedProtocol, row):
        raise AssertionError(
            "Full PostgreSQL param refresh must not run "
            "for a SQLite protocol mirror"
        )

    mapper._refreshSqliteProtocolMirrorFromPostgresqlRow = safeRefresh
    mapper._refreshProtocolFromPostgresqlRow = failFullRefresh

    result = mapper._selectProtocolByIdFromPostgresql(100)

    assert result is protocol

    assert safeRefreshCalls == [{
        "protocol": protocol,
        "protocolId": 100,
    }]


def test_SelectByIdKeepsFullRefreshForPostgresqlProtocol():
    protocol = buildProtocol(ExampleProtocol, 100)

    mapper = buildMapper([
        buildRow(100),
    ])

    mapper._runtimeProtocolsById[100] = protocol

    fullRefreshCalls = []

    def fullRefresh(cachedProtocol, row):
        fullRefreshCalls.append({
            "protocol": cachedProtocol,
            "protocolId": int(row["protocolId"]),
        })
        return cachedProtocol

    def failSafeRefresh(cachedProtocol, row):
        raise AssertionError(
            "SQLite mirror refresh must not run "
            "for a native PostgreSQL protocol"
        )

    mapper._refreshProtocolFromPostgresqlRow = fullRefresh
    mapper._refreshSqliteProtocolMirrorFromPostgresqlRow = failSafeRefresh

    result = mapper._selectProtocolByIdFromPostgresql(100)

    assert result is protocol

    assert fullRefreshCalls == [{
        "protocol": protocol,
        "protocolId": 100,
    }]


def test_SelectRuntimeProtocolByIdReusesSqliteMirrorIdentity():
    fallback = RebuildingFallbackMapper(ExampleProtocol)

    mapper = buildMapper(
        rows=[
            buildRow(100),
        ],
        fallback=fallback,
    )

    firstResult = mapper.selectRuntimeProtocolById(100)
    secondResult = mapper.selectRuntimeProtocolById(100)

    assert firstResult is secondResult
    assert firstResult is fallback.createdProtocols[0]

    # SQLite is consulted only during the first hydration.
    assert fallback.calls == [100]
    assert len(fallback.createdProtocols) == 1

    assert mapper._runtimeProtocolsById[100] is firstResult
    assert mapper._sqliteProtocolMirrorIds == {100}

    assert mapper.flatMapper.byIdCalls == [
        (4, 100),
        (4, 100),
    ]


def test_SelectRuntimeProtocolByIdCachesFallbackOnlyProtocol():
    fallback = RebuildingFallbackMapper(ExampleProtocol)

    mapper = buildMapper(
        rows=[],
        fallback=fallback,
    )

    firstResult = mapper.selectRuntimeProtocolById(100)
    secondResult = mapper.selectRuntimeProtocolById(100)

    assert firstResult is secondResult
    assert firstResult is fallback.createdProtocols[0]

    assert fallback.calls == [100]
    assert len(fallback.createdProtocols) == 1

    assert mapper._runtimeProtocolsById[100] is firstResult
    assert mapper._sqliteProtocolMirrorIds == {100}

    assert mapper.flatMapper.byIdCalls == [
        (4, 100),
        (4, 100),
    ]


def test_GetPostgresqlProtocolLabelsBuildsFromPostgresqlRowsWithoutFallback():
    fallbackProtocol = buildProtocol(
        ExampleProtocol,
        100,
    )

    fallback = FakeFallbackMapper([
        fallbackProtocol,
    ])

    mapper = buildMapper(
        rows=[
            buildRow(100),
            buildRow(101),
        ],
        fallback=fallback,
    )

    labelsById = {
        100: "Import movies",
        101: "Import movies (2)",
    }

    buildCalls = []

    def buildProtocolFromRow(row):
        protocolId = int(row["protocolId"])
        buildCalls.append(protocolId)

        protocol = buildProtocol(
            ExampleProtocol,
            protocolId,
        )
        protocol.setObjLabel(
            labelsById[protocolId]
        )

        return protocol

    mapper._buildProtocolFromPostgresqlRow = (
        buildProtocolFromRow
    )

    assert mapper.getPostgresqlProtocolLabels() == [
        "Import movies",
        "Import movies (2)",
    ]

    assert buildCalls == [
        100,
        101,
    ]

    # Reading labels must never load the SQLite batch.
    assert fallback.calls == []