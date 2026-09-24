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
import socket
import sys
import types

import pytest

import scipionapi_cli.runtime as runtimeModule

from scipionapi_cli.runtime import _canBindTcpPort, normalizeRole, _roleIncludes


def test_NormalizeRoleDefaultsToAll():
    assert normalizeRole(None) == "all"
    assert normalizeRole("") == "all"


def test_NormalizeRoleAcceptsValidRoles():
    assert normalizeRole("api") == "api"
    assert normalizeRole("PLUGINS") == "plugins"
    assert normalizeRole(" protocols ") == "protocols"


def test_NormalizeRoleRejectsInvalidRole():
    with pytest.raises(ValueError):
        normalizeRole("gpu-node")


def test_RoleIncludesOnlyMatchingComponentUnlessAll():
    assert _roleIncludes("all", "api") is True
    assert _roleIncludes("all", "plugins") is True
    assert _roleIncludes("api", "api") is True
    assert _roleIncludes("api", "plugins") is False
    assert _roleIncludes("protocols", "protocols") is True
    assert _roleIncludes("protocols", "api") is False


def test_CanBindTcpPortDetectsOccupiedPort():
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        occupiedPort = listener.getsockname()[1]

        assert _canBindTcpPort(
            "127.0.0.1",
            str(occupiedPort),
        ) is False


def test_RecoverInterruptedPluginTasksOnlyFailsActiveCeleryTasks(
        monkeypatch,
):
    tasks = [
        {
            "taskId": "started-task",
            "backend": "celery",
            "status": "STARTED",
        },
        {
            "taskId": "progress-task",
            "backend": "celery",
            "status": "PROGRESS",
        },
        {
            "taskId": "retry-task",
            "backend": "celery",
            "status": "RETRY",
        },
        {
            "taskId": "pending-task",
            "backend": "celery",
            "status": "PENDING",
        },
        {
            "taskId": "success-task",
            "backend": "celery",
            "status": "SUCCESS",
        },
        {
            "taskId": "local-progress",
            "backend": "local",
            "status": "PROGRESS",
        },
    ]

    updates = []
    logs = []

    class FakeSystemTaskService:
        def listTasks(self, **kwargs):
            assert kwargs == {
                "taskType": "plugin",
                "includeAcknowledged": True,
                "limit": 500,
            }
            return tasks

        def updateTask(self, **kwargs):
            updates.append(kwargs)
            return kwargs

    systemTaskModule = types.ModuleType(
        "app.backend.api.services.system_task_service"
    )
    systemTaskModule.SystemTaskService = FakeSystemTaskService

    pluginTaskLogModule = types.ModuleType(
        "app.backend.api.services.plugin_task_log"
    )
    pluginTaskLogModule.appendPluginTaskLog = (
        lambda taskId, text: logs.append((taskId, text))
    )

    monkeypatch.setitem(
        sys.modules,
        "app.backend.api.services.system_task_service",
        systemTaskModule,
    )
    monkeypatch.setitem(
        sys.modules,
        "app.backend.api.services.plugin_task_log",
        pluginTaskLogModule,
    )

    recovered = (
        runtimeModule
        ._recoverInterruptedPluginTasks()
    )

    assert recovered == 3

    assert [
        item["taskId"]
        for item in updates
    ] == [
        "started-task",
        "progress-task",
        "retry-task",
    ]

    for update in updates:
        assert update["status"] == "FAILURE"
        assert update["step"] == "Interrupted"
        assert "interrupted" in (
            update["error"].lower()
        )

    assert [
        taskId
        for taskId, _ in logs
    ] == [
        "started-task",
        "progress-task",
        "retry-task",
    ]


