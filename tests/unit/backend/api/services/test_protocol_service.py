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


class FakeCurrentProject:
    def __init__(self, projectPath):
        self.path = projectPath


def test_BuildNewProtocolContextInSubprocessUsesPostgresqlRuntimeProject(
        authTestEnv,
        monkeypatch,
):
    protocolServiceModule = importlib.import_module(
        "app.backend.api.services.protocol_service"
    )

    runnerCalls = []

    class FakeJsonSubprocessRunner:
        def run(
                self,
                code,
                operationName,
                extraEnv=None,
        ):
            runnerCalls.append({
                "code": code,
                "operationName": operationName,
                "extraEnv": dict(
                    extraEnv or {}
                ),
            })

            return {
                "status": "ok",
            }

    monkeypatch.setattr(
        protocolServiceModule,
        "JsonSubprocessRunner",
        FakeJsonSubprocessRunner,
    )

    service = (
        protocolServiceModule
        .ProtocolService()
    )
    currentProject = FakeCurrentProject(
        "/tmp/postgresql-project"
    )

    result = service._buildNewProtocolContextInSubprocess(
        currentProject=currentProject,
        projectId=344,
        protocolClassName="ProtNewPlugin",
    )

    assert result == {
        "status": "ok",
    }
    assert len(runnerCalls) == 1

    runnerCall = runnerCalls[0]
    subprocessCode = runnerCall["code"]

    assert runnerCall["operationName"] == (
        "Build new protocol context"
    )
    assert runnerCall["extraEnv"] == {
        "SCIPIONWEB_PROJECT_PATH": "/tmp/postgresql-project",
        "SCIPIONWEB_PROJECT_ID": 344,
        "SCIPIONWEB_PROTOCOL_CLASS": "ProtNewPlugin",
    }

    assert (
        "from app.backend.database import getMapper"
        in subprocessCode
    )
    assert (
        "projectService._loadPostgresqlRuntimeProject("
        in subprocessCode
    )
    assert (
        "project.closeMapper()"
        in subprocessCode
    )
    assert (
        "mapper.db.close()"
        in subprocessCode
    )

    assert (
        "from pyworkflow.project import Manager"
        not in subprocessCode
    )
    assert (
        "manager.loadProject("
        not in subprocessCode
    )


def test_BuildNewProtocolContextInSubprocessResolvesProjectGetPath(
        authTestEnv,
        monkeypatch,
):
    protocolServiceModule = importlib.import_module(
        "app.backend.api.services.protocol_service"
    )

    runnerCalls = []

    class FakeCurrentProjectWithGetter:
        def getPath(self):
            return "/tmp/project-from-get-path"

    class FakeJsonSubprocessRunner:
        def run(
                self,
                code,
                operationName,
                extraEnv=None,
        ):
            runnerCalls.append({
                "code": code,
                "operationName": operationName,
                "extraEnv": dict(
                    extraEnv or {}
                ),
            })

            return {
                "status": "ok",
            }

    monkeypatch.setattr(
        protocolServiceModule,
        "JsonSubprocessRunner",
        FakeJsonSubprocessRunner,
    )

    service = (
        protocolServiceModule
        .ProtocolService()
    )

    result = service._buildNewProtocolContextInSubprocess(
        currentProject=FakeCurrentProjectWithGetter(),
        projectId=344,
        protocolClassName="ProtNewPlugin",
    )

    assert result == {
        "status": "ok",
    }
    assert runnerCalls[0]["extraEnv"] == {
        "SCIPIONWEB_PROJECT_PATH": (
            "/tmp/project-from-get-path"
        ),
        "SCIPIONWEB_PROJECT_ID": 344,
        "SCIPIONWEB_PROTOCOL_CLASS": "ProtNewPlugin",
    }