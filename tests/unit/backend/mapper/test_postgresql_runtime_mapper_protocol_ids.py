# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de Bioinformatica of Centro Nacional de Biotecnologia, CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307 USA
# *
# * All comments concerning this program package may be sent to
# * 'scipion@cnb.csic.es'
# *
# ******************************************************************************
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from pyworkflow.object import Object
from pyworkflow.protocol.protocol import Protocol

from app.backend.mapper.postgresql import (
    POSTGRESQL_RUNTIME_OBJECT_ID_START,
    PostgresqlFlatMapper,
)
from app.backend.mapper.postgresql_runtime_mapper import PostgresqlRuntimeMapper


class ExampleProtocol(Protocol):
    def __init__(self, objId=None):
        self._objId = objId

    def getObjId(self):
        return self._objId

    def setObjId(self, objId):
        self._objId = int(objId)


class ExampleObject(Object):
    pass


class FakeFlatMapper:
    def __init__(self, protocolIds=None, objectIds=None):
        self.db = SimpleNamespace()
        self.protocolIds = list(protocolIds or [])
        self.objectIds = list(objectIds or [])
        self.protocolAllocationCalls = []
        self.objectAllocationCalls = []

    def allocateProjectProtocolId(self, projectId):
        self.protocolAllocationCalls.append(int(projectId))

        if not self.protocolIds:
            raise AssertionError("Unexpected protocol id allocation")

        return self.protocolIds.pop(0)

    def allocateProjectObjectId(self, projectId):
        self.objectAllocationCalls.append(int(projectId))

        if not self.objectIds:
            raise AssertionError("Unexpected object id allocation")

        return self.objectIds.pop(0)


class FakeProtocolCounterDb:
    def __init__(self, storedCandidate, existingCompactMax):
        self.storedCandidate = int(storedCandidate)
        self.existingCompactMax = int(existingCompactMax)
        self.executeCalls = []
        self.fetchOneCalls = []

    def transaction(self):
        return nullcontext()

    def execute(self, query, params=None, commit=True):
        normalizedQuery = " ".join(str(query).split())

        self.executeCalls.append({
            "query": normalizedQuery,
            "params": params,
            "commit": commit,
        })

        return SimpleNamespace()

    def fetchOne(self, query, params=None):
        normalizedQuery = " ".join(str(query).split())

        self.fetchOneCalls.append({
            "query": normalizedQuery,
            "params": params,
        })

        if 'SELECT "nextProtocolId"' in normalizedQuery:
            return {
                "nextProtocolId": self.storedCandidate,
            }

        if "MAX(" in normalizedQuery and "FROM protocols" in normalizedQuery:
            return {
                "value": self.existingCompactMax,
            }

        raise AssertionError(
            "Unexpected query: %s" % normalizedQuery
        )


def buildRuntimeMapper(protocolIds=None, objectIds=None):
    mapper = object.__new__(PostgresqlRuntimeMapper)
    mapper.projectId = 31
    mapper.flatMapper = FakeFlatMapper(
        protocolIds=protocolIds,
        objectIds=objectIds,
    )

    return mapper


def test_ProjectSqliteProtocolIdCompatibilityIsRemoved():
    mapper = buildRuntimeMapper()

    assert not hasattr(
        mapper,
        "_getProjectSqlitePath",
    )
    assert not hasattr(
        mapper,
        "_existsInProjectSqlite",
    )


def test_EnsureObjIdAllocatesProtocolFromPostgresqlCounter():
    mapper = buildRuntimeMapper(
        protocolIds=[
            602,
        ],
    )
    protocol = ExampleProtocol()

    protocolId = mapper._ensureObjId(
        protocol
    )

    assert protocolId == 602
    assert protocol.getObjId() == 602
    assert mapper.flatMapper.protocolAllocationCalls == [
        31,
    ]


def test_EnsureObjIdKeepsExistingProtocolIdentity():
    mapper = buildRuntimeMapper(
        protocolIds=[
            603,
        ],
    )
    protocol = ExampleProtocol(
        objId=777
    )

    protocolId = mapper._ensureObjId(
        protocol
    )

    assert protocolId == 777
    assert protocol.getObjId() == 777
    assert mapper.flatMapper.protocolAllocationCalls == []


def test_EnsureObjIdAllocatesNonProtocolFromObjectNamespace():
    mapper = buildRuntimeMapper(
        objectIds=[
            POSTGRESQL_RUNTIME_OBJECT_ID_START,
        ],
    )
    runtimeObject = ExampleObject()

    objectId = mapper._ensureObjId(
        runtimeObject
    )

    assert objectId == POSTGRESQL_RUNTIME_OBJECT_ID_START
    assert runtimeObject.getObjId() == POSTGRESQL_RUNTIME_OBJECT_ID_START
    assert mapper.flatMapper.objectAllocationCalls == [
        31,
    ]


def test_AssignFreshRuntimeObjectIdReplacesExistingObjectIdentity():
    freshObjectId = (
        POSTGRESQL_RUNTIME_OBJECT_ID_START
        + 481
    )

    mapper = buildRuntimeMapper(
        objectIds=[
            freshObjectId,
        ],
    )

    runtimeObject = ExampleObject()
    runtimeObject.setObjId(
        77
    )

    objectId = (
        mapper
        ._assignFreshRuntimeObjectId(
            runtimeObject
        )
    )

    assert objectId == freshObjectId
    assert runtimeObject.getObjId() == freshObjectId

    assert mapper.flatMapper.objectAllocationCalls == [
        31,
    ]


def test_AllocateProjectProtocolIdRebasesLegacyMillionCounter():
    db = FakeProtocolCounterDb(
        storedCandidate=POSTGRESQL_RUNTIME_OBJECT_ID_START + 200,
        existingCompactMax=601,
    )

    mapper = object.__new__(
        PostgresqlFlatMapper
    )

    mapper.db = db

    protocolId = mapper.allocateProjectProtocolId(
        projectId=31
    )

    assert protocolId == 602

    updateCalls = [
        call
        for call in db.executeCalls
        if call["query"].startswith(
            "UPDATE project_object_id_counters"
        )
    ]

    assert len(updateCalls) == 1
    assert updateCalls[0]["params"] == (
        603,
        31,
    )

