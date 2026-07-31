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
from typing import Any, Dict, Iterator, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeProtocolRouterService:
    # fakeProtocolRouterService
    def __init__(self):
        self.projectByIdResult: Any = {"id": 1, "name": "Demo Project"}
        self.projectDbRowResult: Any = {
            "id": 1,
            "name": "Demo Project",
        }
        self.protocolParamsResult: Any = {
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
        }
        self.newProtocolParamsResult: Any = {
            "protocolClassName": "MyProtClass",
            "params": {"x": 2},
        }
        self.protocolLogsResult: Any = {
            "output": "stdout text",
            "errors": "stderr text",
            "schedule": "schedule text",
        }

        self.launchError = None  # type: Optional[Exception]
        self.saveError = None  # type: Optional[Exception]

        self.lastGetProjectByIdCall: Optional[Dict[str, Any]] = None
        self.lastGetProjectDbRowCall: Optional[
            Dict[str, Any]
        ] = None
        self.lastGetProtocolParamsCall: Optional[Dict[str, Any]] = None
        self.lastGetNewProtocolParamsCall: Optional[Dict[str, Any]] = None
        self.lastLaunchProtocolCall: Optional[Dict[str, Any]] = None
        self.lastSaveProtocolCall: Optional[Dict[str, Any]] = None
        self.lastGetProtocolLogsCall: Optional[Dict[str, Any]] = None
        self.postgresqlRuntimeMutationResult: Any = {
            "id": 1,
            "name": "Demo Project",
        }

        self.lastLoadPostgresqlRuntimeProjectForMutationCall: Optional[
            Dict[str, Any]
        ] = None

    def loadPostgresqlRuntimeProjectForMutation(
            self,
            mapper,
            projectId,
            currentUser,
    ):
        self.lastLoadPostgresqlRuntimeProjectForMutationCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
        }

    def getProjectById(self, mapper, projectId, currentUser):
        self.lastGetProjectByIdCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
        }
        return self.projectByIdResult

    def getProjectDbRow(
            self,
            mapper,
            projectId,
            currentUser,
    ):
        self.lastGetProjectDbRowCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
        }

        return self.projectDbRowResult

    def getProtocolParams(self, projectId, protocolId, mapper=None):
        self.lastGetProtocolParamsCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "mapper": mapper,
        }
        return self.protocolParamsResult

    def getNewProtocolParams(self, projectId, protClassName):
        self.lastGetNewProtocolParamsCall = {
            "projectId": projectId,
            "protClassName": protClassName,
        }
        return self.newProtocolParamsResult

    def launchProtocol(self, protocolId, protocolClassName, params):
        self.lastLaunchProtocolCall = {
            "protocolId": protocolId,
            "protocolClassName": protocolClassName,
            "params": params,
        }
        if self.launchError is not None:
            raise self.launchError

    def saveProtocol(self, protocolId, protocolClassName, params):
        self.lastSaveProtocolCall = {
            "protocolId": protocolId,
            "protocolClassName": protocolClassName,
            "params": params,
        }
        if self.saveError is not None:
            raise self.saveError

    def getProtocolLogs(self, projectId, protocolId, offset, errOffset, scheduleOffset, mapper=None):
        self.lastGetProtocolLogsCall = {
            "projectId": projectId,
            "protocolId": protocolId,
            "offset": offset,
            "errOffset": errOffset,
            "scheduleOffset": scheduleOffset,
            "mapper": mapper,
        }
        return self.protocolLogsResult


@pytest.fixture
def protocolRouterModule(authTestEnv):
    # protocolRouterModule
    return importlib.import_module("app.backend.api.routers.protocol_router")


@pytest.fixture
def fakeProtocolRouterService():
    # fakeProtocolRouterServiceFixture
    return FakeProtocolRouterService()


