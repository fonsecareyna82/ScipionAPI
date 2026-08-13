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
from typing import Any, Callable, Dict

from fastapi import HTTPException, status
from app.backend.runtime.protocol_status_sync_service import RuntimeProtocolStatusSyncService

logger = logging.getLogger(__name__)


class RuntimeProtocolRestartService:
    """Orchestrate a protocol-subworkflow restart."""

    @staticmethod
    def _getActiveProtocolIds(workflowProtocolMap):
        activeProtocolIds = []
        values = workflowProtocolMap.values() if isinstance(workflowProtocolMap, dict) else workflowProtocolMap or []

        for value in values:
            protocol = value[0] if isinstance(value, (tuple, list)) and value else value

            if protocol is None:
                continue

            protocolStatus = str(protocol.getStatus() or "").strip().lower()

            if protocolStatus in RuntimeProtocolStatusSyncService.ACTIVE_STATUS_TEXTS:
                activeProtocolIds.append(str(protocol.getObjId()))

        return activeProtocolIds

    def restartProtocolSubworkflow(
            self,
            *,
            mapper,
            projectId: int,
            protocolId,
            getPostgresqlRuntimeSubworkflowCallback: Callable,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback: Callable,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback: Callable,
            validatePostgresqlRestartSubworkflowCallback: Callable,
            launchPostgresqlRestartSubworkflowCallback: Callable,
            buildProtocolMutationResultCallback: Callable,
            stopPostgresqlProtocolsCallback: Callable,
    ) -> Dict[str, Any]:
        try:
            workflowProtocolMap = getPostgresqlRuntimeSubworkflowCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

        except Exception as error:
            logger.exception(
                "Failed to resolve subworkflow for "
                "restart-all. projectId=%s "
                "protocolId=%s",
                projectId,
                protocolId,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to resolve protocol subworkflow: %s" % error,
            )

        validationInfo = validatePostgresqlRestartSubworkflowCallback(
            mapper=mapper,
            projectId=projectId,
            workflowProtocolMap=workflowProtocolMap,
        )

        activeProtocolIds = self._getActiveProtocolIds(workflowProtocolMap)
        stopInfo = None

        if activeProtocolIds:
            stopInfo = stopPostgresqlProtocolsCallback(mapper=mapper, projectId=projectId,
                                                       protocolIds=activeProtocolIds)
            stopErrors = list((stopInfo or {}).get("errors") or [])

            if stopErrors:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=stopErrors)

            workflowProtocolMap = getPostgresqlRuntimeSubworkflowCallback(mapper=mapper, projectId=projectId,
                                                                          protocolId=protocolId)

        validationInfo = validatePostgresqlRestartSubworkflowCallback(mapper=mapper, projectId=projectId,
                                                                      workflowProtocolMap=workflowProtocolMap)

        if validationInfo.get("errors"):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=validationInfo["errors"])

        launchInfo = launchPostgresqlRestartSubworkflowCallback(
            mapper=mapper,
            projectId=projectId,
            workflowProtocolMap=workflowProtocolMap,
            validationInfo=validationInfo,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback=deletePersistedProtocolOutputsForRuntimeProtocolsCallback,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback,
        )

        if launchInfo.get("errors"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=launchInfo["errors"],
            )

        cleanupInfo = launchInfo.get("outputCleanup")
        refCleanupInfo = launchInfo.get("inputRefCleanup")

        return buildProtocolMutationResultCallback(
            "Protocol subtree restarted successfully",
            protocolsCount=int(launchInfo.get("protocolsCount", 0) or 0),
            dependenciesCount=0,
            postgresqlCleanup=cleanupInfo,
            postgresqlInputRefCleanup=refCleanupInfo,
            postgresqlInputValidation=validationInfo,
            postgresqlWorkerLaunch=launchInfo,
            postgresqlRuntimeRestart=True,
            postgresqlStop=stopInfo,
        )