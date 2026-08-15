import logging
import os
import time
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# loadDotEnvFromRepoRoot
repoRoot = Path(__file__).resolve().parents[2]  # ScipionAPI/
dotEnvPath = (repoRoot / "scipion_home" / ".env").resolve()
load_dotenv(dotEnvPath, override=False)

from celery import Celery, Task
from celery.exceptions import Ignore

from app.backend.api.services.environment import prepareEnvironment
from app.backend.api.services.plugin_task_log import (
    appendPluginTaskLog,
    pluginTaskLogCapture,
    writePluginTaskStep,
)
from app.backend.api.services.plugins_revision import bumpPluginsRevision
from app.backend.api.services.reload_trigger import triggerBackendReloadIfEnabled
from app.backend.api.services.system_task_service import SystemTaskService

celeryApp = Celery("scipionweb")
celeryApp.config_from_object("app.workers.celeryconfig")
logger = logging.getLogger(__name__)
systemTaskService = SystemTaskService()

logger.debug(
    "celeryEnvLoaded dotEnvPath=%s scipionHome=%s",
    str(dotEnvPath),
    os.environ.get("SCIPION_HOME"),
)

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_YELLOW = "\033[33m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"


def ansi(text: str, color: str, bold: bool = False) -> str:
    prefix = f"{ANSI_BOLD}{color}" if bold else color
    return f"{prefix}{text}{ANSI_RESET}"


PROTOCOL_SUCCESS_STATUSES = {
    "finished",
    "interactive",
}

PROTOCOL_FAILURE_STATUSES = {
    "failed",
}

PROTOCOL_CANCELLED_STATUSES = {
    "aborted",
}

PROTOCOL_TERMINAL_STATUSES = (
    PROTOCOL_SUCCESS_STATUSES
    | PROTOCOL_FAILURE_STATUSES
    | PROTOCOL_CANCELLED_STATUSES
)


def _getProtocolStatus(mapper, projectId: int, protocolId: int) -> str:
    protocolRow = mapper.getProtocolByProtocolId(protocolId=protocolId, projectId=projectId)

    if protocolRow is None:
        raise RuntimeError(
            "Protocol was not found in PostgreSQL. "
            f"projectId={projectId} protocolId={protocolId}"
        )

    return str(protocolRow.get("status") or "").strip().lower()


def _waitForProtocolTerminalStatus(
    mapper,
    projectId: int,
    protocolId: int,
    timeoutSeconds=None,
    pollSeconds: float = 1.0,
) -> str:
    deadline = None if timeoutSeconds is None else time.monotonic() + max(0.0, float(timeoutSeconds))

    while True:
        protocolStatus = _getProtocolStatus(mapper, projectId, protocolId)

        if protocolStatus in PROTOCOL_TERMINAL_STATUSES:
            return protocolStatus

        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError(
                "Protocol worker exited but protocol did not reach a terminal state. "
                f"projectId={projectId} protocolId={protocolId} status={protocolStatus}"
            )

        time.sleep(max(0.1, float(pollSeconds)))


class InstallPluginTask(Task):
    acks_late = True

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logger.warning("Task %s retrying: %s", task_id, exc)
        appendPluginTaskLog(str(task_id), ansi(f"[retry] {str(exc)}", ANSI_YELLOW, bold=True))
        systemTaskService.updateTask(
            taskId=str(task_id),
            status="RETRY",
            error=str(exc),
        )
        super().on_retry(exc, task_id, args, kwargs, einfo)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Task %s failed: %s", task_id, exc)
        appendPluginTaskLog(str(task_id), ansi(f"[failure] {str(exc)}", ANSI_RED, bold=True))
        systemTaskService.updateTask(
            taskId=str(task_id),
            status="FAILURE",
            error=str(exc),
        )
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_success(self, retval, task_id, args, kwargs):
        appendPluginTaskLog(
            str(task_id),
            ansi("[success] Task completed successfully", ANSI_GREEN, bold=True),
        )
        systemTaskService.updateTask(
            taskId=str(task_id),
            status="SUCCESS",
            step="Completed",
            result=retval,
            error=None,
        )
        super().on_success(retval, task_id, args, kwargs)


