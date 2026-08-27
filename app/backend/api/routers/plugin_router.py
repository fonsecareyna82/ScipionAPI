import asyncio
import importlib
import logging
from datetime import datetime

from typing import Any, Dict, Optional, Literal, Set, List
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
from app.backend.api.services.system_task_service import SystemTaskService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plugins", tags=["Plugins"])
service = PluginService()
develService = PluginDevelService()
systemTaskService = SystemTaskService()

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
    from app.workers.task_queue import installPluginsBatchTask  # type: ignore
    _celeryInstallBatchAvailable = True
except Exception:
    installPluginsBatchTask = None  # type: ignore
    _celeryInstallBatchAvailable = False

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

try:
    from app.workers.task_queue import installPluginBinaryTask  # type: ignore
    _celeryInstallBinaryAvailable = True
except Exception:
    installPluginBinaryTask = None  # type: ignore
    _celeryInstallBinaryAvailable = False


try:
    from app.workers.task_queue import uninstallPluginBinaryTask  # type: ignore
    _celeryUninstallBinaryAvailable = True
except Exception:
    uninstallPluginBinaryTask = None  # type: ignore
    _celeryUninstallBinaryAvailable = False


_inProcessResults: Dict[str, Dict[str, Any]] = {}
_inProcessTasks: Dict[str, asyncio.Task] = {}
_refreshedTerminalTaskIds: Set[str] = set()


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


class InstallPluginsBatchRequest(BaseModel):
    plugins: List[str] = Field(..., description="Plugin pip names to install or update")
    skipBinaries: bool = Field(False, description="Skip binaries when supported by the configured Scipion installer")


class AcknowledgePluginTasksRequest(BaseModel):
    statuses: List[str] = Field(default_factory=list)


class AcknowledgePluginTasksResponse(BaseModel):
    acknowledged: int


class SystemTaskResponse(BaseModel):
    id: int
    taskId: str
    taskType: str
    operation: str
    subject: str
    subjectLabel: Optional[str] = None
    status: str
    step: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Any] = None
    meta: Optional[Any] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    backend: str
    acknowledged: bool
    retryOfTaskId: Optional[str] = None
    createdAt: datetime
    startedAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None
    updatedAt: datetime


def _isTerminalTaskStatus(status: Optional[str]) -> bool:
    return str(status or "").upper() in {"SUCCESS", "FAILURE"}


def _getStoredSystemTask(taskId: str) -> Optional[Dict[str, Any]]:
    try:
        return systemTaskService.getTask(taskId)
    except Exception:
        logger.debug(
            "Could not load persisted system task. taskId=%s",
            taskId,
            exc_info=True,
        )
        return None


def _reconcileSystemTaskFromCelery(
        systemTask: Optional[Dict[str, Any]],
        celeryTask,
) -> Optional[Dict[str, Any]]:
    if systemTask is None:
        return None

    if str(systemTask.get("backend") or "").strip().lower() != "celery":
        return systemTask

    storedStatus = str(systemTask.get("status") or "").strip().upper()

    if storedStatus in {"SUCCESS", "FAILURE", "CANCELLED"}:
        return systemTask

    celeryStatus = str(getattr(celeryTask, "status", "") or "").strip().upper()

    if not celeryStatus:
        return systemTask

    # Celery uses PENDING both for genuinely pending tasks and for task ids
    # whose result is no longer available. Never use it to regress PostgreSQL.
    if celeryStatus == "PENDING":
        return systemTask

    normalizedStatus = (
        "CANCELLED"
        if celeryStatus == "REVOKED"
        else celeryStatus
    )

    if normalizedStatus not in {
        "STARTED",
        "PROGRESS",
        "RETRY",
        "SUCCESS",
        "FAILURE",
        "CANCELLED",
    }:
        return systemTask

    try:
        meta = celeryTask.info
    except Exception:
        meta = None

    step = None

    if isinstance(meta, dict):
        step = meta.get("step")

    updateKwargs = {
        "taskId": str(systemTask["taskId"]),
        "status": normalizedStatus,
        "meta": meta,
    }

    if step:
        updateKwargs["step"] = str(step)

    if normalizedStatus == "SUCCESS":
        updateKwargs["step"] = "Completed"
        updateKwargs["result"] = getattr(celeryTask, "result", None)
        updateKwargs["error"] = None

    elif normalizedStatus == "FAILURE":
        updateKwargs["error"] = str(
            getattr(celeryTask, "result", None)
            or "Task failed"
        )

    elif normalizedStatus == "RETRY":
        retryError = getattr(celeryTask, "result", None)

        if retryError is not None:
            updateKwargs["error"] = str(retryError)

    elif normalizedStatus == "CANCELLED":
        updateKwargs["step"] = "Cancelled"
        updateKwargs["error"] = None

    try:
        updatedTask = systemTaskService.updateTask(**updateKwargs)
        return updatedTask or systemTask

    except Exception:
        logger.debug(
            "Could not reconcile persisted system task from Celery. taskId=%s celeryStatus=%s",
            systemTask.get("taskId"),
            celeryStatus,
            exc_info=True,
        )
        return systemTask


