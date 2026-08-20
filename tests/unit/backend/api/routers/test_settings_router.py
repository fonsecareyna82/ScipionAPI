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


class FakeSettingsService:
    # fakeSettingsService
    def __init__(self):
        self.userSettingsResult = {
            "theme": "system",
            "uiDensity": "comfortable",
            "fontScale": 1.0,
            "language": "en",
            "timeZone": "Europe/Madrid",
            "graphMiniMapEnabled": True,
            "graphFocusModeEnabled": False,
            "protocolOutputThumbnailsEnabled": False,
            "workflowsAutoRefreshSec": 5,
            "workflowViewMode": "treeTb"
        }
        self.instanceSettingsResult = {
            "defaultQueueName": "default",
            "maxConcurrentRunsPerUser": 2,
        }
        self.environmentVariablesResult = [
            {
                "name": "API_HOST",
                "value": "0.0.0.0",
                "default": "0.0.0.0",
                "description": "API bind host",
                "source": "env",
                "isDefault": True,
                "type": "string",
            },
            {
                "name": "API_PORT",
                "value": "8080",
                "default": "8080",
                "description": "API bind port",
                "source": "env",
                "isDefault": True,
                "type": "int",
            },
        ]
        self.hostSettingsResult = {
            "hostAlias": "localhost",
            "schedulerName": "Local",
            "mandatory": False,
            "parallelCommand": "mpirun -np %(JOB_NODES)d",
            "submitCommand": "qsub",
            "cancelCommand": "qdel",
            "checkCommand": "qstat",
            "jobDoneRegex": "",
            "submitTemplate": "#!/bin/bash\n{{command}}",
            "queues": [
                {
                    "name": "default",
                    "params": [
                        {
                            "variableName": "JOB_TIME",
                            "value": "01:00:00",
                            "label": "Job time",
                            "help": "Requested wall time",
                        }
                    ],
                }
            ],
        }

        self.getUserSettingsError = None  # type: Optional[Exception]
        self.putUserSettingsError = None  # type: Optional[Exception]
        self.patchUserSettingsError = None  # type: Optional[Exception]
        self.getInstanceSettingsError = None  # type: Optional[Exception]
        self.putInstanceSettingsError = None  # type: Optional[Exception]
        self.patchInstanceSettingsError = None  # type: Optional[Exception]
        self.getEnvironmentVariablesError = None  # type: Optional[Exception]
        self.patchEnvironmentVariablesError = None  # type: Optional[Exception]
        self.getHostSettingsError = None  # type: Optional[Exception]
        self.putHostSettingsError = None  # type: Optional[Exception]
        self.patchHostSettingsError = None  # type: Optional[Exception]

        self.lastGetUserSettingsCall = None  # type: Optional[Dict[str, Any]]
        self.lastPutUserSettingsCall = None  # type: Optional[Dict[str, Any]]
        self.lastPatchUserSettingsCall = None  # type: Optional[Dict[str, Any]]
        self.lastGetInstanceSettingsCall = None  # type: Optional[Dict[str, Any]]
        self.lastPutInstanceSettingsCall = None  # type: Optional[Dict[str, Any]]
        self.lastPatchInstanceSettingsCall = None  # type: Optional[Dict[str, Any]]
        self.lastGetEnvironmentVariablesCall = None  # type: Optional[Dict[str, Any]]
        self.lastPatchEnvironmentVariablesCall = None  # type: Optional[Dict[str, Any]]
        self.lastGetHostSettingsCall = None  # type: Optional[Dict[str, Any]]
        self.lastPutHostSettingsCall = None  # type: Optional[Dict[str, Any]]
        self.lastPatchHostSettingsCall = None  # type: Optional[Dict[str, Any]]

    def getUserSettings(self, mapper, currentUser):
        self.lastGetUserSettingsCall = {
            "mapper": mapper,
            "currentUser": currentUser,
        }
        if self.getUserSettingsError is not None:
            raise self.getUserSettingsError
        return self.userSettingsResult

    def putUserSettings(self, mapper, currentUser, payload):
        self.lastPutUserSettingsCall = {
            "mapper": mapper,
            "currentUser": currentUser,
            "payload": payload,
        }
        if self.putUserSettingsError is not None:
            raise self.putUserSettingsError
        return self.userSettingsResult

    def patchUserSettings(self, mapper, currentUser, patch):
        self.lastPatchUserSettingsCall = {
            "mapper": mapper,
            "currentUser": currentUser,
            "patch": patch,
        }
        if self.patchUserSettingsError is not None:
            raise self.patchUserSettingsError
        return self.userSettingsResult

    def getInstanceSettings(self, mapper, currentUser):
        self.lastGetInstanceSettingsCall = {
            "mapper": mapper,
            "currentUser": currentUser,
        }
        if self.getInstanceSettingsError is not None:
            raise self.getInstanceSettingsError
        return self.instanceSettingsResult

    def putInstanceSettings(self, mapper, currentUser, payload):
        self.lastPutInstanceSettingsCall = {
            "mapper": mapper,
            "currentUser": currentUser,
            "protocolOutputThumbnailsEnabled": False,
            "payload": payload,
        }
        if self.putInstanceSettingsError is not None:
            raise self.putInstanceSettingsError
        return self.instanceSettingsResult

    def patchInstanceSettings(self, mapper, currentUser, patch):
        self.lastPatchInstanceSettingsCall = {
            "mapper": mapper,
            "currentUser": currentUser,
            "patch": patch,
        }
        if self.patchInstanceSettingsError is not None:
            raise self.patchInstanceSettingsError
        return self.instanceSettingsResult

    def getEnvironmentVariables(self, currentUser):
        self.lastGetEnvironmentVariablesCall = {
            "currentUser": currentUser,
        }
        if self.getEnvironmentVariablesError is not None:
            raise self.getEnvironmentVariablesError
        return self.environmentVariablesResult

    def patchEnvironmentVariables(self, currentUser, patch):
        self.lastPatchEnvironmentVariablesCall = {
            "currentUser": currentUser,
            "patch": patch,
        }
        if self.patchEnvironmentVariablesError is not None:
            raise self.patchEnvironmentVariablesError
        return self.environmentVariablesResult

    def getHostSettings(self, mapper, currentUser):
        self.lastGetHostSettingsCall = {
            "mapper": mapper,
            "currentUser": currentUser,
        }
        if self.getHostSettingsError is not None:
            raise self.getHostSettingsError
        return self.hostSettingsResult

    def putHostSettings(self, mapper, currentUser, payload):
        self.lastPutHostSettingsCall = {
            "mapper": mapper,
            "currentUser": currentUser,
            "payload": payload,
        }
        if self.putHostSettingsError is not None:
            raise self.putHostSettingsError
        return self.hostSettingsResult

    def patchHostSettings(self, mapper, currentUser, patch):
        self.lastPatchHostSettingsCall = {
            "mapper": mapper,
            "currentUser": currentUser,
            "patch": patch,
        }
        if self.patchHostSettingsError is not None:
            raise self.patchHostSettingsError
        return self.hostSettingsResult


