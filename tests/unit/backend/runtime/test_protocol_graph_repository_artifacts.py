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
from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository


class FakeDb:
    def __init__(self):
        self.calls = []

    def fetchAll(self, query, params=None):
        queryText = " ".join(
            str(query).split()
        )

        self.calls.append({
            "query": queryText,
            "params": params,
        })

        if "FROM scipion_sets stored_set" in queryText:
            return [
                {
                    "id": 71,
                    "projectId": 7,
                    "protocolDbId": 31,
                    "objectId": 81,
                    "outputName": "outputTiltSeries",
                    "setClassName": "SetOfTiltSeries",
                    "itemClassName": "TiltSeries",
                    "properties": {
                        "fileName": "output.sqlite",
                    },
                    "rootItemsCount": 4,
                    "tablesCount": 2,
                    "tableItemsCount": 8,
                },
            ]

        if "FROM scipion_objects object_row" in queryText:
            return [
                {
                    "name": "outputVolume",
                    "path": "outputVolume",
                    "className": "Volume",
                    "scipionObjId": 91,
                },
            ]

        raise AssertionError(
            "Unexpected query: %s"
            % queryText
        )


class FakeMapper:
    def __init__(self):
        self.db = FakeDb()


def test_LoadProtocolRuntimeArtifactRows():
    mapper = FakeMapper()

    result = ProtocolGraphRepository().loadProtocolRuntimeArtifactRows(
        mapper=mapper,
        projectId=7,
        protocolId=19,
    )

    assert result == {
        "sets": [
            {
                "id": 71,
                "projectId": 7,
                "protocolDbId": 31,
                "objectId": 81,
                "outputName": "outputTiltSeries",
                "setClassName": "SetOfTiltSeries",
                "itemClassName": "TiltSeries",
                "properties": {
                    "fileName": "output.sqlite",
                },
            },
        ],
        "objects": [
            {
                "name": "outputVolume",
                "path": "outputVolume",
                "className": "Volume",
                "scipionObjId": 91,
            },
        ],
        "setCountsById": {
            71: {
                "rootItemsCount": 4,
                "tablesCount": 2,
                "tableItemsCount": 8,
            },
        },
    }

    assert len(mapper.db.calls) == 2

    setCall = mapper.db.calls[0]
    setQuery = setCall["query"]

    assert setCall["params"] == (
        7,
        "19",
    )

    assert "FROM scipion_sets stored_set" in setQuery
    assert 'protocol_row."projectId" = stored_set."projectId"' in setQuery
    assert 'protocol_row.id = stored_set."protocolDbId"' in setQuery
    assert "FROM scipion_set_items root_item" in setQuery
    assert "FROM scipion_set_tables set_table" in setQuery
    assert "JOIN scipion_set_table_items table_item" in setQuery
    assert 'root_item."setId" = stored_set.id' in setQuery
    assert 'set_table."setId" = stored_set.id' in setQuery

    objectCall = mapper.db.calls[1]
    objectQuery = objectCall["query"]

    assert objectCall["params"] == (
        7,
        "19",
    )

    assert "FROM scipion_objects object_row" in objectQuery
    assert 'protocol_row."projectId" = object_row."projectId"' in objectQuery
    assert 'protocol_row.id = object_row."protocolDbId"' in objectQuery
    assert 'object_row."parentObjectId" IS NULL' in objectQuery