def _refreshPluginCatalogAfterTask(taskId: str, status: Optional[str]) -> None:
    if not _isTerminalTaskStatus(status):
        return

    if taskId in _refreshedTerminalTaskIds:
        return

    _refreshedTerminalTaskIds.add(taskId)

    try:
        service.clearCache()
    except Exception:
        logger.exception("Could not clear plugin catalog cache after task %s", taskId)

    try:
        importlib.invalidate_caches()
    except Exception:
        logger.debug("Could not invalidate import caches after task %s", taskId, exc_info=True)


def _startCeleryPluginSystemTask(
        celeryTask,
        args: List[Any],
        operation: str,
        subject: str,
        payload: Dict[str, Any],
        retryOfTaskId: Optional[str] = None,
) -> TaskStartResponse:
    taskId = uuid4().hex

    logPath = initializePluginTaskLog(
        taskId,
        subject,
        operation,
    )

    systemTaskService.createTask(
        taskId=taskId,
        taskType="plugin",
        operation=operation,
        subject=subject,
        backend="celery",
        status="PENDING",
        payload=payload,
        retryOfTaskId=retryOfTaskId,
        logPath=str(logPath),
    )

    try:
        celeryTask.apply_async(
            args=args,
            task_id=taskId,
        )
    except Exception as error:
        systemTaskService.updateTask(
            taskId=taskId,
            status="FAILURE",
            error=str(error),
        )
        raise

    return TaskStartResponse(
        taskId=taskId,
        status="PENDING",
        backend="celery",
    )

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

        pluginLabel = str(
            validation.get("pipName")
            or validation.get("path")
            or "devel-plugin"
        )

        if (
                _celeryAppAvailable
                and _celeryInstallDevelAvailable
                and installDevelPluginTask is not None
        ):
            taskId = uuid4().hex
            logPath = initializePluginTaskLog(
                taskId,
                pluginLabel,
                "install-devel",
            )

            systemTaskService.createTask(
                taskId=taskId,
                taskType="plugin",
                operation="install-devel",
                subject=pluginLabel,
                backend="celery",
                status="PENDING",
                payload={
                    "path": payload.path,
                    "skipBinaries": bool(payload.skipBinaries),
                    "force": bool(payload.force),
                },
                logPath=str(logPath),
            )

            try:
                installDevelPluginTask.apply_async(
                    args=[
                        payload.path,
                        payload.skipBinaries,
                        payload.force,
                    ],
                    task_id=taskId,
                )
            except Exception as error:
                systemTaskService.updateTask(
                    taskId=taskId,
                    status="FAILURE",
                    error=str(error),
                )
                raise

            return TaskStartResponse(
                taskId=taskId,
                status="PENDING",
                backend="celery",
            )

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
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


