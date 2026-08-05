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