@pytest.fixture
def protocolClient(
    protocolRouterModule,
    fakeProjectMapper,
    fakeProtocolRouterService,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(protocolRouterModule.router)

    app.dependency_overrides[protocolRouterModule.getMapper] = lambda: fakeProjectMapper
    app.dependency_overrides[protocolRouterModule.getCurrentUser] = lambda: {
        "id": 1,
        "email": "user@example.com",
        "role": "user",
    }
    app.dependency_overrides[protocolRouterModule.getProjectService] = (
        lambda: fakeProtocolRouterService
    )

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_LoadProtocolReturns404WhenPostgresqlRuntimeProjectMissing(
        protocolClient,
        fakeProtocolRouterService,
):
    fakeProtocolRouterService.postgresqlRuntimeMutationResult = None

    response = protocolClient.get(
        "/protocols/1/10"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"

    assert fakeProtocolRouterService.lastGetProjectByIdCall is None
    assert fakeProtocolRouterService.lastGetProtocolParamsCall is None


def test_LoadProtocolUsesPostgresqlRuntimeContextAndReturnsProtocolParams(
        protocolClient,
        fakeProtocolRouterService,
        fakeProjectMapper,
):
    response = protocolClient.get(
        "/protocols/1/10"
    )

    assert response.status_code == 200

    assert response.json() == {
        "protocolId": "10",
        "protocolClassName": "ProtClass",
        "params": {"a": 1},
    }

    assert (
        fakeProtocolRouterService
        .lastLoadPostgresqlRuntimeProjectForMutationCall
        == {
            "mapper": fakeProjectMapper,
            "projectId": 1,
            "currentUser": {
                "id": 1,
                "email": "user@example.com",
                "role": "user",
            },
        }
    )

    assert fakeProtocolRouterService.lastGetProjectByIdCall is None

    assert fakeProtocolRouterService.lastGetProtocolParamsCall == {
        "mapper": fakeProjectMapper,
        "projectId": 1,
        "protocolId": 10,
    }


def test_LoadNewProtocolReturns404WhenProjectMissing(protocolClient, fakeProtocolRouterService):
    fakeProtocolRouterService.postgresqlRuntimeMutationResult = None

    response = protocolClient.get("/protocols/1/protclass/MyProtClass")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_LoadNewProtocolReturnsProtocolTemplate(
        protocolClient,
        fakeProtocolRouterService,
        fakeProjectMapper,
):
    response = protocolClient.get("/protocols/1/protclass/MyProtClass")

    assert response.status_code == 200
    assert response.json() == {
        "protocolClassName": "MyProtClass",
        "params": {"x": 2},
    }

    assert fakeProtocolRouterService.lastGetNewProtocolParamsCall == {
        "projectId": 1,
        "protClassName": "MyProtClass",
    }
    assert (
            fakeProtocolRouterService
            .lastLoadPostgresqlRuntimeProjectForMutationCall
            == {
                "mapper": fakeProjectMapper,
                "projectId": 1,
                "currentUser": {
                    "id": 1,
                    "email": "user@example.com",
                    "role": "user",
                },
            }
    )


def test_LaunchProtocolEndpointIsDisabled(protocolClient):
    response = protocolClient.post(
        "/protocols/launch",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
        },
    )

    assert response.status_code == 404


def test_SaveProtocolEndpointIsDisabled(protocolClient):
    response = protocolClient.post(
        "/protocols/save",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
        },
    )

    assert response.status_code == 404


def test_GetProtocolLogsReturns404WhenProjectMissing(
        protocolClient,
        fakeProtocolRouterService,
        fakeProjectMapper,
):
    fakeProtocolRouterService.projectDbRowResult = None

    response = protocolClient.get(
        "/protocols/logs/1/10/0/0/0"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Project not found"
    )

    assert (
        fakeProtocolRouterService
        .lastGetProjectDbRowCall
    ) == {
        "mapper": fakeProjectMapper,
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }

    assert (
        fakeProtocolRouterService
        .lastGetProjectByIdCall
    ) is None

    assert (
        fakeProtocolRouterService
        .lastGetProtocolLogsCall
    ) is None


def test_GetProtocolLogsReturnsPayload(
        protocolClient,
        fakeProtocolRouterService,
        fakeProjectMapper,
):
    response = protocolClient.get(
        "/protocols/logs/1/10/5/7/9"
    )

    assert response.status_code == 200

    assert response.json() == {
        "output": "stdout text",
        "errors": "stderr text",
        "schedule": "schedule text",
    }

    assert (
        fakeProtocolRouterService
        .lastGetProjectDbRowCall
    ) == {
        "mapper": fakeProjectMapper,
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }

    assert (
        fakeProtocolRouterService
        .lastGetProjectByIdCall
    ) is None

    assert (
        fakeProtocolRouterService
        .lastGetProtocolLogsCall
    ) == {
        "projectId": 1,
        "protocolId": 10,
        "offset": 5,
        "errOffset": 7,
        "scheduleOffset": 9,
        "mapper": fakeProjectMapper,
    }