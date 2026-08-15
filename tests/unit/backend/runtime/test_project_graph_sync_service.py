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


def test_LegacyProjectGraphSyncUsesPreparedProtocolForRelations(monkeypatch):
    module = importlib.import_module(
        "app.backend.runtime.project_graph_sync_service"
    )

    inputRefProtocols = []
    collectedRelationProtocols = []
    synchronizedProtocolMaps = []

    class FakeProtocol:
        def __init__(self, objectId):
            self.objectId = objectId

        def getObjId(self):
            return self.objectId

    class FakeNode:
        def __init__(self, protocol):
            self.run = protocol
            self._parents = []

    class FakeRunsGraph:
        def __init__(self, protocol):
            self._nodesDict = {
                "10": FakeNode(protocol),
            }

    class FakeProject:
        def __init__(self, protocol):
            self.protocol = protocol

        def getRunsGraph(self, refresh=False, checkPids=False):
            return FakeRunsGraph(self.protocol)

    class FakeMapper:
        def saveProtocol(self, protocolContext):
            return 500

        def replaceProjectProtocolDependencies(self, projectId, edges):
            return len(edges)

        def replaceProjectProtocolInputRefs(self, projectId, inputRefs):
            return len(inputRefs)

    class FakeStepPersistenceService:
        def buildProtocolStepsForPostgresql(self, protocol):
            return []

    class FakeOutputPersistenceService:
        def shouldSyncProtocolOutputs(self, protocol):
            return False

        def countRuntimeOutputKinds(self, outputs):
            return {}

    class FakeInputRefBuilderService:
        def buildProtocolInputRefsForPostgresql(
                self,
                projectId,
                protocol,
                protocolDbIdByScipionId,
                strict,
        ):
            inputRefProtocols.append(protocol)
            return []

    class FakeRelationSyncService:
        def collectRuntimeProtocolRelations(
                self,
                currentProject,
                protocolId,
                runtimeProtocol,
        ):
            collectedRelationProtocols.append(runtimeProtocol)

            return {
                "relations": [
                    {
                        "id": 1,
                        "name": "source",
                    },
                ],
            }

        def syncProjectRelations(self, **kwargs):
            synchronizedProtocolMaps.append(
                dict(kwargs["protocolsByScipionId"])
            )

            assert kwargs["relationsByScipionId"] == {
                "10": [
                    {
                        "id": 1,
                        "name": "source",
                    },
                ],
            }

            return {
                "relationsDeclared": 1,
                "relations": 1,
                "relationsSkipped": 0,
                "skippedRelations": [],
                "relationsStale": 0,
                "staleRelations": [],
                "relationMissing": [],
                "relationErrors": [],
                "cleanup": [],
                "complete": True,
            }

    monkeypatch.setattr(
        module,
        "RuntimeProtocolStepPersistenceService",
        FakeStepPersistenceService,
    )
    monkeypatch.setattr(
        module,
        "RuntimeProtocolOutputPersistenceService",
        FakeOutputPersistenceService,
    )
    monkeypatch.setattr(
        module,
        "RuntimeProtocolInputRefBuilderService",
        FakeInputRefBuilderService,
    )
    monkeypatch.setattr(
        module,
        "RuntimeProjectRelationSyncService",
        FakeRelationSyncService,
    )

    graphProtocol = FakeProtocol(10)
    runtimeProtocol = FakeProtocol(10)

    def failRegisterOutput(**kwargs):
        raise AssertionError(
            "Output registration must not run in this test"
        )

    service = module.RuntimeProjectGraphSyncService()

    result = service.syncLegacyProjectGraphToPostgresql(
        mapper=FakeMapper(),
        projectId=376,
        currentProject=FakeProject(graphProtocol),
        buildProtocolContextCallback=lambda projectId, protocol, mapper: {
            "projectId": projectId,
            "protocolId": protocol.getObjId(),
        },
        tryGetScipionProtocolByRuntimeIdCallback=lambda protocolId: None,
        getScipionObjectIdCallback=lambda protocol: protocol.getObjId(),
        registerOutputCallback=failRegisterOutput,
        shouldPreservePostgresqlOnlyProtocolsCallback=lambda: True,
        prepareProtocolForOutputPersistenceCallback=lambda protocolId, protocol: runtimeProtocol,
        refresh=False,
        checkPid=False,
        strict=True,
        syncRelations=True,
    )

    assert inputRefProtocols == [
        graphProtocol,
    ]

    assert collectedRelationProtocols == [
        runtimeProtocol,
    ]

    assert synchronizedProtocolMaps == [
        {
            "10": runtimeProtocol,
        },
    ]

    assert result["relationsDeclared"] == 1
    assert result["relations"] == 1