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

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.api.routers import plugin_router


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

    def installPlugin(self, pluginName, taskId=None, skipBinaries=False):
        self.installCalls.append({
            "pluginName": pluginName,
            "taskId": taskId,
            "skipBinaries": skipBinaries,
        })
        return {"installed": "SUCCESS", "skipBinaries": skipBinaries}

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

    def installPlugin(self, pluginName, taskId=None, skipBinaries=False):
        return {"installed": "SUCCESS", "skipBinaries": skipBinaries}

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


@pytest.fixture()
def pluginClient(monkeypatch):
    app = FastAPI()
    app.include_router(plugin_router.router)

    plugin_router._inProcessResults.clear()
    plugin_router._inProcessTasks.clear()
    plugin_router._refreshedTerminalTaskIds.clear()

    monkeypatch.setattr(plugin_router, "_celeryAppAvailable", False)
    monkeypatch.setattr(plugin_router, "_celeryInstallAvailable", False)
    monkeypatch.setattr(plugin_router, "_celeryInstallBatchAvailable", False)
    monkeypatch.setattr(plugin_router, "_celeryInstallDevelAvailable", False)
    monkeypatch.setattr(plugin_router, "_celeryUninstallAvailable", False)
    monkeypatch.setattr(plugin_router, "celeryApp", None)
    monkeypatch.setattr(plugin_router, "installPluginTask", None)
    monkeypatch.setattr(plugin_router, "installPluginsBatchTask", None)
    monkeypatch.setattr(plugin_router, "installDevelPluginTask", None)
    monkeypatch.setattr(plugin_router, "uninstallPluginTask", None)

    yield TestClient(app)

    plugin_router._inProcessResults.clear()
    plugin_router._inProcessTasks.clear()
    plugin_router._refreshedTerminalTaskIds.clear()


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

    async def fakeStartInProcessTask(taskFn, pluginName, operation, **taskKwargs):
        captured["taskFn"] = taskFn
        captured["pluginName"] = pluginName
        captured["operation"] = operation
        captured["taskKwargs"] = taskKwargs
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
    assert captured["taskKwargs"] == {"skipBinaries": False}


def test_InstallPluginPassesSkipBinariesToLocalBackend(pluginClient, pluginRouterModule, monkeypatch):
    captured = {}

    async def fakeStartInProcessTask(taskFn, pluginName, operation, **taskKwargs):
        captured["taskFn"] = taskFn
        captured["pluginName"] = pluginName
        captured["operation"] = operation
        captured["taskKwargs"] = taskKwargs
        return {
            "taskId": "local-install-skip-binaries-1",
            "status": "STARTED",
            "backend": "local",
        }

    monkeypatch.setattr(pluginRouterModule, "_startInProcessTask", fakeStartInProcessTask)

    response = pluginClient.post("/plugins/install/scipion-em-xmipp?skipBinaries=true")

    assert response.status_code == 200
    assert response.json() == {
        "taskId": "local-install-skip-binaries-1",
        "status": "STARTED",
        "backend": "local",
    }
    assert captured["taskFn"] == pluginRouterModule.service.installPlugin
    assert captured["pluginName"] == "scipion-em-xmipp"
    assert captured["operation"] == "install"
    assert captured["taskKwargs"] == {"skipBinaries": True}


def test_UninstallPluginUsesLocalBackendWhenCeleryUnavailable(pluginClient, pluginRouterModule, monkeypatch):
    captured = {}

    async def fakeStartInProcessTask(taskFn, pluginName, operation, **taskKwargs):
        captured["taskFn"] = taskFn
        captured["pluginName"] = pluginName
        captured["operation"] = operation
        captured["taskKwargs"] = taskKwargs
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
    assert captured["taskKwargs"] == {}


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
    assert fakeTask.calls[0]["args"] == ["scipion-em-relion", False]
    assert fakeTask.calls[0]["task_id"] == body["taskId"]


def test_InstallPluginPassesSkipBinariesToCelery(pluginClient, pluginRouterModule, monkeypatch):
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

    response = pluginClient.post("/plugins/install/scipion-em-relion?skipBinaries=true")

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
    assert fakeTask.calls[0]["args"] == ["scipion-em-relion", True]
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