@celeryApp.task(base=InstallPluginTask, bind=True, name="app.tasks.installPluginTask")
def installPluginTask(self, pip_name: str, skip_binaries: bool = False) -> str:
    taskId = str(self.request.id)

    with pluginTaskLogCapture(taskId):
        self.update_state(state="PROGRESS", meta={"step": "Preparing environment..."})
        writePluginTaskStep(taskId, "Preparing environment...")
        prepareEnvironment()

        self.update_state(state="PROGRESS", meta={"step": "Loading service..."})
        writePluginTaskStep(taskId, "Loading service...")
        from app.backend.api.services.plugin_service import PluginService
        service = PluginService()

        installStep = "Installing plugin without binaries..." if skip_binaries else "Installing plugin..."
        self.update_state(state="PROGRESS", meta={"step": installStep})
        writePluginTaskStep(taskId, installStep)
        service.installPlugin(pip_name, taskId=taskId, skipBinaries=skip_binaries)

        self.update_state(state="PROGRESS", meta={"step": "Refreshing plugin metadata..."})
        writePluginTaskStep(taskId, "Refreshing plugin metadata...")
        newRev = bumpPluginsRevision()
        logger.warning("pluginsRevisionBumped=%s", newRev)
        logger.warning(
            "pluginsRevisionBumped=%s scipionHome=%s",
            newRev,
            os.environ.get("SCIPION_HOME"),
        )
        writePluginTaskStep(taskId, f"Plugins revision bumped to {newRev}")

        writePluginTaskStep(taskId, "Triggering backend reload if enabled...")
        triggerBackendReloadIfEnabled()

        self.update_state(state="PROGRESS", meta={"step": "Completed"})
        writePluginTaskStep(taskId, "Completed")
        suffix = " without binaries" if skip_binaries else ""
        return f"Plugin {pip_name} installed successfully{suffix}!"


@celeryApp.task(base=InstallPluginTask, bind=True, name="app.tasks.installPluginsBatchTask")
def installPluginsBatchTask(self, pip_names: List[str], skip_binaries: bool = False) -> str:
    taskId = str(self.request.id)
    cleanPipNames = [str(pipName).strip() for pipName in pip_names if str(pipName).strip()]
    total = len(cleanPipNames)

    with pluginTaskLogCapture(taskId):
        self.update_state(state="PROGRESS", meta={"step": "Preparing environment..."})
        writePluginTaskStep(taskId, "Preparing environment...")
        prepareEnvironment()

        self.update_state(state="PROGRESS", meta={"step": "Loading service..."})
        writePluginTaskStep(taskId, "Loading service...")
        from app.backend.api.services.plugin_service import PluginService
        service = PluginService()

        installed = []
        failed = []

        for index, pipName in enumerate(cleanPipNames, start=1):
            step = f"Installing {index}/{total}: {pipName}"
            if skip_binaries:
                step = f"Installing {index}/{total} without binaries: {pipName}"

            self.update_state(
                state="PROGRESS",
                meta={
                    "step": step,
                    "current": pipName,
                    "index": index,
                    "total": total,
                    "installed": installed,
                    "failed": failed,
                },
            )
            writePluginTaskStep(taskId, step)

            try:
                service.installPlugin(pipName, taskId=taskId, skipBinaries=skip_binaries)
                installed.append(pipName)
                writePluginTaskStep(taskId, f"Completed {index}/{total}: {pipName}")
            except Exception as exc:
                failed.append({"pipName": pipName, "error": str(exc)})
                writePluginTaskStep(taskId, f"Failed {index}/{total}: {pipName}: {exc}")
                raise

        self.update_state(state="PROGRESS", meta={"step": "Refreshing plugin metadata..."})
        writePluginTaskStep(taskId, "Refreshing plugin metadata...")
        newRev = bumpPluginsRevision()
        logger.warning("pluginsRevisionBumped=%s", newRev)
        logger.warning(
            "pluginsRevisionBumped=%s scipionHome=%s",
            newRev,
            os.environ.get("SCIPION_HOME"),
        )
        writePluginTaskStep(taskId, f"Plugins revision bumped to {newRev}")

        writePluginTaskStep(taskId, "Triggering backend reload if enabled...")
        triggerBackendReloadIfEnabled()

        self.update_state(
            state="PROGRESS",
            meta={
                "step": "Completed",
                "total": total,
                "installed": installed,
                "failed": failed,
            },
        )
        writePluginTaskStep(taskId, "Completed")
        suffix = " without binaries" if skip_binaries else ""
        return f"Installed {len(installed)} plugin(s){suffix}."