def test_StartPluginWorkerRecoversInterruptedTasksBeforeLaunch(
        tmp_path,
        monkeypatch,
):
    pidPath = tmp_path / "worker.pid"
    logPath = tmp_path / "celery.log"

    spec = {
        "kind": "plugins",
        "repoRoot": tmp_path,
        "pidPath": pidPath,
        "logPath": logPath,
        "celeryApp": "app.workers.task_queue",
        "celeryLogLevel": "info",
        "queueName": "plugins",
        "hostname": "plugins@%h",
        "concurrency": 1,
        "startupWait": 0.1,
    }

    states = iter([
        {
            "kind": "plugins",
            "state": "stopped",
            "pid": None,
            "pidPath": str(pidPath),
        },
        {
            "kind": "plugins",
            "state": "running",
            "pid": 12345,
            "pidPath": str(pidPath),
        },
    ])

    events = []

    monkeypatch.setattr(
        runtimeModule,
        "_getWorkerRuntimeSpec",
        lambda workerKind: spec,
    )

    monkeypatch.setattr(
        runtimeModule,
        "getWorkerProcessState",
        lambda workerKind: next(states),
    )

    monkeypatch.setattr(
        runtimeModule,
        "_recoverInterruptedPluginTasks",
        lambda: events.append("recover") or 1,
    )

    monkeypatch.setattr(
        runtimeModule,
        "_buildCeleryWorkerCommand",
        lambda **kwargs: ["celery-worker"],
    )

    def fakeStartDetachedProcess(*args, **kwargs):
        events.append("launch")
        return 12345

    monkeypatch.setattr(
        runtimeModule,
        "_startDetachedProcess",
        fakeStartDetachedProcess,
    )

    monkeypatch.setattr(
        runtimeModule,
        "_writePid",
        lambda path, pid: None,
    )

    result = runtimeModule.startWorkerProcess(
        "plugins"
    )

    assert events == [
        "recover",
        "launch",
    ]

    assert result["state"] == "running"
    assert result["pid"] == 12345


def test_StartCommandRecoversInterruptedTasksBeforePluginWorkerLaunch(
        tmp_path,
        monkeypatch,
):
    runDir = tmp_path / ".run"
    runDir.mkdir()

    (runDir / "api.pid").write_text(
        "101",
        encoding="utf-8",
    )

    (runDir / "protocol-worker.pid").write_text(
        "303",
        encoding="utf-8",
    )

    env = {
        "API_HOST": "127.0.0.1",
        "API_PORT": "39080",
        "LOGS_PATH": str(
            tmp_path / "logs"
        ),
        "CELERY_APP": "app.workers.task_queue",
        "CELERY_LOGLEVEL": "info",
        "SERVE_WEB": "0",
    }

    events = []

    monkeypatch.setattr(
        runtimeModule,
        "resolveRepoRoot",
        lambda: tmp_path,
    )

    monkeypatch.setattr(
        runtimeModule,
        "_loadEnv",
        lambda repoRoot: env,
    )

    monkeypatch.setattr(
        runtimeModule,
        "_resolveEnvPath",
        lambda repoRoot:
            tmp_path
            / "scipion_home"
            / ".env",
    )

    def fakeDescribePidState(path):
        if path.name == "api.pid":
            return "RUNNING", 101

        if path.name == "protocol-worker.pid":
            return "RUNNING", 303

        if path.name == "worker.pid":
            if path.exists():
                return "RUNNING", 202

            return "STOPPED", None

        raise AssertionError(
            f"Unexpected PID path: {path}"
        )

    monkeypatch.setattr(
        runtimeModule,
        "_describePidState",
        fakeDescribePidState,
    )

    monkeypatch.setattr(
        runtimeModule,
        "_waitForTcp",
        lambda *args, **kwargs: True,
    )

    monkeypatch.setattr(
        runtimeModule,
        "_waitForHttp",
        lambda *args, **kwargs:
            (True, "HTTP 200"),
    )

    monkeypatch.setattr(
        runtimeModule,
        "_recoverInterruptedPluginTasks",
        lambda: events.append("recover") or 1,
    )

    def fakeStartDetachedProcess(
            args,
            cwd,
            env,
            logPath,
            sanityWaitSec,
    ):
        events.append("launch")
        return 202

    monkeypatch.setattr(
        runtimeModule,
        "_startDetachedProcess",
        fakeStartDetachedProcess,
    )

    monkeypatch.setattr(
        runtimeModule,
        "_printPanel",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        runtimeModule,
        "_printKeyValueTable",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        runtimeModule,
        "_printServiceStatusTable",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        runtimeModule,
        "_printSummaryTable",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        runtimeModule,
        "_printInfo",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        runtimeModule,
        "_printSuccess",
        lambda *args, **kwargs: None,
    )

    runtimeModule.startCommand()

    assert events == [
        "recover",
        "launch",
    ]

    assert (
        runDir
        / "worker.pid"
    ).read_text(
        encoding="utf-8"
    ) == "202"


