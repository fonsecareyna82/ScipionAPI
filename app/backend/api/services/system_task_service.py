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
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.backend.database import SessionLocal
from app.backend.models.system_task_model import SystemTask


_UNSET = object()

_ACTIVE_STATUSES = {
    "PENDING",
    "STARTED",
    "PROGRESS",
    "RETRY",
}

_TERMINAL_STATUSES = {
    "SUCCESS",
    "FAILURE",
    "CANCELLED",
}


def _now():
    return datetime.now(timezone.utc)


def _jsonSafe(value):
    if value is None:
        return None

    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


class SystemTaskService:
    @staticmethod
    def _toDict(task: SystemTask) -> Dict[str, Any]:
        return {
            "id": task.id,
            "taskId": task.taskId,
            "taskType": task.taskType,
            "operation": task.operation,
            "subject": task.subject,
            "subjectLabel": task.subjectLabel,
            "status": task.status,
            "step": task.step,
            "error": task.error,
            "result": task.result,
            "meta": task.meta,
            "payload": task.payload or {},
            "backend": task.backend,
            "acknowledged": bool(task.acknowledged),
            "retryOfTaskId": task.retryOfTaskId,
            "createdAt": task.createdAt,
            "startedAt": task.startedAt,
            "finishedAt": task.finishedAt,
            "updatedAt": task.updatedAt,
        }

    def createTask(
            self,
            taskId: str,
            taskType: str,
            operation: str,
            subject: str,
            backend: str,
            status: str = "PENDING",
            subjectLabel: Optional[str] = None,
            payload: Optional[Dict[str, Any]] = None,
            retryOfTaskId: Optional[str] = None,
            logPath: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalizedStatus = str(status or "PENDING").upper()
        now = _now()

        with SessionLocal() as session:
            existing = (
                session
                .query(SystemTask)
                .filter(SystemTask.taskId == str(taskId))
                .one_or_none()
            )

            if existing is not None:
                return self._toDict(existing)

            task = SystemTask(
                taskId=str(taskId),
                taskType=str(taskType),
                operation=str(operation),
                subject=str(subject),
                subjectLabel=subjectLabel,
                status=normalizedStatus,
                payload=_jsonSafe(payload or {}),
                backend=str(backend),
                acknowledged=False,
                retryOfTaskId=retryOfTaskId,
                logPath=logPath,
                startedAt=now if normalizedStatus in _ACTIVE_STATUSES - {"PENDING"} else None,
                finishedAt=now if normalizedStatus in _TERMINAL_STATUSES else None,
                updatedAt=now,
            )

            session.add(task)
            session.commit()
            session.refresh(task)

            return self._toDict(task)

    def updateTask(
            self,
            taskId: str,
            status: Optional[str] = None,
            step: Any = _UNSET,
            error: Any = _UNSET,
            result: Any = _UNSET,
            meta: Any = _UNSET,
    ) -> Optional[Dict[str, Any]]:
        now = _now()

        with SessionLocal() as session:
            task = (
                session
                .query(SystemTask)
                .filter(SystemTask.taskId == str(taskId))
                .one_or_none()
            )

            if task is None:
                return None

            if status is not None:
                normalizedStatus = str(status).upper()
                task.status = normalizedStatus

                if normalizedStatus in _ACTIVE_STATUSES and task.startedAt is None:
                    task.startedAt = now

                if normalizedStatus in _TERMINAL_STATUSES and task.finishedAt is None:
                    task.finishedAt = now

                if normalizedStatus == "FAILURE":
                    task.acknowledged = False

            if step is not _UNSET:
                task.step = None if step is None else str(step)

            if error is not _UNSET:
                task.error = None if error is None else str(error)

            if result is not _UNSET:
                task.result = _jsonSafe(result)

            if meta is not _UNSET:
                task.meta = _jsonSafe(meta)

            task.updatedAt = now

            session.commit()
            session.refresh(task)

            return self._toDict(task)

    def getTask(self, taskId: str) -> Optional[Dict[str, Any]]:
        with SessionLocal() as session:
            task = (
                session
                .query(SystemTask)
                .filter(SystemTask.taskId == str(taskId))
                .one_or_none()
            )

            return None if task is None else self._toDict(task)

    def listTasks(
            self,
            taskType: Optional[str] = None,
            status: Optional[str] = None,
            includeAcknowledged: bool = False,
            limit: int = 100,
    ) -> List[Dict[str, Any]]:
        safeLimit = max(1, min(int(limit), 500))

        with SessionLocal() as session:
            query = session.query(SystemTask)

            if taskType:
                query = query.filter(SystemTask.taskType == str(taskType))

            if status:
                query = query.filter(SystemTask.status == str(status).upper())

            if not includeAcknowledged:
                query = query.filter(SystemTask.acknowledged.is_(False))

            tasks = (
                query
                .order_by(SystemTask.createdAt.desc(), SystemTask.id.desc())
                .limit(safeLimit)
                .all()
            )

            return [self._toDict(task) for task in tasks]

    def acknowledgeTasks(
            self,
            taskType: Optional[str] = None,
            statuses: Optional[List[str]] = None,
    ) -> int:
        normalizedStatuses = []

        if statuses is not None:
            for status in statuses:
                normalizedStatus = str(status or "").strip().upper()

                if (
                        normalizedStatus
                        and normalizedStatus not in normalizedStatuses
                ):
                    normalizedStatuses.append(normalizedStatus)

            if not normalizedStatuses:
                return 0

        with SessionLocal() as session:
            query = (
                session
                .query(SystemTask)
                .filter(SystemTask.acknowledged.is_(False))
            )

            if taskType:
                query = query.filter(
                    SystemTask.taskType == str(taskType)
                )

            if normalizedStatuses:
                query = query.filter(
                    SystemTask.status.in_(normalizedStatuses)
                )

            updatedCount = query.update(
                {
                    SystemTask.acknowledged: True,
                    SystemTask.updatedAt: _now(),
                },
                synchronize_session=False,
            )

            session.commit()

            return int(updatedCount or 0)

    def acknowledgeTask(self, taskId: str) -> Optional[Dict[str, Any]]:
        with SessionLocal() as session:
            task = (
                session
                .query(SystemTask)
                .filter(SystemTask.taskId == str(taskId))
                .one_or_none()
            )

            if task is None:
                return None

            task.acknowledged = True
            task.updatedAt = _now()

            session.commit()
            session.refresh(task)

            return self._toDict(task)