@pytest.fixture
def settingsRouterModule(authTestEnv):
    # settingsRouterModule
    return importlib.import_module("app.backend.api.routers.settings_router")


@pytest.fixture
def fakeSettingsService():
    # fakeSettingsServiceFixture
    return FakeSettingsService()


@pytest.fixture
def settingsClient(settingsRouterModule, fakeProjectMapper, fakeSettingsService):
    # settingsClient
    app = FastAPI()
    app.include_router(settingsRouterModule.router)

    app.dependency_overrides[settingsRouterModule.getMapper] = lambda: fakeProjectMapper
    app.dependency_overrides[settingsRouterModule.getSettingsService] = lambda: fakeSettingsService
    app.dependency_overrides[settingsRouterModule.getCurrentUser] = lambda: {
        "id": 1,
        "email": "user@example.com",
        "role": "user",
    }
    app.dependency_overrides[settingsRouterModule.requireAdmin] = lambda: {
        "id": 99,
        "email": "admin@example.com",
        "role": "admin",
    }

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_GetUserSettingsReturnsPayload(settingsClient, fakeSettingsService):
    response = settingsClient.get("/settings/user")

    assert response.status_code == 200
    assert response.json() == fakeSettingsService.userSettingsResult
    assert fakeSettingsService.lastGetUserSettingsCall == {
        "mapper": fakeSettingsService.lastGetUserSettingsCall["mapper"],
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }


