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
            allowMissingParentOutputs: bool = False,
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

        protocolId = protocolIdentityResolver.resolveScipionProtocolId(
            getProtocolIdCallback(protocol),
        )

        if protocolId is None:
            return {
                "prepared": 0,
                "skipped": True,
                "reason": "protocol_without_id",
                "items": [],
                "errors": [],
            }

        protocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbId(
            protocolId,
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

        for row in rows or []:
            inputName = str(row.get("inputName") or "").strip()
            parentOutputName = str(
                row.get("parentOutputName") or ""
            ).strip()

            parentProtocolId = row.get("parentProtocolId")
            parentProtocolDbId = row.get("parentProtocolDbId")

            if not inputName:
                continue

            if (
                    not parentOutputName
                    or parentProtocolId in (None, "")
            ):
                errors.append({
                    "inputName": inputName,
                    "itemIndex": row.get(
                        "itemIndex"
                    ),
                    "parentProtocolDbId": row.get(
                        "parentProtocolDbId"
                    ),
                    "parentProtocolId": parentProtocolId,
                    "parentOutputName": parentOutputName,
                    "error": (
                        "Invalid PostgreSQL input reference"
                    ),
                })

                continue

            itemReport = {
                "inputName": inputName,
                "itemIndex": row.get("itemIndex"),
                "parentProtocolId": str(parentProtocolId),
                "parentProtocolDbId": parentProtocolDbId,
                "parentOutputName": parentOutputName,
                "hadRuntimeAttribute": False,
                "pointerReset": False,
                "parentProtocolReadOnly": True,
                "outputRelationRepairSkipped": True,
            }

            try:
                parentScipionProtocolId, parentProtocol = (
                    getParentProtocolCallback(
                        mapper=mapper,
                        projectId=projectId,
                        parentId=parentProtocolId,
                    )
                )

                if parentProtocol is None:
                    raise ValueError(
                        "Parent protocol %s could not be loaded"
                        % str(parentScipionProtocolId)
                    )

                try:
                    itemReport["hadRuntimeAttribute"] = bool(
                        hasattr(parentProtocol, parentOutputName)
                    )
                except Exception:
                    itemReport["hadRuntimeAttribute"] = False

                resolvedParentProtocolDbId = parentProtocolDbId

                if resolvedParentProtocolDbId in (None, ""):
                    resolvedParentProtocolDbId = (
                        protocolIdentityResolver
                        .resolvePostgresqlProtocolDbId(
                            parentScipionProtocolId,
                        )
                    )

                if resolvedParentProtocolDbId in (None, ""):
                    raise ValueError(
                        "Parent protocol %s was not found in PostgreSQL"
                        % str(parentScipionProtocolId)
                    )

                itemReport["parentProtocolDbId"] = int(
                    resolvedParentProtocolDbId
                )

                outputInfo = (
                    protocolGraphRepository
                    .getPostgresqlRuntimeOutputInfo(
                        mapper=mapper,
                        projectId=projectId,
                        parentProtocolDbId=int(
                            resolvedParentProtocolDbId
                        ),
                        outputName=parentOutputName,
                    )
                )

                if not outputInfo.get("exists"):
                    if allowMissingParentOutputs:
                        itemReport["missingParentOutput"] = True
                        itemReport["missingParentOutputReason"] = (
                            "parent_output_not_produced_yet"
                        )
                    else:
                        raise ValueError(
                            "Parent output %s.%s was not found in PostgreSQL"
                            % (
                                str(parentScipionProtocolId),
                                parentOutputName,
                            )
                        )
                else:
                    itemReport["outputInfo"] = {
                        "kind": outputInfo.get("kind"),
                        "setId": outputInfo.get("setId"),
                        "objectId": outputInfo.get("objectId"),
                        "className": outputInfo.get("className"),
                        "itemClassName": outputInfo.get(
                            "itemClassName"
                        ),
                        "itemsCount": outputInfo.get("itemsCount"),
                    }

                param = protocol.getParam(inputName)

                if isinstance(param, MultiPointerParam):
                    pointerList = multiPointerLists.get(inputName)

                    if pointerList is None:
                        pointerList = PointerList()
                        multiPointerLists[inputName] = pointerList

                        # The PointerList belongs exclusively to the child protocol.
                        setattr(protocol, inputName, pointerList)

                    pointer = Pointer(
                        parentProtocol,
                        extended=parentOutputName,
                    )

                    pointerList.append(pointer)

                    pointerValue = "%s.%s" % (
                        str(parentScipionProtocolId),
                        parentOutputName,
                    )

                    itemReport["multiPointer"] = True
                    itemReport["pointerReset"] = True
                    itemReport["pointerValue"] = pointerValue
                    itemReport["paramDefaultUpdateSkipped"] = (
                        "multipointer_runtime_pointer_list"
                    )
                    itemReport["pointerResolutionSkipped"] = (
                        "parent_protocol_and_outputs_are_read_only"
                    )

                    preparedItems.append(itemReport)
                    continue

                pointer = Pointer(
                    parentProtocol,
                    extended=parentOutputName,
                )

                # Always replace the child runtime attribute with a fresh
                # Pointer. PostgreSQL input refs are the source of truth.
                setattr(
                    protocol,
                    inputName,
                    pointer,
                )

                pointerValue = "%s.%s" % (
                    str(parentScipionProtocolId),
                    parentOutputName,
                )

                pointerTarget = pointer.getObjValue()

                if (
                        pointerTarget is None
                        or isinstance(pointerTarget, str)
                ):
                    raise RuntimeError(
                        "Could not restore runtime Pointer object. "
                        "protocolId=%s inputName=%s value=%s"
                        % (
                            protocolId,
                            inputName,
                            pointerValue,
                        )
                    )

                itemReport[
                    "paramDefaultUpdateSkipped"
                ] = (
                    "postgresql_input_refs_are_authoritative"
                )

                itemReport["pointerReset"] = True
                itemReport["pointerValue"] = pointerValue

                # Do not call pointer.get() here. Resolving the pointer may
                # access or materialize an output belonging to the parent.
                itemReport["pointerResolutionSkipped"] = (
                    "parent_protocol_and_outputs_are_read_only"
                )

                preparedItems.append(itemReport)

            except Exception as exc:
                logger.exception(
                    "Failed to prepare PostgreSQL child runtime pointer. "
                    "projectId=%s protocolId=%s inputName=%s "
                    "parentProtocolId=%s parentOutputName=%s",
                    projectId,
                    protocolId,
                    inputName,
                    parentProtocolId,
                    parentOutputName,
                )

                itemReport["error"] = str(exc)
                errors.append(itemReport)

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