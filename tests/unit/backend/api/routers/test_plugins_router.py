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
import sys
import types
from typing import Any, Dict, Iterator, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakePluginService:
    # fakePluginService
    def __init__(self):
        self.pluginsResult = [
            {"pipName": "scipion-em-xmipp", "name": "Xmipp"},
            {"pipName": "scipion-em-relion", "name": "Relion"},
        ]
        self.pluginByName = {
            "scipion-em-xmipp": {"pipName": "scipion-em-xmipp", "name": "Xmipp"},
            "scipion-em-relion": {"pipName": "scipion-em-relion", "name": "Relion"},
        }
        self.clearCacheCalls = 0
        self.installCalls = []
        self.uninstallCalls = []

    def getPlugins(self):
        return self.pluginsResult

    def getPlugin(self, pluginName):
        return self.pluginByName.get(pluginName)

    def installPlugin(self, pluginName, taskId=None):
        self.installCalls.append({"pluginName": pluginName, "taskId": taskId})
        return {"installed": "SUCCESS"}

    def uninstallPlugin(self, pluginName, taskId=None):
        self.uninstallCalls.append({"pluginName": pluginName, "taskId": taskId})
        return {"uninstalled": "SUCCESS"}

    def clearCache(self):
        self.clearCacheCalls += 1


class ImportSafePluginService:
    # importSafePluginService
    def __init__(self, *args, **kwargs):
        pass

    def getPlugins(self):
        return []

    def getPlugin(self, pluginName):
        return None

    def installPlugin(self, pluginName, taskId=None):
        return {"installed": "SUCCESS"}

    def uninstallPlugin(self, pluginName, taskId=None):
        return {"uninstalled": "SUCCESS"}

    def clearCache(self):
        pass


class FakeCeleryResult:
    # fakeCeleryResult
    def __init__(self, status, result=None, info=None):
        self.status = status
        self.result = result
        self.info = info


class FakeCeleryApp:
    # fakeCeleryApp
    def __init__(self, resultByTaskId):
        self.resultByTaskId = resultByTaskId

    def AsyncResult(self, taskId):
        return self.resultByTaskId[taskId]


class FakeCeleryTask:
    # fakeCeleryTask
    def __init__(self):
        self.calls = []

    def apply_async(self, args=None, task_id=None):
        self.calls.append({
            "args": args,
            "task_id": task_id,
        })


@pytest.fixture
def pluginRouterModule(monkeypatch):
    # pluginRouterModule
    moduleName = "app.backend.api.services.plugin_service"
    previousPluginServiceModule = sys.modules.get(moduleName)
    previousPluginRouterModule = sys.modules.get("app.backend.api.routers.plugin_router")

    fakePluginServiceModule = types.ModuleType(moduleName)
    fakePluginServiceModule.PluginService = ImportSafePluginService
    sys.modules[moduleName] = fakePluginServiceModule

    sys.modules.pop("app.backend.api.routers.plugin_router", None)

    try:
        module = importlib.import_module("app.backend.api.routers.plugin_router")
        yield module
    finally:
        sys.modules.pop("app.backend.api.routers.plugin_router", None)

        if previousPluginServiceModule is None:
            sys.modules.pop(moduleName, None)
        else:
            sys.modules[moduleName] = previousPluginServiceModule

        if previousPluginRouterModule is not None:
            sys.modules["app.backend.api.routers.plugin_router"] = previousPluginRouterModule


@pytest.fixture
def fakePluginService():
    # fakePluginServiceFixture
    return FakePluginService()


@pytest.fixture
def pluginClient(pluginRouterModule, fakePluginService, monkeypatch):
    # pluginClient
    monkeypatch.setattr(pluginRouterModule, "service", fakePluginService)
    monkeypatch.setattr(pluginRouterModule, "_inProcessResults", {})
    monkeypatch.setattr(pluginRouterModule, "_inProcessTasks", {})
    monkeypatch.setattr(pluginRouterModule, "_celeryAppAvailable", False)
    monkeypatch.setattr(pluginRouterModule, "_celeryInstallAvailable", False)
    monkeypatch.setattr(pluginRouterModule, "_celeryUninstallAvailable", False)
    monkeypatch.setattr(pluginRouterModule, "celeryApp", None)
    monkeypatch.setattr(pluginRouterModule, "installPluginTask", None)
    monkeypatch.setattr(pluginRouterModule, "uninstallPluginTask", None)

    app = FastAPI()
    app.include_router(pluginRouterModule.router)

    with TestClient(app) as client:
        yield client


