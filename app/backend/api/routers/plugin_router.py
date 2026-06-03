import asyncio
import logging
from typing import Any, Dict, Optional, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.backend.api.services.plugin_devel_service import PluginDevelService
from app.backend.api.services.plugin_service import PluginService
from app.backend.api.services.plugin_task_log import (
    appendPluginTaskLog,
    initializePluginTaskLog,
    pluginTaskLogCapture,
    readPluginTaskLog,
    writePluginTaskStep,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plugins", tags=["Plugins"])
service = PluginService()
develService = PluginDevelService()

try:
    from app.workers.task_queue import celeryApp  # type: ignore
    _celeryAppAvailable = True
except Exception:
    celeryApp = None  # type: ignore
    _celeryAppAvailable = False

try:
    from app.workers.task_queue import installPluginTask  # type: ignore
    _celeryInstallAvailable = True
except Exception:
    installPluginTask = None  # type: ignore
    _celeryInstallAvailable = False

try:
    from app.workers.task_queue import installDevelPluginTask  # type: ignore
    _celeryInstallDevelAvailable = True
except Exception:
    installDevelPluginTask = None  # type: ignore
    _celeryInstallDevelAvailable = False


try:
    from app.workers.task_queue import uninstallPluginTask  # type: ignore
    _celeryUninstallAvailable = True
except Exception:
    uninstallPluginTask = None  # type: ignore
    _celeryUninstallAvailable = False


_inProcessResults: Dict[str, Dict[str, Any]] = {}
_inProcessTasks: Dict[str, asyncio.Task] = {}


class TaskStartResponse(BaseModel):
    taskId: str = Field(..., description="Task identifier")
    status: str = Field(..., description="Initial task status")
    backend: Literal["celery", "local"] = Field(..., description="Task execution backend")


class TaskStatusResponse(BaseModel):
    taskId: str
    status: str
    backend: Literal["celery", "local"]
    result: Optional[Any] = None
    error: Optional[str] = None
    meta: Optional[Any] = None


class TaskLogResponse(BaseModel):
    taskId: str
    backend: Literal["celery", "local"]
    offset: int
    nextOffset: int
    text: str
    completed: bool
    status: Optional[str] = None


class DevelPluginPathRequest(BaseModel):
    path: str = Field(..., description="Local path to a Scipion plugin source directory")


class InstallDevelPluginRequest(BaseModel):
    path: str = Field(..., description="Local path to a Scipion plugin source directory")
    skipBinaries: bool = Field(False, description="Skip binaries when supported by the configured Scipion installer")
    force: bool = Field(False, description="Force reinstall when supported by the configured Scipion installer")


@router.get("/", response_model=Any)
def loadPlugins():
    return service.getPlugins()


@router.post("/devel/validate", response_model=Any)
def validateDevelPluginPath(payload: DevelPluginPathRequest):
    try:
        return develService.validateDevelPluginPath(payload.path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devel", response_model=Any)
def listDevelPlugins():
    try:
        return develService.listDevelPlugins()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devel/browser/paths", response_model=Any)
def getDevelPluginBrowserPaths():
    try:
        return develService.getDevelPluginBrowserPaths()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devel/browser/list", response_model=Any)
def listDevelPluginBrowserDirectory(path: str = Query("", description="Relative path inside the devel plugin browser root")):
    try:
        return develService.listDevelPluginBrowserDirectory(path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NotADirectoryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/devel/install", response_model=TaskStartResponse)
async def installDevelPlugin(payload: InstallDevelPluginRequest):
    try:
        validation = develService.validateDevelPluginPath(payload.path)
        if not validation.get("valid"):
            raise HTTPException(status_code=400, detail=validation)

        pluginLabel = str(validation.get("pipName") or validation.get("path") or "devel-plugin")

        if _celeryAppAvailable and _celeryInstallDevelAvailable and installDevelPluginTask is not None:
            taskId = uuid4().hex
            initializePluginTaskLog(taskId, pluginLabel, "install-devel")
            installDevelPluginTask.apply_async(
                args=[payload.path, payload.skipBinaries, payload.force],
                task_id=taskId,
            )
            return TaskStartResponse(taskId=taskId, status="PENDING", backend="celery")

        return await _startInProcessTask(
            develService.installDevelPlugin,
            payload.path,
            "install-devel",
            skipBinaries=payload.skipBinaries,
            force=payload.force,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pluginName}", response_model=Any)
def loadPlugin(pluginName: str):
    plugin = service.getPlugin(pluginName)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return plugin


async def _startInProcessTask(taskFn, pluginName: str, operation: str, **taskKwargs) -> TaskStartResponse:
    taskId = uuid4().hex
    initializePluginTaskLog(taskId, pluginName, operation)
    loop = asyncio.get_running_loop()

    async def runner():
        try:
            writePluginTaskStep(taskId, "Starting in-process task...")
            with pluginTaskLogCapture(taskId):
                result = await loop.run_in_executor(None, lambda: taskFn(pluginName, taskId, **taskKwargs))
            writePluginTaskStep(taskId, "In-process task completed.")
            _inProcessResults[taskId] = {"status": "SUCCESS", "result": result, "error": None}
        except Exception as e:
            logger.exception("In-process task failed.")
            appendPluginTaskLog(taskId, f"[error] {str(e)}")
            _inProcessResults[taskId] = {"status": "FAILURE", "result": None, "error": str(e)}

    _inProcessTasks[taskId] = asyncio.create_task(runner())
    _inProcessResults[taskId] = {"status": "STARTED", "result": None, "error": None}
    return TaskStartResponse(taskId=taskId, status="STARTED", backend="local")


@router.post("/install/{pluginName}", response_model=TaskStartResponse)
async def installPlugin(pluginName: str, skipBinaries: bool = False):
    try:
        if _celeryAppAvailable and _celeryInstallAvailable and installPluginTask is not None:
            taskId = uuid4().hex
            initializePluginTaskLog(taskId, pluginName, "install")
            installPluginTask.apply_async(args=[pluginName, skipBinaries], task_id=taskId)
            return TaskStartResponse(taskId=taskId, status="PENDING", backend="celery")

        return await _startInProcessTask(
            service.installPlugin,
            pluginName,
            "install",
            skipBinaries=skipBinaries,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/uninstall/{pluginName}", response_model=TaskStartResponse)
async def uninstallPlugin(pluginName: str):
    try:
        if _celeryAppAvailable and _celeryUninstallAvailable and uninstallPluginTask is not None:
            taskId = uuid4().hex
            initializePluginTaskLog(taskId, pluginName, "uninstall")
            uninstallPluginTask.apply_async(args=[pluginName], task_id=taskId)
            return TaskStartResponse(taskId=taskId, status="PENDING", backend="celery")

        return await _startInProcessTask(service.uninstallPlugin, pluginName, "uninstall")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{taskId}", response_model=TaskStatusResponse)
async def getTaskStatus(taskId: str):
    if _celeryAppAvailable and celeryApp is not None:
        task = celeryApp.AsyncResult(taskId)
        status = task.status

        meta = None
        try:
            meta = task.info
        except Exception:
            meta = None

        if status in ("SUCCESS", "FAILURE"):
            service.clearCache()
            try:
                import importlib
                importlib.invalidate_caches()
            except Exception:
                pass

        if status == "SUCCESS":
            return TaskStatusResponse(
                taskId=taskId,
                status=status,
                backend="celery",
                result=task.result,
                error=None,
                meta=meta,
            )
        if status == "FAILURE":
            return TaskStatusResponse(
                taskId=taskId,
                status=status,
                backend="celery",
                result=None,
                error=str(task.result),
                meta=meta,
            )

        return TaskStatusResponse(
            taskId=taskId,
            status=status,
            backend="celery",
            result=None,
            error=None,
            meta=meta,
        )

    local = _inProcessResults.get(taskId)
    if local is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatusResponse(
        taskId=taskId,
        status=str(local.get("status", "UNKNOWN")),
        backend="local",
        result=local.get("result"),
        error=local.get("error"),
        meta=None,
    )


@router.get("/tasks/{taskId}/log", response_model=TaskLogResponse)
async def getTaskLog(taskId: str, offset: int = 0, limit: int = 65536):
    text, nextOffset = readPluginTaskLog(taskId, offset=offset, limit=limit)

    status: Optional[str] = None
    completed = False
    backend: Literal["celery", "local"] = "local"

    if _celeryAppAvailable and celeryApp is not None:
        task = celeryApp.AsyncResult(taskId)
        status = str(task.status)
        completed = status in ("SUCCESS", "FAILURE")
        backend = "celery"
    else:
        local = _inProcessResults.get(taskId)
        if local is not None:
            status = str(local.get("status", "UNKNOWN"))
            completed = status in ("SUCCESS", "FAILURE")
            backend = "local"

    return TaskLogResponse(
        taskId=taskId,
        backend=backend,
        offset=offset,
        nextOffset=nextOffset,
        text=text,
        completed=completed,
        status=status,
    )
