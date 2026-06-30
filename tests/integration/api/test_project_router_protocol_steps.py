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
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
import pytest


class FakeProtocolStepsProjectService:
    def __init__(self):
        self.projectByIdResult = {"id": 1, "name": "Demo project"}
        self.lastGetProjectByIdCall = None

        self.protocolStepsResult = [
            {
                "index": 1,
                "name": "resumeStep",
                "status": "finished",
                "prerequisites": [],
                "args": [],
                "initTime": None,
                "endTime": None,
                "elapsedSeconds": 0,
                "error": None,
                "interactive": False,
                "needsGpu": False,
                "event": None,
                "updatedAt": None,
            },
        ]
        self.lastListProtocolStepsCall = None

        self.updateProtocolStepStatusResult = {
            "index": 2,
            "name": "processStep",
            "status": "finished",
            "prerequisites": [1],
            "args": ["TS_1"],
            "initTime": None,
            "endTime": None,
            "elapsedSeconds": 0,
            "error": None,
            "interactive": False,
            "needsGpu": True,
            "event": None,
            "updatedAt": None,
        }
        self.updateProtocolStepStatusError = None
        self.lastUpdateProtocolStepStatusCall = None
        self.projectDbRowResult = {"id": 1, "name": "Demo project"}
        self.lastGetProjectDbRowCall = None

    def getProjectById(self, mapper, projectId, currentUser, refresh=False, checkPid=False):
        self.lastGetProjectByIdCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
            "refresh": refresh,
            "checkPid": checkPid,
        }
        return self.projectByIdResult

    def listProtocolStepsService(self, mapper, projectId, protocolId):
        self.lastListProtocolStepsCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
        }
        return self.protocolStepsResult

    def getProjectDbRow(self, mapper, projectId, currentUser):
        self.lastGetProjectDbRowCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
        }
        return self.projectDbRowResult

    def updateProtocolStepStatusService(
            self,
            mapper,
            projectId,
            protocolId,
            stepIndex,
            stepStatus,
    ):
        self.lastUpdateProtocolStepStatusCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
            "stepIndex": stepIndex,
            "stepStatus": stepStatus,
        }
        if self.updateProtocolStepStatusError is not None:
            raise self.updateProtocolStepStatusError
        return self.updateProtocolStepStatusResult


@pytest.fixture
def fakeProtocolStepsProjectService():
    return FakeProtocolStepsProjectService()


@pytest.fixture
def protocolStepsClient(
    projectRouterModule,
    fakeProjectMapper,
    fakeProtocolStepsProjectService,
):
    app = FastAPI()
    app.include_router(projectRouterModule.router)

    app.dependency_overrides[projectRouterModule.getMapper] = lambda: fakeProjectMapper
    app.dependency_overrides[projectRouterModule.getCurrentUser] = lambda: {
        "id": 1,
        "email": "user@example.com",
        "role": "user",
    }
    app.dependency_overrides[
        projectRouterModule.getProjectService
    ] = lambda: fakeProtocolStepsProjectService

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_ListProtocolStepsReturns404WhenProjectMissing(
    protocolStepsClient,
    fakeProtocolStepsProjectService,
):
    fakeProtocolStepsProjectService.projectDbRowResult = None

    response = protocolStepsClient.get("/projects/1/protocols/10/steps")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_ListProtocolStepsDelegatesToService(
    protocolStepsClient,
    fakeProjectMapper,
    fakeProtocolStepsProjectService,
):
    response = protocolStepsClient.get("/projects/1/protocols/10/steps")

    assert response.status_code == 200
    assert response.json() == fakeProtocolStepsProjectService.protocolStepsResult
    assert fakeProtocolStepsProjectService.lastListProtocolStepsCall == {
        "mapper": fakeProjectMapper,
        "projectId": 1,
        "protocolId": 10,
    }
    assert fakeProtocolStepsProjectService.lastGetProjectDbRowCall == {
        "mapper": fakeProjectMapper,
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }
    assert fakeProtocolStepsProjectService.lastGetProjectByIdCall is None


def test_UpdateProtocolStepStatusReturns404WhenProjectMissing(
    protocolStepsClient,
    fakeProtocolStepsProjectService,
):
    fakeProtocolStepsProjectService.projectByIdResult = None

    response = protocolStepsClient.patch(
        "/projects/1/protocols/10/steps/2/status",
        json={"status": "finished"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_UpdateProtocolStepStatusRejectsInvalidStatus(protocolStepsClient):
    response = protocolStepsClient.patch(
        "/projects/1/protocols/10/steps/2/status",
        json={"status": "running"},
    )

    assert response.status_code == 422


def test_UpdateProtocolStepStatusDelegatesToService(
    protocolStepsClient,
    fakeProjectMapper,
    fakeProtocolStepsProjectService,
):
    response = protocolStepsClient.patch(
        "/projects/1/protocols/10/steps/2/status",
        json={"status": "finished"},
    )

    assert response.status_code == 200
    assert response.json() == fakeProtocolStepsProjectService.updateProtocolStepStatusResult
    assert fakeProtocolStepsProjectService.lastUpdateProtocolStepStatusCall == {
        "mapper": fakeProjectMapper,
        "projectId": 1,
        "protocolId": 10,
        "stepIndex": 2,
        "stepStatus": "finished",
    }


def test_UpdateProtocolStepStatusPropagatesHttpException(
    protocolStepsClient,
    fakeProtocolStepsProjectService,
):
    fakeProtocolStepsProjectService.updateProtocolStepStatusError = HTTPException(
        status_code=404,
        detail="Step not found: 99",
    )

    response = protocolStepsClient.patch(
        "/projects/1/protocols/10/steps/99/status",
        json={"status": "new"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Step not found: 99"