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
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class DatabaseStub:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.calls = []

    def fetchAll(self, query, params=None):
        self.calls.append({
            "query": " ".join(str(query).split()),
            "params": params,
        })

        return list(self.rows)


def test_ListProjectTomogramCandidateItemRows():
    expectedRows = [
        {
            "setId": 11,
            "projectId": 7,
            "protocolDbId": 500,
            "outputName": "outputTomograms",
            "setClassName": "SetOfTomograms",
            "itemClassName": "Tomogram",
            "scipionItemId": 1,
        },
    ]

    database = DatabaseStub(rows=expectedRows)
    mapper = ScipionSetPostgresqlMapper(db=database)

    result = mapper.listProjectTomogramCandidateItemRows(projectId=7)

    assert result == expectedRows
    assert len(database.calls) == 1

    call = database.calls[0]
    query = call["query"]

    assert call["params"] == (7,)
    assert "FROM scipion_sets s" in query
    assert "JOIN scipion_set_items i" in query
    assert 'i."setId" = s.id' in query
    assert 'WHERE s."projectId" = %s' in query
    assert "LIKE '%%tomogram%%'" in query
    assert "LIKE '%%volume%%'" in query
    assert 's."protocolDbId" ASC' in query
    assert 's."outputName" ASC' in query
    assert 'i."scipionItemId" ASC' in query