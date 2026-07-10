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
from typing import Any, Callable, Dict

from fastapi import HTTPException, status
from pyworkflow.protocol import STATUS_FINISHED, STATUS_NEW


class RuntimeProtocolStepStatusService:
    """
    Handles protocol step listing and manual step status updates.

    This keeps step/runtime-specific logic out of ProjectService while still
    using callbacks for project-specific resolution.
    """

    def listProtocolSteps(
            self,
            *,
            mapper,
            projectId: int,
            protocolId: int,
            usesPostgresqlRuntimeCallback: Callable[[], bool],
            syncPostgresqlRuntimeProtocolCallback: Callable,
            resolveScipionProtocolIdCallback: Callable,
    ):
        scipionProtocolId = resolveScipionProtocolIdCallback(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        if usesPostgresqlRuntimeCallback():
            syncPostgresqlRuntimeProtocolCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
                registerOutputs=False,
            )

        return mapper.listProtocolSteps(projectId, scipionProtocolId)

    def updateProtocolStepStatus(
            self,
            *,
            mapper,
            projectId: int,
            protocolId: int,
            stepIndex: int,
            stepStatus: str,
            resolveScipionProtocolIdCallback: Callable,
            getProtocolByRuntimeIdCallback: Callable,
    ) -> Dict[str, Any]:
        statusMap = {
            "new": STATUS_NEW,
            "finished": STATUS_FINISHED,
        }

        normalizedStatus = str(stepStatus or "").strip().lower()

        if normalizedStatus not in statusMap:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid step status. Allowed values: new, finished",
            )

        targetStatus = statusMap[normalizedStatus]

        scipionProtocolId = resolveScipionProtocolIdCallback(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol = getProtocolByRuntimeIdCallback(scipionProtocolId)

        try:
            steps = protocol.loadSteps() or []
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load protocol steps: {e}",
            )

        targetStep = self._findStepByIndex(
            steps=steps,
            stepIndex=stepIndex,
        )

        if targetStep is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Step not found: {stepIndex}",
            )

        stepObjId = self._resolveStepObjId(targetStep)

        if stepObjId is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not resolve object id for step {stepIndex}",
            )

        try:
            protocol._updateSteps(
                lambda step: step.setStatus(targetStatus),
                where="id='%s'" % stepObjId,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update Scipion step status: {e}",
            )

        row = mapper.updateProtocolStepStatus(
            projectId=projectId,
            protocolId=scipionProtocolId,
            stepIndex=stepIndex,
            stepStatus=targetStatus,
        )

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Protocol step not found in PostgreSQL: {stepIndex}",
            )

        return row

    @staticmethod
    def _findStepByIndex(
            *,
            steps,
            stepIndex: int,
    ):
        for fallbackIndex, step in enumerate(steps, start=1):
            rawIndex = getattr(step, "_index", None) or fallbackIndex

            try:
                if int(rawIndex) == int(stepIndex):
                    return step
            except Exception:
                continue

        return None

    @staticmethod
    def _resolveStepObjId(step):
        stepObjId = None

        try:
            stepObjId = step.getObjId()
        except Exception:
            stepObjId = None

        if stepObjId is not None:
            return stepObjId

        stepObjId = getattr(step, "_objId", None)

        try:
            if hasattr(stepObjId, "get"):
                stepObjId = stepObjId.get()
        except Exception:
            pass

        return stepObjId