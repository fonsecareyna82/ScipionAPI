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

from pyworkflow.protocol.protocol import Protocol

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class ExampleProtocol(Protocol):
    pass


class OtherProtocol(Protocol):
    pass


class FakeDb:
    def __init__(self):
        self.fetchAllCalls = []

    def fetchAll(
            self,
            query,
            params=None,
    ):
        self.fetchAllCalls.append({
            "query": " ".join(
                str(
                    query
                ).split()
            ),
            "params": params,
        })

        return []


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


def buildMapper(
        rows=None,
        writeFallback=None,
):
    return PostgresqlRuntimeMapper(
        flatMapper=FakeFlatMapper(rows),
        projectId=4,
        dictClasses={
            "ExampleProtocol": ExampleProtocol,
            "OtherProtocol": OtherProtocol,
        },
        writeFallbackMapper=writeFallback,
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


def test_SelectAllBatchBuildsOnlyPostgresqlProtocols():
    firstProtocol = buildProtocol(ExampleProtocol, 100)
    secondProtocol = buildProtocol(ExampleProtocol, 101)

    mapper = buildMapper(rows=[
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

    result = mapper.selectAllBatch(objectFilter=lambda obj: isinstance(obj, Protocol))

    assert result == [
        firstProtocol,
        secondProtocol,
    ]

    assert buildCalls == [
        100,
        101,
    ]

    assert mapper.flatMapper.calls == [4]
    assert mapper._sqliteProtocolMirrorIds == set()


def test_SelectAllBatchAppliesObjectFilter():
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

    mapper._buildProtocolFromPostgresqlRow = lambda row: protocolsById[int(row["protocolId"])]

    result = mapper.selectAllBatch(objectFilter=lambda protocol: protocol.getObjId() == 101)

    assert result == [
        secondProtocol,
    ]


def test_SelectAllBatchRejectsInvalidObjectFilter():
    mapper = buildMapper()

    with pytest.raises(
            TypeError,
            match="objectFilter must be callable or None",
    ):
        mapper.selectAllBatch(objectFilter="Protocol")


def test_SelectAllBatchSafelyRefreshesCachedWriteMirror():
    protocol = buildProtocol(ExampleProtocol, 100)

    row = buildRow(100)
    row["status"] = "running"
    row["params"] = {
        "inputParticles": "99.outputParticles",
    }

    mapper = buildMapper(rows=[row])
    mapper._runtimeProtocolsById[100] = protocol
    mapper._sqliteProtocolMirrorIds.add(100)

    statusCalls = []
    paramCalls = []
    workingDirCalls = []

    mapper._applyStoredProtocolStatus = lambda currentProtocol, status: statusCalls.append((currentProtocol, status))
    mapper._applyStoredProtocolParams = lambda currentProtocol, params: paramCalls.append((currentProtocol, params))
    mapper._ensureProtocolWorkingDir = lambda currentProtocol: workingDirCalls.append(currentProtocol)

    result = mapper.selectAllBatch(objectFilter=lambda obj: isinstance(obj, Protocol))

    assert result == [
        protocol,
    ]

    assert statusCalls == [
        (protocol, "running"),
    ]

    assert paramCalls == []
    assert workingDirCalls == [protocol]
    assert mapper._runtimeProtocolsById[100] is protocol
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


def test_SelectByIdReturnsNoneForMissingObject():
    mapper = buildMapper()

    mapper._selectProtocolByIdFromPostgresql = lambda objId: None
    mapper._selectSetByIdFromPostgresql = lambda objId: None
    mapper._selectGenericObjectByIdFromPostgresql = lambda objId: None

    assert mapper.selectById(999) is None


def test_SelectRuntimeProtocolByIdReusesWriteMirrorIdentity():
    writeFallback = RebuildingFallbackMapper(
        ExampleProtocol
    )

    mapper = buildMapper(
        rows=[
            buildRow(100),
        ],
        writeFallback=writeFallback,
    )

    firstResult = mapper.selectRuntimeProtocolById(
        100
    )

    secondResult = mapper.selectRuntimeProtocolById(
        100
    )

    assert firstResult is secondResult

    assert firstResult is (
        writeFallback.createdProtocols[0]
    )

    # The SQLite execution mirror is consulted only during the first hydration.
    assert writeFallback.calls == [
        100,
    ]

    assert len(
        writeFallback.createdProtocols
    ) == 1

    assert mapper._runtimeProtocolsById[
        100
    ] is firstResult

    assert mapper._sqliteProtocolMirrorIds == {
        100,
    }

    assert mapper.flatMapper.byIdCalls == [
        (
            4,
            100,
        ),
        (
            4,
            100,
        ),
    ]


def test_SelectRuntimeProtocolByIdCachesWriteMirrorOnlyProtocol():
    writeFallback = RebuildingFallbackMapper(
        ExampleProtocol
    )

    mapper = buildMapper(
        rows=[],
        writeFallback=writeFallback,
    )

    firstResult = mapper.selectRuntimeProtocolById(
        100
    )

    secondResult = mapper.selectRuntimeProtocolById(
        100
    )

    assert firstResult is secondResult

    assert firstResult is (
        writeFallback.createdProtocols[0]
    )

    assert writeFallback.calls == [
        100,
    ]

    assert len(
        writeFallback.createdProtocols
    ) == 1

    assert mapper._runtimeProtocolsById[
        100
    ] is firstResult

    assert mapper._sqliteProtocolMirrorIds == {
        100,
    }

    assert mapper.flatMapper.byIdCalls == [
        (
            4,
            100,
        ),
        (
            4,
            100,
        ),
    ]


def test_GetPostgresqlProtocolLabelsReadsStoredLabelsWithoutBuildingProtocols():
    firstRow = buildRow(100)
    firstRow["params"] = {
        "object.label": "Import movies",
    }

    secondRow = buildRow(101)
    secondRow["params"] = {
        "object.label": {
            "value": "Import movies (2)",
        },
    }

    unlabeledRow = buildRow(102)
    unlabeledRow["params"] = {}

    mapper = buildMapper(rows=[
        firstRow,
        secondRow,
        unlabeledRow,
    ])

    def failBuildProtocolFromRow(row):
        raise AssertionError(
            "Reading PostgreSQL labels must not build protocols"
        )

    mapper._buildProtocolFromPostgresqlRow = (
        failBuildProtocolFromRow
    )

    assert mapper.getPostgresqlProtocolLabels() == [
        "Import movies",
        "Import movies (2)",
    ]

    assert mapper.flatMapper.calls == [
        4,
    ]