@celeryApp.task(base=InstallPluginTask, bind=True, name="app.tasks.installDevelPluginTask")
def installDevelPluginTask(
    self,
    plugin_path: str,
    skip_binaries: bool = False,
    force: bool = False,
) -> str:
    taskId = str(self.request.id)

    with pluginTaskLogCapture(taskId):
        self.update_state(state="PROGRESS", meta={"step": "Preparing environment..."})
        writePluginTaskStep(taskId, "Preparing environment...")
        prepareEnvironment()

        self.update_state(state="PROGRESS", meta={"step": "Loading devel service..."})
        writePluginTaskStep(taskId, "Loading devel service...")
        from app.backend.api.services.plugin_devel_service import PluginDevelService
        service = PluginDevelService()

        self.update_state(state="PROGRESS", meta={"step": "Installing devel plugin..."})
        writePluginTaskStep(taskId, "Installing devel plugin...")
        result = service.installDevelPlugin(
            plugin_path,
            taskId=taskId,
            skipBinaries=skip_binaries,
            force=force,
        )

        self.update_state(state="PROGRESS", meta={"step": "Refreshing plugin metadata..."})
        writePluginTaskStep(taskId, "Refreshing plugin metadata...")
        newRev = bumpPluginsRevision()
        logger.warning("pluginsRevisionBumped=%s", newRev)
        logger.warning(
            "pluginsRevisionBumped=%s scipionHome=%s",
            newRev,
            os.environ.get("SCIPION_HOME"),
        )
        writePluginTaskStep(taskId, f"Plugins revision bumped to {newRev}")

        writePluginTaskStep(taskId, "Triggering backend reload if enabled...")
        triggerBackendReloadIfEnabled()

        self.update_state(state="PROGRESS", meta={"step": "Completed"})
        writePluginTaskStep(taskId, "Completed")
        return f"Devel plugin {result.get('pipName')} installed successfully from {result.get('path')}!"


@celeryApp.task(base=InstallPluginTask, bind=True, name="app.tasks.uninstallPluginTask")
def uninstallPluginTask(self, pip_name: str) -> str:
    taskId = str(self.request.id)

    with pluginTaskLogCapture(taskId):
        self.update_state(state="PROGRESS", meta={"step": "Preparing environment..."})
        writePluginTaskStep(taskId, "Preparing environment...")
        prepareEnvironment()

        self.update_state(state="PROGRESS", meta={"step": "Loading service..."})
        writePluginTaskStep(taskId, "Loading service...")
        from app.backend.api.services.plugin_service import PluginService
        service = PluginService()

        self.update_state(state="PROGRESS", meta={"step": "Uninstalling plugin..."})
        writePluginTaskStep(taskId, "Uninstalling plugin...")
        service.uninstallPlugin(pip_name, taskId=taskId)

        self.update_state(state="PROGRESS", meta={"step": "Refreshing plugin metadata..."})
        writePluginTaskStep(taskId, "Refreshing plugin metadata...")
        newRev = bumpPluginsRevision()
        logger.warning("pluginsRevisionBumped=%s", newRev)
        logger.warning(
            "pluginsRevisionBumped=%s scipionHome=%s",
            newRev,
            os.environ.get("SCIPION_HOME"),
        )
        writePluginTaskStep(taskId, f"Plugins revision bumped to {newRev}")

        writePluginTaskStep(taskId, "Triggering backend reload if enabled...")
        triggerBackendReloadIfEnabled()

        self.update_state(state="PROGRESS", meta={"step": "Completed"})
        writePluginTaskStep(taskId, "Completed")
        return f"Plugin {pip_name} uninstalled successfully!"


