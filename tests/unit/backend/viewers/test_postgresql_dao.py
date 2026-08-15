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

import importlib
import numpy as np

import pytest


class FakeDb:
    def __init__(self, countsByTableId=None):
        self.countsByTableId = countsByTableId or {}
        self.fetchOneCalls = []

    def fetchOne(self, sql, params=None):
        self.fetchOneCalls.append(
            {
                "sql": sql,
                "params": params,
            }
        )

        tableId = None
        if params:
            try:
                tableId = int(params[0])
            except Exception:
                tableId = None

        return {"count": self.countsByTableId.get(tableId, 0)}


class FakeSetMapper:
    def __init__(
        self,
        storedSet,
        logicalTables=None,
        columnsByTableId=None,
        itemsByTableId=None,
    ):
        self.storedSet = storedSet
        self.logicalTables = logicalTables or []
        self.columnsByTableId = columnsByTableId or {}
        self.itemsByTableId = itemsByTableId or {}
        self.getStoredSetCalls = []
        self.listStoredSetTablesCalls = []
        self.getStoredSetTableColumnsCalls = []
        self.getStoredSetTableItemsCalls = []

    def getStoredSet(self, projectId, protocolDbId, outputName, limit=None, offset=0):
        self.getStoredSetCalls.append(
            {
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "outputName": outputName,
                "limit": limit,
                "offset": offset,
            }
        )

        storedSet = dict(self.storedSet)
        items = list(storedSet.get("items") or [])
        start = max(0, int(offset or 0))

        if limit is None:
            storedSet["items"] = items[start:]
        else:
            storedSet["items"] = items[start:start + int(limit)]

        return storedSet

    def listStoredSetTables(self, setId):
        self.listStoredSetTablesCalls.append(setId)
        return list(self.logicalTables)

    def getStoredSetTableColumns(self, tableId):
        self.getStoredSetTableColumnsCalls.append(tableId)
        return list(self.columnsByTableId.get(int(tableId), []))

    def getStoredSetTableItems(self, tableId, limit=None, offset=0):
        self.getStoredSetTableItemsCalls.append(
            {
                "tableId": tableId,
                "limit": limit,
                "offset": offset,
            }
        )

        items = list(self.itemsByTableId.get(int(tableId), []))
        start = max(0, int(offset or 0))

        if limit is None:
            return items[start:]

        return items[start:start + int(limit)]


class FakeObjectManager:
    def __init__(self, hiddenLabels=None):
        self.hiddenLabels = set(hiddenLabels or [])

    def isLabelVisible(self, label):
        return label not in self.hiddenLabels


@pytest.fixture
def postgresqlDaoModule(authTestEnv):
    return importlib.import_module("app.backend.viewers.postgresql_dao")


def _makeStoredSet(setClassName="SetOfClasses3D", itemClassName="Class3D"):
    return {
        "id": 100,
        "setClassName": setClassName,
        "itemClassName": itemClassName,
        "columns": [
            {
                "labelProperty": "score",
                "position": 0,
                "className": "Float",
            },
        ],
        "items": [
            {
                "id": 1,
                "scipionItemId": 1,
                "enabled": True,
                "values": {
                    "score": 0.5,
                },
            },
            {
                "id": 2,
                "scipionItemId": 2,
                "enabled": True,
                "values": {
                    "score": 0.7,
                },
            },
        ],
        "properties": {
            "boxSize": 128,
            "itemsCount": 2,
        },
        "setProperties": [
            {
                "key": "samplingRate",
                "value": 1.25,
            },
        ],
    }


def _makeLogicalTables(rootItemClassName="Class3D", childItemClassName="Particle"):
    return [
        {
            "id": 1001,
            "name": "objects",
            "alias": "Root objects",
            "itemClassName": rootItemClassName,
        },
        {
            "id": 1002,
            "name": "Class001_Objects",
            "alias": "Class001 objects",
            "itemClassName": childItemClassName,
        },
    ]


def _makeColumnsByTableId():
    return {
        1001: [
            {
                "labelProperty": "score",
                "position": 0,
                "className": "Float",
            },
        ],
        1002: [
            {
                "labelProperty": "particleId",
                "position": 0,
                "className": "Integer",
            },
        ],
    }


