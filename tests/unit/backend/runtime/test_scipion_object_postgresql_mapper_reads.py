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

from app.backend.mapper.scipion_object_mapper import (
    ScipionObjectPostgresqlMapper,
)


class FakeDatabase:
    def __init__(
            self,
            rows=None,
            row=None,
    ):
        self.rows = list(
            rows or []
        )

        self.row = row
        self.calls = []
        self.transactionCalls = 0

    @contextmanager
    def transaction(self):
        self.transactionCalls += 1
        yield self

    def fetchOne(
            self,
            query,
            values,
    ):
        self.calls.append({
            "query": query,
            "values": values,
        })

        if self.row is None:
            return None

        return dict(
            self.row
        )

    def fetchAll(
            self,
            query,
            values,
    ):
        self.calls.append({
            "query": query,
            "values": values,
        })

        return list(
            self.rows
        )


def test_GetStoredObjectSubtreeUsesRecursiveQuery():
    expectedRows = [{
        "id": 10,
        "scipionObjId": 701,
    }]

    database = FakeDatabase(
        rows=expectedRows,
    )

    mapper = (
        ScipionObjectPostgresqlMapper(
            database
        )
    )

    result = (
        mapper
        .getStoredObjectSubtreeByScipionObjId(
            projectId=7,
            scipionObjId=701,
        )
    )

    assert result == expectedRows
    assert len(database.calls) == 1

    call = database.calls[0]

    assert call["values"] == (
        7,
        701,
    )

    assert (
        "WITH RECURSIVE selected_root"
        in call["query"]
    )

    assert (
        'protocol."protocolId"'
        in call["query"]
    )

    assert (
        'child."parentObjectId" = object_tree.id'
        in call["query"]
    )

    assert (
        "ORDER BY depth ASC"
        in call["query"]
    )

    assert (
        'selected_root."rootParentScipionObjId"'
        in call["query"]
    )

    assert (
        call["query"].count(
            'object_tree."rootParentScipionObjId"'
        )
        == 1
    )

    assert (
        call["query"].count(
            '"rootParentScipionObjId"'
        )
        == 4
    )


def test_ListCanonicalStoredObjectRowsFiltersClassAfterCanonicalSelection():
    expectedRows = [{
        "id": 10,
        "runtimeObjectId": 700,
        "className": "FakeComposite",
    }]

    database = FakeDatabase(rows=expectedRows)
    mapper = ScipionObjectPostgresqlMapper(database)

    result = mapper.listCanonicalStoredObjectRows(
        projectId=7,
        className="FakeComposite",
    )

    assert result == expectedRows
    assert len(database.calls) == 1

    call = database.calls[0]

    assert call["values"] == (
        7,
        "FakeComposite",
    )

    assert (
        'DISTINCT ON (object_row."scipionObjId")'
        in call["query"]
    )

    assert (
        'ORDER BY object_row."scipionObjId",'
        in call["query"]
    )

    assert (
        "object_row.id DESC"
        in call["query"]
    )

    assert (
        'stored_set."objectId" = object_row.id'
        in call["query"]
    )

    assert (
        'WHERE NOT canonical."isStoredSet"'
        in call["query"]
    )

    assert (
        'AND canonical."className" = %s'
        in call["query"]
    )


def test_ListCanonicalStoredObjectRowsCanReturnAllClasses():
    database = FakeDatabase()
    mapper = ScipionObjectPostgresqlMapper(database)

    mapper.listCanonicalStoredObjectRows(projectId=7)

    call = database.calls[0]

    assert call["values"] == (7,)

    assert (
        'AND canonical."className" = %s'
        not in call["query"]
    )


def test_ListProtocolTreeOutputRowsExcludesStoredSetRoots():
    expectedRows = [
        {
            "outputName": "outputVolume",
            "rootObjectId": 81,
            "scipionObjId": 91,
            "className": "Volume",
            "value": None,
            "label": "",
            "comment": "",
            "metadata": {
                "mapperKind": "tree",
            },
        },
    ]

    database = FakeDatabase(
        rows=expectedRows
    )

    mapper = ScipionObjectPostgresqlMapper(
        database
    )

    result = mapper.listProtocolTreeOutputRows(
        projectId=7,
        protocolDbId=31,
    )

    assert result == expectedRows
    assert len(database.calls) == 1
    assert database.transactionCalls == 0

    call = database.calls[0]

    assert call["values"] == (
        7,
        31,
    )

    assert (
        "FROM scipion_objects object_row"
        in call["query"]
    )

    assert (
        'object_row."parentObjectId" IS NULL'
        in call["query"]
    )

    assert (
        "NOT EXISTS"
        in call["query"]
    )

    assert (
        "FROM scipion_sets stored_set"
        in call["query"]
    )

    assert (
        'stored_set."objectId" = object_row.id'
        in call["query"]
    )

    assert (
        'ORDER BY "outputName"'
        in call["query"]
    )


