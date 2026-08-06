"""Assembling the protocol graph (nodes + edges + per-protocol summaries)
shown in the workflow canvas, using PostgreSQL as the source of truth with
an optional live-runtime enrichment pass per node.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional

from app.backend.api.services.project.core.protocol_resolution import (
    tryGetScipionProtocolByRuntimeId,
)
from app.backend.runtime import RuntimeProtocolStatusSyncService


def toPersistedOutputInt(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None

    try:
        return int(value)
    except Exception:
        pass

    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def toPersistedOutputFloat(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None

    if isinstance(value, (list, tuple)) and value:
        value = value[0]

    try:
        return float(value)
    except Exception:
        pass

    text = str(value).strip()
    if not text:
        return None

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None

    try:
        return float(match.group(0))
    except Exception:
        return None


def formatProtocolElapsedSecondsFromPostgresql(value: Any) -> str:
    elapsedSeconds = toPersistedOutputFloat(value)
    if elapsedSeconds is None or elapsedSeconds <= 0:
        return ""

    return str(int(elapsedSeconds))


def _buildProtocolThumbnailUrl(projectId: int, protocolId: int) -> str:
    return f"/projects/{projectId}/protocols/{protocolId}/thumbnail"


def _buildProtocolThumbnailRebuildUrl(projectId: int, protocolId: int) -> str:
    return f"/projects/{projectId}/protocols/{protocolId}/thumbnail/rebuild"


def buildProtocolsGraph(
        currentProject,
        projectId: int,
        protocolRows: List[Dict[str, Any]],
        tags: Dict[str, List[str]],
        dependencyMap: Optional[Dict[str, Dict[str, List[str]]]] = None,
        runMap: Optional[Dict[str, Any]] = None,
        persistedOutputsByProtocolId: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
        protocolStepSummaryByProtocolId: Optional[Dict[str, Dict[str, Any]]] = None,
        inputRefsByProtocolId: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        allowRuntimeFallback: bool = True,
) -> dict:
    """Assemble protocol graph using PostgreSQL as source of truth for nodes + edges."""
    graphData: Dict[str, Any] = {}
    adjacency = dependencyMap or {}
    liveRuns = runMap or {}
    persistedOutputsByProtocolId = persistedOutputsByProtocolId or {}
    protocolStepSummaryByProtocolId = protocolStepSummaryByProtocolId or {}
    inputRefsByProtocolId = inputRefsByProtocolId or {}
    runtimeProtocolStatusSyncService = RuntimeProtocolStatusSyncService()

    def sortKey(row: Dict[str, Any]):
        raw = str(row.get("protocolId") or "")
        try:
            return (0, int(raw))
        except Exception:
            return (1, raw)

    orderedRows = sorted(protocolRows or [], key=sortKey)

    protocolIds: List[str] = []
    for row in orderedRows:
        rawId = row.get("protocolId")
        if rawId is None:
            continue
        protocolIds.append(str(rawId))

    # Root node synthesized from DB graph:
    # protocols without parents hang directly from PROJECT
    rootChildren = [
        pid for pid in protocolIds
        if not (adjacency.get(pid, {}).get("parents") or [])
    ]

    projectLabel = "PROJECT"
    try:
        if currentProject is not None:
            projectLabel = os.path.basename(currentProject.getPath()) or "PROJECT"
    except Exception:
        projectLabel = "PROJECT"

    graphData["PROJECT"] = {
        "protocolId": "PROJECT",
        "children": rootChildren,
        "parents": [],
        "label": projectLabel,
        "status": "",
        "parameter": [],
        "inputs": [],
        "outputs": [],
        "cpuTime": "",
        "elapsedTime": "",
        "isInteractive": False,
        "numberOfSteps": 0,
        "stepsDone": 0,
        "tags": [],
        "thumbnailUrl": None,
        "thumbnailRebuildUrl": None,
    }

    for row in orderedRows:
        rawNodeId = row.get("protocolId")
        if rawNodeId is None:
            continue

        nodeId = str(rawNodeId)
        persistedOutputsByName = persistedOutputsByProtocolId.get(nodeId, {})
        stepSummary = protocolStepSummaryByProtocolId.get(nodeId, {}) or {}
        persistedInputRefs = inputRefsByProtocolId.get(nodeId, [])
        nodeDeps = adjacency.get(nodeId, {"parents": [], "children": []})
        childrenIds = list(nodeDeps.get("children") or [])
        parentIds = list(nodeDeps.get("parents") or [])

        statusValue = row.get("status")
        status = str(statusValue) if statusValue is not None else ""

        protocolClassName = str(row.get("protocolClassName") or "")

        params = row.get("params") or {}
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {}

        if not isinstance(params, dict):
            params = {}

        runtimeMetadata = params.get(
            RuntimeProtocolStatusSyncService.RUNTIME_METADATA_KEY
        ) or {}

        if not isinstance(runtimeMetadata, dict):
            runtimeMetadata = {}

        def getParamValue(*names):
            for name in names:
                if name not in params:
                    continue

                value = params.get(name)

                if isinstance(value, dict):
                    for valueKey in (
                            "value",
                            "editableValue",
                            "default",
                            "objValue",
                            "_value",
                    ):
                        if valueKey in value:
                            value = value.get(valueKey)
                            break

                if value is None:
                    continue

                text = str(value).strip()
                if text and text.lower() not in ("none", "null"):
                    return text

            return ""

        storedRunName = getParamValue(
            "runName",
            "_runName",
        )

        storedTitle = getParamValue(
            "title",
            "_title",
            "objLabel",
            "_objLabel",
        )

        storedComment = getParamValue(
            "_objComment",
            "objComment",
            "comment",
            "_comment",
        )

        label = storedTitle or storedRunName or protocolClassName or nodeId

        inputs = []
        outputs = []
        seenOutputNames = set()

        cpuTime = formatProtocolElapsedSecondsFromPostgresql(
            runtimeMetadata.get("cpuTimeSeconds")
        )

        elapsedTimeSeconds = runtimeProtocolStatusSyncService.getEffectiveElapsedTimeSeconds(
            runtimeMetadata,
            status,
            fallbackElapsedSeconds=stepSummary.get("elapsedSeconds"),
        )
        elapsedTime = formatProtocolElapsedSecondsFromPostgresql(elapsedTimeSeconds)
        isinteractive = bool(stepSummary.get("isInteractive"))
        numberOfSteps = toPersistedOutputInt(
            stepSummary.get("numberOfSteps")
        ) or 0
        stepsDone = toPersistedOutputInt(
            stepSummary.get("stepsDone")
        ) or 0
        thumbnailUrl = None
        thumbnailRebuildUrl = None
        runName = storedRunName
        comment = storedComment
        title = storedTitle

        # Prefer the live protocol object coming from runs graph.
        # Runtime fallback is optional so the graph can be built from PostgreSQL only.
        protocol = liveRuns.get(nodeId)

        if protocol is None and allowRuntimeFallback:
            protocol = tryGetScipionProtocolByRuntimeId(currentProject, nodeId)

        if protocol is not None:
            try:
                runtimeLabel = str(protocol) or ""
                if runtimeLabel:
                    label = runtimeLabel
                    if not title:
                        title = runtimeLabel
            except Exception:
                pass

            try:
                runtimeRunName = protocol.runName.get()
                if runtimeRunName is None:
                    runtimeRunName = protocol.getRunName()

                runtimeRunName = str(runtimeRunName or "").strip()
                if runtimeRunName:
                    runName = runtimeRunName
            except Exception:
                pass

            try:
                comment = protocol._objComment
            except Exception:
                pass

            try:
                protStatus = protocol.getStatus()
                if protStatus:
                    status = str(protStatus)
            except Exception:
                pass

            try:
                liveRuntimeMetadata = (
                    RuntimeProtocolStatusSyncService()
                    .buildRuntimeMetadata(protocol)
                )

                liveCpuTime = liveRuntimeMetadata.get(
                    "cpuTimeSeconds"
                )

                if liveCpuTime is not None:
                    cpuTime = formatProtocolElapsedSecondsFromPostgresql(
                        liveCpuTime
                    )

                liveElapsedTimeSeconds = toPersistedOutputFloat(liveRuntimeMetadata.get("elapsedTimeSeconds"))
                persistedElapsedTimeSeconds = toPersistedOutputFloat(elapsedTimeSeconds)

                if liveElapsedTimeSeconds is not None:
                    elapsedTimeSeconds = max(persistedElapsedTimeSeconds or 0.0, liveElapsedTimeSeconds, 0.0)
                    elapsedTime = formatProtocolElapsedSecondsFromPostgresql(elapsedTimeSeconds)

            except Exception:
                pass

            try:
                isinteractive = bool(protocol.isInteractive())
            except Exception:
                isinteractive = False

            try:
                numberOfSteps = protocol.numberOfSteps
            except Exception:
                numberOfSteps = 0

            try:
                stepsDone = protocol.stepsDone
            except Exception:
                stepsDone = 0

            try:
                currentProject._fixProtParamsConfiguration(protocol)
            except Exception:
                pass

            try:
                protocolIdInt = int(nodeId)
                thumbnailUrl = _buildProtocolThumbnailUrl(projectId, protocolIdInt)
                thumbnailRebuildUrl = _buildProtocolThumbnailRebuildUrl(projectId, protocolIdInt)
            except Exception:
                thumbnailUrl = None
                thumbnailRebuildUrl = None

            try:
                for key, attr in protocol.iterInputAttributes():
                    inputItem = {}
                    try:
                        inputItem["name"] = key
                        inputItem["paramClass"] = "PointerParam"
                        inputItem["pointerClass"] = attr.get().getClassName() if attr and attr.get() else ""
                        inputItem["info"] = str(attr.get())
                    except Exception:
                        inputItem["pointerClass"] = ""
                        inputItem["info"] = ""

                    try:
                        parentId = attr.getObjValue().getObjId()
                        inputItem["value"] = "%s.%s" % (str(parentId), attr.getExtended())
                        inputItem["parentId"] = parentId
                    except Exception:
                        inputItem["value"] = ""
                        inputItem["parentId"] = None

                    inputs.append(inputItem)
            except Exception:
                inputs = []

            try:
                for key, attr in protocol.iterOutputAttributes():
                    outputName = str(key)
                    seenOutputNames.add(outputName)

                    outputItem = {}
                    outputItem["name"] = key
                    outputItem["paramClass"] = "PointerParam"
                    outputItem["pointerClass"] = attr.__class__.__name__

                    try:
                        outputItem["info"] = attr.__str__()
                    except Exception:
                        outputItem["info"] = ""

                    try:
                        parentId = protocol.getObjId()
                        outputItem["value"] = "%s.%s" % (str(parentId), key)
                        outputItem["parentId"] = parentId
                    except Exception:
                        outputItem["value"] = ""
                        outputItem["parentId"] = None

                    persistedOutput = persistedOutputsByName.get(outputName)
                    outputItem["persisted"] = bool(persistedOutput)
                    outputItem["persistence"] = persistedOutput
                    if not outputItem.get("info") and persistedOutput:
                        outputItem["info"] = persistedOutput.get("info") or ""

                    outputs.append(outputItem)

            except Exception:
                outputs = []
                seenOutputNames = set()

        else:
            try:
                protocolIdInt = int(nodeId)
                thumbnailUrl = _buildProtocolThumbnailUrl(projectId, protocolIdInt)
                thumbnailRebuildUrl = _buildProtocolThumbnailRebuildUrl(projectId, protocolIdInt)
            except Exception:
                thumbnailUrl = None
                thumbnailRebuildUrl = None

        if not inputs:
            for inputRef in persistedInputRefs:
                inputName = str(
                    inputRef.get("inputName") or ""
                ).strip()

                if not inputName:
                    continue

                parentProtocolId = inputRef.get("parentProtocolId")
                parentOutputName = str(
                    inputRef.get("parentOutputName") or ""
                ).strip()
                objectId = inputRef.get("objectId")

                value = ""

                if parentProtocolId not in (None, ""):
                    value = str(parentProtocolId)

                    if parentOutputName:
                        value = "%s.%s" % (
                            value,
                            parentOutputName,
                        )
                elif objectId not in (None, ""):
                    value = str(objectId)

                inputs.append({
                    "name": inputName,
                    "paramClass": "PointerParam",
                    "pointerClass": str(
                        inputRef.get("objectClassName") or ""
                    ),
                    "info": (
                            parentOutputName
                            or str(inputRef.get("objectClassName") or "")
                    ),
                    "value": value,
                    "parentId": parentProtocolId,
                    "itemIndex": int(
                        inputRef.get("itemIndex") or 0
                    ),
                    "objectId": objectId,
                    "persisted": True,
                })

        # Add persisted outputs even when there is no runtime protocol object.
        # If runtime already provided the output, only enrich that runtime output above.
        for outputName, persistedOutput in persistedOutputsByName.items():
            if outputName in seenOutputNames:
                continue

            outputs.append({
                "name": outputName,
                "paramClass": "PointerParam",
                "pointerClass": persistedOutput.get("className") or "",
                "info": persistedOutput.get("info") or "",
                "value": "%s.%s" % (nodeId, outputName),
                "parentId": nodeId,
                "persisted": True,
                "persistence": persistedOutput,
            })

        graphData[nodeId] = {
            "protocolId": nodeId,
            "children": childrenIds,
            "parents": parentIds,
            "label": label,
            "title": title,
            "runName": runName,
            "comment": comment,
            "status": status,
            "parameter": [],
            "inputs": inputs,
            "outputs": outputs,
            "cpuTime": cpuTime,
            "elapsedTime": elapsedTime,
            "isInteractive": isinteractive,
            "numberOfSteps": numberOfSteps,
            "stepsDone": stepsDone,
            "tags": tags.get(nodeId, []),
            "thumbnailUrl": thumbnailUrl,
            "thumbnailRebuildUrl": thumbnailRebuildUrl,
        }

    return graphData
