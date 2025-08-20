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
import logging
from celery import Celery, Task


celeryApp = Celery('scipionweb')
celeryApp.config_from_object('app.celeryconfig')

from app.backend.api.services.environment import prepareEnvironment

logger = logging.getLogger(__name__)


class InstallPluginTask(Task):
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 600
    max_retries = 3
    acks_late = True

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        self.update_state(state="RETRY", meta={"error": str(exc)})
        super().on_retry(exc, task_id, args, kwargs, einfo)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"Task {task_id} failed: {exc}")
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celeryApp.task(
    base=InstallPluginTask,
    bind=True,
    name="app.tasks.installPluginTask",
)
def installPluginTask(self, pip_name: str) -> str:
    # Step 1: Load the service
    self.update_state(state="PROGRESS", meta={"step": "loading_service"})
    from app.backend.api.services.plugin_service import PluginService
    service = PluginService()

    # Step 2: Get the plugin
    self.update_state(state="PROGRESS", meta={"step": "fetching_plugin"})
    plugins_map = service.pluginRepository.getPlugins(getPipData=True)
    plugin = plugins_map.get(pip_name)
    if plugin is None:
        raise ValueError(f"No existe plugin con pipName ‘{pip_name}’")

    # Step 3: Prepare the environment
    self.update_state(state="PROGRESS", meta={"step": "preparing_environment"})
    prepareEnvironment()

    # Step 4: Install the plugin
    self.update_state(state="PROGRESS", meta={"step": "installing_pip_module"})
    try:
        plugin.installPipModule()
    except Exception as e:
        logger.exception("Error en installPipModule")
        raise

    # Step 5: Install binaries
    self.update_state(state="PROGRESS", meta={"step": "installing_binaries"})
    try:
        plugin.installBin({"args": ["-j", 3]})
    except Exception as e:
        logger.exception("Error en installBin")
        raise
    # Final
    self.update_state(state="SUCCESS", meta={"step": "completed"})
    return f"Plugin {pip_name} installed successfully!"