def test_ListProtocolTreeOutputNameRowsExcludesStoredSetRoots():
    expectedRows = [
        {
            "outputName": "outputVolume",
        },
    ]

    database = FakeDatabase(rows=expectedRows)
    mapper = ScipionObjectPostgresqlMapper(database)

    result = mapper.listProtocolTreeOutputNameRows(projectId=7, protocolDbId=31)

    assert result == expectedRows
    assert len(database.calls) == 1
    assert database.transactionCalls == 0

    call = database.calls[0]

    assert call["values"] == (7, 31)
    assert 'AS "outputName"' in call["query"]
    assert "FROM scipion_objects object_row" in call["query"]
    assert 'object_row."projectId" = %s' in call["query"]
    assert 'object_row."protocolDbId" = %s' in call["query"]
    assert 'object_row."parentObjectId" IS NULL' in call["query"]
    assert "NOT EXISTS" in call["query"]
    assert "FROM scipion_sets stored_set" in call["query"]
    assert 'stored_set."objectId" = object_row.id' in call["query"]


def test_ListProtocolOutputFileRowsReadsSetAndTreeRoots():
    expectedRows = [
        {
            "file_name": "Runs/000010_Test/extra/output.sqlite",
        },
        {
            "file_name": "Runs/000010_Test/extra/output.mrc",
        },
    ]

    database = FakeDatabase(rows=expectedRows)
    mapper = ScipionObjectPostgresqlMapper(database)

    result = mapper.listProtocolOutputFileRows(projectId=7, protocolDbId=31)

    assert result == expectedRows
    assert len(database.calls) == 1
    assert database.transactionCalls == 0

    call = database.calls[0]
    query = " ".join(call["query"].split())

    assert call["values"] == (7, 31, 7, 31)
    assert "SELECT DISTINCT file_name" in query
    assert "FROM scipion_sets stored_set" in query
    assert "LEFT JOIN scipion_objects root_object" in query
    assert 'root_object.id = stored_set."objectId"' in query
    assert "root_object.metadata ->> 'fileName'" in query
    assert "UNION" in query
    assert "FROM scipion_objects object_row" in query
    assert "object_row.metadata ->> 'fileName'" in query
    assert 'object_row."parentObjectId" IS NULL' in query
    assert "file_name IS NOT NULL" in query
    assert "file_name <> ''" in query


def test_ListProjectTreeOutputRowsExcludesStoredSetRoots():
    expectedRows = [
        {
            "protocolId": "10",
            "id": 81,
            "scipionObjId": 91,
            "name": "outputVolume",
            "path": "outputVolume",
            "className": "Volume",
        },
    ]

    database = FakeDatabase(rows=expectedRows)
    mapper = ScipionObjectPostgresqlMapper(database)

    result = mapper.listProjectTreeOutputRows(projectId=7)

    assert result == expectedRows
    assert len(database.calls) == 1
    assert database.transactionCalls == 0

    call = database.calls[0]

    assert call["values"] == (7,)
    assert 'protocol_row."protocolId"' in call["query"]
    assert "FROM scipion_objects object_row" in call["query"]
    assert "JOIN protocols protocol_row" in call["query"]
    assert 'protocol_row.id = object_row."protocolDbId"' in call["query"]
    assert 'object_row."parentObjectId" IS NULL' in call["query"]
    assert "NOT EXISTS" in call["query"]
    assert "FROM scipion_sets stored_set" in call["query"]
    assert 'stored_set."objectId" = object_row.id' in call["query"]
    assert 'ORDER BY protocol_row."protocolId", object_row.path' in call["query"]


def test_DeleteProtocolOutputSnapshotsUsesSingleTransaction():
    class SnapshotCursor:
        def __init__(self, rowcount):
            self.rowcount = rowcount

    class SnapshotDatabase:
        def __init__(self):
            self.calls = []
            self.transactionCalls = 0
            self.rowcounts = iter([1, 3, 0, 2])

        @contextmanager
        def transaction(self):
            self.transactionCalls += 1
            yield self

        def execute(self, query, values, commit=True):
            self.calls.append({
                "query": query,
                "values": values,
                "commit": commit,
            })

            return SnapshotCursor(next(self.rowcounts))

    database = SnapshotDatabase()
    mapper = ScipionObjectPostgresqlMapper(database)

    result = mapper.deleteProtocolOutputSnapshots(
        projectId=7,
        protocolDbId=31,
        outputNames=[
            "outputMask",
            "outputParticles",
        ],
    )

    assert result == [
        {
            "outputName": "outputMask",
            "setsDeleted": 1,
            "objectsDeleted": 3,
        },
        {
            "outputName": "outputParticles",
            "setsDeleted": 0,
            "objectsDeleted": 2,
        },
    ]

    assert database.transactionCalls == 1
    assert len(database.calls) == 4
    assert all(call["commit"] is False for call in database.calls)

    firstSetDelete = database.calls[0]
    firstObjectDelete = database.calls[1]
    secondSetDelete = database.calls[2]
    secondObjectDelete = database.calls[3]

    assert "DELETE FROM scipion_sets" in firstSetDelete["query"]
    assert firstSetDelete["values"] == (7, 31, "outputMask")

    assert "DELETE FROM scipion_objects" in firstObjectDelete["query"]
    assert "CHAR_LENGTH(%s) + 1" in firstObjectDelete["query"]
    assert firstObjectDelete["values"] == (7, 31, "outputMask", "outputMask", "outputMask")

    assert "DELETE FROM scipion_sets" in secondSetDelete["query"]
    assert secondSetDelete["values"] == (7, 31, "outputParticles")

    assert "DELETE FROM scipion_objects" in secondObjectDelete["query"]
    assert secondObjectDelete["values"] == (7, 31, "outputParticles", "outputParticles", "outputParticles")