@celeryApp.task(bind=True, name="app.tasks.executeProtocolTask")
def executeProtocolTask(self, project_id: int, protocol_id: int, run_mode: str = "resume"):
    from app.backend.runtime.postgresql_protocol_worker import (
        RuntimePostgresqlProtocolWorker,
        normalizePostgresqlRunMode,
    )

    projectId = int(project_id)
    protocolId = int(protocol_id)
    runMode = normalizePostgresqlRunMode(run_mode)
    originalCwd = os.getcwd()
    runtimeWorker = None

    try:
        self.update_state(
            state="PROGRESS",
            meta={
                "step": "Preparing protocol runtime...",
                "projectId": projectId,
                "protocolId": protocolId,
                "runMode": runMode,
            },
        )

        prepareEnvironment()

        runtimeWorker = RuntimePostgresqlProtocolWorker(
            projectId=projectId,
            protocolId=protocolId,
            runMode=runMode,
        )

        runtimeWorker.load(
            configureLogging=False
        )

        self.update_state(
            state="PROGRESS",
            meta={
                "step": "Launching protocol...",
                "projectId": projectId,
                "protocolId": protocolId,
                "runMode": runMode,
            },
        )

        returnCode = runtimeWorker.project._startPostgresqlProtocolWorker(
            protocol=runtimeWorker.protocol,
            runMode=runMode,
            wait=True,
        )

        protocolStatus = _getProtocolStatus(runtimeWorker.mapper, projectId, protocolId)

        if protocolStatus not in PROTOCOL_TERMINAL_STATUSES:
            self.update_state(
                state="PROGRESS",
                meta={
                    "step": "Waiting for protocol completion...",
                    "projectId": projectId,
                    "protocolId": protocolId,
                    "runMode": runMode,
                    "protocolStatus": protocolStatus,
                },
            )

            protocolStatus = _waitForProtocolTerminalStatus(
                mapper=runtimeWorker.mapper,
                projectId=projectId,
                protocolId=protocolId,
                timeoutSeconds=None if returnCode == 0 else 5.0,
            )

        if protocolStatus in PROTOCOL_FAILURE_STATUSES:
            raise RuntimeError(
                "Protocol execution failed. "
                f"projectId={projectId} protocolId={protocolId}"
            )

        if protocolStatus in PROTOCOL_CANCELLED_STATUSES:
            self.update_state(
                state="CANCELLED",
                meta={
                    "step": "Cancelled",
                    "projectId": projectId,
                    "protocolId": protocolId,
                    "runMode": runMode,
                    "protocolStatus": protocolStatus,
                },
            )
            raise Ignore()

        return {
            "projectId": projectId,
            "protocolId": protocolId,
            "runMode": runMode,
            "protocolStatus": protocolStatus,
            "coordinatorReturnCode": int(returnCode),
        }

    finally:
        if runtimeWorker is not None:
            runtimeWorker.close()

        try:
            os.chdir(originalCwd)
        except Exception:
            logger.warning(
                "Could not restore Celery protocol worker cwd: %s",
                originalCwd,
                exc_info=True,
            )