def test_PutUserSettingsDelegatesToService(settingsClient, fakeSettingsService):
    response = settingsClient.put(
        "/settings/user",
        json={
            "theme": "dark",
            "uiDensity": "compact",
            "fontScale": 1.1,
            "language": "es",
            "timeZone": "Europe/Madrid",
            "graphMiniMapEnabled": False,
            "graphFocusModeEnabled": True,
            "workflowsAutoRefreshSec": 10,
        },
    )

    assert response.status_code == 200
    call = fakeSettingsService.lastPutUserSettingsCall
    assert call["currentUser"] == {
        "id": 1,
        "email": "user@example.com",
        "role": "user",
    }
    assert call["payload"].dict() == {
        "theme": "dark",
        "uiDensity": "compact",
        "fontScale": 1.1,
        "language": "es",
        "timeZone": "Europe/Madrid",
        "graphMiniMapEnabled": False,
        "graphFocusModeEnabled": True,
        "workflowsAutoRefreshSec": 10,
        "protocolOutputThumbnailsEnabled": False,
        "workflowViewMode": "treeTb"
    }


def test_PatchUserSettingsDelegatesToService(settingsClient, fakeSettingsService):
    response = settingsClient.patch(
        "/settings/user",
        json={
            "theme": "light",
            "graphFocusModeEnabled": True,
        },
    )

    assert response.status_code == 200
    call = fakeSettingsService.lastPatchUserSettingsCall
    assert call["patch"].dict(exclude_unset=True) == {
        "theme": "light",
        "graphFocusModeEnabled": True,
    }


def test_GetUserSettingsWrapsUnexpectedError(settingsClient, fakeSettingsService):
    fakeSettingsService.getUserSettingsError = RuntimeError("user settings exploded")

    response = settingsClient.get("/settings/user")

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to load user settings: user settings exploded"


def test_GetInstanceSettingsReturnsPayload(settingsClient, fakeSettingsService):
    response = settingsClient.get("/settings/instance")

    assert response.status_code == 200
    assert response.json() == fakeSettingsService.instanceSettingsResult
    assert fakeSettingsService.lastGetInstanceSettingsCall == {
        "mapper": fakeSettingsService.lastGetInstanceSettingsCall["mapper"],
        "currentUser": {
            "id": 99,
            "email": "admin@example.com",
            "role": "admin",
        },
    }


def test_PutInstanceSettingsDelegatesToService(settingsClient, fakeSettingsService):
    response = settingsClient.put(
        "/settings/instance",
        json={
            "defaultQueueName": "gpu",
            "maxConcurrentRunsPerUser": 4,
        },
    )

    assert response.status_code == 200
    call = fakeSettingsService.lastPutInstanceSettingsCall
    assert call["payload"].dict() == {
        "defaultQueueName": "gpu",
        "maxConcurrentRunsPerUser": 4,
    }


def test_PatchInstanceSettingsDelegatesToService(settingsClient, fakeSettingsService):
    response = settingsClient.patch(
        "/settings/instance",
        json={
            "maxConcurrentRunsPerUser": 8,
        },
    )

    assert response.status_code == 200
    call = fakeSettingsService.lastPatchInstanceSettingsCall
    assert call["patch"].dict(exclude_unset=True) == {
        "maxConcurrentRunsPerUser": 8,
    }


def test_GetEnvironmentVariablesReturnsPayload(settingsClient, fakeSettingsService):
    response = settingsClient.get("/settings/environment")

    assert response.status_code == 200
    assert response.json() == fakeSettingsService.environmentVariablesResult
    assert fakeSettingsService.lastGetEnvironmentVariablesCall == {
        "currentUser": {
            "id": 99,
            "email": "admin@example.com",
            "role": "admin",
        },
    }