def _makeItemsByTableId():
    return {
        1001: [
            {
                "id": 1,
                "scipionItemId": 1,
                "enabled": True,
                "values": {
                    "score": 0.5,
                },
            },
        ],
        1002: [
            {
                "id": 11,
                "scipionItemId": 11,
                "enabled": True,
                "values": {
                    "particleId": 101,
                },
            },
        ],
    }


def _buildDao(postgresqlDaoModule, monkeypatch, setMapper, db=None):
    db = db or FakeDb(countsByTableId={1001: 1, 1002: 1})
    monkeypatch.setattr(
        postgresqlDaoModule,
        "ScipionSetPostgresqlMapper",
        lambda dbConnection: setMapper,
    )

    return postgresqlDaoModule.PostgresqlDAO(
        db=db,
        projectId=1,
        protocolId=10,
        outputName="outputClasses",
    )


def _buildLogicalDao(
    postgresqlDaoModule,
    monkeypatch,
    setClassName="SetOfClasses3D",
    rootItemClassName="Class3D",
    childItemClassName="Particle",
):
    storedSet = _makeStoredSet(
        setClassName=setClassName,
        itemClassName=rootItemClassName,
    )
    logicalTables = _makeLogicalTables(
        rootItemClassName=rootItemClassName,
        childItemClassName=childItemClassName,
    )
    setMapper = FakeSetMapper(
        storedSet=storedSet,
        logicalTables=logicalTables,
        columnsByTableId=_makeColumnsByTableId(),
        itemsByTableId=_makeItemsByTableId(),
    )
    dao = _buildDao(postgresqlDaoModule, monkeypatch, setMapper)

    return dao, setMapper


def _getActionNames(table):
    return [
        action.getName()
        for action in table.getActions()
    ]


def test_GetTablesAddsPropertiesTable(postgresqlDaoModule, monkeypatch):
    dao, _setMapper = _buildLogicalDao(postgresqlDaoModule, monkeypatch)

    tables = dao.getTables()

    assert set(tables.keys()) == {"objects", "Class001_Objects", "Properties"}
    assert tables["Properties"].getAlias() == "Properties"
    assert dao._useLogicalTables is True
    assert dao._objectsType["Class3D"] == "SetOfClasses3D"
    assert dao._objectsType["Particle"] == "SetOfParticles"


def test_GetPropertiesTableRowsIncludesSelfAndSize(postgresqlDaoModule, monkeypatch):
    dao, _setMapper = _buildLogicalDao(postgresqlDaoModule, monkeypatch)
    dao.getTables()

    rowsByKey = {
        row["key"]: row["value"]
        for row in dao._getPropertiesRows()
    }

    assert rowsByKey["self"] == "SetOfClasses3D"
    assert rowsByKey["_size"] == "2"
    assert rowsByKey["samplingRate"] == "1.25"
    assert rowsByKey["boxSize"] == "128"


def test_GetPropertiesTableHasNoActions(postgresqlDaoModule, monkeypatch):
    dao, _setMapper = _buildLogicalDao(postgresqlDaoModule, monkeypatch)
    table = dao.getTables()["Properties"]

    dao.fillTable(table, FakeObjectManager())

    assert _getActionNames(table) == []


def test_GenerateTableActionsAddsParticleAction(postgresqlDaoModule, monkeypatch):
    dao, _setMapper = _buildLogicalDao(postgresqlDaoModule, monkeypatch)
    table = dao.getTables()["Class001_Objects"]

    dao.fillTable(table, FakeObjectManager())

    assert _getActionNames(table) == ["Particle"]


def test_GenerateTableActionsAddsRelionPseudoSubtomogramAction(
    postgresqlDaoModule,
    monkeypatch,
):
    storedSet = _makeStoredSet(
        setClassName="RelionSetOfPseudoSubtomograms",
        itemClassName="RelionPSubtomogram",
    )
    setMapper = FakeSetMapper(storedSet=storedSet)
    dao = _buildDao(postgresqlDaoModule, monkeypatch, setMapper)

    table = dao.getTables()["objects"]
    dao.fillTable(table, FakeObjectManager())

    assert dao._objectsType["RelionPSubtomogram"] == "RelionSetOfPseudoSubtomograms"
    assert _getActionNames(table) == ["RelionPSubtomogram"]


