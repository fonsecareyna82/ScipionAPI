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
from datetime import datetime, timezone

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
        self.installBinaryCalls = []
        self.uninstallBinaryCalls = []

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

    def installPluginBinary(
            self,
            pluginName,
            binaryTarget,
            taskId=None,
    ):
        self.installBinaryCalls.append({
            "pluginName": pluginName,
            "binaryTarget": binaryTarget,
            "taskId": taskId,
        })

        return {
            "installed": "SUCCESS",
            "pluginName": pluginName,
            "binaryTarget": binaryTarget,
        }

    def uninstallPluginBinary(
            self,
            pluginName,
            binaryTarget,
            taskId=None,
    ):
        self.uninstallBinaryCalls.append({
            "pluginName": pluginName,
            "binaryTarget": binaryTarget,
            "taskId": taskId,
        })

        return {
            "uninstalled": "SUCCESS",
            "pluginName": pluginName,
            "binaryTarget": binaryTarget,
        }

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

    def installPluginBinary(
            self,
            pluginName,
            binaryTarget,
            taskId=None,
    ):
        return {
            "installed": "SUCCESS",
            "pluginName": pluginName,
            "binaryTarget": binaryTarget,
        }

    def uninstallPluginBinary(
            self,
            pluginName,
            binaryTarget,
            taskId=None,
    ):
        return {
            "uninstalled": "SUCCESS",
            "pluginName": pluginName,
            "binaryTarget": binaryTarget,
        }

    def clearCache(self):
        pass


class FakeCeleryResult:
    # fakeCeleryResult
    def __init__(self, status, result=None, info=None):
        self.status = status
        self.result = result
        self.info = info


class FakeCeleryControl:
    def __init__(self):
        self.revokeCalls = []

    def revoke(
            self,
            taskId,
            terminate=False,
            signal=None,
    ):
        self.revokeCalls.append({
            "taskId": taskId,
            "terminate": terminate,
            "signal": signal,
        })


def test_CancelPluginTaskRevokesRunningCeleryTask(
        pluginClient,
        pluginRouterModule,
        fakeSystemTaskService,
        monkeypatch,
):
    now = datetime.now(timezone.utc)
    fakeSystemTaskService.tasksById[
        "running-task"
    ] = {
        "id": 1,
        "taskId": "running-task",
        "taskType": "plugin",
        "operation": "install",
        "subject": "scipion-em-test",
        "subjectLabel": None,
        "status": "PROGRESS",
        "step": "Installing binaries...",
        "error": None,
        "result": None,
        "meta": None,
        "payload": {},
        "backend": "celery",
        "acknowledged": False,
        "retryOfTaskId": None,
        "createdAt": now,
        "startedAt": now,
        "finishedAt": None,
        "updatedAt": now,
    }

    celery = FakeCeleryApp({
        "running-task":
            FakeCeleryResult(
                status="PROGRESS",
            ),
    })

    monkeypatch.setattr(
        pluginRouterModule,
        "_celeryAppAvailable",
        True,
    )

    monkeypatch.setattr(
        pluginRouterModule,
        "celeryApp",
        celery,
    )

    monkeypatch.setattr(
        pluginRouterModule,
        "_refreshPluginCatalogAfterTask",
        lambda *args, **kwargs: None,
    )

    response = pluginClient.post(
        "/plugins/tasks/"
        "running-task/cancel"
    )

    assert response.status_code == 200

    assert (
        response.json()["status"]
        == "CANCELLED"
    )

    assert (
        celery.control.revokeCalls
        == [{
            "taskId": "running-task",
            "terminate": True,
            "signal": "SIGTERM",
        }]
    )


class FakeCeleryApp:
    # fakeCeleryApp
    def __init__(self, resultByTaskId):
        self.resultByTaskId = (
            resultByTaskId
        )
        self.control = (
            FakeCeleryControl()
        )

    def AsyncResult(self, taskId):
        return self.resultByTaskId[
            taskId
        ]


