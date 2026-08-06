"""Tracking protocol ids across a workflow import, sanitizing external
references, and remapping pointer/relation params from the workflow's
original ids onto the newly-imported protocols' real ids.
"""
import re
from typing import Any, Dict, List
from typing import Set as TypingSet


def getWorkflowProtocolItems(workflowContent: Any) -> List[Dict[str, Any]]:
    if isinstance(workflowContent, list):
        return [item for item in workflowContent if isinstance(item, dict)]

    if isinstance(workflowContent, dict):
        for key in ("workflow", "content", "protocols"):
            value = workflowContent.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def getWorkflowProtocolId(protocolItem: Dict[str, Any], fallbackIndex: int) -> str:
    protocolId = (
        protocolItem.get("object.id")
        or protocolItem.get("id")
        or protocolItem.get("_objId")
        or fallbackIndex
    )

    return str(protocolId).strip()


def collectWorkflowProtocolIds(workflowContent: Any) -> TypingSet[str]:
    protocolIds: TypingSet[str] = set()

    for index, protocolItem in enumerate(getWorkflowProtocolItems(workflowContent)):
        protocolId = getWorkflowProtocolId(protocolItem, index)
        if protocolId:
            protocolIds.add(protocolId)

    return protocolIds


def sanitizeWorkflowExternalReferences(workflowContent: Any) -> Any:
    copiedProtocolIds = collectWorkflowProtocolIds(workflowContent)
    if not copiedProtocolIds:
        return workflowContent

    dropValue = object()
    pointerPattern = re.compile(r"^\s*(\d+)\.([A-Za-z_][A-Za-z0-9_\.]*)\s*$")

    def sanitizeValue(value: Any) -> Any:
        if isinstance(value, str):
            match = pointerPattern.match(value)
            if match and match.group(1) not in copiedProtocolIds:
                return dropValue
            return value

        if isinstance(value, list):
            nextList = []
            for item in value:
                nextItem = sanitizeValue(item)
                if nextItem is not dropValue:
                    nextList.append(nextItem)
            return nextList

        if isinstance(value, dict):
            nextDict = {}
            for key, item in value.items():
                nextItem = sanitizeValue(item)
                if nextItem is not dropValue:
                    nextDict[key] = nextItem
            return nextDict

        return value

    return sanitizeValue(workflowContent)


def getImportedWorkflowProtocol(importedValue):
    if isinstance(importedValue, (tuple, list)) and importedValue:
        return importedValue[0]

    return importedValue


def remapImportedWorkflowPointerValue(
        rawValue: Any,
        importedProtocolIdMap: Dict[str, str],
) -> Any:
    if isinstance(rawValue, str):
        pointerValue = rawValue.strip()

        if "." not in pointerValue:
            return rawValue

        sourceParentId, outputName = pointerValue.split(".", 1)
        sourceParentId = sourceParentId.strip()
        outputName = outputName.strip()

        newParentId = importedProtocolIdMap.get(sourceParentId)

        if newParentId is None or not outputName:
            return rawValue

        return "%s.%s" % (newParentId, outputName)

    if isinstance(rawValue, list):
        return [
            remapImportedWorkflowPointerValue(item, importedProtocolIdMap)
            for item in rawValue
        ]

    if isinstance(rawValue, tuple):
        return [
            remapImportedWorkflowPointerValue(item, importedProtocolIdMap)
            for item in rawValue
        ]

    if isinstance(rawValue, dict):
        return {
            key: remapImportedWorkflowPointerValue(value, importedProtocolIdMap)
            for key, value in rawValue.items()
        }

    return rawValue


def workflowProtocolMapToProtocols(workflowProtocolMap) -> List[Any]:
    if not workflowProtocolMap:
        return []

    if isinstance(workflowProtocolMap, dict):
        protocols = []

        for value in workflowProtocolMap.values():
            if isinstance(value, (tuple, list)) and value:
                protocols.append(value[0])
            else:
                protocols.append(value)

        return protocols

    return list(workflowProtocolMap or [])


def buildImportedWorkflowPointerParamsByProtocolId(
        workflowContent: Any,
        importedProtocolMap: Dict[Any, Any],
        getScipionObjectIdCallback=None,
) -> Dict[str, Dict[str, Any]]:
    from pyworkflow.protocol.params import MultiPointerParam, PointerParam, RelationParam

    from app.backend.api.services.project.core.scipion_object_helpers import getScipionObjectId

    resolveObjectId = getScipionObjectIdCallback or getScipionObjectId

    workflowItemsBySourceId = {}

    for index, protocolItem in enumerate(getWorkflowProtocolItems(workflowContent)):
        sourceId = getWorkflowProtocolId(protocolItem, index)

        if sourceId:
            workflowItemsBySourceId[str(sourceId)] = protocolItem

    importedProtocolsBySourceId = {}
    importedProtocolIdMap = {}

    for rawSourceId, importedValue in (importedProtocolMap or {}).items():
        sourceId = str(rawSourceId).strip()
        protocol = getImportedWorkflowProtocol(importedValue)
        newProtocolId = resolveObjectId(protocol)

        if not sourceId or newProtocolId is None:
            continue

        importedProtocolsBySourceId[sourceId] = protocol
        importedProtocolIdMap[sourceId] = str(newProtocolId)

    pointerParamsByProtocolId = {}

    for sourceId, protocol in importedProtocolsBySourceId.items():
        protocolItem = workflowItemsBySourceId.get(sourceId)

        if not isinstance(protocolItem, dict):
            continue

        pointerParams = {}

        for paramName, rawValue in protocolItem.items():
            try:
                param = protocol.getParam(paramName)
            except Exception:
                param = None

            if not isinstance(
                    param,
                    (
                        PointerParam,
                        MultiPointerParam,
                        RelationParam,
                    ),
            ):
                continue

            pointerParams[paramName] = remapImportedWorkflowPointerValue(
                rawValue,
                importedProtocolIdMap,
            )

        if not pointerParams:
            continue

        newProtocolId = importedProtocolIdMap[sourceId]
        pointerParamsByProtocolId[newProtocolId] = pointerParams

    return pointerParamsByProtocolId
