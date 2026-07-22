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


class RuntimeProtocolContinueService:
    """Orchestrate continuation of a protocol subworkflow."""

    def continueProtocolSubworkflow(
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
            syncPostgresqlRuntimeProtocolsAfterMutationCallback: Callable,
            buildProtocolMutationResultCallback: Callable,
    ) -> Dict[str, Any]:
        """
        Continue the selected protocol subworkflow.

        Parent protocols and their outputs are strictly read-only:

        - No parent output is replaced or repaired.
        - No parent protocol is persisted.
        - No persisted outputs are deleted.
        - Only input Pointer attributes belonging to resumed protocols
          may be restored.
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

                # PostgreSQL currently provides the full downstream workflow.
                # There is no separate active-protocol collection yet.
                activeProtocolList = {}

            else:
                workflowProtocolList, activeProtocolList = (
                    currentProject._getSubworkflow(protocol)
                )

        except Exception as exc:
            logger.exception(
                "Failed to resolve subworkflow for continue-all. "
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

        continuedProtocolMap = (
            activeProtocolList
            or workflowProtocolList
        )

        protocolsToResume = workflowProtocolMapToProtocolsCallback(
            continuedProtocolMap
        )

        if not protocolsToResume:
            return buildProtocolMutationResultCallback(
                "No protocols to continue"
            )

        pointerRestoreInfo = None

        if usingPostgresqlRuntime:
            parentProtocolsById = {}

            workflowProtocols = workflowProtocolMapToProtocolsCallback(
                workflowProtocolList
            )

            workflowProtocolsById = {}

            for workflowProtocol in workflowProtocols:
                workflowProtocolId = getattr(
                    workflowProtocol,
                    "getObjId",
                    lambda: None,
                )()

                if workflowProtocolId in (None, ""):
                    continue

                workflowProtocolsById[
                    str(workflowProtocolId)
                ] = workflowProtocol

            for cachedProtocol in workflowProtocols:
                cachedProtocolId = getattr(
                    cachedProtocol,
                    "getObjId",
                    lambda: None,
                )()

                if cachedProtocolId is None:
                    continue

                parentProtocolsById[str(cachedProtocolId)] = (
                    cachedProtocol
                )

                try:
                    parentProtocolsById[int(cachedProtocolId)] = (
                        cachedProtocol
                    )
                except Exception:
                    pass

            pointerRestoreInfo = (
                restorePostgresqlRuntimePointersForProtocolsCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=protocolsToResume,
                    prepareOutputsForLaunch=False,
                    allowMissingParentOutputs=True,
                    parentProtocolsById=parentProtocolsById,
                )
            )

            if pointerRestoreInfo.get("errors"):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(
                        "Failed to restore PostgreSQL runtime pointers "
                        "before continue-all: %s"
                        % pointerRestoreInfo.get("errors")
                    ),
                )

            runtimeMapper = None

            try:
                runtimeMapper = (
                    currentProject.getPostgresqlRuntimeMapper()
                )
            except Exception:
                runtimeMapper = None

            for protocolToResume in protocolsToResume:
                protocolRuntimeId = getattr(
                    protocolToResume,
                    "getObjId",
                    lambda: None,
                )()

                if (
                        runtimeMapper is not None
                        and not runtimeMapper._existsInWriteFallback(
                            protocolRuntimeId
                        )
                ):
                    raise HTTPException(
                        status_code=(
                            status.HTTP_500_INTERNAL_SERVER_ERROR
                        ),
                        detail=(
                            "Protocol %s exists in PostgreSQL but not "
                            "in the SQLite execution DB."
                            % protocolRuntimeId
                        ),
                    )

        errorList = []

        try:
            currentProject._continueWorkflow(
                errorList,
                continuedProtocolMap,
            )

        except Exception as exc:
            logger.exception(
                "Failed to continue workflow subtree. "
                "projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Failed to continue protocol subtree: %s"
                    % str(exc)
                ),
            )

        if errorList:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[
                    str(error)
                    for error in errorList
                ],
            )

        postgresqlSync = None

        if usingPostgresqlRuntime:
            postgresqlSync = (
                syncPostgresqlRuntimeProtocolsAfterMutationCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=protocolsToResume,
                    registerOutputs=False,
                )
            )

        return buildProtocolMutationResultCallback(
            "Protocol subtree continued successfully",
            protocolsCount=(
                int(
                    postgresqlSync.get(
                        "protocolsCount",
                        0,
                    ) or 0
                )
                if postgresqlSync
                else len(protocolsToResume)
            ),
            dependenciesCount=0,
            postgresqlPointerRestore=pointerRestoreInfo,
            postgresqlRuntimeContinue=True,
            postgresqlRuntimeSync=postgresqlSync,
        )