class FakeCeleryTask:
    # fakeCeleryTask
    def __init__(self):
        self.calls = []

    def apply_async(self, args=None, task_id=None):
        self.calls.append({
            "args": args,
            "task_id": task_id,
        })


class FakeSystemTaskService:
    def __init__(self):
        self.createCalls = []
        self.updateCalls = []
        self.listCalls = []
        self.getCalls = []
        self.acknowledgeCalls = []
        self.acknowledgeManyCalls = []
        self.tasksById = {}

    def createTask(self, **kwargs):
        self.createCalls.append(kwargs)

        task = {
            "id": len(self.createCalls),
            "taskId": kwargs["taskId"],
            "taskType": kwargs["taskType"],
            "operation": kwargs["operation"],
            "subject": kwargs["subject"],
            "subjectLabel": kwargs.get("subjectLabel"),
            "status": kwargs.get("status", "PENDING"),
            "step": None,
            "error": None,
            "result": None,
            "meta": None,
            "payload": kwargs.get("payload", {}),
            "backend": kwargs["backend"],
            "acknowledged": False,
            "retryOfTaskId": kwargs.get("retryOfTaskId"),
            "createdAt": None,
            "startedAt": None,
            "finishedAt": None,
            "updatedAt": None,
        }

        self.tasksById[task["taskId"]] = task

        return dict(task)

    def updateTask(self, **kwargs):
        self.updateCalls.append(kwargs)

        taskId = kwargs["taskId"]
        task = self.tasksById.get(taskId)

        if task is None:
            return None

        for key in (
            "status",
            "step",
            "error",
            "result",
            "meta",
        ):
            if key in kwargs:
                task[key] = kwargs[key]

        return dict(task)

    def getTask(self, taskId):
        self.getCalls.append(taskId)

        task = self.tasksById.get(taskId)

        return None if task is None else dict(task)

    def listTasks(self, **kwargs):
        self.listCalls.append(kwargs)

        tasks = [
            dict(task)
            for task in self.tasksById.values()
        ]

        requestedStatus = kwargs.get("status")

        if requestedStatus:
            normalizedStatus = str(
                requestedStatus
            ).strip().upper()

            tasks = [
                task
                for task in tasks
                if str(
                    task.get("status") or ""
                ).strip().upper() == normalizedStatus
            ]

        return tasks

    def acknowledgeTasks(
            self,
            taskType=None,
            statuses=None,
    ):
        self.acknowledgeManyCalls.append({
            "taskType": taskType,
            "statuses": statuses,
        })

        normalizedStatuses = {
            str(status).upper()
            for status in (statuses or [])
        }

        acknowledged = 0

        for task in self.tasksById.values():
            if (
                    taskType
                    and task.get("taskType") != taskType
            ):
                continue

            if (
                    normalizedStatuses
                    and str(
                        task.get("status") or ""
                    ).upper() not in normalizedStatuses
            ):
                continue

            if task.get("acknowledged"):
                continue

            task["acknowledged"] = True
            acknowledged += 1

        return acknowledged

    def acknowledgeTask(self, taskId):
        self.acknowledgeCalls.append(taskId)

        task = self.tasksById.get(taskId)

        if task is None:
            return None

        task["acknowledged"] = True

        return dict(task)