def test_install_batch_rejects_empty_selection(pluginClient):
    response = pluginClient.post(
        "/plugins/install-batch",
        json={"plugins": ["", "   "], "skipBinaries": True},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "No plugins selected"


def test_install_batch_requires_celery_for_multiple_plugins(pluginClient):
    response = pluginClient.post(
        "/plugins/install-batch",
        json={"plugins": ["scipion-em-a", "scipion-em-b"], "skipBinaries": True},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Batch plugin install requires Celery"


def test_install_batch_uses_local_fallback_for_single_plugin(pluginClient, monkeypatch):
    started = []

    async def fakeStartInProcessTask(taskFn, pluginName, operation, **taskKwargs):
        started.append(
            {
                "taskFn": taskFn,
                "pluginName": pluginName,
                "operation": operation,
                "taskKwargs": taskKwargs,
            }
        )
        return plugin_router.TaskStartResponse(taskId="task-1", status="STARTED", backend="local")

    monkeypatch.setattr(plugin_router, "_startInProcessTask", fakeStartInProcessTask)

    response = pluginClient.post(
        "/plugins/install-batch",
        json={"plugins": ["scipion-em-a", "scipion-em-a", ""], "skipBinaries": True},
    )

    assert response.status_code == 200
    assert response.json() == {"taskId": "task-1", "status": "STARTED", "backend": "local"}
    assert len(started) == 1
    assert started[0]["taskFn"] == plugin_router.service.installPlugin
    assert started[0]["pluginName"] == "scipion-em-a"
    assert started[0]["operation"] == "install"
    assert started[0]["taskKwargs"] == {"skipBinaries": True}


def test_install_batch_submits_celery_task_when_available(pluginClient, monkeypatch):
    calls = []
    initialized = []

    class DummyTask:
        def apply_async(self, args, task_id):
            calls.append({"args": args, "task_id": task_id})

    monkeypatch.setattr(plugin_router, "_celeryAppAvailable", True)
    monkeypatch.setattr(plugin_router, "_celeryInstallBatchAvailable", True)
    monkeypatch.setattr(plugin_router, "installPluginsBatchTask", DummyTask())
    monkeypatch.setattr(plugin_router, "initializePluginTaskLog", lambda taskId, pluginName, operation: initialized.append((taskId, pluginName, operation)))
    monkeypatch.setattr(plugin_router.uuid4, "__call__", lambda: "fixed-task-id", raising=False)

    response = pluginClient.post(
        "/plugins/install-batch",
        json={"plugins": ["scipion-em-a", "scipion-em-b", "scipion-em-a"], "skipBinaries": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["backend"] == "celery"
    assert initialized[0][1:] == ("batch:2", "install-batch")
    assert calls == [{"args": [["scipion-em-a", "scipion-em-b"], False], "task_id": body["taskId"]}]


def test_terminal_task_status_refreshes_plugin_catalog_once(pluginClient, monkeypatch):
    clearCalls = []

    class DummyService:
        def clearCache(self):
            clearCalls.append("clear")

    monkeypatch.setattr(plugin_router, "service", DummyService())

    plugin_router._inProcessResults["task-1"] = {"status": "SUCCESS", "result": {"ok": True}, "error": None}

    first = pluginClient.get("/plugins/tasks/task-1")
    second = pluginClient.get("/plugins/tasks/task-1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "SUCCESS"
    assert second.json()["status"] == "SUCCESS"
    assert clearCalls == ["clear"]


def test_terminal_task_log_refreshes_plugin_catalog_once(pluginClient, monkeypatch):
    clearCalls = []

    class DummyService:
        def clearCache(self):
            clearCalls.append("clear")

    monkeypatch.setattr(plugin_router, "service", DummyService())
    monkeypatch.setattr(plugin_router, "readPluginTaskLog", lambda taskId, offset=0, limit=65536: ("done", 4))

    plugin_router._inProcessResults["task-2"] = {"status": "FAILURE", "result": None, "error": "boom"}

    first = pluginClient.get("/plugins/tasks/task-2/log")
    second = pluginClient.get("/plugins/tasks/task-2/log")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["completed"] is True
    assert first.json()["status"] == "FAILURE"
    assert clearCalls == ["clear"]
