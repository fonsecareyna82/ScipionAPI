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
import importlib


def test_GetProjectByIdLoadsWorkflowDirectlyFromPostgresql(
        authTestEnv,
        tmp_path,
        monkeypatch,
):
    module = importlib.import_module(
        "app.backend.api.services.project_service"
    )

    service = object.__new__(
        module.ProjectService
    )

    service.currentProject = None

    class FakeMapper:
        def getProject(self, projectId, userId):
            assert projectId == 7
            assert userId == 11

            return {
                "id": 7,
                "ownerId": 11,
                "name": str(tmp_path),
                "createdAt": "2026-07-24T12:30:00",
                "updatedAt": None,
                "status": "active",
            }

    def failLegacyProjectLoad(*args, **kwargs):
        raise AssertionError(
            "Legacy project.sqlite workflow loading must not be used"
        )

    monkeypatch.setattr(
        service,
        "loadProject",
        failLegacyProjectLoad,
    )

    def failRuntimeProjectLoad(**kwargs):
        raise AssertionError("Read-only PostgreSQL workflow loading must not create a runtime project")

    monkeypatch.setattr(service, "_loadPostgresqlRuntimeProject", failRuntimeProjectLoad)

    monkeypatch.setattr(
        service,
        "loadProjectFromPostgresql",
        lambda dbProj, mapper: {
            "id": dbProj["id"],
            "protocols": {},
        },
    )

    result = service.getProjectById(mapper=FakeMapper(),
                                    projectId=7,
                                    currentUser={"id": 11},
                                    refresh=False,
                                    checkPid=False,
                                    loadWorkflowFromPostgresql=True,
                                    usePostgresqlRuntimeProject=True)

    assert result == {
        "id": 7,
        "protocols": {},
    }

    assert service.currentProject is None


def test_GetProjectByIdLoadsPostgresqlWorkflowBeforeConsistencyAudit(
        authTestEnv,
        tmp_path,
        monkeypatch,
):
    module = importlib.import_module(
        "app.backend.api.services.project_service"
    )
    consistencyModule = importlib.import_module(
        "app.backend.api.services.project_consistency_service"
    )

    service = object.__new__(
        module.ProjectService
    )
    service.currentProject = None

    class FakeMapper:
        def getProject(self, projectId, userId):
            assert projectId == 7
            assert userId == 11

            return {
                "id": 7,
                "ownerId": 11,
                "name": str(tmp_path),
                "createdAt": "2026-07-24T12:30:00",
                "updatedAt": None,
                "status": "active",
            }

    mapper = FakeMapper()

    def failLegacyProjectLoad(*args, **kwargs):
        raise AssertionError(
            "getProjectById must not load project.sqlite"
        )

    def failRuntimeProjectLoad(**kwargs):
        raise AssertionError(
            "Consistency requests must not create a PostgreSQL runtime project"
        )

    monkeypatch.setattr(
        service,
        "loadProject",
        failLegacyProjectLoad,
    )
    monkeypatch.setattr(
        service,
        "_loadPostgresqlRuntimeProject",
        failRuntimeProjectLoad,
    )
    monkeypatch.setattr(
        service,
        "loadProjectFromPostgresql",
        lambda dbProj, mapper: {
            "id": dbProj["id"],
            "protocols": {},
        },
    )

    auditCalls = []

    def validateConsistency(
            consistencyService,
            **kwargs,
    ):
        auditCalls.append(kwargs)

        return {
            "ok": True,
            "projectId": kwargs["projectId"],
        }

    monkeypatch.setattr(
        consistencyModule.ProjectConsistencyService,
        "validateProjectPostgresqlConsistency",
        validateConsistency,
    )

    result = service.getProjectById(
        mapper=mapper,
        projectId=7,
        currentUser={"id": 11},
        refresh=False,
        checkPid=False,
        validateConsistency=True,
        failOnConsistencyError=True,
        loadWorkflowFromPostgresql=False,
        usePostgresqlRuntimeProject=True,
    )

    assert result == {
        "id": 7,
        "protocols": {},
        "postgresqlConsistency": {
            "ok": True,
            "projectId": 7,
        },
    }

    assert auditCalls == [
        {
            "mapper": mapper,
            "projectId": 7,
            "currentUser": {"id": 11},
            "refresh": False,
            "checkPid": False,
        },
    ]


def test_LoadLegacyProjectForImportLoadsProjectSqlite(
        authTestEnv,
        tmp_path,
        monkeypatch,
):
    module = importlib.import_module(
        "app.backend.api.services.project_service"
    )

    service = object.__new__(module.ProjectService)
    service.currentProject = None

    loadCalls = []

    class FakeLegacyProject:
        def __init__(self, domain, path):
            self.domain = domain
            self.path = path

        def getDbPath(self):
            return str(tmp_path / "project.sqlite")

        def load(self, dbPath):
            loadCalls.append(dbPath)

    monkeypatch.setattr(
        module,
        "ScipionProject",
        FakeLegacyProject,
    )

    project = service._loadLegacyProjectForImport(str(tmp_path))

    assert project.path == str(tmp_path)
    assert loadCalls == [str(tmp_path / "project.sqlite")]
    assert service.currentProject is project

