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

        self.lastGetProjectByIdCall: Dict[str, Any]
        self.lastGetProtocolParamsCall: Dict[str, Any]
        self.lastGetNewProtocolParamsCall: Dict[str, Any]
        self.lastLaunchProtocolCall: Dict[str, Any]
        self.lastSaveProtocolCall: Dict[str, Any]
        self.lastGetProtocolLogsCall: Dict[str, Any]

    def getProjectById(self, mapper, projectId, currentUser):
        self.lastGetProjectByIdCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
        }
        return self.projectByIdResult

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
    # protocolClient
    monkeypatch.setattr(protocolRouterModule, "service", fakeProtocolRouterService)

    app = FastAPI()
    app.include_router(protocolRouterModule.router)

    app.dependency_overrides[protocolRouterModule.getMapper] = lambda: fakeProjectMapper
    app.dependency_overrides[protocolRouterModule.getCurrentUser] = lambda: {
        "id": 1,
        "email": "user@example.com",
        "role": "user",
    }

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_LoadProtocolReturns404WhenProjectMissing(protocolClient, fakeProtocolRouterService):
    fakeProtocolRouterService.projectByIdResult = None

    response = protocolClient.get("/protocols/1/10")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_LoadProtocolReturnsProtocolParams(protocolClient, fakeProtocolRouterService):
    response = protocolClient.get("/protocols/1/10")

    assert response.status_code == 200
    assert response.json() == {
        "protocolId": "10",
        "protocolClassName": "ProtClass",
        "params": {"a": 1},
    }

    assert fakeProtocolRouterService.lastGetProtocolParamsCall == {
        "projectId": 1,
        "protocolId": 10,
        "mapper": fakeProtocolRouterService.lastGetProtocolParamsCall["mapper"],
    }


def test_LoadNewProtocolReturns404WhenProjectMissing(protocolClient, fakeProtocolRouterService):
    fakeProtocolRouterService.projectByIdResult = None

    response = protocolClient.get("/protocols/1/protclass/MyProtClass")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_LoadNewProtocolReturnsProtocolTemplate(protocolClient, fakeProtocolRouterService):
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


def test_GetProtocolLogsReturns404WhenProjectMissing(protocolClient, fakeProtocolRouterService):
    fakeProtocolRouterService.projectByIdResult = None

    response = protocolClient.get("/protocols/logs/1/10/0/0/0")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_GetProtocolLogsReturnsPayload(protocolClient, fakeProtocolRouterService):
    response = protocolClient.get("/protocols/logs/1/10/5/7/9")

    assert response.status_code == 200
    assert response.json() == {
        "output": "stdout text",
        "errors": "stderr text",
        "schedule": "schedule text",
    }

    assert fakeProtocolRouterService.lastGetProtocolLogsCall == {
        "projectId": 1,
        "protocolId": 10,
        "offset": 5,
        "errOffset": 7,
        "scheduleOffset": 9,
        "mapper": fakeProtocolRouterService.lastGetProtocolLogsCall["mapper"],
    }