@router.get("/tasks", response_model=List[SystemTaskResponse])
def listPluginTasks(
        status: Optional[str] = None,
        includeAcknowledged: bool = False,
        limit: int = 100,
):
    tasks = systemTaskService.listTasks(
        taskType="plugin",
        status=status,
        includeAcknowledged=includeAcknowledged,
        limit=limit,
    )

    if not _celeryAppAvailable or celeryApp is None:
        return tasks

    reconciledTasks = []

    for task in tasks:
        backend = str(task.get("backend") or "").strip().lower()
        storedStatus = str(task.get("status") or "").strip().upper()

        if backend != "celery":
            reconciledTasks.append(task)
            continue

        if storedStatus in {"SUCCESS", "FAILURE", "CANCELLED"}:
            reconciledTasks.append(task)
            continue

        try:
            celeryTask = celeryApp.AsyncResult(
                str(task["taskId"])
            )

            reconciledTask = _reconcileSystemTaskFromCelery(
                systemTask=task,
                celeryTask=celeryTask,
            )

            reconciledTasks.append(
                reconciledTask or task
            )

        except Exception:
            logger.debug(
                "Could not inspect Celery task while listing plugin tasks. taskId=%s",
                task.get("taskId"),
                exc_info=True,
            )

            reconciledTasks.append(task)

    if status:
        requestedStatus = str(status).strip().upper()

        reconciledTasks = [
            task
            for task in reconciledTasks
            if str(task.get("status") or "").strip().upper() == requestedStatus
        ]

    return reconciledTasks


@router.post(
    "/tasks/acknowledge",
    response_model=AcknowledgePluginTasksResponse,
)
def acknowledgePluginTasks(
        payload: AcknowledgePluginTasksRequest,
):
    allowedStatuses = {
        "SUCCESS",
        "FAILURE",
        "CANCELLED",
    }

    statuses = []

    for status in payload.statuses:
        normalizedStatus = str(
            status or ""
        ).strip().upper()

        if (
                normalizedStatus
                and normalizedStatus not in statuses
        ):
            statuses.append(
                normalizedStatus
            )

    if not statuses:
        raise HTTPException(
            status_code=400,
            detail="At least one task status is required",
        )

    invalidStatuses = [
        status
        for status in statuses
        if status not in allowedStatuses
    ]

    if invalidStatuses:
        raise HTTPException(
            status_code=400,
            detail="Only terminal plugin task statuses can be acknowledged",
        )

    acknowledged = systemTaskService.acknowledgeTasks(
        taskType="plugin",
        statuses=statuses,
    )

    return AcknowledgePluginTasksResponse(
        acknowledged=acknowledged,
    )


@router.post(
    "/tasks/{taskId}/acknowledge",
    response_model=SystemTaskResponse,
)
def acknowledgePluginTask(taskId: str):
    task = systemTaskService.acknowledgeTask(taskId)

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    return task


@router.get("/{pluginName}", response_model=Any)
def loadPlugin(pluginName: str):
    plugin = service.getPlugin(pluginName)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return plugin


@router.post(
    "/{pluginName}/binaries/{binaryTarget}/install",
    response_model=TaskStartResponse,
)
async def installPluginBinary(
        pluginName: str,
        binaryTarget: str,
):
    try:
        payload = {
            "pluginName": pluginName,
            "binaryTarget": binaryTarget,
        }

        if (
                _celeryAppAvailable
                and _celeryInstallBinaryAvailable
                and installPluginBinaryTask is not None
        ):
            return _startCeleryPluginSystemTask(
                celeryTask=installPluginBinaryTask,
                args=[
                    pluginName,
                    binaryTarget,
                ],
                operation="install-binary",
                subject=pluginName,
                payload=payload,
            )

        return await _startInProcessTask(
            service.installPluginBinary,
            pluginName,
            "install-binary",
            binaryTarget=binaryTarget,
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )


@router.post(
    "/{pluginName}/binaries/{binaryTarget}/uninstall",
    response_model=TaskStartResponse,
)
async def uninstallPluginBinary(
        pluginName: str,
        binaryTarget: str,
):
    try:
        payload = {
            "pluginName": pluginName,
            "binaryTarget": binaryTarget,
        }

        if (
                _celeryAppAvailable
                and _celeryUninstallBinaryAvailable
                and uninstallPluginBinaryTask is not None
        ):
            return _startCeleryPluginSystemTask(
                celeryTask=uninstallPluginBinaryTask,
                args=[
                    pluginName,
                    binaryTarget,
                ],
                operation="uninstall-binary",
                subject=pluginName,
                payload=payload,
            )

        return await _startInProcessTask(
            service.uninstallPluginBinary,
            pluginName,
            "uninstall-binary",
            binaryTarget=binaryTarget,
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )


