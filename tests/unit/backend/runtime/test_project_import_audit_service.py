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
import inspect

import app.backend.runtime.project_import_audit_service as auditModule
from app.backend.runtime.project_import_audit_service import RuntimeProjectImportAuditService


class ForbiddenDatabase:
    def fetchOne(self, *args, **kwargs):
        raise AssertionError("RuntimeProjectImportAuditService must not call db.fetchOne()")

    def fetchAll(self, *args, **kwargs):
        raise AssertionError("RuntimeProjectImportAuditService must not call db.fetchAll()")

    def execute(self, *args, **kwargs):
        raise AssertionError("RuntimeProjectImportAuditService must not call db.execute()")


class MapperStub:
    def __init__(self):
        self.db = ForbiddenDatabase()


def test_AuditProjectDelegatesRuntimeCounts(monkeypatch):
    mapper = MapperStub()
    repositoryCalls = []

    class ProjectRuntimeRepositoryStub:
        def getProjectRuntimeResourceCounts(self, mapper, projectId):
            repositoryCalls.append({
                "mapper": mapper,
                "projectId": projectId,
            })

            return {
                "projects": 1,
                "protocols": 2,
                "dependencies": 3,
                "inputRefs": 4,
                "steps": 5,
                "outputs": 6,
                "objects": 7,
                "sets": 8,
                "setItems": 9,
                "relations": 10,
            }

    monkeypatch.setattr(auditModule, "ProjectRuntimeRepository", ProjectRuntimeRepositoryStub)

    migrationReport = {
        "protocols": 2,
        "dependencies": 3,
        "inputRefs": 4,
        "steps": 5,
        "outputs": 6,
        "objects": 7,
        "sets": 8,
        "setItems": 9,
        "relations": 10,
    }

    result = RuntimeProjectImportAuditService().auditProject(mapper=mapper, projectId=7, migrationReport=migrationReport)

    expected = {
        "projects": 1,
        **migrationReport,
    }

    assert result == {
        "complete": True,
        "expected": expected,
        "actual": expected,
        "mismatches": [],
    }

    assert repositoryCalls == [
        {
            "mapper": mapper,
            "projectId": 7,
        },
    ]

    source = inspect.getsource(RuntimeProjectImportAuditService.auditProject)

    assert "getProjectRuntimeResourceCounts(" in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source

