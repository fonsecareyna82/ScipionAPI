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


class FakeSetMapper:
    def __init__(self, storedSet):
        self.storedSet = storedSet
        self.calls = []

    def getStoredSet(self, projectId, protocolDbId, outputName, limit=None, offset=0):
        self.calls.append(
            {
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "outputName": outputName,
                "limit": limit,
                "offset": offset,
            }
        )
        return self.storedSet


def test_PostgresqlFscReaderBuildsRowsFromExplicitXY(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_fsc_reader")

    storedSet = {
        "id": 1,
        "setClassName": "SetOfFSCs",
        "itemClassName": "FSC",
        "items": [
            {
                "id": 10,
                "scipionItemId": 101,
                "label": "Half maps",
                "values": {
                    "x": [0.01, 0.02, 0.03],
                    "y": [0.9, 0.5, 0.1],
                },
            }
        ],
    }

    reader = module.PostgresqlFscReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputFsc",
    )
    reader.setMapper = FakeSetMapper(storedSet)

    assert reader.hasOutput() is True
    assert reader.getFscRows() == {
        "threshold": 0.143,
        "rows": [
            {
                "label": "Half maps",
                "resolution": 3.5,
                "x": [0.01, 0.02, 0.03],
                "y": [0.9, 0.5, 0.1],
            }
        ],
    }


def test_PostgresqlFscReaderBuildsRowsFromDataMatrix(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_fsc_reader")

    storedSet = {
        "id": 1,
        "setClassName": "SetOfFSCs",
        "itemClassName": "FSC",
        "items": [
            {
                "id": 10,
                "scipionItemId": 101,
                "label": None,
                "values": {
                    "_objLabel": "FSC class 1",
                    "data": [
                        [0.01, 0.02, 0.03],
                        [0.95, 0.8, 0.1],
                    ],
                    "resolution": 4.2,
                },
            }
        ],
    }

    reader = module.PostgresqlFscReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputFsc",
    )
    reader.setMapper = FakeSetMapper(storedSet)

    assert reader.getFscRows() == {
        "threshold": 0.143,
        "rows": [
            {
                "label": "FSC class 1",
                "resolution": 4.2,
                "x": [0.01, 0.02, 0.03],
                "y": [0.95, 0.8, 0.1],
            }
        ],
    }


def test_PostgresqlFscReaderReturnsNoneWhenRowsAreNotParseable(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_fsc_reader")

    storedSet = {
        "id": 1,
        "setClassName": "SetOfFSCs",
        "itemClassName": "FSC",
        "items": [
            {
                "id": 10,
                "scipionItemId": 101,
                "label": "Broken",
                "values": {
                    "foo": "bar",
                },
            }
        ],
    }

    reader = module.PostgresqlFscReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputFsc",
    )
    reader.setMapper = FakeSetMapper(storedSet)

    assert reader.hasOutput() is True
    assert reader.getFscRows() is None
    assert reader.lastSkipReason == "fsc_rows_not_found"