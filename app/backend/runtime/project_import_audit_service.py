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
from typing import Any, Dict


class RuntimeProjectImportAuditService:
    """Audit a migrated project using PostgreSQL as the only source."""

    def auditProject(
            self,
            *,
            mapper,
            projectId: int,
            migrationReport: Dict[str, Any],
    ) -> Dict[str, Any]:
        expected = {
            "projects": 1,
            "protocols": int(
                migrationReport.get("protocols") or 0
            ),
            "dependencies": int(
                migrationReport.get("dependencies") or 0
            ),
            "inputRefs": int(
                migrationReport.get("inputRefs") or 0
            ),
            "steps": int(
                migrationReport.get("steps") or 0
            ),
            "outputs": int(
                migrationReport.get("outputs") or 0
            ),
            "objects": int(
                migrationReport.get("objects") or 0
            ),
            "sets": int(
                migrationReport.get("sets") or 0
            ),
            "setItems": int(
                migrationReport.get("setItems") or 0
            ),
            "legacyRelations": int(
                migrationReport.get("relations") or 0
            ),
            "objectRelations": int(
                migrationReport.get("relations") or 0
            ),
        }

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
                      FROM scipion_set_items i
                      JOIN scipion_sets s
                        ON s.id = i."setId"
                     WHERE s."projectId" = %s
                ) AS "setItems",
                (
                    SELECT COUNT(*)
                      FROM scipion_relations
                     WHERE "projectId" = %s
                ) AS "legacyRelations",
                (
                    SELECT COUNT(*)
                      FROM scipion_object_relations
                     WHERE "projectId" = %s
                ) AS "objectRelations"
            """,
            (
                int(projectId),
                int(projectId),
                int(projectId),
                int(projectId),
                int(projectId),
                int(projectId),
                int(projectId),
                int(projectId),
                int(projectId),
                int(projectId),
                int(projectId),
            ),
        )

        actual = {
            key: int((row or {}).get(key) or 0)
            for key in expected
        }

        mismatches = []

        for key, expectedValue in expected.items():
            actualValue = actual[key]

            if actualValue != expectedValue:
                mismatches.append({
                    "resource": key,
                    "expected": expectedValue,
                    "actual": actualValue,
                })

        if mismatches:
            raise RuntimeError(
                "PostgreSQL project import audit failed: %s"
                % mismatches
            )

        return {
            "complete": True,
            "expected": expected,
            "actual": actual,
            "mismatches": [],
        }

    def auditLoadedProject(
            self,
            *,
            loadedProject: Dict[str, Any],
            migrationReport: Dict[str, Any],
    ) -> Dict[str, Any]:
        graph = (loadedProject or {}).get("protocols") or {}

        if "PROJECT" not in graph:
            raise RuntimeError(
                "PostgreSQL-only project reconstruction did not produce the PROJECT root"
            )

        protocolNodes = {
            str(protocolId): node
            for protocolId, node in graph.items()
            if str(protocolId) != "PROJECT" and isinstance(node, dict)
        }

        expected = {
            "protocols": int(
                migrationReport.get("protocols") or 0
            ),
            "dependencies": int(
                migrationReport.get("dependencies") or 0
            ),
            "inputRefs": int(
                migrationReport.get("inputRefs") or 0
            ),
            "outputs": int(
                migrationReport.get("outputs") or 0
            ),
        }

        actual = {
            "protocols": len(protocolNodes),
            "dependencies": sum(
                len(node.get("parents") or [])
                for node in protocolNodes.values()
            ),
            "inputRefs": sum(
                len(node.get("inputs") or [])
                for node in protocolNodes.values()
            ),
            "outputs": sum(
                len(node.get("outputs") or [])
                for node in protocolNodes.values()
            ),
        }

        mismatches = []

        for key, expectedValue in expected.items():
            actualValue = actual[key]

            if actualValue != expectedValue:
                mismatches.append({
                    "resource": key,
                    "expected": expectedValue,
                    "actual": actualValue,
                })

        if mismatches:
            raise RuntimeError(
                "PostgreSQL-only project reconstruction audit failed: %s"
                % mismatches
            )

        return {
            "complete": True,
            "expected": expected,
            "actual": actual,
            "mismatches": [],
        }