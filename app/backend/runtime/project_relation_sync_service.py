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
from typing import Any, Dict

from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)


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

            # Resolve every object before deleting the previous snapshot.
            # If PostgreSQL does not contain all required outputs yet, preserve
            # the previous relations and retry on the next synchronization.
            unresolvedRelations = []
            preparedRelations = []

            for relationItem in protocolRelations:
                parentObject = (
                    repository
                    .getPersistedOutputObjectByRuntimeId(
                        mapper=mapper,
                        projectId=projectId,
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
                    .getPersistedOutputObjectByRuntimeId(
                        mapper=mapper,
                        projectId=projectId,
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

                preparedRelations.append({
                    **relationItem,
                    "parentObject": parentObject,
                    "childObject": childObject,
                    "metadata": {
                        "source": (
                            "project_relation_sync"
                        ),
                        "sqliteRelationId": (
                            relationItem[
                                "relationId"
                            ]
                        ),
                    },
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
            "relationMissing": missing,
            "relationErrors": errors,
            "cleanup": cleanupItems,
            "complete": not missing and not errors,
        }
