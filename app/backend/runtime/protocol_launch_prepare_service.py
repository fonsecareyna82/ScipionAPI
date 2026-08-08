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
from typing import Any, Callable, Dict, Optional

from pyworkflow.object import Pointer, PointerList
from pyworkflow.protocol.params import MultiPointerParam

from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository
from app.backend.runtime.protocol_identity import ProtocolIdentityResolver

logger = logging.getLogger(__name__)


class RuntimeProtocolLaunchPrepareService:
    """Prepare PostgreSQL runtime protocol pointers before launch."""

    def preparePointerOutputsForLaunch(
            self,
            mapper,
            projectId: int,
            protocol,
            getProtocolIdCallback: Callable,
            getParentProtocolCallback: Callable,
            resolveRuntimeInputObjectCallback: Callable,
            allowMissingParentOutputs: bool = False,
            parentProtocolsById: Optional[
                Dict[str, Any]
            ] = None,
    ) -> Dict[str, Any]:
        """
        Restore child protocol pointers from PostgreSQL input references.

        Parent protocols and their outputs are strictly read-only:

        - Parent outputs are not attached or replaced.
        - PostgreSQL proxies are not replaced.
        - Output mapper information is not repaired.
        - Runtime output relations are not modified.
        - Parent protocols and outputs are never persisted.

        Only Pointer and PointerList attributes belonging to the child protocol are updated.
        """
        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        protocolId = getProtocolIdCallback(protocol)

        if protocolId is None:
            return {
                "prepared": 0,
                "skipped": True,
                "reason": "protocol_without_id",
                "items": [],
                "errors": [],
            }

        protocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
            protocolId
        )

        if protocolDbId is None:
            return {
                "protocolId": str(protocolId),
                "protocolDbId": None,
                "prepared": 0,
                "skipped": True,
                "reason": "protocol_not_found_in_postgresql",
                "items": [],
                "errors": [],
            }

        protocolGraphRepository = ProtocolGraphRepository()

        rows = protocolGraphRepository.loadInputRefsForProtocol(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=int(protocolDbId),
        )

        preparedItems = []
        errors = []
        multiPointerLists = {}

        resolvedParentProtocolsById = {
            str(parentProtocolId): parentProtocol
            for parentProtocolId, parentProtocol in (parentProtocolsById or {}).items()
        }

        def resolveParentProtocol(parentProtocolId):
            parentScipionProtocolId = parentProtocolId

            parentProtocol = resolvedParentProtocolsById.get(
                str(parentScipionProtocolId)
            )

            if parentProtocol is None:
                parentScipionProtocolId, parentProtocol = getParentProtocolCallback(
                    mapper=mapper,
                    projectId=projectId,
                    parentId=parentProtocolId,
                )

                if parentProtocol is not None:
                    resolvedParentProtocolsById[str(parentProtocolId)] = parentProtocol
                    resolvedParentProtocolsById[str(parentScipionProtocolId)] = parentProtocol

            return parentScipionProtocolId, parentProtocol

        for row in rows or []:
            inputName = str(
                row.get(
                    "inputName"
                )
                or ""
            ).strip()

            parentOutputName = str(
                row.get(
                    "parentOutputName"
                )
                or ""
            ).strip()

            parentProtocolId = row.get(
                "parentProtocolId"
            )

            parentProtocolDbId = row.get(
                "parentProtocolDbId"
            )

            if not inputName:
                continue

            if (
                    not parentOutputName
                    or parentProtocolId
                    in (
                    None,
                    "",
            )
            ):
                errors.append({
                    "inputName": inputName,
                    "itemIndex": row.get(
                        "itemIndex"
                    ),
                    "parentProtocolDbId": (
                        parentProtocolDbId
                    ),
                    "parentProtocolId": (
                        parentProtocolId
                    ),
                    "parentOutputName": (
                        parentOutputName
                    ),
                    "error": (
                        "Invalid PostgreSQL "
                        "input reference"
                    ),
                })

                continue

            outputParts = [
                part
                for part in (
                    parentOutputName
                    .split(".")
                )
                if part
            ]

            rootOutputName = (
                outputParts[0]
                if outputParts
                else parentOutputName
            )

            parentScipionProtocolId = parentProtocolId

            itemReport = {
                "inputName": inputName,
                "itemIndex": row.get(
                    "itemIndex"
                ),
                "parentProtocolId": str(
                    parentScipionProtocolId
                ),
                "parentProtocolDbId": (
                    parentProtocolDbId
                ),
                "parentOutputName": (
                    parentOutputName
                ),
                "rootOutputName": (
                    rootOutputName
                ),
                "pointerReset": False,
                "directOutputPointer": False,
                "parentProtocolReadOnly": True,
                "parentProtocolModified": False,
                "outputRelationRepairSkipped": True,
            }

            try:
                resolvedParentProtocolDbId = (
                    parentProtocolDbId
                )

                if resolvedParentProtocolDbId in (
                        None,
                        "",
                ):
                    resolvedParentProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbIdFromScipionProtocolId(
                        parentScipionProtocolId
                    )

                if resolvedParentProtocolDbId in (
                        None,
                        "",
                ):
                    raise ValueError(
                        "Parent protocol %s was not "
                        "found in PostgreSQL"
                        % parentScipionProtocolId
                    )

                resolvedParentProtocolDbId = int(
                    resolvedParentProtocolDbId
                )

                itemReport[
                    "parentProtocolDbId"
                ] = resolvedParentProtocolDbId

                outputInfo = (
                    protocolGraphRepository
                    .getPostgresqlRuntimeOutputInfo(
                        mapper=mapper,
                        projectId=projectId,
                        parentProtocolDbId=(
                            resolvedParentProtocolDbId
                        ),
                        outputName=rootOutputName,
                    )
                )

                pointer = None

                if outputInfo.get(
                        "exists"
                ):
                    runtimeObjectId = (
                        outputInfo.get(
                            "runtimeObjectId"
                        )
                    )

                    if runtimeObjectId in (
                            None,
                            "",
                    ):
                        raise RuntimeError(
                            "Parent output %s.%s "
                            "does not have a Scipion "
                            "runtime object id"
                            % (
                                parentScipionProtocolId,
                                rootOutputName,
                            )
                        )

                    itemReport.update({
                        "runtimeObjectId": int(
                            runtimeObjectId
                        ),
                        "objectClassName": (
                            outputInfo.get(
                                "className"
                            )
                        ),
                        "outputInfo": {
                            "kind": outputInfo.get(
                                "kind"
                            ),
                            "setId": outputInfo.get(
                                "setId"
                            ),
                            "objectId": outputInfo.get(
                                "objectId"
                            ),
                            "runtimeObjectId": int(
                                runtimeObjectId
                            ),
                            "className": outputInfo.get(
                                "className"
                            ),
                            "itemClassName": (
                                outputInfo.get(
                                    "itemClassName"
                                )
                            ),
                            "itemsCount": (
                                outputInfo.get(
                                    "itemsCount"
                                )
                            ),
                        },
                    })

                    outputObject = (
                        resolveRuntimeInputObjectCallback(
                            int(
                                runtimeObjectId
                            )
                        )
                    )

                    if outputObject is None:
                        raise RuntimeError(
                            "Could not reconstruct "
                            "PostgreSQL runtime output "
                            "%s.%s with runtime id %s"
                            % (
                                parentScipionProtocolId,
                                rootOutputName,
                                runtimeObjectId,
                            )
                        )

                    # Point directly to the detached PostgreSQL output.
                    # Do not attach it to or modify the parent protocol.
                    pointer = Pointer(
                        outputObject
                    )

                    if len(
                            outputParts
                    ) > 1:
                        pointer.setExtendedParts(
                            outputParts[1:]
                        )

                    resolvedPointerObject = (
                        pointer.get()
                    )

                    if resolvedPointerObject is None:
                        raise RuntimeError(
                            "PostgreSQL runtime pointer "
                            "resolved to None. "
                            "protocolId=%s inputName=%s "
                            "value=%s.%s"
                            % (
                                protocolId,
                                inputName,
                                parentScipionProtocolId,
                                parentOutputName,
                            )
                        )

                    itemReport.update({
                        "directOutputPointer": True,
                        "pointerResolved": True,
                    })

                elif allowMissingParentOutputs:
                    parentScipionProtocolId, (
                        parentProtocol
                    ) = resolveParentProtocol(
                        parentProtocolId
                    )

                    if parentProtocol is None:
                        raise ValueError(
                            "Parent protocol %s "
                            "could not be loaded"
                            % parentScipionProtocolId
                        )

                    # Used only when launching a workflow whose upstream
                    # protocol has not produced the output yet. The worker
                    # will replace it with a direct output pointer later.
                    pointer = Pointer(
                        parentProtocol,
                        extended=(
                            parentOutputName
                        ),
                    )

                    itemReport.update({
                        "missingParentOutput": True,
                        "missingParentOutputReason": (
                            "parent_output_not_produced_yet"
                        ),
                        "deferredOutputPointer": True,
                        "pointerResolved": False,
                    })

                else:
                    raise ValueError(
                        "Parent output %s.%s was "
                        "not found in PostgreSQL"
                        % (
                            parentScipionProtocolId,
                            rootOutputName,
                        )
                    )

                param = protocol.getParam(
                    inputName
                )

                if isinstance(
                        param,
                        MultiPointerParam,
                ):
                    pointerList = (
                        multiPointerLists.get(
                            inputName
                        )
                    )

                    if pointerList is None:
                        pointerList = (
                            PointerList()
                        )

                        multiPointerLists[
                            inputName
                        ] = pointerList

                        setattr(
                            protocol,
                            inputName,
                            pointerList,
                        )

                    pointerList.append(
                        pointer
                    )

                    itemReport[
                        "multiPointer"
                    ] = True

                else:
                    setattr(
                        protocol,
                        inputName,
                        pointer,
                    )

                pointerValue = "%s.%s" % (
                    parentScipionProtocolId,
                    parentOutputName,
                )

                itemReport.update({
                    "pointerReset": True,
                    "pointerValue": (
                        pointerValue
                    ),
                    "paramDefaultUpdateSkipped": (
                        "postgresql_input_refs_are_authoritative"
                    ),
                })

                preparedItems.append(
                    itemReport
                )

            except Exception as error:
                logger.exception(
                    "Failed to prepare PostgreSQL "
                    "child runtime pointer. "
                    "projectId=%s protocolId=%s "
                    "inputName=%s parentProtocolId=%s "
                    "parentOutputName=%s",
                    projectId,
                    protocolId,
                    inputName,
                    parentProtocolId,
                    parentOutputName,
                )

                itemReport[
                    "error"
                ] = str(
                    error
                )

                errors.append(
                    itemReport
                )

        report = {
            "protocolId": str(protocolId),
            "protocolDbId": int(protocolDbId),
            "prepared": len(preparedItems),
            "items": preparedItems,
            "errors": errors,
            "skipped": False,
            "parentProtocolsReadOnly": True,
        }

        logger.info(
            "Prepared PostgreSQL child runtime pointers without modifying "
            "parent protocols or outputs. projectId=%s protocolId=%s "
            "report=%s",
            projectId,
            protocolId,
            report,
        )

        return report