def test_GenerateTableActionsAddsVolumesForClass3D(postgresqlDaoModule, monkeypatch):
    dao, _setMapper = _buildLogicalDao(
        postgresqlDaoModule,
        monkeypatch,
        setClassName="SetOfClasses3D",
        rootItemClassName="Class3D",
        childItemClassName="Particle",
    )
    table = dao.getTables()["objects"]

    dao.fillTable(table, FakeObjectManager())

    actionNames = _getActionNames(table)
    assert "Class3D" in actionNames
    assert "Particle" in actionNames
    assert "Volumes" in actionNames


def test_GenerateTableActionsAddsAveragesForClass2D(postgresqlDaoModule, monkeypatch):
    dao, _setMapper = _buildLogicalDao(
        postgresqlDaoModule,
        monkeypatch,
        setClassName="SetOfClasses2D",
        rootItemClassName="Class2D",
        childItemClassName="Particle",
    )
    table = dao.getTables()["objects"]

    dao.fillTable(table, FakeObjectManager())

    actionNames = _getActionNames(table)
    assert "Class2D" in actionNames
    assert "Particle" in actionNames
    assert "Averages" in actionNames


def test_GetTableWithAdditionalInfoReturnsCompatibilityTuple(postgresqlDaoModule, monkeypatch):
    dao, _setMapper = _buildLogicalDao(postgresqlDaoModule, monkeypatch)

    table, displayColumns = dao.getTableWithAdditionalInfo()

    assert table is None
    assert displayColumns == postgresqlDaoModule.ADITIONAL_INFO_DISPLAY_COLUMN_LIST
    assert displayColumns == ["_size", "id"]


def test_PostgresqlDaoNormalizesTypedStringsFromDatabase(postgresqlDaoModule):
    dao = object.__new__(postgresqlDaoModule.PostgresqlDAO)

    matrixText = (
        "[[    1.       0.       0.   -2275.2 ]\n"
        " [    0.       1.       0.   -1616.34]\n"
        " [    0.       0.       1.       0.  ]\n"
        " [    0.       0.       0.       1.  ]]"
    )

    item = {
        "id": 1,
        "enabled": "False",
        "values": {
            "flag": "False",
            "score": "3.5",
            "count": "7",
            "transform_matrix": matrixText,
        },
    }

    columns = [
        {
            "labelProperty": "flag",
            "position": 0,
            "className": "Boolean",
        },
        {
            "labelProperty": "score",
            "position": 1,
            "className": "Float",
        },
        {
            "labelProperty": "count",
            "position": 2,
            "className": "Integer",
        },
        {
            "labelProperty": "transform_matrix",
            "position": 3,
            "className": "Matrix",
        },
    ]

    row = dao._itemToRow(item, columns)

    assert row["enabled"] is False
    assert row["flag"] is False
    assert row["score"] == pytest.approx(3.5)
    assert row["count"] == 7

    assert isinstance(row["transform_matrix"], np.ndarray)
    assert row["transform_matrix"].shape == (4, 4)
    assert row["transform_matrix"][0, 3] == pytest.approx(-2275.2)
    assert row["transform_matrix"][1, 3] == pytest.approx(-1616.34)


def test_PostgresqlDaoParsesJsonMatrixString(postgresqlDaoModule):
    dao = object.__new__(postgresqlDaoModule.PostgresqlDAO)

    matrix = dao._normalizeValue(
        "transform_matrix",
        "[[1, 0, 0, -1.5], [0, 1, 0, 2.5], [0, 0, 1, 0], [0, 0, 0, 1]]",
        {"className": "Matrix"},
    )

    assert isinstance(matrix, np.ndarray)
    assert matrix.shape == (4, 4)
    assert matrix[0, 3] == pytest.approx(-1.5)
    assert matrix[1, 3] == pytest.approx(2.5)


def test_PostgresqlDaoDoesNotUseEvalForMatrixStrings(postgresqlDaoModule):
    dao = object.__new__(postgresqlDaoModule.PostgresqlDAO)

    matrix = dao._toNumpyMatrix("__import__('os').system('echo unsafe')")

    assert isinstance(matrix, np.ndarray)
    assert matrix.size == 0