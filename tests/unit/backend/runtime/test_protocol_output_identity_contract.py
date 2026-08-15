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
from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)


class RecordingDb:
    def __init__(self, row):
        self.row = row
        self.query = None
        self.params = None

    def fetchOne(self, query, params=None):
        self.query = " ".join(str(query).split())
        self.params = params
        return self.row


class FakeMapper:
    def __init__(self, row):
        self.db = RecordingDb(row)


class CaseInsensitiveOutputDb:
    def __init__(self):
        self.fetchAllQueries = []
        self.fetchAllParams = []

    def fetchOne(self, query, params=None):
        normalizedQuery = " ".join(str(query).split())

        if "FROM scipion_set_items" in normalizedQuery:
            return {"count": 3}

        if "FROM scipion_set_tables" in normalizedQuery and "JOIN scipion_set_table_items" not in normalizedQuery:
            return {"count": 0}

        if "JOIN scipion_set_table_items" in normalizedQuery:
            return {"count": 0}

        return None

    def fetchAll(self, query, params=None):
        self.fetchAllQueries.append(" ".join(str(query).split()))
        self.fetchAllParams.append(params)

        return [{
            "kind": "set",
            "setId": 4728,
            "objectId": "20670",
            "runtimeObjectId": "1000062",
            "outputName": "tiltSeries",
            "className": "SetOfTiltSeries",
            "itemClassName": "TiltSeries",
            "properties": {
                "itemsCount": 3,
            },
        }]


class CaseInsensitiveOutputMapper:
    def __init__(self):
        self.db = CaseInsensitiveOutputDb()


def test_InputRefOutputInfoReturnsRuntimeObjectId():
    mapper = FakeMapper({
        "runtimeObjectId": "245",
        "className": "SetOfParticles",
        "outputName": "outputParticles",
    })

    result = ProtocolGraphRepository().getPersistedOutputInfoForInputRef(
        mapper=mapper,
        projectId=7,
        parentProtocolDbId=31,
        outputName="outputParticles",
    )

    assert result == {
        "runtimeObjectId": "245",
        "className": "SetOfParticles",
        "outputName": "outputParticles",
    }

    assert 'AS "runtimeObjectId"' in mapper.db.query
    assert 's."objectId"::text AS "objectId"' not in mapper.db.query


def test_RuntimeOutputInfoKeepsCanonicalAndRuntimeIdsSeparated():
    mapper = FakeMapper({
        "kind": "object",
        "setId": None,
        "objectId": "9001",
        "runtimeObjectId": "245",
        "outputName": "outputVolume",
        "className": "Volume",
        "itemClassName": None,
        "properties": {},
    })

    result = ProtocolGraphRepository().getPostgresqlRuntimeOutputInfo(
        mapper=mapper,
        projectId=7,
        parentProtocolDbId=31,
        outputName="outputVolume",
    )

    assert result["objectId"] == "9001"
    assert result["runtimeObjectId"] == "245"
    assert 'o.id::text AS "objectId"' in mapper.db.query


def test_RuntimeOutputInfoResolvesUniqueCaseInsensitiveOutputName():
    mapper = CaseInsensitiveOutputMapper()

    result = ProtocolGraphRepository().getPostgresqlRuntimeOutputInfo(
        mapper=mapper,
        projectId=399,
        parentProtocolDbId=45325,
        outputName="TiltSeries",
    )

    assert result["exists"] is True
    assert result["outputName"] == "tiltSeries"
    assert result["runtimeObjectId"] == "1000062"
    assert result["className"] == "SetOfTiltSeries"
    assert result["itemsCount"] == 3

    assert len(mapper.db.fetchAllQueries) == 1
    assert 'LOWER(s."outputName") = LOWER(%s)' in mapper.db.fetchAllQueries[0]
    assert mapper.db.fetchAllParams[0] == (
        399,
        45325,
        "TiltSeries",
    )


