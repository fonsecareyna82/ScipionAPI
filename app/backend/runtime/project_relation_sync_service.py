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
from pyworkflow import PROJECT_DBNAME
from pyworkflow.project import Project as ScipionProject
from pyworkflow.protocol.protocol import Protocol


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

    def collectRuntimeProtocolRelations(
            self,
            currentProject,
            protocolId,
            runtimeProtocol,
    ) -> Dict[str, Any]:
        """
        Collect runtime relations from run.db and project.sqlite.

        project.sqlite is opened only through a short-lived isolated mapper.
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

        try:
            projectPath = str(currentProject.getPath())
            sqlitePath = os.path.abspath(
                os.path.join(
                    projectPath,
                    PROJECT_DBNAME,
                )
            )

            if os.path.exists(sqlitePath):
                isolatedMapper = ScipionProject.createMapper(
                    currentProject,
                    sqlitePath,
                )

                sqliteProtocol = isolatedMapper.selectById(
                    int(protocolId)
                )

                if isinstance(sqliteProtocol, Protocol):
                    sqliteProtocol.setMapper(
                        isolatedMapper
                    )

                    protocolCandidates.append(
                        (
                            "project_sqlite_isolated",
                            sqliteProtocol,
                        )
                    )

                elif sqliteProtocol is not None:
                    logger.warning(
                        "Ignoring invalid isolated SQLite "
                        "protocol candidate. protocolId=%s "
                        "className=%s objectName=%s "
                        "parentId=%s",
                        protocolId,
                        sqliteProtocol.__class__.__name__,
                        getattr(
                            sqliteProtocol,
                            "_objName",
                            None,
                        ),
                        getattr(
                            sqliteProtocol,
                            "_objParentId",
                            None,
                        ),
                    )

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

    @staticmethod
    def _callOptionalGetter(
            obj,
            getterName: str,
    ):
        if obj is None:
            return None

        getter = getattr(
            obj,
            getterName,
            None,
        )

        if not callable(getter):
            return None

        try:
            return getter()
        except Exception:
            return None

    def _collectCurrentOutputRuntimeObjectIds(self, protocol):
        """
        Return the current output ids of one completed protocol.

        None means that pruning is unsafe because the protocol is not finished
        or its current outputs cannot be identified reliably.
        """
        isFinished = getattr(protocol, "isFinished", None)

        if not callable(isFinished):
            return None

        try:
            if not isFinished():
                return None
        except Exception:
            return None

        iterOutputAttributes = getattr(protocol, "iterOutputAttributes", None)

        if not callable(iterOutputAttributes):
            return None

        try:
            outputAttributes = list(iterOutputAttributes() or [])
        except Exception:
            return None

        if not outputAttributes:
            return set()

        outputIds = set()

        for _outputName, outputObject in outputAttributes:
            outputId = self._toOptionalInt(
                self._callOptionalGetter(outputObject, "getObjId")
            )

            if outputId is None:
                outputId = self._toOptionalInt(
                    getattr(outputObject, "_objId", None)
                )

            if outputId is None:
                return None

            outputIds.add(outputId)

        return outputIds

    def _describeRuntimeRelationEndpoint(
            self,
            protocol,
            runtimeObjectId,
            extended=None,
    ):
        """
        Resolve a SQLite-local relation endpoint while its mapper is open.

        Relation object ids from run.db/project.sqlite are local persistence
        ids. The stable identity is the producer protocol id plus output name.
        """
        runtimeObjectId = self._toOptionalInt(
            runtimeObjectId
        )

        if runtimeObjectId is None:
            return None

        extendedOutputName = (
            self
            ._normalizeRelationExtended(
                extended
            )
        )

        protocolMapper = getattr(
            protocol,
            "mapper",
            None,
        )

        endpointObject = None

        selectById = getattr(
            protocolMapper,
            "selectById",
            None,
        )

        if callable(selectById):
            try:
                endpointObject = selectById(
                    runtimeObjectId
                )
            except Exception:
                logger.debug(
                    "Could not resolve runtime relation "
                    "endpoint %s from SQLite.",
                    runtimeObjectId,
                    exc_info=True,
                )

        # Some Scipion relations represent an endpoint as:
        # protocolId + extended output path.
        if endpointObject is None:
            if extendedOutputName:
                return {
                    "runtimeObjectId": runtimeObjectId,
                    "producerProtocolId": runtimeObjectId,
                    "outputName": extendedOutputName,
                    "className": None,
                }

            return None

        producerProtocolId = self._toOptionalInt(
            self._callOptionalGetter(
                endpointObject,
                "getObjParentId",
            )
        )

        if producerProtocolId is None:
            producerProtocolId = self._toOptionalInt(
                getattr(
                    endpointObject,
                    "_objParentId",
                    None,
                )
            )

        objectName = self._callOptionalGetter(
            endpointObject,
            "getObjName",
        )

        if objectName in (None, ""):
            objectName = getattr(
                endpointObject,
                "_objName",
                None,
            )

        objectName = str(
            objectName or ""
        ).strip()

        outputName = ""

        if producerProtocolId is not None:
            expectedPrefix = "%s." % (
                producerProtocolId,
            )

            if objectName.startswith(
                    expectedPrefix
            ):
                outputName = objectName[
                    len(expectedPrefix):
                ]

        if not outputName and extendedOutputName:
            outputName = extendedOutputName

        if (
                not outputName
                and "." in objectName
        ):
            possibleProtocolId, possibleOutputName = (
                objectName.split(
                    ".",
                    1,
                )
            )

            if self._toOptionalInt(
                    possibleProtocolId
            ) is not None:
                producerProtocolId = (
                    self._toOptionalInt(
                        possibleProtocolId
                    )
                )
                outputName = (
                    possibleOutputName
                )

        if not outputName:
            outputName = objectName

        if (
                producerProtocolId is None
                or not outputName
        ):
            return None

        return {
            "runtimeObjectId": runtimeObjectId,
            "producerProtocolId": (
                producerProtocolId
            ),
            "outputName": outputName,
            "className": (
                endpointObject
                .__class__
                .__name__
            ),
        }

    @staticmethod
    def _mergeRelationEndpoint(
            currentEndpoint,
            candidateEndpoint,
    ):
        if (
                not isinstance(candidateEndpoint, dict)
                or not candidateEndpoint
        ):
            return currentEndpoint

        if (
                not isinstance(currentEndpoint, dict)
                or not currentEndpoint
        ):
            return dict(candidateEndpoint)

        mergedEndpoint = dict(currentEndpoint)

        for key, value in candidateEndpoint.items():
            if (
                    mergedEndpoint.get(key) in (None, "")
                    and value not in (None, "")
            ):
                mergedEndpoint[key] = value

        return mergedEndpoint

    @staticmethod
    def _isNestedScalarRelationEndpoint(endpoint) -> bool:
        if not isinstance(endpoint, dict):
            return False

        className = str(endpoint.get("className") or "").strip()
        outputName = str(endpoint.get("outputName") or "").strip()

        if className not in {"Boolean", "Float", "Integer", "Scalar", "String"}:
            return False

        objectId, separator, attributeName = outputName.partition(".")

        return separator == "." and objectId.isdigit() and attributeName.startswith("_")

    def collectProtocolRelations(
            self,
            protocolCandidates,
    ) -> Dict[str, Any]:
        """
        Collect one relation snapshot from all available protocol representations.

        The runtime protocol loaded from logs/run.db is the primary source.
        Additional non-duplicated relations from SQLite mirrors are merged.
        Deleted output generations are pruned later during synchronization.
        """
        relations = []
        relationsByKey = {}
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

                    relation[
                        "_parentEndpoint"
                    ] = (
                        self
                        ._describeRuntimeRelationEndpoint(
                            protocol=protocol,
                            runtimeObjectId=relation.get(
                                "object_parent_id"
                            ),
                            extended=relation.get(
                                "object_parent_extended"
                            ),
                        )
                    )

                    relation[
                        "_childEndpoint"
                    ] = (
                        self
                        ._describeRuntimeRelationEndpoint(
                            protocol=protocol,
                            runtimeObjectId=relation.get(
                                "object_child_id"
                            ),
                            extended=relation.get(
                                "object_child_extended"
                            ),
                        )
                    )
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

                existingRelation = relationsByKey.get(
                    relationKey
                )

                if existingRelation is not None:
                    existingRelation[
                        "_parentEndpoint"
                    ] = self._mergeRelationEndpoint(
                        existingRelation.get(
                            "_parentEndpoint"
                        ),
                        relation.get(
                            "_parentEndpoint"
                        ),
                    )

                    existingRelation[
                        "_childEndpoint"
                    ] = self._mergeRelationEndpoint(
                        existingRelation.get(
                            "_childEndpoint"
                        ),
                        relation.get(
                            "_childEndpoint"
                        ),
                    )

                    continue

                relationsByKey[relationKey] = relation
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

    def _resolvePersistedRelationEndpoint(
            self,
            repository,
            mapper,
            projectId: int,
            runtimeObjectId,
            extended=None,
            endpoint=None,
    ):
        """
        Prefer producer protocol + output name.

        The runtime object id belongs to SQLite and is only used as
        compatibility fallback when no semantic endpoint is available.
        """
        endpoint = (
            endpoint
            if isinstance(
                endpoint,
                dict,
            )
            else {}
        )

        producerProtocolId = (
            self._toOptionalInt(
                endpoint.get(
                    "producerProtocolId"
                )
            )
        )

        outputName = str(
            endpoint.get(
                "outputName"
            )
            or ""
        ).strip()

        if (
                producerProtocolId is not None
                and outputName
        ):
            persistedObject = (
                repository
                .getPersistedOutputObjectByProtocolOutput(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=producerProtocolId,
                    outputName=outputName,
                )
            )

            if persistedObject is not None:
                return persistedObject

        return (
            repository
            .getPersistedOutputObjectByRuntimeId(
                mapper=mapper,
                projectId=projectId,
                runtimeObjectId=runtimeObjectId,
                extended=extended,
            )
        )

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
        skipped = []
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
                        "creatorProtocolId": relation.get("parent_id") or protocolId,
                        "parentRuntimeObjectId": relation.get("object_parent_id"),
                        "childRuntimeObjectId": relation.get("object_child_id"),
                        "parentExtended": relation.get("object_parent_extended"),
                        "childExtended": relation.get("object_child_extended"),
                    }

                    parentEndpoint = relation.get("_parentEndpoint")
                    childEndpoint = relation.get("_childEndpoint")

                    if isinstance(parentEndpoint, dict) and parentEndpoint:
                        relationItem["parentEndpoint"] = parentEndpoint

                    if isinstance(childEndpoint, dict) and childEndpoint:
                        relationItem["childEndpoint"] = childEndpoint

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

            currentOutputIds = self._collectCurrentOutputRuntimeObjectIds(
                protocol
            )

            if currentOutputIds is not None:
                currentRelations = []

                for relationItem in protocolRelations:
                    parentObjectId = relationItem["parentRuntimeObjectId"]
                    childObjectId = relationItem["childRuntimeObjectId"]

                    if (
                            parentObjectId in currentOutputIds
                            or childObjectId in currentOutputIds
                    ):
                        currentRelations.append(relationItem)
                    else:
                        stale.append(relationItem)

                protocolRelations = currentRelations

            # Resolve every object before deleting the previous snapshot.
            # If PostgreSQL does not contain all required outputs yet, preserve
            # the previous relations and retry on the next synchronization.
            unresolvedRelations = []
            preparedRelations = []

            for relationItem in protocolRelations:
                skippedEndpoints = [
                    endpointName
                    for endpointName, endpointKey in (
                        ("parent", "parentEndpoint"),
                        ("child", "childEndpoint"),
                    )
                    if self._isNestedScalarRelationEndpoint(relationItem.get(endpointKey))
                ]

                if skippedEndpoints:
                    skippedRelation = {
                        **relationItem,
                        "reason": "nested_scalar_endpoint",
                        "endpoints": skippedEndpoints,
                    }
                    skipped.append(skippedRelation)

                    logger.warning(
                        "Skipping unsupported nested scalar relation during PostgreSQL migration. "
                        "projectId=%s protocolId=%s relationId=%s endpoints=%s",
                        projectId,
                        protocolIdText,
                        relationItem.get("relationId"),
                        skippedEndpoints,
                    )

                    continue

                parentObject = (
                    self
                    ._resolvePersistedRelationEndpoint(
                        repository=repository,
                        mapper=mapper,
                        projectId=projectId,
                        runtimeObjectId=relationItem[
                            "parentRuntimeObjectId"
                        ],
                        extended=relationItem[
                            "parentExtended"
                        ],
                        endpoint=relationItem.get(
                            "parentEndpoint"
                        ),
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
                    self
                    ._resolvePersistedRelationEndpoint(
                        repository=repository,
                        mapper=mapper,
                        projectId=projectId,
                        runtimeObjectId=relationItem[
                            "childRuntimeObjectId"
                        ],
                        extended=relationItem[
                            "childExtended"
                        ],
                        endpoint=relationItem.get(
                            "childEndpoint"
                        ),
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
                    "parentRuntimeObjectId":
                        relationItem["parentRuntimeObjectId"],

                    "childRuntimeObjectId":
                        relationItem["childRuntimeObjectId"],
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
            "relationsSkipped": len(skipped),
            "skippedRelations": skipped,
            "relationsStale": len(stale),
            "staleRelations": stale,
            "relationMissing": missing,
            "relationErrors": errors,
            "cleanup": cleanupItems,
            "complete": not missing and not errors,
        }
