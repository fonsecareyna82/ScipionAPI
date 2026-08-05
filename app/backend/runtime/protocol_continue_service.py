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
            getPostgresqlRuntimeSubworkflowCallback: Callable,
            buildPostgresqlContinuePlanCallback: Callable,
            launchPostgresqlContinueSubworkflowCallback: Callable,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback: Callable,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback: Callable,
            buildProtocolMutationResultCallback: Callable,
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

        continuePlan = (
            buildPostgresqlContinuePlanCallback(
                mapper=mapper,
                projectId=projectId,
                workflowProtocolMap=(
                    workflowProtocolMap
                ),
            )
        )

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
                )
            )

        restartProtocols = [
            entry["protocol"]
            for entry in (
                continuePlan.get(
                    "entries"
                )
                or []
            )
            if entry.get("action")
            == "restart"
        ]

        restartOutputCleanup = None
        restartInputRefCleanup = None

        # No destructive operation occurs until
        # the complete mixed workflow has passed
        # PostgreSQL validation.
        if restartProtocols:
            restartOutputCleanup = (
                deletePersistedProtocolOutputsForRuntimeProtocolsCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=(
                        restartProtocols
                    ),
                )
            )

            if restartOutputCleanup.get(
                    "errors"
            ):
                raise HTTPException(
                    status_code=(
                        status
                        .HTTP_500_INTERNAL_SERVER_ERROR
                    ),
                    detail={
                        "message": (
                            "Failed to delete "
                            "PostgreSQL outputs for "
                            "protocols restarted by "
                            "continue-all"
                        ),
                        "errors": (
                            restartOutputCleanup
                            .get("errors")
                        ),
                    },
                )

            restartInputRefCleanup = (
                clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=(
                        restartProtocols
                    ),
                )
            )

        launchInfo = (
            launchPostgresqlContinueSubworkflowCallback(
                mapper=mapper,
                projectId=projectId,
                plan=continuePlan,
            )
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
            )
        )