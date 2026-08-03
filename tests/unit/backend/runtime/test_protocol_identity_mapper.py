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
import inspect

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.runtime.protocol_identity import ProtocolIdentityResolver


class FetchDatabaseStub:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def fetchOne(self, query, params=None):
        queryText = " ".join(
            str(query).split()
        )

        self.calls.append({
            "query": queryText,
            "params": params,
        })

        return self.row


class ForbiddenDatabase:
    def fetchOne(self, *args, **kwargs):
        raise AssertionError(
            "ProtocolIdentityResolver must not call db.fetchOne()"
        )

    def fetchAll(self, *args, **kwargs):
        raise AssertionError(
            "ProtocolIdentityResolver must not call db.fetchAll()"
        )

    def execute(self, *args, **kwargs):
        raise AssertionError(
            "ProtocolIdentityResolver must not call db.execute()"
        )


class IdentityMapperStub:
    def __init__(self):
        self.db = ForbiddenDatabase()
        self.calls = []

    def getProjectProtocolByDbId(self, projectId, protocolDbId):
        self.calls.append({
            "method": "getProjectProtocolByDbId",
            "projectId": projectId,
            "protocolDbId": protocolDbId,
        })

        if int(protocolDbId) != 31:
            return None

        return {
            "id": 31,
            "protocolId": "19",
        }

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        self.calls.append({
            "method": "getProjectProtocolByProtocolId",
            "projectId": projectId,
            "protocolId": protocolId,
        })

        if str(protocolId) != "19":
            return None

        return {
            "id": 31,
            "protocolId": "19",
        }


class RuntimeMapperStub:
    def __init__(self, flatMapper):
        self.db = flatMapper.db
        self.flatMapper = flatMapper


def test_FlatMapperReadsProjectProtocolByDbId():
    database = FetchDatabaseStub(
        row={
            "id": 31,
            "projectId": 7,
            "protocolId": "19",
            "protocolClassName": "TestProtocol",
            "status": "saved",
            "params": {},
            "parentIds": [],
            "childIds": [],
            "relationsSynchronized": False,
            "createdAt": None,
            "updatedAt": None,
        }
    )

    mapper = object.__new__(
        PostgresqlFlatMapper
    )

    mapper.db = database

    result = mapper.getProjectProtocolByDbId(
        projectId=7,
        protocolDbId=31,
    )

    assert result["id"] == 31
    assert result["projectId"] == 7
    assert result["protocolId"] == "19"

    assert len(database.calls) == 1

    call = database.calls[0]

    assert call["params"] == (
        7,
        31,
    )

    assert "FROM protocols" in call["query"]
    assert '"projectId" = %s' in call["query"]
    assert "AND id = %s" in call["query"]
    assert '"protocolId" = %s' not in call["query"]


def test_ProtocolIdentityResolverDelegatesToMapper():
    mapper = IdentityMapperStub()

    resolver = ProtocolIdentityResolver(
        mapper=mapper,
        projectId=7,
    )

    assert resolver.getProtocolRowByDbId(
        31
    ) == {
        "id": 31,
        "protocolId": "19",
    }

    assert resolver.getProtocolRowByScipionProtocolId(
        19
    ) == {
        "id": 31,
        "protocolId": "19",
    }

    assert mapper.calls == [
        {
            "method": "getProjectProtocolByDbId",
            "projectId": 7,
            "protocolDbId": 31,
        },
        {
            "method": "getProjectProtocolByProtocolId",
            "projectId": 7,
            "protocolId": "19",
        },
    ]

    source = inspect.getsource(
        ProtocolIdentityResolver
    )

    assert "getProjectProtocolByDbId" in source
    assert "getProjectProtocolByProtocolId" in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source


def test_ProtocolIdentityResolverUsesRuntimeFlatMapper():
    flatMapper = IdentityMapperStub()

    resolver = ProtocolIdentityResolver(
        mapper=RuntimeMapperStub(
            flatMapper
        ),
        projectId=7,
    )

    assert resolver.resolveScipionProtocolId(
        31
    ) == 19

    assert resolver.resolvePostgresqlProtocolDbId(
        19
    ) == 31

    assert flatMapper.calls == [
        {
            "method": "getProjectProtocolByDbId",
            "projectId": 7,
            "protocolDbId": 31,
        },
        {
            "method": "getProjectProtocolByProtocolId",
            "projectId": 7,
            "protocolId": "19",
        },
    ]


def test_ProtocolIdentityResolverKeepsDbOnlyCompatibility():
    database = FetchDatabaseStub(
        row={
            "id": 31,
            "protocolId": "19",
        }
    )

    resolver = ProtocolIdentityResolver(
        projectId=7,
        db=database,
    )

    result = resolver.getProtocolRowByDbId(
        31
    )

    assert result == {
        "id": 31,
        "protocolId": "19",
    }

    assert len(database.calls) == 1
    assert database.calls[0]["params"] == (
        7,
        31,
    )


def test_ProtocolIdentityResolverSupportsPartialMapperWithDatabaseOnly():
    database = FetchDatabaseStub(
        row={
            "id": 500,
            "protocolId": "10",
        }
    )

    class PartialMapper:
        def __init__(self, db):
            self.db = db

    resolver = ProtocolIdentityResolver(
        mapper=PartialMapper(database),
        projectId=7,
    )

    assert resolver.resolveScipionProtocolId(500) == 10
    assert resolver.resolvePostgresqlProtocolDbId(10) == 500

    assert len(database.calls) == 2

    dbIdCall = database.calls[0]

    assert dbIdCall["params"] == (
        7,
        500,
    )

    assert "FROM protocols" in dbIdCall["query"]
    assert "AND id = %s" in dbIdCall["query"]

    protocolIdCall = database.calls[1]

    assert protocolIdCall["params"] == (
        7,
        "10",
    )

    assert "FROM protocols" in protocolIdCall["query"]
    assert 'AND "protocolId" = %s' in protocolIdCall["query"]