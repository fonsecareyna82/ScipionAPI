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
import logging
from typing import Any, Callable, Dict, List, Set as TypingSet, Tuple, Optional

from app.backend.runtime.project_relation_sync_service import RuntimeProjectRelationSyncService
from app.backend.runtime.protocol_output_persistence_service import (
    RuntimeProtocolOutputPersistenceService,
)
from app.backend.runtime.protocol_step_persistence_service import (
    RuntimeProtocolStepPersistenceService,
)
from app.backend.runtime.protocol_input_ref_builder_service import (
    RuntimeProtocolInputRefBuilderService,
)

logger = logging.getLogger(__name__)


class RuntimeProjectGraphSyncService:
    """Synchronize the Scipion project graph into PostgreSQL runtime tables."""

    def syncProjectProtocolsAndDependencies(
            self,
            mapper,
            projectId: int,
            currentProject,
            buildProtocolContextCallback: Callable,
            tryGetScipionProtocolByRuntimeIdCallback: Callable,
            getScipionObjectIdCallback: Callable,
            registerOutputCallback: Callable,
            shouldPreservePostgresqlOnlyProtocolsCallback: Callable,
            prepareProtocolForOutputPersistenceCallback:
            Optional[Callable] = None,
            refresh: bool = False,
            checkPid: bool = False,
            strict: bool = False,
            syncRelations: bool = False,
    ) -> Dict[str, Any]:
        runtimeProjectRelationSyncService = RuntimeProjectRelationSyncService()
        if currentProject is None:
            raise RuntimeError("No current project loaded")

        runs = currentProject.getRunsGraph(
            refresh=refresh,
            checkPids=checkPid,
        )
        nodesDict = getattr(runs, "_nodesDict", {}) or {}

        protocolDbIdByScipionId: Dict[str, int] = {}
        currentProtocolIds: TypingSet[str] = set()
        protocolsByScipionId: Dict[str, Any] = {}

        outputSyncResults: List[Dict[str, Any]] = []
        outputSyncErrors: List[Dict[str, Any]] = []
        outputSyncDeclared: List[Dict[str, Any]] = []
        outputSyncMissing: List[Dict[str, Any]] = []
        outputSyncRemoved: List[
            Dict[str, Any]
        ] = []

        stepsSyncCount = 0
        stepsSyncProtocolsCount = 0
        stepsSyncErrors: List[Dict[str, Any]] = []

        runtimeProtocolStepPersistenceService = RuntimeProtocolStepPersistenceService()
        runtimeProtocolOutputPersistenceService = RuntimeProtocolOutputPersistenceService()
        runtimeProtocolInputRefBuilderService = RuntimeProtocolInputRefBuilderService()

        # 1) Save all protocol nodes that are currently present in the real Scipion graph.
        for nodeId, nodeObj in nodesDict.items():
            nodeIdText = str(nodeId)

            if nodeIdText == "PROJECT":
                continue

            protocol = getattr(nodeObj, "run", None)

            if protocol is None:
                protocol = tryGetScipionProtocolByRuntimeIdCallback(nodeId)

            if protocol is None:
                continue

            protocolContext = buildProtocolContextCallback(
                projectId,
                protocol,
                mapper,
            )
            protocolDbId = mapper.saveProtocol(protocolContext)

            try:
                protocolSteps = runtimeProtocolStepPersistenceService.buildProtocolStepsForPostgresql(
                    protocol,
                )
                protocolScipionId = getScipionObjectIdCallback(protocol)

                if protocolSteps and protocolScipionId is not None:
                    mapper.replaceProtocolSteps(
                        projectId=projectId,
                        protocolDbId=int(protocolDbId),
                        protocolId=int(protocolScipionId),
                        steps=protocolSteps,
                    )

                    stepsSyncCount += len(protocolSteps)
                    stepsSyncProtocolsCount += 1

            except Exception as exc:
                stepsSyncErrors.append({
                    "protocolId": nodeIdText,
                    "error": str(exc),
                })
                logger.exception(
                    "Failed to sync protocol steps. projectId=%s protocolId=%s",
                    projectId,
                    nodeIdText,
                )

            outputProtocol = protocol

            if callable(
                    prepareProtocolForOutputPersistenceCallback
            ):
                try:
                    preparedProtocol = (
                        prepareProtocolForOutputPersistenceCallback(
                            protocolId=nodeIdText,
                            protocol=protocol,
                        )
                    )

                    if preparedProtocol is not None:
                        preparedProtocolId = (
                            getScipionObjectIdCallback(
                                preparedProtocol
                            )
                        )

                        if (
                                preparedProtocolId is None
                                or str(
                                    preparedProtocolId
                                ) != nodeIdText
                        ):
                            raise RuntimeError(
                                "Prepared output protocol identity "
                                "does not match graph protocol. "
                                "expected=%s actual=%s"
                                % (
                                    nodeIdText,
                                    preparedProtocolId,
                                )
                            )

                        outputProtocol = (
                            preparedProtocol
                        )

                except Exception as error:
                    outputSyncErrors.append({
                        "protocolId": (
                            nodeIdText
                        ),
                        "operation": (
                            "prepare_output_protocol"
                        ),
                        "error": str(error),
                    })

                    logger.exception(
                        "Could not prepare authoritative "
                        "protocol for output persistence. "
                        "projectId=%s protocolId=%s",
                        projectId,
                        nodeIdText,
                    )

            if runtimeProtocolOutputPersistenceService.shouldSyncProtocolOutputs(
                    protocol=outputProtocol,
            ):
                try:
                    outputReport = registerOutputCallback(
                        projectId=projectId,
                        protocol=outputProtocol,
                        mapper=mapper,
                        returnReport=True,
                    )

                    outputSyncResults.extend(outputReport.get("persisted") or [])
                    for removedOutput in (
                            outputReport.get(
                                "removed"
                            )
                            or []
                    ):
                        outputSyncRemoved.append({
                            "protocolId": nodeIdText,
                            **removedOutput,
                        })

                    declaredOutputs = outputReport.get("declared") or []
                    persistedOutputs = outputReport.get("persisted") or []
                    if strict:
                        for persistedOutput in (
                                persistedOutputs
                        ):
                            outputClassName = str(
                                persistedOutput.get(
                                    "outputClassName"
                                )
                                or ""
                            )

                            mapperKind = str(
                                persistedOutput.get(
                                    "mapperKind"
                                )
                                or ""
                            )

                            if (
                                    outputClassName.startswith(
                                        "SetOf"
                                    )
                                    and mapperKind
                                    != "flat_set"
                            ):
                                outputSyncErrors.append({
                                    "protocolId": (
                                        nodeIdText
                                    ),
                                    "outputName": (
                                        persistedOutput.get(
                                            "outputName"
                                        )
                                    ),
                                    "outputClassName": (
                                        outputClassName
                                    ),
                                    "mapperKind": (
                                        mapperKind
                                    ),
                                    "reason": (
                                        "set_output_not_fully_migrated"
                                    ),
                                })
                    skippedOutputs = outputReport.get("skipped") or []
                    erroredOutputs = outputReport.get("errors") or []

                    for declaredOutput in declaredOutputs:
                        outputSyncDeclared.append({
                            "protocolId": nodeIdText,
                            "outputName": declaredOutput.get("outputName"),
                            "outputClassName": declaredOutput.get("outputClassName"),
                        })

                    outputSyncMissing.extend(
                        runtimeProtocolOutputPersistenceService.buildMissingOutputSyncItems(
                            protocolId=nodeIdText,
                            declaredOutputs=declaredOutputs,
                            persistedOutputs=persistedOutputs,
                            skippedOutputs=skippedOutputs,
                            outputErrors=erroredOutputs,
                        )
                    )

                    for skippedOutput in skippedOutputs:
                        outputSyncErrors.append({
                            "protocolId": nodeIdText,
                            "outputName": skippedOutput.get("outputName"),
                            "outputClassName": skippedOutput.get("outputClassName"),
                            "reason": skippedOutput.get("reason"),
                        })

                    for outputError in erroredOutputs:
                        outputSyncErrors.append({
                            "protocolId": nodeIdText,
                            "outputName": outputError.get("outputName"),
                            "outputClassName": outputError.get("outputClassName"),
                            "error": outputError.get("error"),
                        })

                except Exception as exc:
                    outputSyncErrors.append({
                        "protocolId": nodeIdText,
                        "error": str(exc),
                    })
                    logger.exception(
                        "Failed to sync protocol outputs. projectId=%s protocolId=%s",
                        projectId,
                        nodeIdText,
                    )

            currentProtocolIds.add(nodeIdText)
            protocolDbIdByScipionId[nodeIdText] = int(protocolDbId)
            protocolsByScipionId[nodeIdText] = protocol

        # 2) Do not purge PostgreSQL protocol rows while PostgreSQL runtime mapper
        # is active/migrating.
        #
        # PostgreSQL can now contain protocols that do not exist in project.sqlite.
        # If we purge rows based only on the legacy Scipion/SQLite graph, loading or
        # refreshing a project can delete valid PostgreSQL-only protocols.
        purgedProtocols = 0

        if not shouldPreservePostgresqlOnlyProtocolsCallback():
            purgedProtocols = mapper.deleteProjectProtocolsNotInProtocolIds(
                projectId,
                sorted(currentProtocolIds),
            )

        # 3) Build edges parent -> child using DB ids.
        edges: List[Tuple[int, int]] = []

        for nodeId, nodeObj in nodesDict.items():
            childDbId = protocolDbIdByScipionId.get(str(nodeId))

            if not childDbId:
                continue

            for parent in getattr(nodeObj, "_parents", []) or []:
                parentNodeId = str(parent.getName())

                if parentNodeId == "PROJECT":
                    continue

                parentDbId = protocolDbIdByScipionId.get(parentNodeId)

                if not parentDbId:
                    continue

                edges.append((parentDbId, childDbId))

        savedEdges = mapper.replaceProjectProtocolDependencies(
            projectId,
            edges,
        )

        # 4) Build exact protocol input refs.
        inputRefs: List[Dict[str, Any]] = []

        for protocolIdText, protocol in protocolsByScipionId.items():
            inputRefs.extend(
                runtimeProtocolInputRefBuilderService.buildProtocolInputRefsForPostgresql(
                    projectId=projectId,
                    protocol=protocol,
                    protocolDbIdByScipionId=(
                        protocolDbIdByScipionId
                    ),
                    strict=strict,
                )
            )

        savedInputRefs = 0
        replaceInputRefs = getattr(mapper, "replaceProjectProtocolInputRefs", None)

        if callable(replaceInputRefs):
            savedInputRefs = replaceInputRefs(projectId, inputRefs)

        outputResultsByKind = runtimeProtocolOutputPersistenceService.countRuntimeOutputKinds(
            outputSyncResults,
        )

        storedObjectsCount = 0
        setItemsCount = 0

        for outputResult in outputSyncResults:
            mapperKind = str(outputResult.get("mapperKind") or "")

            if mapperKind == "flat_set":
                storedObjectsCount += 1
                setItemsCount += int(
                    outputResult.get("itemsCount") or 0
                )
            else:
                storedObjectsCount += int(
                    outputResult.get("storedObjectsCount") or 1
                )

        relationReport = {
            "relationsDeclared": 0,
            "relations": 0,
            "relationsStale": 0,
            "staleRelations": [],
            "relationMissing": [],
            "relationErrors": [],
            "complete": True,
        }

        if syncRelations:
            relationsByScipionId = {}

            for protocolIdText, protocol in (
                    protocolsByScipionId.items()
            ):
                relationSnapshot = (
                    runtimeProjectRelationSyncService
                    .collectRuntimeProtocolRelations(
                        currentProject=currentProject,
                        protocolId=protocolIdText,
                        runtimeProtocol=protocol,
                    )
                )

                relationsByScipionId[
                    protocolIdText
                ] = list(
                    relationSnapshot.get(
                        "relations"
                    )
                    or []
                )

            relationReport = (
                runtimeProjectRelationSyncService
                .syncProjectRelations(
                    mapper=mapper,
                    projectId=projectId,
                    protocolsByScipionId=(
                        protocolsByScipionId
                    ),
                    protocolDbIdByScipionId=(
                        protocolDbIdByScipionId
                    ),
                    relationsByScipionId=(
                        relationsByScipionId
                    ),
                )
            )

        fatalErrors = []

        fatalErrors.extend([
            {
                "kind": "step",
                **item,
            }
            for item in stepsSyncErrors
        ])

        fatalErrors.extend([
            {
                "kind": "output",
                **item,
            }
            for item in outputSyncMissing
        ])

        fatalErrors.extend([
            {
                "kind": "output",
                **item,
            }
            for item in outputSyncErrors
        ])

        fatalErrors.extend([
            {
                "kind": "relation",
                **item,
            }
            for item in relationReport["relationMissing"]
        ])

        fatalErrors.extend([
            {
                "kind": "relation",
                **item,
            }
            for item in relationReport["relationErrors"]
        ])

        report = {
            "protocols": len(protocolDbIdByScipionId),
            "dependencies": int(savedEdges),
            "inputRefs": int(savedInputRefs),
            "steps": int(stepsSyncCount),
            "stepsProtocols": int(stepsSyncProtocolsCount),
            "stepErrors": stepsSyncErrors,
            "outputsDeclared": len(outputSyncDeclared),
            "outputs": len(outputSyncResults),
            "outputsRemoved": len(
                outputSyncRemoved
            ),
            "removedOutputs": (
                outputSyncRemoved
            ),
            "outputsMissing": len(outputSyncMissing),
            "outputsByKind": outputResultsByKind,
            "objects": int(storedObjectsCount),
            "sets": int(outputResultsByKind.get("flat_set", 0)),
            "setItems": int(setItemsCount),
            "outputMissing": outputSyncMissing,
            "outputErrors": outputSyncErrors,
            "purgedProtocols": int(purgedProtocols or 0),
            "fatalErrors": fatalErrors,
            "complete": not fatalErrors,
            "relationsDeclared": relationReport["relationsDeclared"],
            "relations": relationReport["relations"],
            "relationsStale": int(relationReport.get("relationsStale", 0,) or 0),
            "staleRelations": (relationReport.get("staleRelations") or []),
            "relationMissing": relationReport["relationMissing"],
            "relationErrors": relationReport["relationErrors"],
        }

        if strict and fatalErrors:
            raise RuntimeError(
                "Project graph migration to PostgreSQL was incomplete. "
                "stepErrors=%s outputErrors=%s outputsMissing=%s "
                "relationErrors=%s relationsMissing=%s fatalErrors=%s"
                % (
                    len(stepsSyncErrors),
                    len(outputSyncErrors),
                    len(outputSyncMissing),
                    len(relationReport["relationErrors"]),
                    len(relationReport["relationMissing"]),
                    fatalErrors[:20],
                )
            )

        return report