def test_PatchEnvironmentVariablesDelegatesToService(settingsClient, fakeSettingsService):
    response = settingsClient.patch(
        "/settings/environment",
        json={
            "API_HOST": "127.0.0.1",
            "API_PORT": "9090",
        },
    )

    assert response.status_code == 200
    assert fakeSettingsService.lastPatchEnvironmentVariablesCall == {
        "currentUser": {
            "id": 99,
            "email": "admin@example.com",
            "role": "admin",
        },
        "patch": {
            "API_HOST": "127.0.0.1",
            "API_PORT": "9090",
        },
    }


def test_GetHostSettingsReturnsPayload(settingsClient, fakeSettingsService):
    response = settingsClient.get("/settings/host")

    assert response.status_code == 200
    assert response.json() == fakeSettingsService.hostSettingsResult
    assert fakeSettingsService.lastGetHostSettingsCall == {
        "mapper": fakeSettingsService.lastGetHostSettingsCall["mapper"],
        "currentUser": {
            "id": 99,
            "email": "admin@example.com",
            "role": "admin",
        },
    }


def test_HostSettingsOutAllowsSparseRuntimeHostConfiguration():
    from app.backend.api.schemas.settings_schema import HostSettingsOut

    settings = HostSettingsOut.parse_obj(
        {
            "hostAlias": "localhost",
            "schedulerName": "",
            "mandatory": False,
            "parallelCommand": "mpirun -np %_(JOB_NODES)d %_(COMMAND)s",
            "submitCommand": "",
            "cancelCommand": "",
            "checkCommand": "",
            "jobDoneRegex": "",
            "submitTemplate": "",
            "queues": [],
        }
    )

    assert settings.hostAlias == "localhost"
    assert settings.schedulerName == ""
    assert settings.parallelCommand == (
        "mpirun -np %_(JOB_NODES)d %_(COMMAND)s"
    )
    assert settings.submitCommand == ""
    assert settings.cancelCommand == ""
    assert settings.checkCommand == ""
    assert settings.submitTemplate == ""
    assert settings.queues == []


def test_PutHostSettingsDelegatesToService(settingsClient, fakeSettingsService):
    response = settingsClient.put(
        "/settings/host",
        json={
            "hostAlias": "cluster-a",
            "schedulerName": "Slurm",
            "mandatory": True,
            "parallelCommand": "srun -n %(JOB_NODES)d",
            "submitCommand": "sbatch",
            "cancelCommand": "scancel",
            "checkCommand": "squeue",
            "jobDoneRegex": "COMPLETED",
            "submitTemplate": "#!/bin/bash\n{{command}}",
            "queues": [
                {
                    "name": "main",
                    "params": [
                        {
                            "variableName": "JOB_MEM",
                            "value": "64G",
                            "label": "Memory",
                            "help": "Requested memory",
                        }
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    call = fakeSettingsService.lastPutHostSettingsCall
    assert call["payload"].dict() == {
        "hostAlias": "cluster-a",
        "schedulerName": "Slurm",
        "mandatory": True,
        "parallelCommand": "srun -n %(JOB_NODES)d",
        "submitCommand": "sbatch",
        "cancelCommand": "scancel",
        "checkCommand": "squeue",
        "jobDoneRegex": "COMPLETED",
        "submitTemplate": "#!/bin/bash\n{{command}}",
        "queues": [
            {
                "name": "main",
                "params": [
                    {
                        "variableName": "JOB_MEM",
                        "value": "64G",
                        "label": "Memory",
                        "help": "Requested memory",
                    }
                ],
            }
        ],
    }


def test_PatchHostSettingsDelegatesToService(settingsClient, fakeSettingsService):
    response = settingsClient.patch(
        "/settings/host",
        json={
            "mandatory": True,
            "submitCommand": "sbatch",
        },
    )

    assert response.status_code == 200
    call = fakeSettingsService.lastPatchHostSettingsCall
    assert call["patch"].dict(exclude_unset=True) == {
        "mandatory": True,
        "submitCommand": "sbatch",
    }


def test_PatchHostSettingsWrapsUnexpectedError(settingsClient, fakeSettingsService):
    fakeSettingsService.patchHostSettingsError = RuntimeError("host patch failed")

    response = settingsClient.patch(
        "/settings/host",
        json={
            "mandatory": True,
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to patch host settings: host patch failed"