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
import app.backend.mapper as backendMapperModule

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


def test_RegisterOutputFinalizesNativePostgresqlSetWithoutSnapshot(
        monkeypatch,
):
    finalized = []

    class NativeRuntimeSetStub:
        def getObjId(self):
            return 91

        def getClassName(self):
            return "SetOfParticles"

        def isPostgresqlRuntimeOutput(self):
            return True

    class ProtocolStub:
        def __init__(self, outputSet):
            self.outputSet = outputSet

        def getObjId(self):
            return 23

        def iterOutputAttributes(self):
            return [
                (
                    "outputParticles",
                    self.outputSet,
                ),
            ]

    class RuntimeMapperStub:
        def __init__(self):
            self.db = object()

    class SetMapperStub:
        def __init__(self, db):
            self.db = db

        def finalizeRuntimeSetOutput(
                self,
                projectId,
                protocolDbId,
                outputName,
                scipionSet,
        ):
            finalized.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "outputName": outputName,
                "runtimeObjectId": (
                    scipionSet.getObjId()
                ),
            })

            return {
                "setId": 71,
                "runtimeObjectId": (
                    scipionSet.getObjId()
                ),
                "outputName": outputName,
            }

        def storeSet(self, **kwargs):
            pytest.fail(
                "Native PostgreSQL output must not "
                "be persisted through storeSet()."
            )

    class ObjectMapperStub:
        def __init__(self, db):
            self.db = db

    outputSet = NativeRuntimeSetStub()
    protocol = ProtocolStub(
        outputSet
    )
    service = (
        RuntimeProtocolOutputPersistenceService()
    )

    monkeypatch.setattr(
        backendMapperModule,
        "ScipionSetPostgresqlMapper",
        SetMapperStub,
    )

    monkeypatch.setattr(
        backendMapperModule,
        "ScipionObjectPostgresqlMapper",
        ObjectMapperStub,
    )

    monkeypatch.setattr(
        service,
        "resolveProtocolDbIdForOutputPersistence",
        lambda **kwargs: 17,
    )

    monkeypatch.setattr(
        service,
        "_prepareOutputObjectIdsForPersistence",
        lambda **kwargs: pytest.fail(
            "Native PostgreSQL output identity "
            "must not be prepared again."
        ),
    )

    monkeypatch.setattr(
        service,
        "_openRelativeSetMapperForPersistence",
        lambda **kwargs: pytest.fail(
            "Native PostgreSQL output must not "
            "open a compatibility SQLite mapper."
        ),
    )

    report = service.registerOutput(
        projectId=7,
        protocol=protocol,
        mapper=RuntimeMapperStub(),
        returnReport=True,
    )

    assert finalized == [
        {
            "projectId": 7,
            "protocolDbId": 17,
            "outputName": (
                "outputParticles"
            ),
            "runtimeObjectId": 91,
        },
    ]

    assert report["errors"] == []
    assert report["skipped"] == []

    assert len(
        report["persisted"]
    ) == 1

    persistedOutput = (
        report["persisted"][0]
    )

    assert (
        persistedOutput["setId"]
        == 71
    )

    assert (
        persistedOutput[
            "postgresqlNativeOutput"
        ]
        is True
    )

    assert (
        outputSet.getObjId()
        == 91
    )


