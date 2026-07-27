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

from app.backend.mapper.postgresql_set_runtime_mapper import (
    PostgresqlSetRuntimeMapper,
)


class FakeDb:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row
        self.query = None
        self.params = None

    def fetchAll(self, query, params=None):
        self.query = " ".join(str(query).split())
        self.params = params

        if "FROM scipion_set_columns" in self.query:
            return [
                {
                    "labelProperty": "_tomoId",
                    "className": "String",
                    "valueType": "text",
                    "position": 0,
                },
                {
                    "labelProperty": "_score",
                    "className": "Float",
                    "valueType": "float",
                    "position": 1,
                },
                {
                    "labelProperty": "_filename",
                    "className": "String",
                    "valueType": "text",
                    "position": 2,
                },
            ]

        return self.rows

    def fetchOne(self, query, params=None):
        self.query = " ".join(str(query).split())
        self.params = params
        return self.row


def buildItem(row):
    return dict(row)


def test_SelectAllUsesScipionItemIdForIdOrdering():
    db = FakeDb(rows=[
        {
            "scipionItemId": 7,
            "values": {},
        },
    ])

    mapper = PostgresqlSetRuntimeMapper(
        db=db,
        setId=31,
        itemBuilder=buildItem,
    )

    result = mapper.selectAll(
        orderBy="id",
        iterate=False,
    )

    assert result[0]["scipionItemId"] == 7
    assert 'ORDER BY "scipionItemId" ASC' in db.query
    assert db.params == (31,)


def test_SelectAllSupportsJsonFieldEquality():
    db = FakeDb(rows=[])

    mapper = PostgresqlSetRuntimeMapper(
        db=db,
        setId=31,
        itemBuilder=buildItem,
    )

    mapper.selectAll(
        where='_tomoId="TS_01"',
        iterate=False,
    )

    assert '"values" ->> %s = %s' in db.query
    assert db.params == (
        31,
        "_tomoId",
        "TS_01",
    )


def test_SelectByIdUsesRuntimeItemId():
    db = FakeDb(row={
        "scipionItemId": 18,
        "values": {},
    })

    mapper = PostgresqlSetRuntimeMapper(
        db=db,
        setId=31,
        itemBuilder=buildItem,
    )

    item = mapper.selectById(18)

    assert item["scipionItemId"] == 18
    assert '"scipionItemId" = %s' in db.query
    assert db.params == (
        31,
        18,
    )


def test_MapperRequiresExactlyOneStorageScope():
    with pytest.raises(
            ValueError,
            match="Exactly one",
    ):
        PostgresqlSetRuntimeMapper(
            db=FakeDb(),
            itemBuilder=buildItem,
        )

    with pytest.raises(
            ValueError,
            match="Exactly one",
    ):
        PostgresqlSetRuntimeMapper(
            db=FakeDb(),
            setId=31,
            tableId=91,
            itemBuilder=buildItem,
        )



class FakeLogicalTableDb:
    def __init__(self):
        self.query = None
        self.params = None

    def fetchAll(self, query, params=None):
        self.query = " ".join(
            str(query).split()
        )
        self.params = params

        if (
                "FROM scipion_set_table_columns"
                in self.query
        ):
            return [
                {
                    "labelProperty": "_tiltAngle",
                    "className": "Float",
                    "valueType": "float",
                    "position": 0,
                },
            ]

        if (
                "FROM scipion_set_table_items"
                in self.query
        ):
            return [
                {
                    "id": 701,
                    "tableId": 91,
                    "scipionItemId": 3,
                    "enabled": True,
                    "label": "",
                    "comment": "",
                    "creation": None,
                    "values": {
                        "_tiltAngle": -45.0,
                    },
                    "createdAt": None,
                    "updatedAt": None,
                },
            ]

        return []

    def fetchOne(self, query, params=None):
        self.query = " ".join(
            str(query).split()
        )
        self.params = params

        if "FROM scipion_set_tables" in self.query:
            return {
                "properties": {
                    "source": "postgresql",
                    "parentItemId": 7,
                },
            }

        if "COUNT(*) AS count" in self.query:
            return {
                "count": 1,
            }

        if 'MAX("scipionItemId")' in self.query:
            return {
                "maxItemId": 3,
            }

        return None


def test_LogicalTableMapperReadsChildItems():
    db = FakeLogicalTableDb()

    mapper = PostgresqlSetRuntimeMapper(
        db=db,
        tableId=91,
        itemBuilder=buildItem,
    )

    items = mapper.selectAll(
        iterate=False,
    )

    assert len(items) == 1
    assert items[0]["scipionItemId"] == 3

    assert (
        "FROM scipion_set_table_items"
        in db.query
    )

    assert (
        'WHERE "tableId" = %s'
        in db.query
    )

    assert db.params == (91,)


def test_LogicalTableMapperUsesStoredProperties():
    mapper = PostgresqlSetRuntimeMapper(
        db=FakeLogicalTableDb(),
        tableId=91,
        itemBuilder=buildItem,
    )

    assert mapper.hasProperty("source")
    assert (
        mapper.getProperty("source")
        == "postgresql"
    )

    assert mapper.getPropertyKeys() == [
        "parentItemId",
        "source",
    ]


def test_SelectAllSupportsNumericComparison():
    db = FakeDb(
        rows=[]
    )

    mapper = PostgresqlSetRuntimeMapper(
        db=db,
        setId=31,
        itemBuilder=buildItem,
    )

    mapper.selectAll(
        where="_score > 0.5",
        iterate=False,
    )

    assert (
        'NULLIF("values" ->> %s, \'\')'
        '::DOUBLE PRECISION > %s'
        in db.query
    )

    assert db.params == (
        31,
        "_score",
        0.5,
    )


