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
from app.backend.runtime.protocol_output_persistence_service import (
    RuntimeProtocolOutputPersistenceService,
)
from app.backend.runtime import (
    protocol_output_persistence_service as outputPersistenceModule,
)

class FakeDb:
    def __init__(self):
        self.queries = []

    def fetchAll(self, query, params=None):
        normalizedQuery = " ".join(
            str(query).split()
        )

        self.queries.append(
            {
                "query": normalizedQuery,
                "params": params,
            }
        )

        return []


class FakeMapper:
    def __init__(self):
        self.db = FakeDb()


def test_PersistedOutputReadersExcludeReservedRuntimeSets():
    mapper = FakeMapper()
    service = RuntimeProtocolOutputPersistenceService()

    assert service.loadPersistedOutputsByProtocolId(
        mapper=mapper,
        projectId=7,
    ) == {}

    assert service.loadPersistedOutputSummariesByProtocolId(
        mapper=mapper,
        projectId=7,
    ) == {}

    setQueries = [
        call["query"]
        for call in mapper.db.queries
        if (
            'FROM scipion_sets s JOIN protocols p '
            'ON p.id = s."protocolDbId"'
        ) in call["query"]
    ]

    assert len(setQueries) == 2

    for query in setQueries:
        assert (
            "COALESCE( "
            "s.properties ->> 'runtimeReserved', "
            "'false' ) <> 'true'"
        ) in query


def test_ProtocolFormOutputReaderExcludesReservedRuntimeSets(
        monkeypatch,
):
    mapper = FakeMapper()
    service = RuntimeProtocolOutputPersistenceService()

    monkeypatch.setattr(
        outputPersistenceModule.ProtocolIdentityResolver,
        "resolvePostgresqlProtocolDbId",
        lambda self, protocolId: 17,
    )

    assert service.loadPersistedProtocolOutputs(
        mapper=mapper,
        projectId=7,
        protocolId=19,
    ) == {}

    setQuery = next(
        call["query"]
        for call in mapper.db.queries
        if (
            'FROM scipion_sets s '
            'LEFT JOIN scipion_objects root '
            'ON root.id = s."objectId"'
        ) in call["query"]
    )

    assert (
        "COALESCE( "
        "s.properties ->> 'runtimeReserved', "
        "'false' ) <> 'true'"
    ) in setQuery