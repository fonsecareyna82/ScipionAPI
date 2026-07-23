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


class RuntimeProtocolResetService:
    """Orchestrate reset of a protocol and its downstream subworkflow."""

    def resetProtocolSubworkflow(
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
        Reset the selected protocol and its downstream subworkflow.

        SQLite execution mirrors are reset first using Scipion's native
        behaviour. PostgreSQL outputs and references are cleaned only after
        every runtime protocol has been reset successfully.
        """
        protocol = (
            getScipionProtocolForRuntimeCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )
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
                (
                    workflowProtocolList,
                    _activeProtocolList,
                ) = currentProject._getSubworkflow(
                    protocol
                )

        except Exception as error:
            logger.exception(
                "Failed to resolve subworkflow for reset-from. "
                "projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )

            raise HTTPException(
                status_code=(
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                ),
                detail=(
                        "Failed to resolve protocol "
                        "subworkflow: %s"
                        % str(error)
                ),
            ) from error

        workflowProtocols = (
            workflowProtocolMapToProtocolsCallback(
                workflowProtocolList
            )
        )

        protocolsAfterReset = []

        for (
                protocolToReset,
                _protocolLevel,
        ) in workflowProtocolList.values():
            if protocolToReset.isSaved():
                protocolsAfterReset.append(
                    protocolToReset
                )
                continue

            runtimeProtocolId = getattr(
                protocolToReset,
                "getObjId",
                lambda: None,
            )()

            try:
                resetProtocol = (
                    currentProject.resetProtocol(
                        protocolToReset
                    )
                )

                protocolsAfterReset.append(
                    resetProtocol
                    or protocolToReset
                )

            except Exception as error:
                logger.exception(
                    "Failed to reset runtime protocol. "
                    "projectId=%s protocolId=%s",
                    projectId,
                    runtimeProtocolId,
                )

                raise HTTPException(
                    status_code=(
                        status.HTTP_500_INTERNAL_SERVER_ERROR
                    ),
                    detail={
                        "message": (
                            "Failed to reset runtime protocol"
                        ),
                        "protocolId": (
                            str(runtimeProtocolId)
                            if runtimeProtocolId
                               not in (None, "")
                            else None
                        ),
                        "error": str(error),
                    },
                ) from error

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
            "Reset runtime protocol subtree and deleted "
            "persisted PostgreSQL outputs. "
            "projectId=%s protocolId=%s "
            "cleanup=%s refCleanup=%s",
            projectId,
            protocolId,
            cleanupInfo,
            refCleanupInfo,
        )

        postgresqlSync = None

        if usingPostgresqlRuntime:
            postgresqlSync = (
                syncPostgresqlRuntimeProtocolsAfterMutationCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=protocolsAfterReset,
                    registerOutputs=False,
                    syncRelations=False,
                    authoritativeProtocolState=True,
                )
            )

        return buildProtocolMutationResultCallback(
            "Protocol subtree reset successfully",
            protocolsCount=(
                int(
                    postgresqlSync.get(
                        "protocolsCount",
                        0,
                    ) or 0
                )
                if postgresqlSync
                else len(protocolsAfterReset)
            ),
            dependenciesCount=0,
            postgresqlCleanup=cleanupInfo,
            postgresqlInputRefCleanup=(
                refCleanupInfo
            ),
            postgresqlRuntimeReset=True,
            postgresqlRuntimeSync=postgresqlSync,
        )