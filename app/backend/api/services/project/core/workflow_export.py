"""Building the JSON/header content for a workflow export (Scipion's
loadProtocols/exportProtocols native JSON, wrapped with a ScipionWeb
metadata header listing required plugins).
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from typing import Set as TypingSet

from fastapi import HTTPException, status

from app.backend.api.services.project.core.workflow_import import extractWorkflowJsonText


def sanitizeWorkflowHeaderValue(value: Any) -> str:
    return (
        str(value or "")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("|", "/")
        .replace(";", " ")
        .strip()
    )


def getProtocolPluginNameForExport(protocol: Any) -> str:
    try:
        plugin = protocol.getPlugin()
    except Exception:
        plugin = None

    if plugin is not None:
        try:
            name = plugin.getName()
            if name:
                return str(name).strip()
        except Exception:
            pass

        try:
            moduleName = getattr(plugin, "__name__", None)
            if moduleName:
                return str(moduleName).strip()
        except Exception:
            pass

    try:
        moduleName = protocol.__class__.__module__
        if moduleName:
            return str(moduleName).split(".")[0].strip()
    except Exception:
        pass

    return ""


def getProtocolClassNameForExport(protocol: Any) -> str:
    try:
        className = protocol.getClassName()
        if className:
            return str(className).strip()
    except Exception:
        pass

    try:
        return protocol.__class__.__name__
    except Exception:
        return ""


def getProtocolObjIdForExport(protocol: Any) -> str:
    try:
        objId = protocol.getObjId()
        if objId is not None:
            return str(objId).strip()
    except Exception:
        pass

    return ""


def buildWorkflowPluginMetadata(protocolList: List[Any]) -> Dict[str, Any]:
    protocolPlugins: List[Dict[str, str]] = []
    requiredPluginNames: List[str] = []
    seenPluginNames: TypingSet[str] = set()

    for protocol in protocolList or []:
        protocolId = getProtocolObjIdForExport(protocol)
        className = getProtocolClassNameForExport(protocol)
        pluginName = getProtocolPluginNameForExport(protocol)

        if pluginName and pluginName not in seenPluginNames:
            seenPluginNames.add(pluginName)
            requiredPluginNames.append(pluginName)

        protocolPlugins.append(
            {
                "protocolId": protocolId,
                "className": className,
                "pluginName": pluginName,
            }
        )

    requiredPluginNames.sort()

    return {
        "format": "scipionweb.workflow.export",
        "version": 1,
        "requiredPluginNames": requiredPluginNames,
        "protocolPlugins": protocolPlugins,
        "exportedAt": datetime.utcnow().isoformat() + "Z",
    }


def buildWorkflowTemplateHeader(protocolList: List[Any]) -> str:
    metadata = buildWorkflowPluginMetadata(protocolList)

    requiredPluginNames = [
        sanitizeWorkflowHeaderValue(name)
        for name in metadata.get("requiredPluginNames", [])
        if sanitizeWorkflowHeaderValue(name)
    ]

    lines = [
        "ScipionWeb metadata format: scipionweb.workflow.metadata",
        "ScipionWeb metadata version: 1",
        "ScipionWeb exported at UTC: %s" % sanitizeWorkflowHeaderValue(
            metadata.get("exportedAt", "")
        ),
        "Scipion required plugins: %s" % ", ".join(requiredPluginNames),
    ]

    return "\n".join(lines).rstrip() + "\n\n"


def decodeExportJsonPayload(rawExport: Any) -> Any:
    if isinstance(rawExport, str):
        text = rawExport.strip()
        if not text:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Scipion export returned empty content",
            )

        try:
            return json.loads(text)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Scipion export returned invalid JSON text: {e}",
            )

    if isinstance(rawExport, (list, dict)):
        return rawExport

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unsupported export payload returned by Scipion",
    )


def normalizeExportJsonContent(rawExport: Any) -> str:
    if isinstance(rawExport, str):
        text = rawExport.strip()
        if not text:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Scipion export returned empty content",
            )

        text = extractWorkflowJsonText(text)

        try:
            json.loads(text)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Scipion export returned invalid JSON text: {e}",
            )

        return text

    if isinstance(rawExport, (list, dict)):
        try:
            return json.dumps(rawExport, indent=2, ensure_ascii=False)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to serialize export payload: {e}",
            )

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unsupported export payload returned by Scipion",
    )


def buildWorkflowExportJsonContent(
        rawExport: Any,
        protocolList: List[Any],
) -> str:
    jsonContent = normalizeExportJsonContent(rawExport)
    header = buildWorkflowTemplateHeader(protocolList)

    return header + jsonContent


def normalizeProtocolIdsForExport(
        protocolIds: Optional[List[Union[int, str]]],
) -> List[str]:
    out: List[str] = []
    seen: TypingSet[str] = set()

    for raw in protocolIds or []:
        value = str(raw).strip()
        if not value or value.upper() == "PROJECT":
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)

    return out
