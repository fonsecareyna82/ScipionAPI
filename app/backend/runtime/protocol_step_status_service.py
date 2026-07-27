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
    ) -> Dict[str, Any]:
        """
        Update one persisted protocol step directly in PostgreSQL.

        This operation does not load a Scipion project or protocol
        and does not access project.sqlite or steps.sqlite.
        """
        statusMap = {
            "new": STATUS_NEW,
            "finished": STATUS_FINISHED,
        }

        normalizedStatus = str(
            stepStatus
            or ""
        ).strip().lower()

        if normalizedStatus not in statusMap:
            raise HTTPException(
                status_code=(
                    status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail=(
                    "Invalid step status. "
                    "Allowed values: new, finished"
                ),
            )

        targetStatus = statusMap[
            normalizedStatus
        ]

        scipionProtocolId = (
            resolveScipionProtocolIdCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )
        )

        row = mapper.updateProtocolStepStatus(
            projectId=projectId,
            protocolId=scipionProtocolId,
            stepIndex=stepIndex,
            stepStatus=targetStatus,
        )

        if not row:
            raise HTTPException(
                status_code=(
                    status.HTTP_404_NOT_FOUND
                ),
                detail=(
                    "Protocol step not found "
                    f"in PostgreSQL: {stepIndex}"
                ),
            )

        return row

