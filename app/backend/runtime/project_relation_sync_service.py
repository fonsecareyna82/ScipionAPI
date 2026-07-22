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
import os
import logging
from typing import Any, Dict

from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)
from app.backend.runtime.protocol_output_persistence_service import (
    RuntimeProtocolOutputPersistenceService,
)
from pyworkflow import PROJECT_DBNAME
from pyworkflow.project import Project as ScipionProject


logger = logging.getLogger(__name__)


class RuntimeProjectRelationSyncService:
    """Migrate original Scipion project relations into PostgreSQL."""

    @staticmethod
    def _buildRelationIdentity(
            relationName,
            creatorProtocolId,
            parentRuntimeObjectId,
            childRuntimeObjectId,
            parentExtended=None,
            childExtended=None,
    ):
        """
        Build the logical PostgreSQL identity of one runtime relation.

        SQLite relation ids are deliberately excluded because rerunning or
        continuing a protocol may create a new SQLite row for an already
        existing logical relation.
        """
        def normalize(value):
            return (
                ""
                if value is None
                else str(value)
            )

        return (
            normalize(
                relationName
            ),
            normalize(
                creatorProtocolId
            ),
            normalize(
                parentRuntimeObjectId
            ),
            normalize(
                childRuntimeObjectId
            ),
            normalize(
                parentExtended
            ),
            normalize(
                childExtended
            ),
        )

    @staticmethod
    def _toOptionalInt(
            value,
    ):
        if value in (
                None,
                "",
        ):
            return None

        try:
            return int(
                value
            )
        except Exception:
            pass

        try:
            return int(
                float(
                    value
                )
            )
        except Exception:
            return None

    @staticmethod
    def _normalizeRelationExtended(
            value,
    ) -> str:
        """
        Normalize an extended path to its root output name.

        Examples:
            outputParticles
            outputParticles._samplingRate

        Both resolve to outputParticles.
        """
        valueText = str(
            value or ""
        ).strip()

        if not valueText:
            return ""

        return valueText.split(
            ".",
            1,
        )[0]

    @classmethod
    def _buildRelationEndpointIdentity(
            cls,
            runtimeObjectId,
            extended=None,
    ):
        runtimeObjectId = cls._toOptionalInt(
            runtimeObjectId
        )

        if runtimeObjectId is None:
            return None

        return (
            runtimeObjectId,
            cls._normalizeRelationExtended(
                extended
            ),
        )

    @classmethod
    def _relationEndpointMatchesCurrentOutput(
            cls,
            endpoint,
            currentOutputEndpoints,
    ) -> bool:
        if endpoint is None:
            return False

        if endpoint in currentOutputEndpoints:
            return True

        runtimeObjectId, extended = endpoint

        # A relation may point to an attribute beneath a current root
        # output. In that case the current output endpoint is stored
        # without an extended path.
        if extended:
            return (
                runtimeObjectId,
                "",
            ) in currentOutputEndpoints

        return False

    def _collectAuthoritativeCurrentOutputEndpoints(
            self,
            protocol,
            protocolId,
    ):
        """
        Return the current persistable output identities when the protocol
        exposes a final output snapshot.

        None means that stale-relation pruning must not be performed. This
        deliberately preserves the old strict behavior for running protocols,
        incomplete protocols and compatibility objects whose outputs cannot be
        inspected safely.
        """
        outputPersistenceService = (
            RuntimeProtocolOutputPersistenceService()
        )

        if not (
                outputPersistenceService
                .shouldReconcileMissingProtocolOutputs(
                    protocol
                )
        ):
            return None

        protocolId = self._toOptionalInt(
            protocolId
        )

        if protocolId is None:
            return None

        try:
            outputAttributes = list(
                protocol.iterOutputAttributes()
            )
        except Exception:
            return None

        currentOutputEndpoints = set()

        for outputItem in outputAttributes:
            outputName = None
            outputObject = outputItem

            if (
                    isinstance(
                        outputItem,
                        (
                            tuple,
                            list,
                        ),
                    )
                    and len(
                        outputItem
                    ) >= 2
            ):
                outputName = outputItem[0]
                outputObject = outputItem[1]

            if outputObject is None:
                continue

            try:
                isPersistableOutput = (
                    outputPersistenceService
                    .isScipionSetLikeOutput(
                        outputObject
                    )
                    or outputPersistenceService
                    .isPersistableNonSetOutput(
                        outputObject
                    )
                )
            except Exception:
                isPersistableOutput = False

            if not isPersistableOutput:
                continue

            outputObjectId = self._toOptionalInt(
                outputPersistenceService
                .getScipionObjectId(
                    outputObject
                )
            )

            if outputObjectId is not None:
                currentOutputEndpoints.add((
                    outputObjectId,
                    "",
                ))

            outputName = (
                self
                ._normalizeRelationExtended(
                    outputName
                )
            )

            if outputName:
                # Some Scipion relations represent an output as:
                # protocolId + outputName
                currentOutputEndpoints.add((
                    protocolId,
                    outputName,
                ))

        # An empty or unreadable output collection is not sufficient evidence
        # for deleting relation history. Preserve strict legacy behavior.
        if not currentOutputEndpoints:
            return None

        return currentOutputEndpoints

    def _filterRelationsForCurrentOutputs(
            self,
            protocol,
            protocolId,
            relations,
    ) -> Dict[str, Any]:
        """
        Remove relation rows that belong exclusively to deleted/replaced
        output generations.

        A relation remains active when at least one endpoint references a
        current protocol output. We do not activate the opposite endpoint:
        doing so would traverse through a common input and resurrect every
        historical output generation connected to that input.
        """
        relations = list(
            relations or []
        )

        currentOutputEndpoints = (
            self
            ._collectAuthoritativeCurrentOutputEndpoints(
                protocol=protocol,
                protocolId=protocolId,
            )
        )

        if currentOutputEndpoints is None:
            return {
                "relations": relations,
                "staleRelations": [],
                "pruned": False,
            }

        activeRelations = []
        staleRelations = []

        for relation in relations:
            parentEndpoint = (
                self
                ._buildRelationEndpointIdentity(
                    relation.get(
                        "parentRuntimeObjectId"
                    ),
                    relation.get(
                        "parentExtended"
                    ),
                )
            )

            childEndpoint = (
                self
                ._buildRelationEndpointIdentity(
                    relation.get(
                        "childRuntimeObjectId"
                    ),
                    relation.get(
                        "childExtended"
                    ),
                )
            )

            referencesCurrentOutput = (
                self
                ._relationEndpointMatchesCurrentOutput(
                    parentEndpoint,
                    currentOutputEndpoints,
                )
                or self
                ._relationEndpointMatchesCurrentOutput(
                    childEndpoint,
                    currentOutputEndpoints,
                )
            )

            if referencesCurrentOutput:
                activeRelations.append(
                    relation
                )

                continue

            staleRelations.append({
                **relation,
                "reason": (
                    "not_referenced_by_current_outputs"
                ),
            })

        return {
            "relations": activeRelations,
            "staleRelations": staleRelations,
            "pruned": True,
        }

    def collectRuntimeProtocolRelations(
            self,
            currentProject,
            protocolId,
            runtimeProtocol,
    ) -> Dict[str, Any]:
        """
        Collect runtime relations from run.db and project.sqlite.

        project.sqlite is opened temporarily when the PostgreSQL runtime
        project does not keep a persistent SQLite fallback mapper.
        """
        if currentProject is None:
            raise RuntimeError(
                "Cannot collect runtime relations without current project"
            )

        protocolCandidates = [
            (
                "runtime_db",
                runtimeProtocol,
            ),
        ]

        isolatedMapper = None
        sqliteProtocolFound = False
        seenFallbackMappers = set()

        try:
            runtimeMapper = None

            try:
                runtimeMapper = (
                    currentProject
                    .getPostgresqlRuntimeMapper()
                )
            except Exception:
                runtimeMapper = None

            for fallbackName in (
                    "readFallbackMapper",
                    "writeFallbackMapper",
            ):
                fallbackMapper = getattr(
                    runtimeMapper,
                    fallbackName,
                    None,
                )

                if fallbackMapper is None:
                    continue

                fallbackIdentity = id(
                    fallbackMapper
                )

                if (
                        fallbackIdentity
                        in seenFallbackMappers
                ):
                    continue

                seenFallbackMappers.add(
                    fallbackIdentity
                )

                selectById = getattr(
                    fallbackMapper,
                    "selectById",
                    None,
                )

                if not callable(selectById):
                    continue

                try:
                    fallbackProtocol = selectById(
                        int(protocolId)
                    )
                except Exception:
                    logger.debug(
                        "Could not load protocol %s from "
                        "SQLite %s mapper.",
                        protocolId,
                        fallbackName,
                        exc_info=True,
                    )
                    continue

                if fallbackProtocol is None:
                    continue

                fallbackProtocol.setMapper(
                    fallbackMapper
                )

                protocolCandidates.append((
                    fallbackName,
                    fallbackProtocol,
                ))

                sqliteProtocolFound = True

            if not sqliteProtocolFound:
                projectPath = str(
                    currentProject.getPath()
                )

                sqlitePath = os.path.abspath(
                    os.path.join(
                        projectPath,
                        PROJECT_DBNAME,
                    )
                )

                if os.path.exists(sqlitePath):
                    isolatedMapper = (
                        ScipionProject.createMapper(
                            currentProject,
                            sqlitePath,
                        )
                    )

                    sqliteProtocol = (
                        isolatedMapper.selectById(
                            int(protocolId)
                        )
                    )

                    if sqliteProtocol is not None:
                        sqliteProtocol.setMapper(
                            isolatedMapper
                        )

                        protocolCandidates.append((
                            "project_sqlite_isolated",
                            sqliteProtocol,
                        ))

            return self.collectProtocolRelations(
                protocolCandidates
            )

        finally:
            if isolatedMapper is not None:
                try:
                    isolatedMapper.close()
                except Exception:
                    logger.debug(
                        "Could not close isolated SQLite "
                        "relation mapper.",
                        exc_info=True,
                    )

    def collectProtocolRelations(
            self,
            protocolCandidates,
    ) -> Dict[str, Any]:
        """
        Collect one relation snapshot from all available protocol representations.

        The runtime protocol loaded from logs/run.db is the primary source.
        SQLite fallback protocols are also inspected because some Scipion paths
        may already have copied their relations into project.sqlite.
        """
        relations = []
        relationKeys = set()
        sources = []
        errors = []

        for sourceName, protocol in protocolCandidates:
            if protocol is None:
                continue

            try:
                sourceRelations = protocol.getRelations() or []
            except Exception as error:
                errors.append({
                    "source": sourceName,
                    "error": str(error),
                })
                continue

            sourceAdded = 0

            for rawRelation in sourceRelations:
                try:
                    relation = dict(rawRelation)
                except Exception as error:
                    errors.append({
                        "source": sourceName,
                        "error": str(error),
                    })
                    continue

                relationKey = self._buildRelationIdentity(
                    relationName=relation.get(
                        "name"
                    ),
                    creatorProtocolId=relation.get(
                        "parent_id"
                    ),
                    parentRuntimeObjectId=relation.get(
                        "object_parent_id"
                    ),
                    childRuntimeObjectId=relation.get(
                        "object_child_id"
                    ),
                    parentExtended=relation.get(
                        "object_parent_extended"
                    ),
                    childExtended=relation.get(
                        "object_child_extended"
                    ),
                )

                if relationKey in relationKeys:
                    continue

                relationKeys.add(relationKey)
                relations.append(relation)
                sourceAdded += 1

            if sourceAdded:
                sources.append({
                    "source": sourceName,
                    "relations": sourceAdded,
                })

        return {
            "relations": relations,
            "sources": sources,
            "errors": errors,
        }

    def syncProjectRelations(
            self,
            *,
            mapper,
            projectId: int,
            protocolsByScipionId: Dict[str, Any],
            protocolDbIdByScipionId: Dict[str, int],
            relationsByScipionId=None,
    ) -> Dict[str, Any]:
        repository = ProtocolGraphRepository()

        declared = []
        persisted = []
        missing = []
        errors = []
        cleanupItems = []
        stale = []

        for protocolId, protocol in protocolsByScipionId.items():
            protocolIdText = str(protocolId)
            protocolDbId = protocolDbIdByScipionId.get(protocolIdText)

            if protocolDbId is None:
                errors.append({
                    "protocolId": protocolIdText,
                    "error": "creator_protocol_not_persisted",
                })
                continue

            preloadedRelations = None

            if relationsByScipionId is not None:
                preloadedRelations = relationsByScipionId.get(
                    protocolIdText
                )

            if preloadedRelations is not None:
                relations = list(preloadedRelations)
            else:
                try:
                    relations = protocol.getRelations() or []
                except Exception as error:
                    errors.append({
                        "protocolId": protocolIdText,
                        "error": str(error),
                    })
                    continue

            protocolRelations = []
            relationKeys = set()
            relationBuildErrors = []

            for rawRelation in relations:
                try:
                    relation = dict(rawRelation)

                    relationItem = {
                        "relationId": relation.get("id"),
                        "relationName": relation.get("name"),
                        "creatorProtocolId": (
                                relation.get("parent_id")
                                or protocolId
                        ),
                        "parentRuntimeObjectId": relation.get(
                            "object_parent_id"
                        ),
                        "childRuntimeObjectId": relation.get(
                            "object_child_id"
                        ),
                        "parentExtended": relation.get(
                            "object_parent_extended"
                        ),
                        "childExtended": relation.get(
                            "object_child_extended"
                        ),
                    }

                    relationItem["creatorProtocolId"] = int(relationItem["creatorProtocolId"])
                    relationItem["parentRuntimeObjectId"] = int(relationItem["parentRuntimeObjectId"])
                    relationItem["childRuntimeObjectId"] = int(relationItem["childRuntimeObjectId"])

                    relationKey = self._buildRelationIdentity(
                        relationName=relationItem[
                            "relationName"
                        ],
                        creatorProtocolId=relationItem[
                            "creatorProtocolId"
                        ],
                        parentRuntimeObjectId=relationItem[
                            "parentRuntimeObjectId"
                        ],
                        childRuntimeObjectId=relationItem[
                            "childRuntimeObjectId"
                        ],
                        parentExtended=relationItem[
                            "parentExtended"
                        ],
                        childExtended=relationItem[
                            "childExtended"
                        ],
                    )

                    if relationKey in relationKeys:
                        continue

                    relationKeys.add(
                        relationKey
                    )

                    declared.append(relationItem)
                    protocolRelations.append(relationItem)

                except Exception as error:
                    relationBuildErrors.append({
                        "protocolId": protocolIdText,
                        "relation": dict(rawRelation),
                        "error": str(error),
                    })

            if relationBuildErrors:
                errors.extend(relationBuildErrors)
                continue

            relationFilterReport = (
                self
                ._filterRelationsForCurrentOutputs(
                    protocol=protocol,
                    protocolId=protocolId,
                    relations=protocolRelations,
                )
            )

            protocolRelations = (
                relationFilterReport[
                    "relations"
                ]
            )

            stale.extend(
                relationFilterReport[
                    "staleRelations"
                ]
            )

            # Resolve every object before deleting the previous snapshot.
            # If PostgreSQL does not contain all required outputs yet, preserve
            # the previous relations and retry on the next synchronization.
            unresolvedRelations = []
            preparedRelations = []

            for relationItem in protocolRelations:
                parentObject = (
                    repository
                    .resolvePersistedRelationEndpoint(
                        mapper=mapper,
                        projectId=projectId,
                        creatorProtocolDbId=int(
                            protocolDbId
                        ),
                        runtimeObjectId=relationItem[
                            "parentRuntimeObjectId"
                        ],
                        extended=relationItem[
                            "parentExtended"
                        ],
                    )
                )

                if parentObject is None:
                    unresolvedRelations.append({
                        **relationItem,
                        "reason": (
                            "parent_output_not_found"
                        ),
                    })

                    continue

                childObject = (
                    repository
                    .resolvePersistedRelationEndpoint(
                        mapper=mapper,
                        projectId=projectId,
                        creatorProtocolDbId=int(
                            protocolDbId
                        ),
                        runtimeObjectId=relationItem[
                            "childRuntimeObjectId"
                        ],
                        extended=relationItem[
                            "childExtended"
                        ],
                    )
                )

                if childObject is None:
                    unresolvedRelations.append({
                        **relationItem,
                        "reason": (
                            "child_output_not_found"
                        ),
                    })

                    continue

                resolvedParentRuntimeObjectId = (
                    self._toOptionalInt(
                        parentObject.get(
                            "runtimeObjectId"
                        )
                    )
                    or relationItem[
                        "parentRuntimeObjectId"
                    ]
                )

                resolvedChildRuntimeObjectId = (
                    self._toOptionalInt(
                        childObject.get(
                            "runtimeObjectId"
                        )
                    )
                    or relationItem[
                        "childRuntimeObjectId"
                    ]
                )

                relationMetadata = {
                    "source": (
                        "project_relation_sync"
                    ),
                    "sqliteRelationId": (
                        relationItem[
                            "relationId"
                        ]
                    ),
                    "originalParentRuntimeObjectId": (
                        relationItem[
                            "parentRuntimeObjectId"
                        ]
                    ),
                    "originalChildRuntimeObjectId": (
                        relationItem[
                            "childRuntimeObjectId"
                        ]
                    ),
                }

                preparedRelations.append({
                    **relationItem,
                    "parentRuntimeObjectId": (
                        resolvedParentRuntimeObjectId
                    ),
                    "childRuntimeObjectId": (
                        resolvedChildRuntimeObjectId
                    ),
                    "parentObject": parentObject,
                    "childObject": childObject,
                    "metadata": relationMetadata,
                })

            if unresolvedRelations:
                missing.extend(
                    unresolvedRelations
                )

                continue
            try:
                replaceReport = (
                    repository
                    .replaceImportedOutputRelationsForCreator(
                        mapper=mapper,
                        projectId=projectId,
                        creatorProtocolDbId=int(
                            protocolDbId
                        ),
                        creatorProtocolId=int(
                            protocolId
                        ),
                        relations=preparedRelations,
                    )
                )

                cleanupItems.append({
                    "protocolId": protocolIdText,
                    "protocolDbId": int(
                        protocolDbId
                    ),
                    **replaceReport.get(
                        "cleanup",
                        {},
                    ),
                })

                persisted.extend(
                    replaceReport.get(
                        "relations",
                        [],
                    )
                )
            except Exception as error:
                errors.append({
                    "protocolId": protocolIdText,
                    "error": str(error),
                })

                logger.exception(
                    "Failed to synchronize project relations. "
                    "projectId=%s protocolId=%s",
                    projectId,
                    protocolIdText,
                )

        return {
            "relationsDeclared": len(declared),
            "relations": len(persisted),
            "relationsStale": len(stale),
            "staleRelations": stale,
            "relationMissing": missing,
            "relationErrors": errors,
            "cleanup": cleanupItems,
            "complete": not missing and not errors,
        }
