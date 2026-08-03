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


def test_InputRefOutputInfoReturnsRuntimeObjectId():
    mapper = FakeMapper({
        "runtimeObjectId": "245",
        "className": "SetOfParticles",
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