def test_LoadPluginsReturnsServiceList(pluginClient):
    response = pluginClient.get("/plugins/")

    assert response.status_code == 200
    assert response.json() == [
        {"pipName": "scipion-em-xmipp", "name": "Xmipp"},
        {"pipName": "scipion-em-relion", "name": "Relion"},
    ]


def test_LoadPluginReturns404WhenPluginMissing(pluginClient):
    response = pluginClient.get("/plugins/missing-plugin")

    assert response.status_code == 404
    assert response.json()["detail"] == "Plugin not found"


def test_LoadPluginReturnsPlugin(pluginClient):
    response = pluginClient.get("/plugins/scipion-em-xmipp")

    assert response.status_code == 200
    assert response.json() == {
        "pipName": "scipion-em-xmipp",
        "name": "Xmipp",
    }


def test_InstallPluginUsesLocalBackendWhenCeleryUnavailable(pluginClient, pluginRouterModule, monkeypatch):
    captured = {}

    async def fakeStartInProcessTask(taskFn, pluginName, operation):
        captured["taskFn"] = taskFn
        captured["pluginName"] = pluginName
        captured["operation"] = operation
        return {
            "taskId": "local-install-1",
            "status": "STARTED",
            "backend": "local",
        }

    monkeypatch.setattr(pluginRouterModule, "_startInProcessTask", fakeStartInProcessTask)

    response = pluginClient.post("/plugins/install/scipion-em-xmipp")

    assert response.status_code == 200
    assert response.json() == {
        "taskId": "local-install-1",
        "status": "STARTED",
        "backend": "local",
    }
    assert captured["taskFn"] == pluginRouterModule.service.installPlugin
    assert captured["pluginName"] == "scipion-em-xmipp"
    assert captured["operation"] == "install"


def test_UninstallPluginUsesLocalBackendWhenCeleryUnavailable(pluginClient, pluginRouterModule, monkeypatch):
    captured = {}

    async def fakeStartInProcessTask(taskFn, pluginName, operation):
        captured["taskFn"] = taskFn
        captured["pluginName"] = pluginName
        captured["operation"] = operation
        return {
            "taskId": "local-uninstall-1",
            "status": "STARTED",
            "backend": "local",
        }

    monkeypatch.setattr(pluginRouterModule, "_startInProcessTask", fakeStartInProcessTask)

    response = pluginClient.post("/plugins/uninstall/scipion-em-xmipp")

    assert response.status_code == 200
    assert response.json() == {
        "taskId": "local-uninstall-1",
        "status": "STARTED",
        "backend": "local",
    }
    assert captured["taskFn"] == pluginRouterModule.service.uninstallPlugin
    assert captured["pluginName"] == "scipion-em-xmipp"
    assert captured["operation"] == "uninstall"


def test_InstallPluginUsesCeleryWhenAvailable(pluginClient, pluginRouterModule, monkeypatch):
    fakeTask = FakeCeleryTask()
    initializeCalls = []

    def fakeInitializePluginTaskLog(taskId, pluginName, operation):
        initializeCalls.append({
            "taskId": taskId,
            "pluginName": pluginName,
            "operation": operation,
        })

    monkeypatch.setattr(pluginRouterModule, "_celeryAppAvailable", True)
    monkeypatch.setattr(pluginRouterModule, "_celeryInstallAvailable", True)
    monkeypatch.setattr(pluginRouterModule, "installPluginTask", fakeTask)
    monkeypatch.setattr(pluginRouterModule, "initializePluginTaskLog", fakeInitializePluginTaskLog)

    response = pluginClient.post("/plugins/install/scipion-em-relion")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["backend"] == "celery"
    assert isinstance(body["taskId"], str)
    assert len(body["taskId"]) > 0

    assert len(initializeCalls) == 1
    assert initializeCalls[0]["pluginName"] == "scipion-em-relion"
    assert initializeCalls[0]["operation"] == "install"

    assert len(fakeTask.calls) == 1
    assert fakeTask.calls[0]["args"] == ["scipion-em-relion"]
    assert fakeTask.calls[0]["task_id"] == body["taskId"]


