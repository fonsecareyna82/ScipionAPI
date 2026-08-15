import logging
from typing import Any, Callable, Dict

from fastapi import HTTPException, status

from app.backend.runtime.protocol_status_sync_service import RuntimeProtocolStatusSyncService


logger = logging.getLogger(__name__)


class RuntimeProtocolContinueService:
    """Orchestrate continuation of a protocol subworkflow."""

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

    def continueProtocolSubworkflow(
            self,
            *,
            mapper,
            projectId: int,
            protocolId,
            getPostgresqlRuntimeSubworkflowCallback: Callable,
            buildPostgresqlContinuePlanCallback: Callable,
            launchPostgresqlContinueSubworkflowCallback: Callable,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback: Callable,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback: Callable,
            buildProtocolMutationResultCallback: Callable,
            stopPostgresqlProtocolsCallback: Callable,
    ) -> Dict[str, Any]:
        """
        Continue the selected downstream workflow.

        PostgreSQL runtime guarantees:

        - Existing parent protocols are read-only.
        - Existing parent outputs are read-only.
        - Streaming protocols are resumed from PostgreSQL steps and outputs.
        - Non-streaming or SAVED protocols are restarted.
        - Outputs are deleted only for protocols classified as restart.
        - project.sqlite, run.db and steps.sqlite are not used.
        """
        try:
            workflowProtocolMap = (
                getPostgresqlRuntimeSubworkflowCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                )
            )

        except Exception as error:
            logger.exception(
                "Failed to resolve subworkflow for "
                "continue-all. projectId=%s "
                "protocolId=%s",
                projectId,
                protocolId,
            )

            raise HTTPException(
                status_code=(
                    status
                    .HTTP_500_INTERNAL_SERVER_ERROR
                ),
                detail=(
                    "Failed to resolve protocol "
                    "subworkflow: %s"
                    % error
                ),
            )

        activeProtocolIds = self._getActiveProtocolIds(workflowProtocolMap)
        stopInfo = None
        stoppedProtocolIds = []

        if activeProtocolIds:
            stopInfo = stopPostgresqlProtocolsCallback(mapper=mapper, projectId=projectId,
                                                       protocolIds=activeProtocolIds)
            stopErrors = list((stopInfo or {}).get("errors") or [])

            if stopErrors:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=stopErrors)

            stoppedProtocolIds = [str(item.get("protocolId")) for item in ((stopInfo or {}).get("stopped") or []) if
                                  item.get("protocolId") not in (None, "")]
            workflowProtocolMap = getPostgresqlRuntimeSubworkflowCallback(mapper=mapper, projectId=projectId,
                                                                          protocolId=protocolId)

        continuePlan = buildPostgresqlContinuePlanCallback(mapper=mapper,
                                                           projectId=projectId,
                                                           workflowProtocolMap=workflowProtocolMap,
                                                           forceRestartProtocolIds=stoppedProtocolIds)

        if continuePlan.get("errors"):
            raise HTTPException(
                status_code=(
                    status
                    .HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail=continuePlan[
                    "errors"
                ],
            )

        planSummary = (
            continuePlan.get(
                "summary"
            )
            or {}
        )

        actionableCount = int(
            planSummary.get(
                "actionableCount",
                0,
            )
            or 0
        )

        if actionableCount == 0:
            return (
                buildProtocolMutationResultCallback(
                    "No protocols require continuation",
                    protocolsCount=int(
                        planSummary.get(
                            "protocolsCount",
                            0,
                        )
                        or 0
                    ),
                    dependenciesCount=0,
                    postgresqlContinuePlan=(
                        planSummary
                    ),
                    postgresqlRuntimeContinue=True,
                    postgresqlStop=stopInfo,
                )
            )

        launchInfo = launchPostgresqlContinueSubworkflowCallback(
            mapper=mapper,
            projectId=projectId,
            plan=continuePlan,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback=deletePersistedProtocolOutputsForRuntimeProtocolsCallback,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback,
        )

        if launchInfo.get("errors"):
            raise HTTPException(
                status_code=(
                    status
                    .HTTP_500_INTERNAL_SERVER_ERROR
                ),
                detail=launchInfo[
                    "errors"
                ],
            )

        restartOutputCleanup = launchInfo.get("restartOutputCleanup")
        restartInputRefCleanup = launchInfo.get("restartInputRefCleanup")

        return (
            buildProtocolMutationResultCallback(
                "Protocol subtree continued successfully",
                protocolsCount=int(
                    launchInfo.get(
                        "protocolsCount",
                        0,
                    )
                    or 0
                ),
                dependenciesCount=0,
                postgresqlContinuePlan=(
                    planSummary
                ),
                postgresqlRestartOutputCleanup=(
                    restartOutputCleanup
                ),
                postgresqlRestartInputRefCleanup=(
                    restartInputRefCleanup
                ),
                postgresqlWorkerLaunch=(
                    launchInfo
                ),
                postgresqlRuntimeContinue=True,
                postgresqlStop=stopInfo,
            )
        )