@pytest.fixture
def pluginRouterModule(monkeypatch):
    pluginServiceModuleName = (
        "app.backend.api.services.plugin_service"
    )
    systemTaskServiceModuleName = (
        "app.backend.api.services.system_task_service"
    )
    taskQueueModuleName = (
        "app.workers.task_queue"
    )
    pluginRouterModuleName = (
        "app.backend.api.routers.plugin_router"
    )

    previousPluginServiceModule = (
        sys.modules.get(
            pluginServiceModuleName
        )
    )
    previousSystemTaskServiceModule = (
        sys.modules.get(
            systemTaskServiceModuleName
        )
    )
    previousTaskQueueModule = (
        sys.modules.get(
            taskQueueModuleName
        )
    )
    previousPluginRouterModule = (
        sys.modules.get(
            pluginRouterModuleName
        )
    )

    fakePluginServiceModule = (
        types.ModuleType(
            pluginServiceModuleName
        )
    )
    fakePluginServiceModule.PluginService = (
        ImportSafePluginService
    )

    fakeSystemTaskServiceModule = (
        types.ModuleType(
            systemTaskServiceModuleName
        )
    )
    fakeSystemTaskServiceModule.SystemTaskService = (
        FakeSystemTaskService
    )

    fakeTaskQueueModule = (
        types.ModuleType(
            taskQueueModuleName
        )
    )

    sys.modules[
        pluginServiceModuleName
    ] = fakePluginServiceModule

    sys.modules[
        systemTaskServiceModuleName
    ] = fakeSystemTaskServiceModule

    sys.modules[
        taskQueueModuleName
    ] = fakeTaskQueueModule

    sys.modules.pop(
        pluginRouterModuleName,
        None,
    )

    try:
        module = importlib.import_module(
            pluginRouterModuleName
        )
        yield module

    finally:
        sys.modules.pop(
            pluginRouterModuleName,
            None,
        )

        if previousPluginServiceModule is None:
            sys.modules.pop(
                pluginServiceModuleName,
                None,
            )
        else:
            sys.modules[
                pluginServiceModuleName
            ] = previousPluginServiceModule

        if previousSystemTaskServiceModule is None:
            sys.modules.pop(
                systemTaskServiceModuleName,
                None,
            )
        else:
            sys.modules[
                systemTaskServiceModuleName
            ] = previousSystemTaskServiceModule

        if previousTaskQueueModule is None:
            sys.modules.pop(
                taskQueueModuleName,
                None,
            )
        else:
            sys.modules[
                taskQueueModuleName
            ] = previousTaskQueueModule

        if previousPluginRouterModule is not None:
            sys.modules[
                pluginRouterModuleName
            ] = previousPluginRouterModule


@pytest.fixture
def fakePluginService():
    # fakePluginServiceFixture
    return FakePluginService()


@pytest.fixture
def fakeSystemTaskService():
    return FakeSystemTaskService()


@pytest.fixture
def pluginClient(
        pluginRouterModule,
        fakePluginService,
        fakeSystemTaskService,
        monkeypatch,
):
    # pluginClient
    monkeypatch.setattr(pluginRouterModule, "service", fakePluginService)
    monkeypatch.setattr(
        pluginRouterModule,
        "systemTaskService",
        fakeSystemTaskService,
    )
    monkeypatch.setattr(pluginRouterModule, "_inProcessResults", {})
    monkeypatch.setattr(pluginRouterModule, "_inProcessTasks", {})
    monkeypatch.setattr(pluginRouterModule, "_refreshedTerminalTaskIds", set())
    monkeypatch.setattr(pluginRouterModule, "_celeryAppAvailable", False)
    monkeypatch.setattr(pluginRouterModule, "_celeryInstallAvailable", False)
    monkeypatch.setattr(pluginRouterModule, "_celeryInstallBatchAvailable", False)
    monkeypatch.setattr(pluginRouterModule, "_celeryInstallDevelAvailable", False)
    monkeypatch.setattr(pluginRouterModule, "_celeryUninstallAvailable", False)
    monkeypatch.setattr(pluginRouterModule, "_celeryInstallBinaryAvailable", False)
    monkeypatch.setattr(pluginRouterModule, "_celeryUninstallBinaryAvailable", False)
    monkeypatch.setattr(pluginRouterModule, "celeryApp", None)
    monkeypatch.setattr(pluginRouterModule, "installPluginTask", None)
    monkeypatch.setattr(pluginRouterModule, "installPluginsBatchTask", None)
    monkeypatch.setattr(pluginRouterModule, "installDevelPluginTask", None)
    monkeypatch.setattr(pluginRouterModule, "uninstallPluginTask", None)
    monkeypatch.setattr(pluginRouterModule, "installPluginBinaryTask", None)
    monkeypatch.setattr(pluginRouterModule, "uninstallPluginBinaryTask", None)

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


