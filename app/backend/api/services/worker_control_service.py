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

from typing import Any, Dict, Optional

from scipionapi_cli.runtime import (
    adoptWorkerProcess,
    getWorkerProcessState,
    restartWorkerProcess,
    startWorkerProcess,
    stopWorkerProcess,
)


class WorkerControlService:
    VALID_WORKERS = {
        "plugins",
        "protocols",
    }

    VALID_ACTIONS = {
        "start",
        "stop",
        "restart",
    }

    def _getCeleryWorkerPid(
            self,
            workerKind: str,
    ) -> Optional[int]:
        from app.workers.task_queue import celeryApp

        inspector = celeryApp.control.inspect(
            timeout=1.0
        )

        stats = inspector.stats() or {}

        hostname = socket.gethostname()
        expectedName = (
            f"{workerKind}@{hostname}"
        )

        workerStats = stats.get(
            expectedName
        ) or {}

        try:
            pid = int(
                workerStats.get("pid")
            )
        except (
                TypeError,
                ValueError,
        ):
            return None

        return pid if pid > 0 else None

    def _adoptWorkerIfNeeded(
            self,
            workerKind: str,
    ) -> None:
        state = getWorkerProcessState(
            workerKind
        )

        if state.get("state") == "running":
            return

        pid = self._getCeleryWorkerPid(
            workerKind
        )

        if pid is None:
            return

        adoptWorkerProcess(
            workerKind,
            pid,
        )

    def control(
        self,
        workerKind: str,
        action: str,
    ) -> Dict[str, Any]:
        kind = str(
            workerKind or ""
        ).strip().lower()

        normalizedAction = str(
            action or ""
        ).strip().lower()

        if kind not in self.VALID_WORKERS:
            raise ValueError(
                f"Unsupported worker: {workerKind}"
            )

        if normalizedAction not in self.VALID_ACTIONS:
            raise ValueError(
                f"Unsupported worker action: {action}"
            )

        self._adoptWorkerIfNeeded(
            kind
        )

        if normalizedAction == "start":
            return startWorkerProcess(
                kind
            )

        if normalizedAction == "stop":
            return stopWorkerProcess(
                kind
            )

        return restartWorkerProcess(
            kind
        )

    def getState(
        self,
        workerKind: str,
    ) -> Dict[str, Any]:
        return getWorkerProcessState(
            workerKind
        )