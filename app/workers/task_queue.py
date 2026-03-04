import logging
import sys
from contextlib import contextmanager

from celery import Celery, Task

celeryApp = Celery("scipionweb")
celeryApp.config_from_object("app.workers.celeryconfig")

from app.backend.api.services.environment import prepareEnvironment

logger = logging.getLogger(__name__)


@contextmanager
def restoreStdStreams():
    # restoreStdStreams
    oldStdout, oldStderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
    try:
        yield
    finally:
        sys.stdout, sys.stderr = oldStdout, oldStderr


class InstallPluginTask(Task):
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 600
    max_retries = 3
    acks_late = True

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        # logRetryOnly
        logger.warning("Task %s retrying: %s", task_id, exc)
        super().on_retry(exc, task_id, args, kwargs, einfo)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        # logFailureOnly
        logger.error("Task %s failed: %s", task_id, exc)
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celeryApp.task(base=InstallPluginTask, bind=True, name="app.tasks.installPluginTask")
def installPluginTask(self, pip_name: str) -> str:
    self.update_state(state="PROGRESS", meta={"step": "Loading service..."})
    from app.backend.api.services.plugin_service import PluginService
    service = PluginService()

    self.update_state(state="PROGRESS", meta={"step": "Fetching plugin..."})
    plugins_map = service.pluginRepository.getPlugins(getPipData=True)
    plugin = plugins_map.get(pip_name)
    if plugin is None:
        raise ValueError(f"No plugin found for pipName '{pip_name}'")

    self.update_state(state="PROGRESS", meta={"step": "Preparing environment..."})
    try:
        prepareEnvironment()
    except SystemExit as e:
        raise RuntimeError(str(e)) from e

    self.update_state(state="PROGRESS", meta={"step": "Installing pip module..."})
    try:
        with restoreStdStreams():
            plugin.installPipModule()
    except Exception:
        logger.exception("Error in installPipModule")
        raise

    self.update_state(state="PROGRESS", meta={"step": "Installing binaries..."})
    try:
        with restoreStdStreams():
            plugin.installBin({"args": ["-j", "3"]})
    except Exception:
        logger.exception("Error in installBin")
        raise

    self.update_state(state="PROGRESS", meta={"step": "Completed"})
    return f"Plugin {pip_name} installed successfully!"


@celeryApp.task(base=InstallPluginTask, bind=True, name="app.tasks.uninstallPluginTask")
def uninstallPluginTask(self, pip_name: str) -> str:
    self.update_state(state="PROGRESS", meta={"step": "Loading service..."})
    from app.backend.api.services.plugin_service import PluginService
    service = PluginService()

    self.update_state(state="PROGRESS", meta={"step": "Preparing environment..."})
    try:
        prepareEnvironment()
    except SystemExit as e:
        raise RuntimeError(str(e)) from e

    self.update_state(state="PROGRESS", meta={"step": "Uninstalling plugin..."})
    try:
        with restoreStdStreams():
            service.uninstallPlugin(pip_name)
    except Exception:
        logger.exception("Error uninstalling plugin")
        raise

    self.update_state(state="PROGRESS", meta={"step": "Completed."})
    return f"Plugin {pip_name} uninstalled successfully!"