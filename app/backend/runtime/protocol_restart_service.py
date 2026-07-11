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


logger = logging.getLogger(__name__)


class RuntimeProtocolRestartService:
    """Orchestrate a protocol-subworkflow restart."""

    def restartProtocolSubworkflow(
            self,
            *,
            mapper,
            projectId: int,
            protocolId,
            usingPostgresqlRuntime: bool,
            currentProject,
            getScipionProtocolForRuntimeCallback: Callable,
            getPostgresqlRuntimeSubworkflowCallback: Callable,
            workflowProtocolMapToProtocolsCallback: Callable,
            restorePostgresqlRuntimePointersForProtocolsCallback: Callable,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback: Callable,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback: Callable,
            syncPostgresqlRuntimeProtocolsAfterMutationCallback: Callable,
            buildProtocolMutationResultCallback: Callable,
    ) -> Dict[str, Any]:
        """
        Restart the selected protocol and its downstream subworkflow.

        Protocols that belong to the restarted subtree may have their persisted
        outputs deleted because they will be executed again from scratch.

        Upstream parent protocols that only provide inputs to this subtree are
        strictly read-only. Pointer restoration must never persist, replace or
        modify those parent protocols or their outputs.
        """
        protocol = getScipionProtocolForRuntimeCallback(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        try:
            if usingPostgresqlRuntime:
                workflowProtocolList = (
                    getPostgresqlRuntimeSubworkflowCallback(
                        mapper=mapper,
                        projectId=projectId,
                        protocolId=protocolId,
                    )
                )
            else:
                workflowProtocolList, _activeProtocolList = (
                    currentProject._getSubworkflow(protocol)
                )

        except Exception as exc:
            logger.exception(
                "Failed to resolve subworkflow for restart-all. "
                "projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Failed to resolve protocol subworkflow: %s"
                    % str(exc)
                ),
            )

        workflowProtocols = workflowProtocolMapToProtocolsCallback(
            workflowProtocolList
        )

        pointerRestoreInfo = None

        if usingPostgresqlRuntime:
            pointerRestoreInfo = (
                restorePostgresqlRuntimePointersForProtocolsCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=workflowProtocols,
                    prepareOutputsForLaunch=True,
                    allowMissingParentOutputs=True,
                )
            )

            if pointerRestoreInfo.get("errors"):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(
                        "Failed to restore PostgreSQL runtime pointers "
                        "before restart-all: %s"
                        % pointerRestoreInfo.get("errors")
                    ),
                )

        # Only outputs owned by protocols inside the restarted subtree
        # are removed. External input-parent protocols are not included.
        cleanupInfo = (
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback(
                mapper=mapper,
                projectId=projectId,
                protocols=workflowProtocols,
            )
        )

        refCleanupInfo = None

        if usingPostgresqlRuntime:
            refCleanupInfo = (
                clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=workflowProtocols,
                )
            )

        logger.info(
            "Deleted persisted protocol outputs before restart-all. "
            "projectId=%s protocolId=%s cleanup=%s refCleanup=%s",
            projectId,
            protocolId,
            cleanupInfo,
            refCleanupInfo,
        )

        errorList = []

        try:
            currentProject._restartWorkflow(
                errorList,
                workflowProtocolList,
            )

        except Exception as exc:
            logger.exception(
                "Failed to restart workflow subtree. "
                "projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Failed to restart protocol subtree: %s"
                    % str(exc)
                ),
            )

        if errorList:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[str(error) for error in errorList],
            )

        postgresqlSync = None

        if usingPostgresqlRuntime:
            postgresqlSync = (
                syncPostgresqlRuntimeProtocolsAfterMutationCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=workflowProtocols,
                    registerOutputs=False,
                )
            )

        return buildProtocolMutationResultCallback(
            "Protocol subtree restarted successfully",
            protocolsCount=(
                int(postgresqlSync.get("protocolsCount", 0) or 0)
                if postgresqlSync
                else len(workflowProtocols or [])
            ),
            dependenciesCount=0,
            postgresqlCleanup=cleanupInfo,
            postgresqlInputRefCleanup=refCleanupInfo,
            postgresqlPointerRestore=pointerRestoreInfo,
            postgresqlRuntimeRestart=True,
            postgresqlRuntimeSync=postgresqlSync,
        )