def test_StartCommandWithProtocolsRoleOnlyLaunchesProtocolWorker(
        tmp_path,
        monkeypatch,
):
    runDir = tmp_path / ".run"
    runDir.mkdir()

    env = {
        "API_HOST": "127.0.0.1",
        "API_PORT": "39080",
        "LOGS_PATH": str(tmp_path / "logs"),
        "CELERY_APP": "app.workers.task_queue",
        "CELERY_LOGLEVEL": "info",
        "SERVE_WEB": "0",
    }

    events = []

    monkeypatch.setattr(runtimeModule, "resolveRepoRoot", lambda: tmp_path)
    monkeypatch.setattr(runtimeModule, "_loadEnv", lambda repoRoot: env)
    monkeypatch.setattr(
        runtimeModule,
        "_resolveEnvPath",
        lambda repoRoot: tmp_path / "scipion_home" / ".env",
    )

    def fakeDescribePidState(path):
        if path.name == "protocol-worker.pid":
            if path.exists():
                return "RUNNING", 303
            return "STOPPED", None

        raise AssertionError(
            f"Unexpected PID path checked while role=protocols: {path}"
        )

    monkeypatch.setattr(runtimeModule, "_describePidState", fakeDescribePidState)

    def fakeCanBindTcpPort(*args, **kwargs):
        raise AssertionError("API port should not be checked when role=protocols")

    monkeypatch.setattr(runtimeModule, "_canBindTcpPort", fakeCanBindTcpPort)

    def fakeRecoverInterruptedPluginTasks():
        raise AssertionError("Plugin task recovery should not run when role=protocols")

    monkeypatch.setattr(
        runtimeModule,
        "_recoverInterruptedPluginTasks",
        fakeRecoverInterruptedPluginTasks,
    )

    def fakeStartDetachedProcess(args, cwd, env, logPath, sanityWaitSec):
        events.append("launch")
        return 303

    monkeypatch.setattr(runtimeModule, "_startDetachedProcess", fakeStartDetachedProcess)

    for name in (
        "_printPanel",
        "_printKeyValueTable",
        "_printServiceStatusTable",
        "_printSummaryTable",
        "_printInfo",
        "_printSuccess",
    ):
        monkeypatch.setattr(runtimeModule, name, lambda *args, **kwargs: None)

    runtimeModule.startCommand("protocols")

    assert events == ["launch"]
    assert (runDir / "protocol-worker.pid").read_text(encoding="utf-8") == "303"
    assert not (runDir / "api.pid").exists()
    assert not (runDir / "worker.pid").exists()


def test_StopCommandWithApiRoleOnlyStopsApi(tmp_path, monkeypatch):
    runDir = tmp_path / ".run"
    runDir.mkdir()

    stoppedPaths = []

    monkeypatch.setattr(runtimeModule, "resolveRepoRoot", lambda: tmp_path)
    monkeypatch.setattr(runtimeModule, "_loadEnv", lambda repoRoot: {})

    def fakeStopPid(path):
        stoppedPaths.append(path.name)
        return "stopped", 101

    monkeypatch.setattr(runtimeModule, "_stopPid", fakeStopPid)

    for name in ("_printPanel", "_printKeyValueTable", "_printServiceStatusTable", "_printSuccess"):
        monkeypatch.setattr(runtimeModule, name, lambda *args, **kwargs: None)

    runtimeModule.stopCommand("api")

    assert stoppedPaths == ["api.pid"]


def test_PluginWorkerRecyclesChildAfterEveryTask():
    command = (
        runtimeModule
        ._buildCeleryWorkerCommand(
            celeryApp=(
                "app.workers.task_queue"
            ),
            celeryLogLevel="info",
            queueName="plugins",
            concurrency=1,
            hostname="plugins@%h",
        )
    )

    assert (
        "--max-tasks-per-child"
        in command
    )

    optionIndex = command.index(
        "--max-tasks-per-child"
    )

    assert (
        command[
            optionIndex + 1
        ]
        == "1"
    )


def test_ProtocolWorkerDoesNotRecycleAfterEveryTask():
    command = (
        runtimeModule
        ._buildCeleryWorkerCommand(
            celeryApp=(
                "app.workers.task_queue"
            ),
            celeryLogLevel="info",
            queueName="protocols",
            concurrency=4,
            hostname="protocols@%h",
        )
    )

    assert (
        "--max-tasks-per-child"
        not in command
    )


