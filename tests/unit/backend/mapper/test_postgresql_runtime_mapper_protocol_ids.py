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
import sqlite3
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


class FakeProject:
    def __init__(self, projectPath, dbPath=None):
        self.path = str(projectPath)
        self.dbPath = str(dbPath) if dbPath is not None else None

    def getPath(self):
        return self.path

    def getDbPath(self):
        return self.dbPath


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


class FakeSqliteObjectsDb:
    def __init__(self, existingRow=None):
        self.existingRow = existingRow
        self.cursor = SimpleNamespace(rowcount=1)
        self.commands = []

    def executeCommand(self, query, params=None):
        self.commands.append({
            "query": " ".join(str(query).split()),
            "params": params,
        })

    def selectObjectById(self, objId):
        return self.existingRow


class FakeWriteFallbackMapper:
    def __init__(self, db):
        self.db = db


def createProjectSqlite(projectPath, occupiedIds=()):
    projectPath.mkdir(parents=True, exist_ok=True)
    sqlitePath = projectPath / "project.sqlite"

    with sqlite3.connect(sqlitePath) as connection:
        connection.execute(
            """
            CREATE TABLE Objects (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER,
                name TEXT,
                classname TEXT,
                value TEXT,
                label TEXT,
                comment TEXT,
                creation TEXT
            )
            """
        )

        for objId in occupiedIds:
            connection.execute(
                """
                INSERT INTO Objects (
                    id,
                    parent_id,
                    name,
                    classname,
                    value,
                    label,
                    comment,
                    creation
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(objId),
                    600,
                    "600.status",
                    "String",
                    "finished",
                    "",
                    "",
                    None,
                ),
            )

    return sqlitePath


def buildRuntimeMapper(project, protocolIds=None, objectIds=None):
    mapper = object.__new__(PostgresqlRuntimeMapper)
    mapper.projectId = 31
    mapper.project = project
    mapper.flatMapper = FakeFlatMapper(
        protocolIds=protocolIds,
        objectIds=objectIds,
    )
    mapper.readFallbackMapper = None
    mapper.writeFallbackMapper = None

    return mapper


def test_ExistsInProjectSqliteReadsPhysicalDatabaseWithoutFallbackMapper(
        tmp_path,
):
    projectPath = tmp_path / "ImportedProject"
    sqlitePath = createProjectSqlite(
        projectPath,
        occupiedIds=[602],
    )

    project = FakeProject(
        projectPath=projectPath,
        dbPath=sqlitePath,
    )

    mapper = buildRuntimeMapper(project)

    assert mapper._existsInProjectSqlite(602) is True
    assert mapper._existsInProjectSqlite(603) is False


def test_ExistsInProjectSqliteResolvesRelativeDatabasePath(
        tmp_path,
):
    projectPath = tmp_path / "ImportedProject"

    createProjectSqlite(
        projectPath,
        occupiedIds=[602],
    )

    project = FakeProject(
        projectPath=projectPath,
        dbPath="project.sqlite",
    )

    mapper = buildRuntimeMapper(project)

    assert mapper._getProjectSqlitePath() == str(
        projectPath / "project.sqlite"
    )

    assert mapper._existsInProjectSqlite(602) is True


def test_ExistsInProjectSqliteReturnsFalseWhenDatabaseDoesNotExist(
        tmp_path,
):
    projectPath = tmp_path / "MissingProject"

    project = FakeProject(
        projectPath=projectPath,
        dbPath=projectPath / "project.sqlite",
    )

    mapper = buildRuntimeMapper(project)

    assert mapper._existsInProjectSqlite(602) is False


def test_EnsureObjIdSkipsOccupiedProjectSqliteIdsForProtocol(
        tmp_path,
):
    projectPath = tmp_path / "ImportedProject"

    sqlitePath = createProjectSqlite(
        projectPath,
        occupiedIds=[
            602,
            603,
            604,
        ],
    )

    project = FakeProject(
        projectPath=projectPath,
        dbPath=sqlitePath,
    )

    mapper = buildRuntimeMapper(
        project,
        protocolIds=[
            602,
            603,
            604,
            605,
        ],
    )

    protocol = ExampleProtocol()

    protocolId = mapper._ensureObjId(protocol)

    assert protocolId == 605
    assert protocol.getObjId() == 605

    assert mapper.flatMapper.protocolAllocationCalls == [
        31,
        31,
        31,
        31,
    ]


def test_EnsureObjIdKeepsExistingProtocolIdentity(
        tmp_path,
):
    projectPath = tmp_path / "ImportedProject"

    sqlitePath = createProjectSqlite(
        projectPath,
        occupiedIds=[602],
    )

    project = FakeProject(
        projectPath=projectPath,
        dbPath=sqlitePath,
    )

    mapper = buildRuntimeMapper(
        project,
        protocolIds=[603],
    )

    protocol = ExampleProtocol(
        objId=777
    )

    protocolId = mapper._ensureObjId(protocol)

    assert protocolId == 777
    assert protocol.getObjId() == 777
    assert mapper.flatMapper.protocolAllocationCalls == []


def test_EnsureObjIdDoesNotCheckProjectSqliteForNonProtocol(
        tmp_path,
):
    projectPath = tmp_path / "ImportedProject"

    sqlitePath = createProjectSqlite(
        projectPath,
        occupiedIds=[602],
    )

    project = FakeProject(
        projectPath=projectPath,
        dbPath=sqlitePath,
    )

    mapper = buildRuntimeMapper(
        project,
        objectIds=[
            POSTGRESQL_RUNTIME_OBJECT_ID_START
        ],
    )

    mapper._existsInProjectSqlite = lambda objId: pytest.fail(
        "Non-protocol ids must not be checked against project.sqlite"
    )

    runtimeObject = ExampleObject()

    objectId = mapper._ensureObjId(
        runtimeObject
    )

    assert objectId == POSTGRESQL_RUNTIME_OBJECT_ID_START
    assert runtimeObject.getObjId() == POSTGRESQL_RUNTIME_OBJECT_ID_START
    assert mapper.flatMapper.objectAllocationCalls == [31]


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


def test_StoreProtocolInWriteFallbackRejectsOccupiedStringIdentity():
    sqliteDb = FakeSqliteObjectsDb(
        existingRow={
            "id": 602,
            "parent_id": 600,
            "name": "600.status",
            "classname": "String",
        }
    )

    mapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 31
    mapper.writeFallbackMapper = FakeWriteFallbackMapper(
        sqliteDb
    )

    protocol = ExampleProtocol(
        objId=602
    )

    with pytest.raises(RuntimeError) as error:
        mapper._storeProtocolInWriteFallback(
            protocol
        )

    assert str(error.value) == (
        "SQLite execution id collision for protocol 602: "
        "expected root class ExampleProtocol, found class String "
        "with parentId=600."
    )


def test_StoreProtocolInWriteFallbackCreatesFreeProtocolRoot():
    sqliteDb = FakeSqliteObjectsDb(
        existingRow=None
    )

    mapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 31
    mapper.writeFallbackMapper = FakeWriteFallbackMapper(
        sqliteDb
    )

    protocol = ExampleProtocol(
        objId=605
    )

    created = mapper._storeProtocolInWriteFallback(
        protocol
    )

    assert created is True

    insertCalls = [
        call
        for call in sqliteDb.commands
        if call["query"].startswith(
            "INSERT INTO Objects"
        )
    ]

    assert len(insertCalls) == 1
    assert insertCalls[0]["params"][0] == 605
    assert insertCalls[0]["params"][2] == "ExampleProtocol"