def test_InstallPluginBinaryUsesLocalBackendWhenCeleryUnavailable(
        pluginClient,
        pluginRouterModule,
        monkeypatch,
):
    captured = {}

    async def fakeStartInProcessTask(
            taskFn,
            pluginName,
            operation,
            **taskKwargs,
    ):
        captured["taskFn"] = taskFn
        captured["pluginName"] = pluginName
        captured["operation"] = operation
        captured["taskKwargs"] = taskKwargs

        return {
            "taskId": "local-install-binary-1",
            "status": "STARTED",
            "backend": "local",
        }

    monkeypatch.setattr(
        pluginRouterModule,
        "_startInProcessTask",
        fakeStartInProcessTask,
    )

    response = pluginClient.post(
        "/plugins/scipion-em-imod/binaries/imod-5.1.9/install"
    )

    assert response.status_code == 200

    assert response.json() == {
        "taskId": "local-install-binary-1",
        "status": "STARTED",
        "backend": "local",
    }

    assert (
        captured["taskFn"]
        == pluginRouterModule.service.installPluginBinary
    )

    assert captured["pluginName"] == "scipion-em-imod"
    assert captured["operation"] == "install-binary"

    assert captured["taskKwargs"] == {
        "binaryTarget": "imod-5.1.9",
    }


def test_UninstallPluginBinaryUsesLocalBackendWhenCeleryUnavailable(
        pluginClient,
        pluginRouterModule,
        monkeypatch,
):
    captured = {}

    async def fakeStartInProcessTask(
            taskFn,
            pluginName,
            operation,
            **taskKwargs,
    ):
        captured["taskFn"] = taskFn
        captured["pluginName"] = pluginName
        captured["operation"] = operation
        captured["taskKwargs"] = taskKwargs

        return {
            "taskId": "local-uninstall-binary-1",
            "status": "STARTED",
            "backend": "local",
        }

    monkeypatch.setattr(
        pluginRouterModule,
        "_startInProcessTask",
        fakeStartInProcessTask,
    )

    response = pluginClient.post(
        "/plugins/scipion-em-imod/binaries/imod-5.1.9/uninstall"
    )

    assert response.status_code == 200

    assert response.json() == {
        "taskId": "local-uninstall-binary-1",
        "status": "STARTED",
        "backend": "local",
    }

    assert (
        captured["taskFn"]
        == pluginRouterModule.service.uninstallPluginBinary
    )

    assert captured["pluginName"] == "scipion-em-imod"
    assert captured["operation"] == "uninstall-binary"

    assert captured["taskKwargs"] == {
        "binaryTarget": "imod-5.1.9",
    }