@router.post(
    "/tasks/{taskId}/retry",
    response_model=TaskStartResponse,
)
async def retryPluginTask(taskId: str):
    try:
        originalTask = systemTaskService.getTask(taskId)

        if originalTask is None:
            raise HTTPException(
                status_code=404,
                detail="Task not found",
            )

        if str(originalTask.get("taskType") or "").strip().lower() != "plugin":
            raise HTTPException(
                status_code=400,
                detail="Task is not a plugin task",
            )

        originalStatus = str(
            originalTask.get("status") or ""
        ).strip().upper()

        if originalStatus != "FAILURE":
            raise HTTPException(
                status_code=409,
                detail="Only failed plugin tasks can be retried",
            )

        operation = str(
            originalTask.get("operation") or ""
        ).strip()

        rawPayload = originalTask.get("payload")
        payload = rawPayload if isinstance(rawPayload, dict) else {}

        if operation == "install":
            pluginName = str(
                payload.get("pluginName")
                or originalTask.get("subject")
                or ""
            ).strip()

            if not pluginName:
                raise HTTPException(
                    status_code=400,
                    detail="Original install task has no plugin name",
                )

            skipBinaries = bool(
                payload.get("skipBinaries", False)
            )

            retryPayload = {
                "pluginName": pluginName,
                "skipBinaries": skipBinaries,
            }

            if (
                    _celeryAppAvailable
                    and _celeryInstallAvailable
                    and installPluginTask is not None
            ):
                return _startCeleryPluginSystemTask(
                    celeryTask=installPluginTask,
                    args=[
                        pluginName,
                        skipBinaries,
                    ],
                    operation="install",
                    subject=pluginName,
                    payload=retryPayload,
                    retryOfTaskId=taskId,
                )

            return await _startInProcessTask(
                service.installPlugin,
                pluginName,
                "install",
                retryOfTaskId=taskId,
                skipBinaries=skipBinaries,
            )

        if operation == "install-batch":
            rawPlugins = payload.get("plugins")

            if not isinstance(rawPlugins, list):
                raise HTTPException(
                    status_code=400,
                    detail="Original batch task has no plugin list",
                )

            plugins = []
            seen = set()

            for pluginName in rawPlugins:
                cleanPluginName = str(
                    pluginName or ""
                ).strip()

                if (
                        not cleanPluginName
                        or cleanPluginName in seen
                ):
                    continue

                seen.add(cleanPluginName)
                plugins.append(cleanPluginName)

            if not plugins:
                raise HTTPException(
                    status_code=400,
                    detail="Original batch task has no valid plugins",
                )

            if not (
                    _celeryAppAvailable
                    and _celeryInstallBatchAvailable
                    and installPluginsBatchTask is not None
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Batch plugin retry requires Celery",
                )

            skipBinaries = bool(
                payload.get("skipBinaries", False)
            )

            taskLabel = f"batch:{len(plugins)}"

            return _startCeleryPluginSystemTask(
                celeryTask=installPluginsBatchTask,
                args=[
                    plugins,
                    skipBinaries,
                ],
                operation="install-batch",
                subject=taskLabel,
                payload={
                    "plugins": plugins,
                    "skipBinaries": skipBinaries,
                },
                retryOfTaskId=taskId,
            )

        if operation == "install-devel":
            path = str(
                payload.get("path") or ""
            ).strip()

            if not path:
                raise HTTPException(
                    status_code=400,
                    detail="Original devel task has no plugin path",
                )

            validation = develService.validateDevelPluginPath(
                path
            )

            if not validation.get("valid"):
                raise HTTPException(
                    status_code=400,
                    detail=validation,
                )

            pluginLabel = str(
                validation.get("pipName")
                or validation.get("path")
                or originalTask.get("subject")
                or "devel-plugin"
            )

            skipBinaries = bool(
                payload.get("skipBinaries", False)
            )

            force = bool(
                payload.get("force", False)
            )

            retryPayload = {
                "path": path,
                "skipBinaries": skipBinaries,
                "force": force,
            }

            if (
                    _celeryAppAvailable
                    and _celeryInstallDevelAvailable
                    and installDevelPluginTask is not None
            ):
                return _startCeleryPluginSystemTask(
                    celeryTask=installDevelPluginTask,
                    args=[
                        path,
                        skipBinaries,
                        force,
                    ],
                    operation="install-devel",
                    subject=pluginLabel,
                    payload=retryPayload,
                    retryOfTaskId=taskId,
                )

            return await _startInProcessTask(
                develService.installDevelPlugin,
                path,
                "install-devel",
                retryOfTaskId=taskId,
                skipBinaries=skipBinaries,
                force=force,
            )
        if operation == "install-binary":
            pluginName = str(
                payload.get("pluginName")
                or originalTask.get("subject")
                or ""
            ).strip()

            binaryTarget = str(
                payload.get("binaryTarget")
                or ""
            ).strip()

            if not pluginName:
                raise HTTPException(
                    status_code=400,
                    detail="Original binary install task has no plugin name",
                )

            if not binaryTarget:
                raise HTTPException(
                    status_code=400,
                    detail="Original binary install task has no binary target",
                )

            retryPayload = {
                "pluginName": pluginName,
                "binaryTarget": binaryTarget,
            }

            if (
                    _celeryAppAvailable
                    and _celeryInstallBinaryAvailable
                    and installPluginBinaryTask is not None
            ):
                return _startCeleryPluginSystemTask(
                    celeryTask=installPluginBinaryTask,
                    args=[
                        pluginName,
                        binaryTarget,
                    ],
                    operation="install-binary",
                    subject=pluginName,
                    payload=retryPayload,
                    retryOfTaskId=taskId,
                )

            return await _startInProcessTask(
                service.installPluginBinary,
                pluginName,
                "install-binary",
                retryOfTaskId=taskId,
                binaryTarget=binaryTarget,
            )

        if operation == "uninstall-binary":
            pluginName = str(
                payload.get("pluginName")
                or originalTask.get("subject")
                or ""
            ).strip()

            binaryTarget = str(
                payload.get("binaryTarget")
                or ""
            ).strip()

            if not pluginName:
                raise HTTPException(
                    status_code=400,
                    detail="Original binary uninstall task has no plugin name",
                )

            if not binaryTarget:
                raise HTTPException(
                    status_code=400,
                    detail="Original binary uninstall task has no binary target",
                )

            retryPayload = {
                "pluginName": pluginName,
                "binaryTarget": binaryTarget,
            }

            if (
                    _celeryAppAvailable
                    and _celeryUninstallBinaryAvailable
                    and uninstallPluginBinaryTask is not None
            ):
                return _startCeleryPluginSystemTask(
                    celeryTask=uninstallPluginBinaryTask,
                    args=[
                        pluginName,
                        binaryTarget,
                    ],
                    operation="uninstall-binary",
                    subject=pluginName,
                    payload=retryPayload,
                    retryOfTaskId=taskId,
                )

            return await _startInProcessTask(
                service.uninstallPluginBinary,
                pluginName,
                "uninstall-binary",
                retryOfTaskId=taskId,
                binaryTarget=binaryTarget,
            )

        if operation == "uninstall":
            pluginName = str(
                payload.get("pluginName")
                or originalTask.get("subject")
                or ""
            ).strip()

            if not pluginName:
                raise HTTPException(
                    status_code=400,
                    detail="Original uninstall task has no plugin name",
                )

            retryPayload = {
                "pluginName": pluginName,
            }

            if (
                    _celeryAppAvailable
                    and _celeryUninstallAvailable
                    and uninstallPluginTask is not None
            ):
                return _startCeleryPluginSystemTask(
                    celeryTask=uninstallPluginTask,
                    args=[
                        pluginName,
                    ],
                    operation="uninstall",
                    subject=pluginName,
                    payload=retryPayload,
                    retryOfTaskId=taskId,
                )

            return await _startInProcessTask(
                service.uninstallPlugin,
                pluginName,
                "uninstall",
                retryOfTaskId=taskId,
            )

        raise HTTPException(
            status_code=400,
            detail=f"Unsupported plugin task operation: {operation}",
        )

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )


async def _startInProcessTask(
            taskFn,
            pluginName: str,
            operation: str,
            retryOfTaskId: Optional[str] = None,
            **taskKwargs,
    ) -> TaskStartResponse:
    taskId = uuid4().hex
    logPath = initializePluginTaskLog(taskId, pluginName, operation)

    taskPayload = {
        "pluginName": pluginName,
        **taskKwargs,
    }

    if operation == "install-devel":
        taskPayload.pop("pluginName", None)
        taskPayload["path"] = pluginName

    systemTaskService.createTask(
        taskId=taskId,
        taskType="plugin",
        operation=operation,
        subject=pluginName,
        backend="local",
        status="STARTED",
        payload=taskPayload,
        retryOfTaskId=retryOfTaskId,
        logPath=str(logPath),
    )

    loop = asyncio.get_running_loop()

    async def runner():
        try:
            writePluginTaskStep(taskId, "Starting in-process task...")
            with pluginTaskLogCapture(taskId):
                result = await loop.run_in_executor(
                    None,
                    lambda: taskFn(
                        pluginName,
                        taskId=taskId,
                        **taskKwargs,
                    ),
                )
            writePluginTaskStep(taskId, "In-process task completed.")
            _inProcessResults[taskId] = {"status": "SUCCESS", "result": result, "error": None}
            systemTaskService.updateTask(
                taskId=taskId,
                status="SUCCESS",
                step="Completed",
                result=result,
                error=None,
            )
        except Exception as e:
            logger.exception("In-process task failed.")
            appendPluginTaskLog(taskId, f"[error] {str(e)}")
            _inProcessResults[taskId] = {"status": "FAILURE", "result": None, "error": str(e)}
            systemTaskService.updateTask(
                taskId=taskId,
                status="FAILURE",
                error=str(e),
            )

    _inProcessTasks[taskId] = asyncio.create_task(runner())
    _inProcessResults[taskId] = {"status": "STARTED", "result": None, "error": None}
    return TaskStartResponse(taskId=taskId, status="STARTED", backend="local")


