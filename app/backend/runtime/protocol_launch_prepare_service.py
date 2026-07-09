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
import re
import logging
from typing import Any, Callable, Dict, Optional

from pyworkflow.object import Pointer
from pyworkflow.protocol.params import MultiPointerParam

from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository
from app.backend.runtime.protocol_identity import ProtocolIdentityResolver
from app.backend.runtime.runtime_output_proxy_service import RuntimeOutputProxyService

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
            repairOutputRelationsCallback: Optional[Callable] = None,
            allowMissingParentOutputs: bool = False,
    ) -> Dict[str, Any]:
        """
        Prepare child protocol pointers before launch using protocol_input_refs.

        This does not rewrite the PostgreSQL graph. It only ensures that Scipion
        runtime can resolve Pointer(parentProtocol, extended=outputName) while
        launching.

        Important:
          - PostgreSQL is treated as the source of truth for parent outputs.
          - A PostgreSQL-backed proxy is attached when the parent output is persisted,
            replacing any stale runtime output attribute.
          - The caller must persist the prepared protocol before launching so the
            execution process can reload the restored pointers.
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

        runtimeOutputProxyService = RuntimeOutputProxyService()
        preparedItems = []
        errors = []

        for row in rows or []:
            inputName = str(row.get("inputName") or "").strip()
            parentOutputName = str(row.get("parentOutputName") or "").strip()
            parentProtocolId = row.get("parentProtocolId")
            parentProtocolDbId = row.get("parentProtocolDbId")

            if not inputName or not parentOutputName or parentProtocolId in (None, ""):
                continue

            itemReport = {
                "inputName": inputName,
                "parentProtocolId": str(parentProtocolId),
                "parentProtocolDbId": parentProtocolDbId,
                "parentOutputName": parentOutputName,
                "attachedProxy": False,
                "hadRuntimeAttribute": False,
                "pointerReset": False,
            }

            try:
                parentScipionProtocolId, parentProtocol = getParentProtocolCallback(
                    mapper=mapper,
                    projectId=projectId,
                    parentId=parentProtocolId,
                )

                try:
                    hasRuntimeAttribute = hasattr(parentProtocol, parentOutputName)
                except Exception:
                    hasRuntimeAttribute = False

                itemReport["hadRuntimeAttribute"] = bool(hasRuntimeAttribute)

                resolvedParentProtocolDbId = parentProtocolDbId

                if resolvedParentProtocolDbId in (None, ""):
                    resolvedParentProtocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbId(
                        parentScipionProtocolId,
                    )

                if resolvedParentProtocolDbId in (None, ""):
                    raise ValueError(
                        "Parent protocol %s was not found in PostgreSQL"
                        % str(parentScipionProtocolId)
                    )

                outputInfo = protocolGraphRepository.getPostgresqlRuntimeOutputInfo(
                    mapper=mapper,
                    projectId=projectId,
                    parentProtocolDbId=int(resolvedParentProtocolDbId),
                    outputName=parentOutputName,
                )

                if not outputInfo.get("exists"):
                    if allowMissingParentOutputs:
                        itemReport["missingParentOutput"] = True
                        itemReport["missingParentOutputReason"] = "parent_output_not_produced_yet"
                    else:
                        raise ValueError(
                            "Parent output %s.%s was not found in PostgreSQL"
                            % (str(parentScipionProtocolId), parentOutputName)
                        )
                else:
                    try:
                        runtimeOutputObj = getattr(parentProtocol, parentOutputName, None)
                    except Exception:
                        runtimeOutputObj = None

                    if repairOutputRelationsCallback is not None:
                        relationRepairReport = repairOutputRelationsCallback(
                            mapper=mapper,
                            projectId=projectId,
                            parentProtocol=parentProtocol,
                            parentProtocolDbId=int(resolvedParentProtocolDbId),
                            parentScipionProtocolId=parentScipionProtocolId,
                            outputName=parentOutputName,
                            outputObj=runtimeOutputObj,
                            inputRefRows=rows,
                            currentInputName=inputName,
                        )

                        if relationRepairReport.get("checked"):
                            itemReport["runtimeOutputRelationRepair"] = relationRepairReport

                    try:
                        runtimeOutputObj = getattr(parentProtocol, parentOutputName, None)
                    except Exception:
                        runtimeOutputObj = None

                    if runtimeOutputObj is None:
                        runtimeOutputProxyService.attachPostgresqlRuntimeOutputProxy(
                            parentProtocol=parentProtocol,
                            outputName=parentOutputName,
                            outputInfo=outputInfo,
                            mapper=mapper,
                        )
                        itemReport["attachedProxy"] = True

                        try:
                            runtimeOutputObj = getattr(parentProtocol, parentOutputName, None)
                        except Exception:
                            runtimeOutputObj = None
                    else:
                        itemReport["attachedProxy"] = False
                        itemReport["keptRuntimeAttribute"] = True

                    itemReport["outputInfo"] = {
                        "kind": outputInfo.get("kind"),
                        "setId": outputInfo.get("setId"),
                        "objectId": outputInfo.get("objectId"),
                        "className": outputInfo.get("className"),
                        "itemClassName": outputInfo.get("itemClassName"),
                        "itemsCount": outputInfo.get("itemsCount"),
                    }

                    if repairOutputRelationsCallback is not None:
                        relationRepairReport = repairOutputRelationsCallback(
                            mapper=mapper,
                            projectId=projectId,
                            parentProtocol=parentProtocol,
                            parentProtocolDbId=int(resolvedParentProtocolDbId),
                            parentScipionProtocolId=parentScipionProtocolId,
                            outputName=parentOutputName,
                            outputObj=runtimeOutputObj,
                            inputRefRows=rows,
                            currentInputName=inputName,
                        )

                        if relationRepairReport.get("checked"):
                            itemReport["runtimeOutputRelationRepair"] = relationRepairReport

                param = protocol.getParam(inputName)

                if isinstance(param, MultiPointerParam):
                    # Do not rebuild the whole PointerList here yet. This helper is
                    # focused on normal PointerParam launch preparation.
                    # MultiPointer support can be added later if needed.
                    itemReport["pointerReset"] = False
                    itemReport["skippedPointerResetReason"] = "multipointer_not_rebuilt"
                else:
                    pointer = getattr(protocol, inputName, None)

                    if pointer is None or isinstance(pointer, str) or not hasattr(pointer, "set"):
                        pointer = Pointer(parentProtocol, extended=parentOutputName)
                        setattr(protocol, inputName, pointer)
                    else:
                        pointer.set(parentProtocol)
                        pointer.setExtended(parentOutputName)

                    itemReport["pointerReset"] = True

                preparedItems.append(itemReport)

            except Exception as e:
                logger.exception(
                    "Failed to prepare PostgreSQL runtime pointer output for launch. "
                    "projectId=%s protocolId=%s inputName=%s parentProtocolId=%s parentOutputName=%s",
                    projectId,
                    protocolId,
                    inputName,
                    parentProtocolId,
                    parentOutputName,
                )

                itemReport["error"] = str(e)
                errors.append(itemReport)

        report = {
            "protocolId": str(protocolId),
            "protocolDbId": int(protocolDbId),
            "prepared": len(preparedItems),
            "items": preparedItems,
            "errors": errors,
            "skipped": False,
        }

        logger.info(
            "Prepared PostgreSQL runtime pointer outputs for launch. "
            "projectId=%s protocolId=%s report=%s",
            projectId,
            protocolId,
            report,
        )

        return report