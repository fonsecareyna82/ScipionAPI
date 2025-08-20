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
from concurrent.futures import ThreadPoolExecutor

import subprocess
import time
import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks
from starlette.concurrency import run_in_threadpool

from pyworkflow.project import Manager
from typing import Any
from app.backend.api.services.plugin_service import PluginService

router = APIRouter(prefix="/plugins", tags=["Plugins"])
manager = Manager()
service = PluginService()


@router.get("/", response_model=Any)
async def loadPlugins():
    return service.getPlugins()


@router.get("/{pluginName}", response_model=Any)
async def loadPlugin(pluginName: str):
    return service.getPlugin(pluginName)


@router.post("/install/{pluginName}", response_model=Any)
async def installPlugin(pluginName: str):
    loop = asyncio.get_running_loop()
    asyncio.ensure_future(
        loop.run_in_executor(None, service.installPlugin, pluginName)
    )
    return {"status": "installation_started"}


@router.post("/uninstall/{pluginName}", response_model=Any)
async def uninstallPlugin(pluginName: str):
    return service.uninstallPlugin(pluginName)


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    from app.workers.task_queue import installPluginTask
    task = installPluginTask.AsyncResult(task_id)
    return {"status": task.status, "result": task.result}
