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
from contextlib import contextmanager
from unittest.mock import Mock

from app.backend.mapper.postgresql import (
    POSTGRESQL_PROTOCOL_ID_START,
    POSTGRESQL_RUNTIME_OBJECT_ID_START,
    PostgresqlFlatMapper,
)
from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class FakeCursor:
    def __init__(
            self,
            rowcount=0,
    ):
        self.rowcount = rowcount


class FakeDatabase:
    def __init__(
            self,
            projectExists=True,
            rowCounts=None,
    ):
        self.projectExists = projectExists
        self.rowCounts = dict(
            rowCounts or {}
        )

        self.calls = []
        self.transactionCalls = 0
        self.cursor = FakeCursor()

    @contextmanager
    def transaction(self):
        self.transactionCalls += 1
        yield self

    def fetchOne(
            self,
            query,
            values,
    ):
        normalizedQuery = " ".join(
            str(query).split()
        )

        self.calls.append({
            "operation": "fetchOne",
            "query": normalizedQuery,
            "values": values,
        })

        if (
                "SELECT id FROM projects"
                in normalizedQuery
        ):
            if self.projectExists:
                return {
                    "id": int(
                        values[0]
                    ),
                }

            return None

        return None

    def execute(
            self,
            query,
            values,
            commit=True,
    ):
        normalizedQuery = " ".join(
            str(query).split()
        )

        self.calls.append({
            "operation": "execute",
            "query": normalizedQuery,
            "values": values,
            "commit": commit,
        })

        queryCounts = (
            (
                "DELETE FROM scipion_relations",
                "relations",
            ),
            (
                "DELETE FROM scipion_sets",
                "sets",
            ),
            (
                "DELETE FROM scipion_objects",
                "objects",
            ),
            (
                "DELETE FROM protocols",
                "protocols",
            ),
        )

        for queryPrefix, countName in queryCounts:
            if normalizedQuery.startswith(
                    queryPrefix
            ):
                self.cursor.rowcount = (
                    self.rowCounts.get(
                        countName,
                        0,
                    )
                )

                return self.cursor

        self.cursor.rowcount = 1

        return self.cursor


def buildRuntimeMapper():
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 7

    mapper.flatMapper = Mock()
    mapper.runtimeSetFactory = Mock()

    mapper._runtimeProtocolsById = {}

    return mapper


def test_DeleteProjectRuntimeDataClearsOnlyMappedProjectData():
    database = FakeDatabase(
        rowCounts={
            "relations": 4,
            "sets": 2,
            "objects": 9,
            "protocols": 3,
        },
    )

    mapper = PostgresqlFlatMapper(
        database
    )

    result = mapper.deleteProjectRuntimeData(
        projectId=7
    )

    assert result == {
        "deletedRelationsCount": 4,
        "deletedSetsCount": 2,
        "deletedObjectsCount": 9,
        "deletedProtocolsCount": 3,
    }

    assert database.transactionCalls == 1
    assert len(database.calls) == 6

    assert database.calls[0]["operation"] == (
        "fetchOne"
    )

    assert database.calls[0]["values"] == (
        7,
    )

    expectedDeletePrefixes = [
        "DELETE FROM scipion_relations",
        "DELETE FROM scipion_sets",
        "DELETE FROM scipion_objects",
        "DELETE FROM protocols",
    ]

    for index, expectedPrefix in enumerate(
            expectedDeletePrefixes,
            start=1,
    ):
        call = database.calls[index]

        assert call["operation"] == "execute"
        assert call["query"].startswith(
            expectedPrefix
        )

        assert call["values"] == (
            7,
        )

        assert call["commit"] is False

    counterCall = database.calls[5]

    assert counterCall["operation"] == "execute"

    assert counterCall["query"].startswith(
        "INSERT INTO project_object_id_counters"
    )

    assert counterCall["values"] == (
        7,
        POSTGRESQL_RUNTIME_OBJECT_ID_START,
        POSTGRESQL_PROTOCOL_ID_START,
    )

    assert counterCall["commit"] is False

    executedSql = " ".join(
        call["query"]
        for call in database.calls
    )

    assert "DELETE FROM projects" not in executedSql
    assert "DELETE FROM project_shares" not in executedSql
    assert "DELETE FROM protocol_tags" not in executedSql
    assert "DELETE FROM scipion_object_types" not in executedSql


def test_DeleteProjectRuntimeDataRejectsMissingProject():
    database = FakeDatabase(
        projectExists=False
    )

    mapper = PostgresqlFlatMapper(
        database
    )

    try:
        mapper.deleteProjectRuntimeData(
            projectId=7
        )
    except RuntimeError as error:
        assert str(error) == (
            "Cannot delete runtime data because "
            "PostgreSQL project 7 does not exist."
        )
    else:
        raise AssertionError(
            "Expected missing PostgreSQL project "
            "to raise RuntimeError"
        )

    assert database.transactionCalls == 1
    assert len(database.calls) == 1


def test_DeleteAllClearsPostgresqlAndRuntimeCaches():
    mapper = buildRuntimeMapper()

    operations = []

    mapper.flatMapper.deleteProjectRuntimeData.side_effect = (
        lambda projectId: (
            operations.append(
                "postgresql"
            )
            or {
                "deletedRelationsCount": 4,
                "deletedSetsCount": 2,
                "deletedObjectsCount": 9,
                "deletedProtocolsCount": 3,
            }
        )
    )

    mapper.runtimeSetFactory.clearCaches.side_effect = (
        lambda: operations.append(
            "runtimeCaches"
        )
    )

    outputObject = object()
    protocol = Mock()
    protocol.outputObject = outputObject

    mapper._runtimeProtocolsById = {
        101: protocol,
    }

    result = mapper.deleteAll()

    assert result is None

    assert operations == ["postgresql", "runtimeCaches"]

    mapper.flatMapper.deleteProjectRuntimeData.assert_called_once_with(
        7
    )

    mapper.runtimeSetFactory.clearCaches.assert_called_once_with()

    assert mapper._runtimeProtocolsById == {}

    assert protocol.outputObject is outputObject
    assert protocol.mock_calls == []


def test_DeleteAllKeepsRuntimeCachesWhenPostgresqlDeleteFails():
    mapper = buildRuntimeMapper()

    mapper.flatMapper.deleteProjectRuntimeData.side_effect = (
        RuntimeError(
            "PostgreSQL delete failed"
        )
    )

    cachedProtocol = object()

    mapper._runtimeProtocolsById = {
        101: cachedProtocol,
    }

    try:
        mapper.deleteAll()
    except RuntimeError as error:
        assert str(error) == (
            "PostgreSQL delete failed"
        )
    else:
        raise AssertionError(
            "Expected PostgreSQL delete failure "
            "to propagate"
        )

    mapper.runtimeSetFactory.clearCaches.assert_not_called()

    assert mapper._runtimeProtocolsById == {
        101: cachedProtocol,
    }