def test_UnsupportedWhereExpressionFailsExplicitly():
    mapper = PostgresqlSetRuntimeMapper(
        db=FakeDb(),
        setId=31,
        itemBuilder=buildItem,
    )

    with pytest.raises(
            NotImplementedError
    ):
        mapper.selectAll(
            where=(
                "_score BETWEEN "
                "0.1 AND 0.5"
            ),
            iterate=False,
        )



def test_UniqueReturnsParallelListsForDistinctRows():
    db = FakeDb(
        rows=[
            {
                "value_0": "TS_01",
                "value_1": 7,
            },
            {
                "value_0": "TS_02",
                "value_1": 8,
            },
        ]
    )

    mapper = PostgresqlSetRuntimeMapper(
        db=db,
        setId=31,
        itemBuilder=buildItem,
    )

    result = mapper.unique(
        [
            "_tomoId",
            "id",
        ],
        where="id > 6",
    )

    assert result == {
        "_tomoId": [
            "TS_01",
            "TS_02",
        ],
        "id": [
            7,
            8,
        ],
    }

    assert (
        'SELECT DISTINCT '
        '"values" ->> %s AS "value_0", '
        '"scipionItemId" AS "value_1"'
        in db.query
    )

    assert (
        '"scipionItemId" > %s'
        in db.query
    )

    assert db.params == (
        "_tomoId",
        31,
        6,
    )


def test_UniqueReturnsListForSingleAttribute():
    db = FakeDb(
        rows=[
            {
                "value_0": "TS_01",
            },
            {
                "value_0": "TS_02",
            },
        ]
    )

    mapper = PostgresqlSetRuntimeMapper(
        db=db,
        setId=31,
        itemBuilder=buildItem,
    )

    result = mapper.unique(
        "_tomoId"
    )

    assert result == [
        "TS_01",
        "TS_02",
    ]

    assert db.params == (
        "_tomoId",
        31,
    )


def test_AggregateGroupsSetItemsByFilename():
    db = FakeDb(
        rows=[
            {
                "count": 2,
                "_filename": (
                    "/data/particles-001.mrcs"
                ),
            },
            {
                "count": 3,
                "_filename": (
                    "/data/particles-002.mrcs"
                ),
            },
        ]
    )

    mapper = PostgresqlSetRuntimeMapper(
        db=db,
        setId=31,
        itemBuilder=buildItem,
    )

    result = mapper.aggregate(
        ["count"],
        "_filename",
        ["_filename"],
    )

    assert result == [
        {
            "count": 2,
            "_filename": (
                "/data/particles-001.mrcs"
            ),
        },
        {
            "count": 3,
            "_filename": (
                "/data/particles-002.mrcs"
            ),
        },
    ]

    assert (
        'COUNT("values" ->> %s) '
        'AS "count"'
        in db.query
    )

    assert (
        '"values" ->> %s '
        'AS "_filename"'
        in db.query
    )

    assert (
        "FROM scipion_set_items"
        in db.query
    )

    assert (
        'WHERE "setId" = %s'
        in db.query
    )

    assert "GROUP BY 2" in db.query

    assert db.params == (
        "_filename",
        "_filename",
        31,
    )


def test_AggregateSupportsMultipleNumericOperations():
    db = FakeDb(
        rows=[
            {
                "min": 0.25,
                "max": 2.5,
            },
        ]
    )

    mapper = PostgresqlSetRuntimeMapper(
        db=db,
        setId=31,
        itemBuilder=buildItem,
    )

    result = mapper.aggregate(
        [
            "min",
            "max",
        ],
        "_score",
    )

    assert result == [
        {
            "min": 0.25,
            "max": 2.5,
        },
    ]

    assert (
        "MIN("
        'NULLIF("values" ->> %s, \'\')'
        "::DOUBLE PRECISION"
        ') AS "min"'
        in db.query
    )

    assert (
        "MAX("
        'NULLIF("values" ->> %s, \'\')'
        "::DOUBLE PRECISION"
        ') AS "max"'
        in db.query
    )

    assert "GROUP BY" not in db.query

    assert db.params == (
        "_score",
        "_score",
        31,
    )


def test_AggregateRejectsUnsupportedOperation():
    mapper = PostgresqlSetRuntimeMapper(
        db=FakeDb(),
        setId=31,
        itemBuilder=buildItem,
    )

    with pytest.raises(
            ValueError,
            match=(
                "Unsupported PostgreSQL "
                "aggregate operation"
            ),
    ):
        mapper.aggregate(
            "median",
            "_score",
        )


def test_LogicalTableMapperRefreshesRecreatedTableId():
    currentScope = {
        "tableId": 91,
    }

    db = FakeLogicalTableDb()

    mapper = PostgresqlSetRuntimeMapper(
        db=db,
        tableId=91,
        tableIdResolver=(
            lambda: currentScope[
                "tableId"
            ]
        ),
        itemBuilder=buildItem,
    )

    mapper.selectAll(
        iterate=False
    )

    assert mapper.tableId == 91
    assert db.params == (91,)

    # Simulate ScipionSetPostgresqlMapper replacing
    # scipion_set_tables and creating a new row id.
    currentScope["tableId"] = 191

    mapper.selectAll(
        iterate=False
    )

    assert mapper.tableId == 191
    assert mapper._scopeId == 191
    assert db.params == (191,)