@router.post("/install-batch", response_model=TaskStartResponse)
async def installPluginsBatch(payload: InstallPluginsBatchRequest):
    try:
        plugins = []
        seen = set()

        for pluginName in payload.plugins:
            cleanPluginName = str(pluginName or "").strip()

            if not cleanPluginName or cleanPluginName in seen:
                continue

            seen.add(cleanPluginName)
            plugins.append(cleanPluginName)

        if not plugins:
            raise HTTPException(
                status_code=400,
                detail="No plugins selected",
            )

        if (
                _celeryAppAvailable
                and _celeryInstallBatchAvailable
                and installPluginsBatchTask is not None
        ):
            taskId = uuid4().hex
            taskLabel = f"batch:{len(plugins)}"

            logPath = initializePluginTaskLog(
                taskId,
                taskLabel,
                "install-batch",
            )

            systemTaskService.createTask(
                taskId=taskId,
                taskType="plugin",
                operation="install-batch",
                subject=taskLabel,
                backend="celery",
                status="PENDING",
                payload={
                    "plugins": plugins,
                    "skipBinaries": bool(payload.skipBinaries),
                },
                logPath=str(logPath),
            )

            try:
                installPluginsBatchTask.apply_async(
                    args=[
                        plugins,
                        payload.skipBinaries,
                    ],
                    task_id=taskId,
                )
            except Exception as error:
                systemTaskService.updateTask(
                    taskId=taskId,
                    status="FAILURE",
                    error=str(error),
                )
                raise

            return TaskStartResponse(
                taskId=taskId,
                status="PENDING",
                backend="celery",
            )

        if len(plugins) == 1:
            return await _startInProcessTask(
                service.installPlugin,
                plugins[0],
                "install",
                skipBinaries=payload.skipBinaries,
            )

        raise HTTPException(
            status_code=503,
            detail="Batch plugin install requires Celery",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


@router.post("/install/{pluginName}", response_model=TaskStartResponse)
async def installPlugin(pluginName: str, skipBinaries: bool = False):
    try:
        if _celeryAppAvailable and _celeryInstallAvailable and installPluginTask is not None:
            taskId = uuid4().hex
            logPath = initializePluginTaskLog(taskId, pluginName, "install")

            systemTaskService.createTask(
                taskId=taskId,
                taskType="plugin",
                operation="install",
                subject=pluginName,
                backend="celery",
                status="PENDING",
                payload={
                    "pluginName": pluginName,
                    "skipBinaries": bool(skipBinaries),
                },
                logPath=str(logPath),
            )

            try:
                installPluginTask.apply_async(
                    args=[pluginName, skipBinaries],
                    task_id=taskId,
                )
            except Exception as error:
                systemTaskService.updateTask(
                    taskId=taskId,
                    status="FAILURE",
                    error=str(error),
                )
                raise

            return TaskStartResponse(
                taskId=taskId,
                status="PENDING",
                backend="celery",
            )

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
        if (
                _celeryAppAvailable
                and _celeryUninstallAvailable
                and uninstallPluginTask is not None
        ):
            taskId = uuid4().hex

            logPath = initializePluginTaskLog(
                taskId,
                pluginName,
                "uninstall",
            )

            systemTaskService.createTask(
                taskId=taskId,
                taskType="plugin",
                operation="uninstall",
                subject=pluginName,
                backend="celery",
                status="PENDING",
                payload={
                    "pluginName": pluginName,
                },
                logPath=str(logPath),
            )

            try:
                uninstallPluginTask.apply_async(
                    args=[pluginName],
                    task_id=taskId,
                )
            except Exception as error:
                systemTaskService.updateTask(
                    taskId=taskId,
                    status="FAILURE",
                    error=str(error),
                )
                raise

            return TaskStartResponse(
                taskId=taskId,
                status="PENDING",
                backend="celery",
            )

        return await _startInProcessTask(
            service.uninstallPlugin,
            pluginName,
            "uninstall",
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


@router.get("/tasks/{taskId}", response_model=TaskStatusResponse)
async def getTaskStatus(taskId: str):
    storedTask = _getStoredSystemTask(taskId)

    if storedTask is not None:
        storedBackend = str(
            storedTask.get("backend") or ""
        ).strip().lower()

        storedStatus = str(
            storedTask.get("status") or ""
        ).strip().upper()

        if (
                storedBackend == "celery"
                and storedStatus in {
                    "SUCCESS",
                    "FAILURE",
                    "CANCELLED",
                }
        ):
            _refreshPluginCatalogAfterTask(
                taskId,
                storedStatus,
            )

            return TaskStatusResponse(
                taskId=taskId,
                status=storedStatus,
                backend="celery",
                result=(
                    storedTask.get("result")
                    if storedStatus == "SUCCESS"
                    else None
                ),
                error=storedTask.get("error"),
                meta=storedTask.get("meta"),
            )

    if _celeryAppAvailable and celeryApp is not None:
        task = celeryApp.AsyncResult(taskId)
        status = str(task.status or "").strip().upper()

        meta = None

        try:
            meta = task.info
        except Exception:
            meta = None

        reconciledTask = _reconcileSystemTaskFromCelery(
            systemTask=storedTask,
            celeryTask=task,
        )

        if (
                status == "PENDING"
                and reconciledTask is not None
        ):
            reconciledStatus = str(
                reconciledTask.get("status") or ""
            ).strip().upper()

            if reconciledStatus != "PENDING":
                _refreshPluginCatalogAfterTask(
                    taskId,
                    reconciledStatus,
                )

                return TaskStatusResponse(
                    taskId=taskId,
                    status=reconciledStatus,
                    backend="celery",
                    result=(
                        reconciledTask.get("result")
                        if reconciledStatus == "SUCCESS"
                        else None
                    ),
                    error=reconciledTask.get("error"),
                    meta=reconciledTask.get("meta"),
                )

        _refreshPluginCatalogAfterTask(
            taskId,
            status,
        )

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
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    status = str(
        local.get("status", "UNKNOWN")
    )

    _refreshPluginCatalogAfterTask(
        taskId,
        status,
    )

    return TaskStatusResponse(
        taskId=taskId,
        status=status,
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

    _refreshPluginCatalogAfterTask(taskId, status)

    return TaskLogResponse(
        taskId=taskId,
        backend=backend,
        offset=offset,
        nextOffset=nextOffset,
        text=text,
        completed=completed,
        status=status,
    )
