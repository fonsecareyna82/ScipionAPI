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
        runtimeStructures = {}

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
                        "Protocol remained active after the PostgreSQL-native stop phase"
                    ),
                })

            try:
                outputNames = [
                    outputName
                    for outputName, _
                    in list(protocol.iterOutputAttributes())
                ]
            except Exception as error:
                errors.append({
                    "protocolId": str(protocolId),
                    "error": "Could not enumerate protocol runtime outputs: %s" % error,
                })
                continue

            try:
                definition = protocol.getDefinition()
                pointerParams = []

                for paramName, param in list(definition.iterParams()):
                    if isinstance(param, MultiPointerParam):
                        pointerParams.append((paramName, "multi"))
                    elif isinstance(param, (PointerParam, RelationParam)):
                        pointerParams.append((paramName, "single"))
            except Exception as error:
                errors.append({
                    "protocolId": str(protocolId),
                    "error": "Could not enumerate protocol runtime input parameters: %s" % error,
                })
                continue

            runtimeStructures[str(protocolId)] = {
                "outputNames": outputNames,
                "pointerParams": pointerParams,
            }

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
            "protocolDbIds": sorted(protocolDbIds),
            "runtimeStructures": runtimeStructures,
            "errors": errors,
            "parentProtocolsModified": False,
        }

    @staticmethod
    def _detachOutputs(
            protocol,
            outputNames=None,
    ) -> None:
        if outputNames is None:
            outputNames = [
                outputName
                for outputName, _
                in list(protocol.iterOutputAttributes())
            ]

        for outputName in outputNames:
            if hasattr(protocol, outputName):
                delattr(protocol, outputName)

        outputs = getattr(protocol, "_outputs", None)

        if outputs is not None:
            outputs.clear()

    @staticmethod
    def _clearRuntimePointers(
            protocol,
            pointerParams=None,
    ) -> None:
        if pointerParams is None:
            definition = protocol.getDefinition()
            pointerParams = []

            for paramName, param in list(definition.iterParams()):
                if isinstance(param, MultiPointerParam):
                    pointerParams.append((paramName, "multi"))
                elif isinstance(param, (PointerParam, RelationParam)):
                    pointerParams.append((paramName, "single"))

        for paramName, pointerKind in pointerParams:
            if pointerKind == "multi":
                setattr(protocol, paramName, PointerList())
            else:
                setattr(protocol, paramName, Pointer())

    def _prepareProtocol(
            self,
            *,
            mapper,
            projectId: int,
            protocol,
            level: int,
            runtimeMapper,
            runtimeStructure=None,
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

        outputNames = None if runtimeStructure is None else list(runtimeStructure.get("outputNames") or [])
        pointerParams = None if runtimeStructure is None else list(runtimeStructure.get("pointerParams") or [])

        self._detachOutputs(
            protocol,
            outputNames=outputNames,
        )

        self._clearRuntimePointers(
            protocol,
            pointerParams=pointerParams,
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
            validationInfo,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback,
            currentUserId=None,
            executionId=None,
    ) -> Dict[str, Any]:

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

        runtimeStructures = validationInfo.get("runtimeStructures") or {}

        preparedItems = []

        outputCleanup = {
            "protocolsCount": 0,
            "setsDeleted": 0,
            "objectsDeleted": 0,
            "filesDeleted": 0,
            "fileErrors": [],
            "items": [],
        }

        inputRefCleanup = {
            "updated": 0,
            "parentProtocolDbIds": [],
        }

        # Prepare the complete subtree before allowing
        # any worker to start.
        for protocol, level in items:
            protocolId = str(protocol.getObjId())
            runtimeStructure = runtimeStructures.get(protocolId)

            if runtimeStructure is None:
                raise RuntimeError(
                    "Validated runtime structure was not found for protocol %s" % protocolId
                )

            itemOutputCleanup = deletePersistedProtocolOutputsForRuntimeProtocolsCallback(
                mapper=mapper,
                projectId=projectId,
                protocols=[protocol],
            )

            outputCleanup["protocolsCount"] += int(itemOutputCleanup.get("protocolsCount") or 0)
            outputCleanup["setsDeleted"] += int(itemOutputCleanup.get("setsDeleted") or 0)
            outputCleanup["objectsDeleted"] += int(itemOutputCleanup.get("objectsDeleted") or 0)
            outputCleanup["filesDeleted"] += int(itemOutputCleanup.get("filesDeleted") or 0)
            outputCleanup["fileErrors"].extend(itemOutputCleanup.get("fileErrors") or [])
            outputCleanup["items"].extend(itemOutputCleanup.get("items") or [])

            itemInputRefCleanup = clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback(
                mapper=mapper,
                projectId=projectId,
                protocols=[protocol],
            )

            inputRefCleanup["updated"] += int(itemInputRefCleanup.get("updated") or 0)

            for parentProtocolDbId in itemInputRefCleanup.get("parentProtocolDbIds") or []:
                if parentProtocolDbId not in inputRefCleanup["parentProtocolDbIds"]:
                    inputRefCleanup["parentProtocolDbIds"].append(parentProtocolDbId)

            preparedItems.append(
                self._prepareProtocol(
                    mapper=mapper,
                    projectId=projectId,
                    protocol=protocol,
                    level=level,
                    runtimeMapper=runtimeMapper,
                    runtimeStructure=runtimeStructure,
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

            if currentUserId is not None:
                (
                    RuntimeProtocolStatusSyncService()
                    .persistProtocolExecutionUser(
                        mapper=mapper,
                        projectId=projectId,
                        protocolId=protocolId,
                        userId=currentUserId,
                        executionId=executionId,
                    )
                )

            try:
                taskId = (
                    currentProject
                    ._enqueuePostgresqlProtocolTask(
                        protocol=protocol,
                        runMode="restart",
                        wait=False,
                    )
                )

                launchedItems.append({
                    **preparedItem,
                    "launched": True,
                    "taskId": str(
                        taskId
                    ),
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
            "protocolsCount": len(preparedItems),
            "prepared": preparedItems,
            "launched": launchedItems,
            "outputCleanup": outputCleanup,
            "inputRefCleanup": inputRefCleanup,
            "errors": errors,
        }