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

from app.backend.runtime.protocol_status_sync_service import RuntimeProtocolStatusSyncService


logger = logging.getLogger(__name__)


class RuntimeProtocolWorkflowExecutionService:
    VALID_MODES = {"continue", "restart"}
    VALID_SCOPES = {"single", "all"}

    @staticmethod
    def _normalizeValue(value, allowedValues, fieldName):
        normalizedValue = str(value or "").strip().lower()

        if normalizedValue not in allowedValues:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid workflow execution %s: %s" % (fieldName, value))

        return normalizedValue

    @staticmethod
    def _workflowItems(workflowProtocolMap):
        items = []
        values = workflowProtocolMap.values() if isinstance(workflowProtocolMap, dict) else workflowProtocolMap or []

        for value in values:
            protocol = value[0] if isinstance(value, (tuple, list)) and value else value
            level = int(value[1]) if isinstance(value, (tuple, list)) and len(value) > 1 else 0

            if protocol is not None:
                items.append((protocol, level))

        items.sort(key=lambda item: (item[1], int(item[0].getObjId())))

        return items

    @staticmethod
    def _getProtocolDisplayName(protocol):
        runNameObject = getattr(protocol, "runName", None)
        runNameGetter = getattr(runNameObject, "get", None)
        runName = runNameGetter() if callable(runNameGetter) else None

        if not runName:
            runName = getattr(protocol, "getRunName", lambda: None)()

        if not runName:
            runName = str(protocol)

        return str(runName)

    def buildPreflight(self, *, mapper, projectId: int, protocolId, mode, getPostgresqlRuntimeSubworkflowCallback: Callable) -> Dict[str, Any]:
        mode = self._normalizeValue(mode, self.VALID_MODES, "mode")
        workflowProtocolMap = getPostgresqlRuntimeSubworkflowCallback(mapper=mapper, projectId=projectId, protocolId=protocolId)
        affectedProtocols = []
        selectedProtocol = None

        for protocol, level in self._workflowItems(workflowProtocolMap):
            protocolRuntimeId = str(protocol.getObjId())
            protocolStatus = str(protocol.getStatus() or "").strip().lower()
            item = {"protocolId": protocolRuntimeId, "runName": self._getProtocolDisplayName(protocol), "status": protocolStatus, "level": int(level), "active": protocolStatus in RuntimeProtocolStatusSyncService.ACTIVE_STATUS_TEXTS}

            if int(level) == 0 and selectedProtocol is None:
                selectedProtocol = item
                continue

            affectedProtocols.append(item)

        return {"protocolId": str((selectedProtocol or {}).get("protocolId") or protocolId), "mode": mode, "requiresConfirmation": bool(affectedProtocols), "selectedProtocol": selectedProtocol, "affectedProtocols": affectedProtocols, "activeProtocolIds": [item["protocolId"] for item in affectedProtocols if item["active"]]}

    def executeWorkflow(self, *, mapper, projectId: int, protocolId, protocolClassName: str, params, mode, scope, prepareRootProtocolCallback: Callable, resetDescendantsCallback: Callable, executeSingleCallback: Callable, executeAllCallback: Callable) -> Dict[str, Any]:
        mode = self._normalizeValue(mode, self.VALID_MODES, "mode")
        scope = self._normalizeValue(scope, self.VALID_SCOPES, "scope")
        prepareInfo = prepareRootProtocolCallback(mapper=mapper, projectId=projectId, protocolId=protocolId, protocolClassName=protocolClassName, params=params, persist=scope == "all")
        resetInfo = None

        if scope == "single":
            resetInfo = resetDescendantsCallback(mapper=mapper, projectId=projectId, protocolId=protocolId, includeRoot=False)
            executionInfo = executeSingleCallback(mapper=mapper, projectId=projectId, protocolId=protocolId, protocolClassName=protocolClassName, params=params, executeMode=mode)
        else:
            executionInfo = executeAllCallback(mapper=mapper, projectId=projectId, protocolId=protocolId, mode=mode)

        result = dict(executionInfo or {})
        result["workflowExecution"] = {"mode": mode, "scope": scope, "rootPreparation": prepareInfo, "descendantReset": resetInfo}

        return result