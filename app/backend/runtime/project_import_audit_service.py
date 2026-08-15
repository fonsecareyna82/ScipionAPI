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
from pathlib import Path
from typing import Any, Dict
from app.backend.runtime.project_runtime_repository import ProjectRuntimeRepository


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
            "relations": int(
                migrationReport.get("relations") or 0
            ),
        }

        resourceCounts = ProjectRuntimeRepository().getProjectRuntimeResourceCounts(mapper=mapper, projectId=projectId)

        actual = {
            key: int(resourceCounts.get(key) or 0)
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
            "protocols": int(migrationReport.get("protocols") or 0),
            "dependencies": int(migrationReport.get("dependencies") or 0),
            "inputRefs": int(migrationReport.get("inputRefs") or 0),
            "outputs": int(migrationReport.get("outputs") or 0),
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

    def auditRuntimeProject(
            self,
            *,
            runtimeProject,
            projectPath: str,
    ) -> Dict[str, Any]:
        if runtimeProject is None:
            raise RuntimeError(
                "PostgreSQL runtime project was not loaded"
            )

        getRuntimeMapper = getattr(
            runtimeProject,
            "getPostgresqlRuntimeMapper",
            None,
        )

        if not callable(getRuntimeMapper):
            raise RuntimeError(
                "Imported project does not expose getPostgresqlRuntimeMapper()"
            )

        runtimeMapper = getRuntimeMapper()

        if runtimeMapper is None:
            raise RuntimeError(
                "Imported project does not expose PostgresqlRuntimeMapper"
            )

        if getattr(runtimeProject, "mapper", None) is not runtimeMapper:
            raise RuntimeError(
                "Imported project is not using its registered PostgreSQL runtime mapper"
            )

        writeFallbackMapper = getattr(
            runtimeMapper,
            "writeFallbackMapper",
            None,
        )

        if writeFallbackMapper is not None:
            raise RuntimeError(
                "Imported project unexpectedly enabled the SQLite write fallback"
            )

        projectDatabase = Path(projectPath) / "project.sqlite"

        remainingProjectDatabases = [
            str(projectDatabase) + suffix
            for suffix in (
                "",
                "-wal",
                "-shm",
                "-journal",
            )
            if os.path.lexists(str(projectDatabase) + suffix)
        ]

        if remainingProjectDatabases:
            raise RuntimeError(
                "PostgreSQL runtime project still has legacy project databases: %s"
                % remainingProjectDatabases
            )

        return {
            "complete": True,
            "runtimeMapper": runtimeMapper.__class__.__name__,
            "writeFallbackEnabled": False,
            "projectSqlitePresent": False,
        }