def test_InstallPluginBinaryUsesCeleryWhenAvailable(
        pluginClient,
        pluginRouterModule,
        fakeSystemTaskService,
        monkeypatch,
):
    fakeTask = FakeCeleryTask()

    monkeypatch.setattr(
        pluginRouterModule,
        "_celeryAppAvailable",
        True,
    )
    monkeypatch.setattr(
        pluginRouterModule,
        "_celeryInstallBinaryAvailable",
        True,
    )
    monkeypatch.setattr(
        pluginRouterModule,
        "installPluginBinaryTask",
        fakeTask,
    )
    monkeypatch.setattr(
        pluginRouterModule,
        "initializePluginTaskLog",
        lambda taskId, pluginName, operation: "/tmp/binary-install.log",
    )

    response = pluginClient.post(
        "/plugins/scipion-em-imod/binaries/imod-5.1.9/install"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "PENDING"
    assert body["backend"] == "celery"

    assert fakeTask.calls == [{
        "args": [
            "scipion-em-imod",
            "imod-5.1.9",
        ],
        "task_id": body["taskId"],
    }]

    createdTask = (
        fakeSystemTaskService
        .createCalls[0]
    )

    assert createdTask["operation"] == "install-binary"
    assert createdTask["subject"] == "scipion-em-imod"

    assert createdTask["payload"] == {
        "pluginName": "scipion-em-imod",
        "binaryTarget": "imod-5.1.9",
    }


def test_UninstallPluginBinaryUsesCeleryWhenAvailable(
        pluginClient,
        pluginRouterModule,
        fakeSystemTaskService,
        monkeypatch,
):
    fakeTask = FakeCeleryTask()

    monkeypatch.setattr(
        pluginRouterModule,
        "_celeryAppAvailable",
        True,
    )
    monkeypatch.setattr(
        pluginRouterModule,
        "_celeryUninstallBinaryAvailable",
        True,
    )
    monkeypatch.setattr(
        pluginRouterModule,
        "uninstallPluginBinaryTask",
        fakeTask,
    )
    monkeypatch.setattr(
        pluginRouterModule,
        "initializePluginTaskLog",
        lambda taskId, pluginName, operation: "/tmp/binary-uninstall.log",
    )

    response = pluginClient.post(
        "/plugins/scipion-em-imod/binaries/imod-5.1.9/uninstall"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "PENDING"
    assert body["backend"] == "celery"

    assert fakeTask.calls == [{
        "args": [
            "scipion-em-imod",
            "imod-5.1.9",
        ],
        "task_id": body["taskId"],
    }]

    createdTask = (
        fakeSystemTaskService
        .createCalls[0]
    )

    assert createdTask["operation"] == "uninstall-binary"

    assert createdTask["payload"] == {
        "pluginName": "scipion-em-imod",
        "binaryTarget": "imod-5.1.9",
    }


def test_InstallPluginUsesCeleryWhenAvailable(
        pluginClient,
        pluginRouterModule,
        fakeSystemTaskService,
        monkeypatch,
):
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

    assert len(fakeSystemTaskService.createCalls) == 1

    createdTask = fakeSystemTaskService.createCalls[0]

    assert createdTask["taskId"] == body["taskId"]
    assert createdTask["taskType"] == "plugin"
    assert createdTask["operation"] == "install"
    assert createdTask["subject"] == "scipion-em-relion"
    assert createdTask["backend"] == "celery"
    assert createdTask["status"] == "PENDING"
    assert createdTask["payload"] == {
        "pluginName": "scipion-em-relion",
        "skipBinaries": False,
    }


def test_InstallPluginPassesSkipBinariesToCelery(
        pluginClient,
        pluginRouterModule,
        fakeSystemTaskService,
        monkeypatch,
):
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

    assert len(fakeSystemTaskService.createCalls) == 1

    createdTask = fakeSystemTaskService.createCalls[0]

    assert createdTask["payload"] == {
        "pluginName": "scipion-em-relion",
        "skipBinaries": True,
    }


def test_ListPluginTasksReconcilesStaleCelerySuccess(
        pluginRouterModule,
        fakeSystemTaskService,
        monkeypatch,
):
    fakeSystemTaskService.tasksById["stale-task"] = {
        "taskId": "stale-task",
        "backend": "celery",
        "status": "PENDING",
        "step": None,
        "error": None,
        "result": None,
        "meta": None,
    }

    monkeypatch.setattr(
        pluginRouterModule,
        "systemTaskService",
        fakeSystemTaskService,
    )

    monkeypatch.setattr(
        pluginRouterModule,
        "_celeryAppAvailable",
        True,
    )

    monkeypatch.setattr(
        pluginRouterModule,
        "celeryApp",
        FakeCeleryApp({
            "stale-task": FakeCeleryResult(
                status="SUCCESS",
                result="Plugin installed successfully!",
                info={"step": "Completed"},
            ),
        }),
    )

    tasks = pluginRouterModule.listPluginTasks()

    assert len(tasks) == 1
    assert tasks[0]["status"] == "SUCCESS"
    assert tasks[0]["step"] == "Completed"
    assert tasks[0]["result"] == "Plugin installed successfully!"
    assert tasks[0]["error"] is None

    assert fakeSystemTaskService.updateCalls == [{
        "taskId": "stale-task",
        "status": "SUCCESS",
        "meta": {"step": "Completed"},
        "step": "Completed",
        "result": "Plugin installed successfully!",
        "error": None,
    }]


def test_RetryFailedInstallUsesOriginalPayloadAndLinksTask(
        pluginClient,
        pluginRouterModule,
        fakeSystemTaskService,
        monkeypatch,
):
    fakeSystemTaskService.tasksById["failed-install"] = {
        "taskId": "failed-install",
        "taskType": "plugin",
        "operation": "install",
        "subject": "scipion-em-relion",
        "status": "FAILURE",
        "payload": {
            "pluginName": "scipion-em-relion",
            "skipBinaries": True,
        },
        "backend": "celery",
    }

    fakeTask = FakeCeleryTask()

    monkeypatch.setattr(
        pluginRouterModule,
        "_celeryAppAvailable",
        True,
    )

    monkeypatch.setattr(
        pluginRouterModule,
        "_celeryInstallAvailable",
        True,
    )

    monkeypatch.setattr(
        pluginRouterModule,
        "installPluginTask",
        fakeTask,
    )

    monkeypatch.setattr(
        pluginRouterModule,
        "initializePluginTaskLog",
        lambda taskId, pluginName, operation: "/tmp/retry-plugin.log",
    )

    response = pluginClient.post(
        "/plugins/tasks/failed-install/retry"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "PENDING"
    assert body["backend"] == "celery"
    assert body["taskId"] != "failed-install"

    assert fakeTask.calls == [{
        "args": [
            "scipion-em-relion",
            True,
        ],
        "task_id": body["taskId"],
    }]

    assert len(fakeSystemTaskService.createCalls) == 1

    createdTask = fakeSystemTaskService.createCalls[0]

    assert createdTask["taskId"] == body["taskId"]
    assert createdTask["operation"] == "install"
    assert createdTask["subject"] == "scipion-em-relion"
    assert createdTask["retryOfTaskId"] == "failed-install"
    assert createdTask["payload"] == {
        "pluginName": "scipion-em-relion",
        "skipBinaries": True,
    }


def test_RetryFailedBinaryInstallUsesOriginalTarget(
        pluginClient,
        pluginRouterModule,
        fakeSystemTaskService,
        monkeypatch,
):
    fakeSystemTaskService.tasksById[
        "failed-binary-install"
    ] = {
        "taskId": "failed-binary-install",
        "taskType": "plugin",
        "operation": "install-binary",
        "subject": "scipion-em-imod",
        "status": "FAILURE",
        "payload": {
            "pluginName": "scipion-em-imod",
            "binaryTarget": "imod-5.1.9",
        },
        "backend": "celery",
    }

    fakeTask = FakeCeleryTask()

    monkeypatch.setattr(
        pluginRouterModule,
        "_celeryAppAvailable",
        True,
    )
    monkeypatch.setattr(
        pluginRouterModule,
        "_celeryInstallBinaryAvailable",
        True,
    )
    monkeypatch.setattr(
        pluginRouterModule,
        "installPluginBinaryTask",
        fakeTask,
    )
    monkeypatch.setattr(
        pluginRouterModule,
        "initializePluginTaskLog",
        lambda taskId, pluginName, operation: "/tmp/retry-binary.log",
    )

    response = pluginClient.post(
        "/plugins/tasks/failed-binary-install/retry"
    )

    assert response.status_code == 200

    body = response.json()

    assert fakeTask.calls == [{
        "args": [
            "scipion-em-imod",
            "imod-5.1.9",
        ],
        "task_id": body["taskId"],
    }]

    createdTask = (
        fakeSystemTaskService
        .createCalls[0]
    )

    assert createdTask["operation"] == "install-binary"
    assert createdTask["retryOfTaskId"] == "failed-binary-install"

    assert createdTask["payload"] == {
        "pluginName": "scipion-em-imod",
        "binaryTarget": "imod-5.1.9",
    }


def test_RetryPluginTaskRejectsNonFailedTask(
        pluginClient,
        fakeSystemTaskService,
):
    fakeSystemTaskService.tasksById["successful-task"] = {
        "taskId": "successful-task",
        "taskType": "plugin",
        "operation": "install",
        "subject": "scipion-em-relion",
        "status": "SUCCESS",
        "payload": {
            "pluginName": "scipion-em-relion",
            "skipBinaries": False,
        },
        "backend": "celery",
    }

    response = pluginClient.post(
        "/plugins/tasks/successful-task/retry"
    )

    assert response.status_code == 409

    assert response.json()["detail"] == (
        "Only failed plugin tasks can be retried"
    )


def test_RetryPluginTaskReturns404WhenTaskDoesNotExist(
        pluginClient,
):
    response = pluginClient.post(
        "/plugins/tasks/missing-task/retry"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_GetTaskStatusDoesNotRegressPersistedProgressToCeleryPending(
        pluginClient,
        pluginRouterModule,
        fakeSystemTaskService,
        monkeypatch,
):
    fakeSystemTaskService.tasksById["progress-task"] = {
        "taskId": "progress-task",
        "backend": "celery",
        "status": "PROGRESS",
        "step": "Installing binaries...",
        "error": None,
        "result": None,
        "meta": {
            "step": "Installing binaries...",
        },
    }

    monkeypatch.setattr(
        pluginRouterModule,
        "_celeryAppAvailable",
        True,
    )

    monkeypatch.setattr(
        pluginRouterModule,
        "celeryApp",
        FakeCeleryApp({
            "progress-task": FakeCeleryResult(
                status="PENDING",
                result=None,
                info=None,
            ),
        }),
    )

    response = pluginClient.get(
        "/plugins/tasks/progress-task"
    )

    assert response.status_code == 200

    assert response.json() == {
        "taskId": "progress-task",
        "status": "PROGRESS",
        "backend": "celery",
        "result": None,
        "error": None,
        "meta": {
            "step": "Installing binaries...",
        },
    }

    assert fakeSystemTaskService.updateCalls == []


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


def test_install_batch_uses_local_fallback_for_single_plugin(pluginClient, pluginRouterModule, monkeypatch):
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
        return pluginRouterModule.TaskStartResponse(taskId="task-1", status="STARTED", backend="local")

    monkeypatch.setattr(pluginRouterModule, "_startInProcessTask", fakeStartInProcessTask)

    response = pluginClient.post(
        "/plugins/install-batch",
        json={"plugins": ["scipion-em-a", "scipion-em-a", ""], "skipBinaries": True},
    )

    assert response.status_code == 200
    assert response.json() == {"taskId": "task-1", "status": "STARTED", "backend": "local"}
    assert len(started) == 1
    assert started[0]["taskFn"] == pluginRouterModule.service.installPlugin
    assert started[0]["pluginName"] == "scipion-em-a"
    assert started[0]["operation"] == "install"
    assert started[0]["taskKwargs"] == {"skipBinaries": True}


def test_install_batch_submits_celery_task_when_available(pluginClient, pluginRouterModule, monkeypatch):
    fakeTask = FakeCeleryTask()
    initializeCalls = []

    def fakeInitializePluginTaskLog(taskId, pluginName, operation):
        initializeCalls.append({
            "taskId": taskId,
            "pluginName": pluginName,
            "operation": operation,
        })

    monkeypatch.setattr(pluginRouterModule, "_celeryAppAvailable", True)
    monkeypatch.setattr(pluginRouterModule, "_celeryInstallBatchAvailable", True)
    monkeypatch.setattr(pluginRouterModule, "installPluginsBatchTask", fakeTask)
    monkeypatch.setattr(pluginRouterModule, "initializePluginTaskLog", fakeInitializePluginTaskLog)

    response = pluginClient.post(
        "/plugins/install-batch",
        json={"plugins": ["scipion-em-a", "scipion-em-b", "scipion-em-a"], "skipBinaries": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["backend"] == "celery"
    assert initializeCalls == [
        {
            "taskId": body["taskId"],
            "pluginName": "batch:2",
            "operation": "install-batch",
        }
    ]
    assert fakeTask.calls == [{"args": [["scipion-em-a", "scipion-em-b"], False], "task_id": body["taskId"]}]


def test_terminal_task_status_refreshes_plugin_catalog_once(pluginClient, pluginRouterModule, fakePluginService):
    pluginRouterModule._inProcessResults["task-1"] = {"status": "SUCCESS", "result": {"ok": True}, "error": None}

    first = pluginClient.get("/plugins/tasks/task-1")
    second = pluginClient.get("/plugins/tasks/task-1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "SUCCESS"
    assert second.json()["status"] == "SUCCESS"
    assert fakePluginService.clearCacheCalls == 1


def test_terminal_task_log_refreshes_plugin_catalog_once(pluginClient, pluginRouterModule, fakePluginService, monkeypatch):
    monkeypatch.setattr(pluginRouterModule, "readPluginTaskLog", lambda taskId, offset=0, limit=65536: ("done", 4))

    pluginRouterModule._inProcessResults["task-2"] = {"status": "FAILURE", "result": None, "error": "boom"}

    first = pluginClient.get("/plugins/tasks/task-2/log")
    second = pluginClient.get("/plugins/tasks/task-2/log")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["completed"] is True
    assert first.json()["status"] == "FAILURE"
    assert fakePluginService.clearCacheCalls == 1


def test_AcknowledgePluginTasksClearsRequestedHistory(
        pluginClient,
        fakeSystemTaskService,
):
    fakeSystemTaskService.tasksById["success-task"] = {
        "taskId": "success-task",
        "taskType": "plugin",
        "status": "SUCCESS",
        "acknowledged": False,
    }

    fakeSystemTaskService.tasksById["cancelled-task"] = {
        "taskId": "cancelled-task",
        "taskType": "plugin",
        "status": "CANCELLED",
        "acknowledged": False,
    }

    fakeSystemTaskService.tasksById["failed-task"] = {
        "taskId": "failed-task",
        "taskType": "plugin",
        "status": "FAILURE",
        "acknowledged": False,
    }

    fakeSystemTaskService.tasksById["running-task"] = {
        "taskId": "running-task",
        "taskType": "plugin",
        "status": "PROGRESS",
        "acknowledged": False,
    }

    response = pluginClient.post(
        "/plugins/tasks/acknowledge",
        json={
            "statuses": [
                "SUCCESS",
                "CANCELLED",
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "acknowledged": 2,
    }

    assert fakeSystemTaskService.tasksById["success-task"]["acknowledged"] is True
    assert fakeSystemTaskService.tasksById["cancelled-task"]["acknowledged"] is True

    assert fakeSystemTaskService.tasksById["failed-task"]["acknowledged"] is False
    assert fakeSystemTaskService.tasksById["running-task"]["acknowledged"] is False


def test_AcknowledgePluginTasksRejectsRunningStatus(
        pluginClient,
):
    response = pluginClient.post(
        "/plugins/tasks/acknowledge",
        json={
            "statuses": [
                "PROGRESS",
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Only terminal plugin task statuses can be acknowledged"
    )


