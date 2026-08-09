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
import subprocess
from typing import Any, Dict

from pyworkflow.protocol import (
    MODE_RESUME,
    STATUS_SAVED,
    STATUS_SCHEDULED,
)

from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)
from app.backend.runtime.protocol_identity import (
    ProtocolIdentityResolver,
)
from app.backend.runtime.protocol_postgresql_restart_launcher_service import (
    RuntimePostgresqlRestartLauncherService,
)
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)


CONTINUE_ACTION_RESTART = "restart"
CONTINUE_ACTION_RESUME = "resume"
CONTINUE_ACTION_SKIP = "skip"
CONTINUE_ACTION_ERROR = "error"


class RuntimePostgresqlContinueLauncherService:
    def __init__(self):
        self.restartLauncher = (
            RuntimePostgresqlRestartLauncherService()
        )

    def buildContinuePlan(
            self,
            *,
            mapper,
            projectId: int,
            workflowProtocolMap,
            currentProject,
    ) -> Dict[str, Any]:
        runtimeMapper = currentProject.getPostgresqlRuntimeMapper() if currentProject is not None else None

        if runtimeMapper is None:
            return {
                "entries": [],
                "errors": [{
                    "error": "PostgreSQL runtime mapper is not available",
                }],
                "summary": {
                    "protocolsCount": 0,
                    "actionableCount": 0,
                    "restartProtocolIds": [],
                    "resumeProtocolIds": [],
                    "skipped": [],
                    "parentProtocolsModified": False,
                },
            }

        items = (
            self.restartLauncher
            ._workflowItems(
                workflowProtocolMap
            )
        )

        identityResolver = (
            ProtocolIdentityResolver(
                mapper=mapper,
                projectId=projectId,
            )
        )

        graphRepository = (
            ProtocolGraphRepository()
        )

        entries = []
        errors = []
        internalProtocolDbIds = set()

        for protocol, level in items:
            protocolId = getattr(
                protocol,
                "getObjId",
                lambda: None,
            )()

            if protocolId in (
                    None,
                    "",
            ):
                errors.append({
                    "protocolId": None,
                    "error": (
                        "Protocol without runtime id"
                    ),
                })
                continue

            protocolId = int(protocolId)

            protocolDbId = identityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
                protocolId
            )

            protocolStatus = str(
                protocol.getStatus()
                or ""
            ).strip().lower()

            entry = {
                "protocol": protocol,
                "protocolId": protocolId,
                "protocolDbId": (
                    int(protocolDbId)
                    if protocolDbId
                    not in (
                        None,
                        "",
                    )
                    else None
                ),
                "level": int(level),
                "status": protocolStatus,
                "streaming": bool(
                    protocol
                    .worksInStreaming()
                ),
                "saved": bool(
                    protocol.isSaved()
                ),
                "scheduled": bool(
                    protocol.isScheduled()
                ),
                "interactive": bool(
                    protocol.isInteractive()
                ),
                "action": None,
                "reason": None,
            }

            entries.append(
                entry
            )

            if protocolDbId in (
                    None,
                    "",
            ):
                entry["action"] = (
                    CONTINUE_ACTION_ERROR
                )

                entry["reason"] = (
                    "protocol_not_found"
                )

                errors.append({
                    "protocolId": str(
                        protocolId
                    ),
                    "error": (
                        "Protocol was not found "
                        "in PostgreSQL"
                    ),
                })

                continue

            internalProtocolDbIds.add(
                int(protocolDbId)
            )

            # Native Scipion does not automatically
            # relaunch interactive protocols.
            if entry["interactive"]:
                entry["action"] = (
                    CONTINUE_ACTION_SKIP
                )

                entry["reason"] = (
                    "interactive_protocol"
                )

                continue

            # A scheduler or coordinator is already
            # responsible for this protocol.
            if entry["scheduled"]:
                entry["action"] = (
                    CONTINUE_ACTION_SKIP
                )

                entry["reason"] = (
                    "already_scheduled"
                )

                continue

            if (
                    protocolStatus
                    in RuntimeProtocolStatusSyncService
                    .ACTIVE_STATUS_TEXTS
            ):
                entry["action"] = (
                    CONTINUE_ACTION_ERROR
                )

                entry["reason"] = (
                    "active_protocol"
                )

                errors.append({
                    "protocolId": str(
                        protocolId
                    ),
                    "status": protocolStatus,
                    "error": (
                        "Active protocols cannot "
                        "be continued until the "
                        "PostgreSQL-native stop "
                        "operation is available"
                    ),
                })

                continue

            if (
                    entry["streaming"]
                    and not entry["saved"]
            ):
                entry["action"] = (
                    CONTINUE_ACTION_RESUME
                )

                entry["reason"] = (
                    "streaming_execution_exists"
                )

            else:
                entry["action"] = (
                    CONTINUE_ACTION_RESTART
                )

                entry["reason"] = (
                    "native_continue_requires_restart"
                )

        # Validate every protocol that will receive
        # a new worker before deleting any output.
        #
        # Any parent contained in the complete
        # continue subtree is considered internal,
        # even when that parent is resumed or was
        # already scheduled.
        for entry in entries:
            if entry["action"] not in {
                CONTINUE_ACTION_RESTART,
                CONTINUE_ACTION_RESUME,
            }:
                continue

            protocolDbId = entry[
                "protocolDbId"
            ]

            refs = (
                graphRepository
                .loadInputRefsForProtocol(
                    mapper=mapper,
                    projectId=projectId,
                    protocolDbId=(
                        protocolDbId
                    ),
                )
            )

            for ref in refs or []:
                parentProtocolDbId = (
                    ref.get(
                        "parentProtocolDbId"
                    )
                )

                parentOutputName = str(
                    ref.get(
                        "parentOutputName"
                    )
                    or ""
                ).strip()

                if parentProtocolDbId in (
                        None,
                        "",
                ):
                    errors.append({
                        **dict(ref),
                        "protocolId": str(
                            entry[
                                "protocolId"
                            ]
                        ),
                        "error": (
                            "Input reference has no "
                            "parent protocol"
                        ),
                    })
                    continue

                parentProtocolDbId = int(
                    parentProtocolDbId
                )

                if (
                        parentProtocolDbId
                        == int(protocolDbId)
                ):
                    errors.append({
                        **dict(ref),
                        "protocolId": str(
                            entry[
                                "protocolId"
                            ]
                        ),
                        "error": (
                            "Self-referencing "
                            "protocol input"
                        ),
                    })
                    continue

                if (
                        parentProtocolDbId
                        in internalProtocolDbIds
                ):
                    continue

                if not parentOutputName:
                    errors.append({
                        **dict(ref),
                        "protocolId": str(
                            entry[
                                "protocolId"
                            ]
                        ),
                        "error": (
                            "External input reference "
                            "has no output name"
                        ),
                    })
                    continue

                rootOutputName = (
                    parentOutputName
                    .split(".", 1)[0]
                )

                outputInfo = (
                    graphRepository
                    .getPostgresqlRuntimeOutputInfo(
                        mapper=mapper,
                        projectId=projectId,
                        parentProtocolDbId=(
                            parentProtocolDbId
                        ),
                        outputName=(
                            rootOutputName
                        ),
                    )
                )

                if not outputInfo.get(
                        "exists"
                ):
                    errors.append({
                        **dict(ref),
                        "protocolId": str(
                            entry[
                                "protocolId"
                            ]
                        ),
                        "error": (
                            "External parent output "
                            "%s was not found"
                            % parentOutputName
                        ),
                    })

        restartProtocolIds = [
            str(entry["protocolId"])
            for entry in entries
            if entry["action"]
            == CONTINUE_ACTION_RESTART
        ]

        resumeProtocolIds = [
            str(entry["protocolId"])
            for entry in entries
            if entry["action"]
            == CONTINUE_ACTION_RESUME
        ]

        skipped = [
            {
                "protocolId": str(
                    entry["protocolId"]
                ),
                "reason": entry["reason"],
            }
            for entry in entries
            if entry["action"]
            == CONTINUE_ACTION_SKIP
        ]

        return {
            "entries": entries,
            "errors": errors,
            "summary": {
                "protocolsCount": len(
                    entries
                ),
                "actionableCount": (
                    len(restartProtocolIds)
                    + len(resumeProtocolIds)
                ),
                "restartProtocolIds": (
                    restartProtocolIds
                ),
                "resumeProtocolIds": (
                    resumeProtocolIds
                ),
                "skipped": skipped,
                "parentProtocolsModified": False,
            },
        }

    def getProtocolsForAction(
            self,
            plan,
            action: str,
    ):
        return [
            entry["protocol"]
            for entry in (
                plan.get("entries")
                or []
            )
            if entry.get("action")
            == action
        ]

    def _prepareResumeProtocol(
            self,
            *,
            mapper,
            projectId: int,
            entry,
            runtimeMapper,
    ) -> Dict[str, Any]:
        protocol = entry["protocol"]

        protocolId = int(
            entry["protocolId"]
        )

        protocolDbId = int(
            entry["protocolDbId"]
        )

        protocol.runMode.set(
            MODE_RESUME
        )

        # Remove stale launcher identity without
        # touching accumulated CPU/elapsed time.
        protocol.setPid(
            0
        )

        jobIds = getattr(
            protocol,
            "_jobId",
            None,
        )

        clearJobIds = getattr(
            jobIds,
            "clear",
            None,
        )

        if callable(clearJobIds):
            clearJobIds()

        protocol._steps = []

        for attributeName in (
                "_stepsDone",
                "_numberOfSteps",
        ):
            attribute = getattr(
                protocol,
                attributeName,
                None,
            )

            setter = getattr(
                attribute,
                "set",
                None,
            )

            if callable(setter):
                setter(
                    0
                )

        # MODE_RESUME preserves the existing
        # working directory and all outputs.
        protocol.makeWorkingDir()

        protocol.setStatus(
            STATUS_SCHEDULED
        )

        runtimeMapper.store(
            protocol
        )

        runtimeMapper.commit()

        # Match native continue semantics:
        # previous steps become SAVED, so the
        # streaming protocol can execute them
        # again while preserving its outputs.
        stepsPrepared = mapper.prepareProtocolStepsForContinue(
            projectId=projectId,
            protocolId=protocolId,
            statusValue=STATUS_SAVED,
            event="continue_resume",
        )

        ProtocolGraphRepository().setProtocolRelationsSynchronized(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            synchronized=False,
        )

        return {
            "protocolId": str(
                protocolId
            ),
            "protocolDbId": (
                protocolDbId
            ),
            "level": int(
                entry["level"]
            ),
            "action": (
                CONTINUE_ACTION_RESUME
            ),
            "interactive": False,
            "outputsPreserved": True,
            "workingDirectoryPreserved": True,
            "stepsPrepared": stepsPrepared,
            "parentProtocolsModified": False,
        }

    def _prepareRestartProtocol(
            self,
            *,
            mapper,
            projectId: int,
            entry,
            runtimeMapper,
    ) -> Dict[str, Any]:
        prepared = (
            self.restartLauncher
            ._prepareProtocol(
                mapper=mapper,
                projectId=projectId,
                protocol=(
                    entry["protocol"]
                ),
                level=int(
                    entry["level"]
                ),
                runtimeMapper=(
                    runtimeMapper
                ),
            )
        )

        return {
            **prepared,
            "action": (
                CONTINUE_ACTION_RESTART
            ),
            "outputsPreserved": False,
            "workingDirectoryPreserved": False,
            "parentProtocolsModified": False,
        }

    @staticmethod
    def _buildWorkerCommand(
            *,
            projectId: int,
            protocolId: int,
            runMode: str,
    ):
        from app.backend.runtime.postgresql_protocol_worker import (
            buildPostgresqlWorkerCommand,
        )

        return buildPostgresqlWorkerCommand(
            projectId=projectId,
            protocolId=protocolId,
            runMode=runMode,
        )

    @staticmethod
    def _spawnWorker(
            *,
            command,
            cwd,
    ):
        return subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

    def launchContinueSubworkflow(
            self,
            *,
            mapper,
            projectId: int,
            currentProject,
            plan,
    ) -> Dict[str, Any]:
        if plan.get("errors"):
            raise ValueError(
                "Cannot launch an invalid "
                "PostgreSQL continue plan"
            )

        runtimeMapper = (
            currentProject
            .getPostgresqlRuntimeMapper()
        )

        if runtimeMapper is None:
            raise RuntimeError(
                "PostgreSQL runtime mapper "
                "is not available"
            )

        entries = list(
            plan.get("entries")
            or []
        )

        preparedItems = []
        skippedItems = []

        # Prepare the entire mixed subtree before
        # allowing any worker to start.
        for entry in entries:
            action = entry.get(
                "action"
            )

            if (
                    action
                    == CONTINUE_ACTION_SKIP
            ):
                skippedItems.append({
                    "protocolId": str(
                        entry["protocolId"]
                    ),
                    "protocolDbId": (
                        entry["protocolDbId"]
                    ),
                    "level": int(
                        entry["level"]
                    ),
                    "action": action,
                    "launched": False,
                    "reason": (
                        entry["reason"]
                    ),
                })

                continue

            if (
                    action
                    == CONTINUE_ACTION_RESUME
            ):
                preparedItems.append(
                    self._prepareResumeProtocol(
                        mapper=mapper,
                        projectId=projectId,
                        entry=entry,
                        runtimeMapper=(
                            runtimeMapper
                        ),
                    )
                )

                continue

            if (
                    action
                    == CONTINUE_ACTION_RESTART
            ):
                preparedItems.append(
                    self._prepareRestartProtocol(
                        mapper=mapper,
                        projectId=projectId,
                        entry=entry,
                        runtimeMapper=(
                            runtimeMapper
                        ),
                    )
                )

        protocolsById = {
            str(entry["protocolId"]): (
                entry["protocol"]
            )
            for entry in entries
        }

        launchedItems = []
        errors = []

        for preparedItem in preparedItems:
            protocolId = int(
                preparedItem[
                    "protocolId"
                ]
            )

            protocol = protocolsById[
                str(protocolId)
            ]

            action = preparedItem[
                "action"
            ]

            command = (
                self._buildWorkerCommand(
                    projectId=projectId,
                    protocolId=protocolId,
                    runMode=action,
                )
            )

            try:
                process = (
                    self._spawnWorker(
                        command=command,
                        cwd=(
                            currentProject.path
                        ),
                    )
                )

                protocol.setPid(
                    process.pid
                )

                protocol.setStatus(
                    STATUS_SCHEDULED
                )

                runtimeMapper.store(
                    protocol
                )

                runtimeMapper.commit()

                launchedItems.append({
                    **preparedItem,
                    "launched": True,
                    "coordinatorPid": int(
                        process.pid
                    ),
                    "command": command,
                })

            except Exception as error:
                protocol.setFailed(
                    str(error)
                )

                runtimeMapper.store(
                    protocol
                )

                runtimeMapper.commit()

                errors.append({
                    **preparedItem,
                    "error": str(error),
                })

        restartCount = sum(
            1
            for item in preparedItems
            if item.get("action")
            == CONTINUE_ACTION_RESTART
        )

        resumeCount = sum(
            1
            for item in preparedItems
            if item.get("action")
            == CONTINUE_ACTION_RESUME
        )

        return {
            "protocolsCount": len(
                entries
            ),
            "preparedCount": len(
                preparedItems
            ),
            "restartedCount": (
                restartCount
            ),
            "resumedCount": (
                resumeCount
            ),
            "skippedCount": len(
                skippedItems
            ),
            "prepared": preparedItems,
            "launched": launchedItems,
            "skipped": skippedItems,
            "errors": errors,
            "parentProtocolsModified": False,
        }