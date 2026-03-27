import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# loadDotEnvFromRepoRoot
repoRoot = Path(__file__).resolve().parents[2]  # ScipionAPI/
dotEnvPath = (repoRoot / "scipion_home" / ".env").resolve()
load_dotenv(dotEnvPath, override=False)

from celery import Celery, Task

from app.backend.api.services.environment import prepareEnvironment
from app.backend.api.services.plugin_task_log import (
    appendPluginTaskLog,
    pluginTaskLogCapture,
    writePluginTaskStep,
)
from app.backend.api.services.plugins_revision import bumpPluginsRevision
from app.backend.api.services.reload_trigger import triggerBackendReloadIfEnabled

celeryApp = Celery("scipionweb")
celeryApp.config_from_object("app.workers.celeryconfig")
logger = logging.getLogger(__name__)

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


class InstallPluginTask(Task):
    acks_late = True

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logger.warning("Task %s retrying: %s", task_id, exc)
        appendPluginTaskLog(str(task_id), ansi(f"[retry] {str(exc)}", ANSI_YELLOW, bold=True))
        super().on_retry(exc, task_id, args, kwargs, einfo)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Task %s failed: %s", task_id, exc)
        appendPluginTaskLog(str(task_id), ansi(f"[failure] {str(exc)}", ANSI_RED, bold=True))
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_success(self, retval, task_id, args, kwargs):
        appendPluginTaskLog(
            str(task_id),
            ansi("[success] Task completed successfully", ANSI_GREEN, bold=True),
        )
        super().on_success(retval, task_id, args, kwargs)


@celeryApp.task(base=InstallPluginTask, bind=True, name="app.tasks.installPluginTask")
def installPluginTask(self, pip_name: str) -> str:
    taskId = str(self.request.id)

    with pluginTaskLogCapture(taskId):
        self.update_state(state="PROGRESS", meta={"step": "Preparing environment..."})
        writePluginTaskStep(taskId, "Preparing environment...")
        prepareEnvironment()

        self.update_state(state="PROGRESS", meta={"step": "Loading service..."})
        writePluginTaskStep(taskId, "Loading service...")
        from app.backend.api.services.plugin_service import PluginService
        service = PluginService()

        self.update_state(state="PROGRESS", meta={"step": "Installing plugin..."})
        writePluginTaskStep(taskId, "Installing plugin...")
        service.installPlugin(pip_name, taskId=taskId)

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
        return f"Plugin {pip_name} installed successfully!"


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