import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.api.routers import plugin_router


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
