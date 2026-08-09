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
from typing import Any, Dict, List, Tuple

from pyworkflow.object import Pointer, PointerList
from pyworkflow.protocol import (
    MODE_RESTART,
    STATUS_SAVED,
    STATUS_SCHEDULED,
)
from pyworkflow.protocol.params import (
    MultiPointerParam,
    PointerParam,
    RelationParam,
)
from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)
from app.backend.runtime.protocol_identity import (
    ProtocolIdentityResolver,
)
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)


class RuntimePostgresqlRestartLauncherService:
    @staticmethod
    def _workflowItems(
            workflowProtocolMap,
    ) -> List[Tuple[Any, int]]:
        items = []

        for value in (
                workflowProtocolMap.values()
                if isinstance(
                    workflowProtocolMap,
                    dict,
                )
                else workflowProtocolMap or []
        ):
            if (
                    isinstance(
                        value,
                        (tuple, list),
                    )
                    and value
            ):
                protocol = value[0]
                level = int(
                    value[1]
                    if len(value) > 1
                    else 0
                )
            else:
                protocol = value
                level = 0

            if protocol is not None:
                items.append(
                    (
                        protocol,
                        level,
                    )
                )

        items.sort(
            key=lambda item: (
                item[1],
                int(
                    item[0].getObjId()
                ),
            )
        )

        return items

    def validateRestartSubworkflow(
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
                "protocolsCount": 0,
                "protocolDbIds": [],
                "errors": [{
                    "error": "PostgreSQL runtime mapper is not available",
                }],
                "parentProtocolsModified": False,
            }

        items = self._workflowItems(
            workflowProtocolMap
        )

        identityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        graphRepository = (
            ProtocolGraphRepository()
        )

        errors = []
        protocolDbIds = set()

        for protocol, level in items:
            protocolId = protocol.getObjId()

            protocolDbId = identityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
                protocolId
            )

            if protocolDbId is None:
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

            protocolDbIds.add(
                int(protocolDbId)
            )

            protocolStatus = str(
                protocol.getStatus()
                or ""
            ).strip().lower()

            if (
                    protocolStatus
                    in RuntimeProtocolStatusSyncService
                    .ACTIVE_STATUS_TEXTS
            ):
                errors.append({
                    "protocolId": str(
                        protocolId
                    ),
                    "status": protocolStatus,
                    "error": (
                        "Active protocols cannot "
                        "be restarted until the "
                        "PostgreSQL-native stop "
                        "operation is available"
                    ),
                })

        for protocol, level in items:
            protocolId = protocol.getObjId()

            protocolDbId = identityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
                protocolId
            )

            if protocolDbId is None:
                continue

            refs = (
                graphRepository
                .loadInputRefsForProtocol(
                    mapper=mapper,
                    projectId=projectId,
                    protocolDbId=int(
                        protocolDbId
                    ),
                )
            )

            for ref in refs or []:
                parentProtocolDbId = ref.get(
                    "parentProtocolDbId"
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
                            protocolId
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
                            protocolId
                        ),
                        "error": (
                            "Self-referencing "
                            "protocol input"
                        ),
                    })
                    continue

                # Outputs belonging to the restarted subtree
                # will be generated again.
                if (
                        parentProtocolDbId
                        in protocolDbIds
                ):
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
                        outputName=rootOutputName,
                    )
                )

                if not outputInfo.get("exists"):
                    errors.append({
                        **dict(ref),
                        "protocolId": str(
                            protocolId
                        ),
                        "error": (
                            "External parent output "
                            "%s was not found"
                            % parentOutputName
                        ),
                    })

        return {
            "protocolsCount": len(items),
            "protocolDbIds": sorted(
                protocolDbIds
            ),
            "errors": errors,
            "parentProtocolsModified": False,
        }

    @staticmethod
    def _detachOutputs(
            protocol,
    ) -> None:
        outputNames = [
            outputName
            for outputName, _
            in list(
                protocol
                .iterOutputAttributes()
            )
        ]

        for outputName in outputNames:
            if hasattr(
                    protocol,
                    outputName,
            ):
                delattr(
                    protocol,
                    outputName,
                )

        outputs = getattr(
            protocol,
            "_outputs",
            None,
        )

        if outputs is not None:
            outputs.clear()

    @staticmethod
    def _clearRuntimePointers(
            protocol,
    ) -> None:
        definition = protocol.getDefinition()

        for paramName, param in (
                definition.iterParams()
        ):
            if isinstance(
                    param,
                    MultiPointerParam,
            ):
                setattr(
                    protocol,
                    paramName,
                    PointerList(),
                )

            elif isinstance(
                    param,
                    (
                        PointerParam,
                        RelationParam,
                    ),
            ):
                setattr(
                    protocol,
                    paramName,
                    Pointer(),
                )

    def _prepareProtocol(
            self,
            *,
            mapper,
            projectId: int,
            protocol,
            level: int,
            runtimeMapper,
    ) -> Dict[str, Any]:
        identityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        protocolId = int(
            protocol.getObjId()
        )

        protocolDbId = identityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
            protocolId
        )

        if protocolDbId is None:
            raise RuntimeError(
                "Protocol %s was not found "
                "in PostgreSQL"
                % protocolId
            )

        protocolDbId = int(
            protocolDbId
        )

        self._detachOutputs(
            protocol
        )

        self._clearRuntimePointers(
            protocol
        )

        protocol.setSaved()

        protocol.runMode.set(
            MODE_RESTART
        )

        protocol.cleanExecutionAttributes()

        protocol._steps = []
        protocol._stepsDone.set(0)
        protocol._numberOfSteps.set(0)
        protocol._cpuTime.set(0)

        protocol.cleanWorkingDir()
        protocol.makeWorkingDir()

        runtimeMapper.deleteRelations(
            protocol
        )

        mapper.deleteProtocolSteps(
            projectId=projectId,
            protocolId=protocolId,
        )

        ProtocolGraphRepository().setProtocolRelationsSynchronized(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            synchronized=False,
        )

        if protocol.isInteractive():
            protocol.setStatus(
                STATUS_SAVED
            )
        else:
            protocol.setStatus(
                STATUS_SCHEDULED
            )

        runtimeMapper.store(
            protocol
        )

        runtimeMapper.commit()

        return {
            "protocolId": str(
                protocolId
            ),
            "protocolDbId": (
                protocolDbId
            ),
            "level": int(level),
            "interactive": bool(
                protocol.isInteractive()
            ),
        }

    def launchRestartSubworkflow(
            self,
            *,
            mapper,
            projectId: int,
            workflowProtocolMap,
            currentProject,
    ) -> Dict[str, Any]:
        from app.backend.runtime.postgresql_protocol_worker import (
            buildPostgresqlWorkerCommand,
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

        items = self._workflowItems(
            workflowProtocolMap
        )

        preparedItems = []

        # Prepare the complete subtree before allowing
        # any worker to start.
        for protocol, level in items:
            preparedItems.append(
                self._prepareProtocol(
                    mapper=mapper,
                    projectId=projectId,
                    protocol=protocol,
                    level=level,
                    runtimeMapper=runtimeMapper,
                )
            )

        launchedItems = []
        errors = []

        protocolsById = {
            str(
                protocol.getObjId()
            ): protocol
            for protocol, _
            in items
        }

        for preparedItem in preparedItems:
            if preparedItem["interactive"]:
                launchedItems.append({
                    **preparedItem,
                    "launched": False,
                    "reason": (
                        "interactive_protocol"
                    ),
                })
                continue

            protocolId = int(
                preparedItem[
                    "protocolId"
                ]
            )

            protocol = protocolsById[
                str(protocolId)
            ]

            command = (
                buildPostgresqlWorkerCommand(
                    projectId=projectId,
                    protocolId=protocolId,
                )
            )

            try:
                process = subprocess.Popen(
                    command,
                    cwd=currentProject.path,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
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

        return {
            "protocolsCount": len(
                preparedItems
            ),
            "prepared": preparedItems,
            "launched": launchedItems,
            "errors": errors,
        }