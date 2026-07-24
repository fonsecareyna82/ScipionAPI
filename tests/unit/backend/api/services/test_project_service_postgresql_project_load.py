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


def test_GetProjectByIdLoadsPostgresqlRuntimeWithoutLegacyProject(
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

    loadedRuntimeProjects = []

    monkeypatch.setattr(
        service,
        "loadProjectRuntimeContext",
        lambda **kwargs: (
            _ for _ in ()
        ).throw(
            AssertionError(
                "Legacy project.sqlite context must not be loaded"
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "_loadPostgresqlRuntimeProject",
        lambda **kwargs: loadedRuntimeProjects.append(
            kwargs
        ),
    )

    monkeypatch.setattr(
        service,
        "loadProjectFromPostgresql",
        lambda dbProj, mapper: {
            "id": dbProj["id"],
            "protocols": {},
        },
    )

    result = service.getProjectById(
        mapper=FakeMapper(),
        projectId=7,
        currentUser={"id": 11},
        refresh=False,
        checkPid=False,
        loadWorkflowFromPostgresql=True,
        usePostgresqlRuntimeProject=True,
        usePostgresqlRuntimeWriteFallback=False,
        syncRuntimeStatuses=True,
    )

    assert result == {
        "id": 7,
        "protocols": {},
    }

    assert len(loadedRuntimeProjects) == 1

    loadCall = loadedRuntimeProjects[0]

    assert loadCall["projectId"] == 7
    assert loadCall["projectPath"] == str(tmp_path)
    assert loadCall["enableWriteFallback"] is False

