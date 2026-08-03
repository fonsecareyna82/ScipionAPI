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
from typing import Dict, Optional


class ProjectRuntimeRepository:
    """PostgreSQL runtime project metadata lookup."""

    def getProjectNameById(
            self,
            mapper,
            projectId: int,
    ) -> Optional[str]:
        row = mapper.db.fetchOne(
            """
            SELECT name
              FROM projects
             WHERE id = %s
            """,
            (int(projectId),),
        )

        if not row:
            return None

        rawPath = row.get("name") if isinstance(row, dict) else row[0]

        if not rawPath:
            return None

        return str(rawPath)

    def getProjectRuntimeResourceCounts(
            self,
            mapper,
            projectId: int,
    ) -> Dict[str, int]:
        resourceNames = (
            "projects",
            "protocols",
            "dependencies",
            "inputRefs",
            "steps",
            "outputs",
            "objects",
            "sets",
            "setItems",
            "relations",
        )

        row = mapper.db.fetchOne(
            """
            SELECT
                (
                    SELECT COUNT(*)
                      FROM projects
                     WHERE id = %s
                ) AS "projects",
                (
                    SELECT COUNT(*)
                      FROM protocols
                     WHERE "projectId" = %s
                ) AS "protocols",
                (
                    SELECT COUNT(*)
                      FROM protocol_dependencies
                     WHERE "projectId" = %s
                ) AS "dependencies",
                (
                    SELECT COUNT(*)
                      FROM protocol_input_refs
                     WHERE "projectId" = %s
                ) AS "inputRefs",
                (
                    SELECT COUNT(*)
                      FROM protocol_steps
                     WHERE "projectId" = %s
                ) AS "steps",
                (
                    SELECT COUNT(*)
                      FROM scipion_objects
                     WHERE "projectId" = %s
                       AND "parentObjectId" IS NULL
                ) AS "outputs",
                (
                    SELECT COUNT(*)
                      FROM scipion_objects
                     WHERE "projectId" = %s
                ) AS "objects",
                (
                    SELECT COUNT(*)
                      FROM scipion_sets
                     WHERE "projectId" = %s
                ) AS "sets",
                (
                    SELECT COUNT(*)
                      FROM scipion_set_items set_item
                      JOIN scipion_sets stored_set
                        ON stored_set.id = set_item."setId"
                     WHERE stored_set."projectId" = %s
                ) AS "setItems",
                (
                    SELECT COUNT(*)
                      FROM scipion_relations
                     WHERE "projectId" = %s
                ) AS "relations"
            """,
            (int(projectId),) * len(resourceNames),
        )

        rowData = dict(row) if row else {}

        return {
            resourceName: int(rowData.get(resourceName) or 0)
            for resourceName in resourceNames
        }

