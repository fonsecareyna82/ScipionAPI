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

import pytest

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


def test_ImportAuditExposesPostMigrationAuditsWithoutRuntimeModeSwitch():
    auditServiceClass = RuntimeProjectImportAuditService
    classSource = inspect.getsource(
        auditServiceClass
    )

    assert hasattr(
        auditServiceClass,
        "auditProject",
    )
    assert hasattr(
        auditServiceClass,
        "auditLoadedProject",
    )
    assert hasattr(
        auditServiceClass,
        "auditRuntimeProject",
    )

    assert "usingPostgresqlRuntimeMapper" not in classSource


class RuntimeProjectStub:
    def __init__(
            self,
            runtimeMapper,
            activeMapper=None,
    ):
        self.runtimeMapper = runtimeMapper
        self.mapper = (
            runtimeMapper
            if activeMapper is None
            else activeMapper
        )

    def getPostgresqlRuntimeMapper(self):
        return self.runtimeMapper


def test_AuditRuntimeProjectValidatesRegisteredPostgresqlMapper(
        tmp_path,
):
    runtimeMapper = object()
    runtimeProject = RuntimeProjectStub(
        runtimeMapper=runtimeMapper,
    )

    result = (
        RuntimeProjectImportAuditService()
        .auditRuntimeProject(
            runtimeProject=runtimeProject,
            projectPath=str(tmp_path),
        )
    )

    assert result == {
        "complete": True,
        "runtimeMapper": "object",
        "writeFallbackEnabled": False,
        "projectSqlitePresent": False,
    }


def test_AuditRuntimeProjectRejectsDifferentActiveMapper(
        tmp_path,
):
    runtimeProject = RuntimeProjectStub(
        runtimeMapper=object(),
        activeMapper=object(),
    )

    with pytest.raises(
            RuntimeError,
            match="registered PostgreSQL runtime mapper",
    ):
        RuntimeProjectImportAuditService().auditRuntimeProject(
            runtimeProject=runtimeProject,
            projectPath=str(tmp_path),
        )


def test_AuditRuntimeProjectRejectsRemainingProjectSqlite(
        tmp_path,
):
    projectDatabase = tmp_path / "project.sqlite"
    projectDatabase.write_text(
        "legacy",
        encoding="utf-8",
    )

    runtimeProject = RuntimeProjectStub(
        runtimeMapper=object(),
    )

    with pytest.raises(
            RuntimeError,
            match="legacy project databases",
    ):
        RuntimeProjectImportAuditService().auditRuntimeProject(
            runtimeProject=runtimeProject,
            projectPath=str(tmp_path),
        )


def test_AuditLoadedProjectValidatesReconstructedGraph():
    loadedProject = {
        "protocols": {
            "PROJECT": {
                "id": "PROJECT",
            },
            "10": {
                "parents": [],
                "inputs": [],
                "outputs": [
                    {
                        "name": "outputParticles",
                    },
                ],
            },
            "11": {
                "parents": [
                    "10",
                ],
                "inputs": [
                    {
                        "name": "inputParticles",
                    },
                ],
                "outputs": [],
            },
        },
    }

    migrationReport = {
        "protocols": 2,
        "dependencies": 1,
        "inputRefs": 1,
        "outputs": 1,
    }

    result = (
        RuntimeProjectImportAuditService()
        .auditLoadedProject(
            loadedProject=loadedProject,
            migrationReport=migrationReport,
        )
    )

    assert result == {
        "complete": True,
        "expected": migrationReport,
        "actual": migrationReport,
        "mismatches": [],
    }