def test_GetTaskStatusReturns404ForUnknownLocalTask(pluginClient):
    response = pluginClient.get("/plugins/tasks/unknown-task")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_GetTaskStatusReturnsLocalSuccess(pluginClient, pluginRouterModule):
    pluginRouterModule._inProcessResults["task-1"] = {
        "status": "SUCCESS",
        "result": {"installed": "SUCCESS"},
        "error": None,
    }

    response = pluginClient.get("/plugins/tasks/task-1")

    assert response.status_code == 200
    assert response.json() == {
        "taskId": "task-1",
        "status": "SUCCESS",
        "backend": "local",
        "result": {"installed": "SUCCESS"},
        "error": None,
        "meta": None,
    }


def test_GetTaskStatusReturnsCelerySuccessAndClearsCache(pluginClient, pluginRouterModule, fakePluginService, monkeypatch):
    monkeypatch.setattr(pluginRouterModule, "_celeryAppAvailable", True)
    monkeypatch.setattr(
        pluginRouterModule,
        "celeryApp",
        FakeCeleryApp({
            "task-2": FakeCeleryResult(
                status="SUCCESS",
                result={"installed": "SUCCESS"},
                info={"step": "done"},
            )
        }),
    )

    response = pluginClient.get("/plugins/tasks/task-2")

    assert response.status_code == 200
    assert response.json() == {
        "taskId": "task-2",
        "status": "SUCCESS",
        "backend": "celery",
        "result": {"installed": "SUCCESS"},
        "error": None,
        "meta": {"step": "done"},
    }
    assert fakePluginService.clearCacheCalls == 1


def test_GetTaskStatusReturnsCeleryFailure(pluginClient, pluginRouterModule, monkeypatch):
    monkeypatch.setattr(pluginRouterModule, "_celeryAppAvailable", True)
    monkeypatch.setattr(
        pluginRouterModule,
        "celeryApp",
        FakeCeleryApp({
            "task-3": FakeCeleryResult(
                status="FAILURE",
                result=RuntimeError("install failed"),
                info={"step": "boom"},
            )
        }),
    )

    response = pluginClient.get("/plugins/tasks/task-3")

    assert response.status_code == 200
    assert response.json() == {
        "taskId": "task-3",
        "status": "FAILURE",
        "backend": "celery",
        "result": None,
        "error": "install failed",
        "meta": {"step": "boom"},
    }


def test_GetTaskLogReturnsLocalLog(pluginClient, pluginRouterModule, monkeypatch):
    pluginRouterModule._inProcessResults["task-4"] = {
        "status": "SUCCESS",
        "result": {"installed": "SUCCESS"},
        "error": None,
    }

    def fakeReadPluginTaskLog(taskId, offset=0, limit=65536):
        assert taskId == "task-4"
        assert offset == 10
        assert limit == 20
        return ("hello log", 19)

    monkeypatch.setattr(pluginRouterModule, "readPluginTaskLog", fakeReadPluginTaskLog)

    response = pluginClient.get("/plugins/tasks/task-4/log?offset=10&limit=20")

    assert response.status_code == 200
    assert response.json() == {
        "taskId": "task-4",
        "backend": "local",
        "offset": 10,
        "nextOffset": 19,
        "text": "hello log",
        "completed": True,
        "status": "SUCCESS",
    }


def test_GetTaskLogReturnsCeleryLog(pluginClient, pluginRouterModule, monkeypatch):
    def fakeReadPluginTaskLog(taskId, offset=0, limit=65536):
        return ("celery log", 8)

    monkeypatch.setattr(pluginRouterModule, "readPluginTaskLog", fakeReadPluginTaskLog)
    monkeypatch.setattr(pluginRouterModule, "_celeryAppAvailable", True)
    monkeypatch.setattr(
        pluginRouterModule,
        "celeryApp",
        FakeCeleryApp({
            "task-5": FakeCeleryResult(
                status="PENDING",
                result=None,
                info=None,
            )
        }),
    )

    response = pluginClient.get("/plugins/tasks/task-5/log")

    assert response.status_code == 200
    assert response.json() == {
        "taskId": "task-5",
        "backend": "celery",
        "offset": 0,
        "nextOffset": 8,
        "text": "celery log",
        "completed": False,
        "status": "PENDING",
    }