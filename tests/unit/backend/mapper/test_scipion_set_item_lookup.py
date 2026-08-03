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
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def fetchOne(self, query, params=None):
        self.calls.append({
            "query": " ".join(str(query).split()),
            "params": params,
        })

        return self.row


def test_GetStoredSetItemByRuntimeObjectId():
    expectedRow = {
        "scipionItemId": 10,
        "label": "Micrograph 10",
        "comment": "",
        "values": {
            "_location._filename": "micrograph_10.mrc",
        },
        "outputName": "outputMicrographs",
        "protocolId": "1",
    }

    database = DatabaseStub(row=expectedRow)
    mapper = ScipionSetPostgresqlMapper(db=database)

    result = mapper.getStoredSetItemByRuntimeObjectId(projectId=7, runtimeObjectId=3000000050, scipionItemId=10)

    assert result == expectedRow
    assert len(database.calls) == 1

    call = database.calls[0]
    query = call["query"]

    assert call["params"] == (7, 3000000050, 10)
    assert "FROM scipion_sets stored_set" in query
    assert "JOIN scipion_objects object_row" in query
    assert 'object_row."scipionObjId" = %s' in query
    assert 'item."scipionItemId" = %s' in query


def test_GetStoredSetItemByProtocolOutput():
    expectedRow = {
        "scipionItemId": 10,
        "label": "Micrograph 10",
        "comment": "",
        "values": {
            "_location._filename": "micrograph_10.mrc",
        },
        "outputName": "outputMicrographs",
        "protocolId": "1",
    }

    database = DatabaseStub(row=expectedRow)
    mapper = ScipionSetPostgresqlMapper(db=database)

    result = mapper.getStoredSetItemByProtocolOutput(projectId=7, protocolId=1, outputName="outputMicrographs", scipionItemId=10)

    assert result == expectedRow
    assert len(database.calls) == 1

    call = database.calls[0]
    query = call["query"]

    assert call["params"] == (7, "1", "outputMicrographs", 10)
    assert "FROM scipion_sets stored_set" in query
    assert "JOIN scipion_set_items item" in query
    assert 'protocol."protocolId"::text = %s' in query
    assert 'stored_set."outputName" = %s' in query
    assert 'item."scipionItemId" = %s' in query