def test_DeleteProtocolOutputMetadataUsesSingleScopedTransaction():
    class CleanupCursor:
        def __init__(self, rowcount):
            self.rowcount = rowcount

    class CleanupDatabase:
        def __init__(self):
            self.calls = []
            self.transactionCalls = 0
            self.rowcounts = iter([0, 0, 0, 0, 0, 0, 2, 5])

        @contextmanager
        def transaction(self):
            self.transactionCalls += 1
            yield self

        def fetchAll(self, query, values):
            self.calls.append({
                "operation": "fetchAll",
                "query": query,
                "values": values,
            })

            return [
                {
                    "id": 71,
                },
                (
                    72,
                ),
            ]

        def execute(self, query, values, commit=True):
            self.calls.append({
                "operation": "execute",
                "query": query,
                "values": values,
                "commit": commit,
            })

            return CleanupCursor(next(self.rowcounts))

    database = CleanupDatabase()
    mapper = ScipionObjectPostgresqlMapper(database)

    result = mapper.deleteProtocolOutputMetadata(projectId=7, protocolDbId=31)

    assert result == {
        "setsDeleted": 2,
        "objectsDeleted": 5,
    }

    assert database.transactionCalls == 1
    assert len(database.calls) == 9

    setRead = database.calls[0]

    assert setRead["operation"] == "fetchAll"
    assert setRead["values"] == (7, 31)
    assert "SELECT id" in setRead["query"]
    assert "FROM scipion_sets" in setRead["query"]
    assert '"projectId" = %s' in setRead["query"]
    assert '"protocolDbId" = %s' in setRead["query"]

    executeCalls = database.calls[1:]

    assert all(call["operation"] == "execute" for call in executeCalls)
    assert all(call["commit"] is False for call in executeCalls)

    expectedSetTables = [
        "scipion_set_table_items",
        "scipion_set_table_columns",
        "scipion_set_tables",
        "scipion_set_items",
        "scipion_set_columns",
        "scipion_set_properties",
        "scipion_sets",
    ]

    for call, tableName in zip(executeCalls[:7], expectedSetTables):
        assert f"DELETE FROM {tableName}" in call["query"]
        assert call["values"] == ([71, 72],)

    objectDelete = executeCalls[7]

    assert objectDelete["values"] == (7, 31, 7, 31)
    assert "WITH RECURSIVE object_tree" in objectDelete["query"]
    assert "FROM scipion_objects object_row" in objectDelete["query"]
    assert 'object_row."projectId" = %s' in objectDelete["query"]
    assert 'object_row."protocolDbId" = %s' in objectDelete["query"]
    assert 'child."parentObjectId" = parent.id' in objectDelete["query"]
    assert 'child."projectId" = %s' in objectDelete["query"]
    assert 'child."protocolDbId" = %s' in objectDelete["query"]
    assert "DELETE FROM protocols" not in objectDelete["query"]


def test_DeleteStoredObjectSubtreesUsesRecursiveSafeDelete():
    database = FakeDatabase(
        row={
            "deletedObjectsCount": 3,
            "deletedRelationsCount": 2,
        },
    )

    mapper = ScipionObjectPostgresqlMapper(
        database
    )

    result = mapper.deleteStoredObjectSubtreesByScipionObjId(
        projectId=7,
        scipionObjId=700,
    )

    assert result == {
        "deletedObjectsCount": 3,
        "deletedRelationsCount": 2,
    }

    assert database.transactionCalls == 1
    assert len(database.calls) == 1

    call = database.calls[0]

    assert call["values"] == (
        7,
        700,
        7,
        7,
        7,
    )

    assert (
        "WITH RECURSIVE selected_roots"
        in call["query"]
    )

    assert (
        'child."parentObjectId" = object_tree.id'
        in call["query"]
    )

    assert (
        call["query"].count(
            'FROM scipion_sets stored_set'
        )
        == 2
    )

    assert (
        'stored_set."objectId" = object_row.id'
        in call["query"]
    )

    assert (
        'stored_set."objectId" = child.id'
        in call["query"]
    )

    assert (
        "DELETE FROM scipion_relations"
        in call["query"]
    )

    assert (
        'relation_row."creatorObjId"'
        in call["query"]
    )

    assert (
        'relation_row."parentObjId"'
        in call["query"]
    )

    assert (
        'relation_row."childObjId"'
        in call["query"]
    )

    assert (
        "DELETE FROM scipion_objects"
        in call["query"]
    )