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

    def syncProjectRelations(
            self,
            *,
            mapper,
            projectId: int,
            protocolsByScipionId: Dict[str, Any],
            protocolDbIdByScipionId: Dict[str, int],
    ) -> Dict[str, Any]:
        repository = ProtocolGraphRepository()

        declared = []
        persisted = []
        missing = []
        errors = []

        for protocolId, protocol in protocolsByScipionId.items():
            protocolDbId = protocolDbIdByScipionId.get(str(protocolId))

            if protocolDbId is None:
                errors.append({
                    "protocolId": str(protocolId),
                    "error": "creator_protocol_not_persisted",
                })
                continue

            try:
                relations = protocol.getRelations() or []
            except Exception as error:
                errors.append({
                    "protocolId": str(protocolId),
                    "error": str(error),
                })
                continue

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

                    declared.append(relationItem)

                    result = repository.insertImportedOutputRelation(
                        mapper=mapper,
                        projectId=projectId,
                        creatorProtocolDbId=int(protocolDbId),
                        creatorProtocolId=int(relationItem["creatorProtocolId"]),
                        relationName=relationItem["relationName"],
                        parentRuntimeObjectId=int(relationItem["parentRuntimeObjectId"]),
                        childRuntimeObjectId=int(relationItem["childRuntimeObjectId"]),
                        parentExtended=relationItem["parentExtended"],
                        childExtended=relationItem["childExtended"],
                        metadata={
                            "source": "project_import",
                            "sqliteRelationId": relationItem["relationId"],
                        },
                    )

                    if result.get("saved"):
                        persisted.append(result)
                    else:
                        missing.append({
                            **relationItem,
                            "reason": result.get("reason"),
                        })

                except Exception as error:
                    errors.append({
                        "protocolId": str(protocolId),
                        "relation": dict(rawRelation),
                        "error": str(error),
                    })

                    logger.exception(
                        "Failed to import project relation. projectId=%s protocolId=%s",
                        projectId,
                        protocolId,
                    )

        return {
            "relationsDeclared": len(declared),
            "relations": len(persisted),
            "relationMissing": missing,
            "relationErrors": errors,
            "complete": not missing and not errors,
        }
