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
from app.backend.mapper.scipion_object_mapper import (
    ScipionObjectPostgresqlMapper,
)


class FakeDatabase:
    def __init__(self, rows=None):
        self.rows = list(
            rows or []
        )
        self.calls = []

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