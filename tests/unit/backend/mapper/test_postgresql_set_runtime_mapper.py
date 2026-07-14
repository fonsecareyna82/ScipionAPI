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
        "id",
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


def test_UnsupportedWhereExpressionFailsExplicitly():
    mapper = PostgresqlSetRuntimeMapper(
        db=FakeDb(),
        setId=31,
        itemBuilder=buildItem,
    )

    with pytest.raises(NotImplementedError):
        mapper.selectAll(
            where="_score > 0.5",
            iterate=False,
        )