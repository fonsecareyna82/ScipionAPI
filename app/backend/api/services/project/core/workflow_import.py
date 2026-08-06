"""Parsing/validating a workflow file for import: extracting embedded JSON,
checking required-plugin availability, and reading a ScipionWeb export
payload. Protocol-id/pointer-remapping concerns live in
workflow_pointer_remap.py.
"""
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from typing import Set as TypingSet
from uuid import uuid4

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


def extractWorkflowJsonText(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return raw

    if raw.startswith("[") or raw.startswith("{"):
        return raw

    lines = raw.splitlines()

    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("[") or stripped.startswith("{"):
            return "\n".join(lines[index:]).strip()

    return raw


def extractRequiredPluginNamesFromWorkflowText(text: str) -> List[str]:
    for line in str(text or "").splitlines():
        cleanLine = line.strip()

        if not cleanLine:
            continue

        if cleanLine.startswith("[") or cleanLine.startswith("{"):
            break

        match = re.match(
            r"^Scipion required plugins:\s*(.*)$",
            cleanLine,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        rawNames = match.group(1).strip()
        if not rawNames:
            return []

        names: List[str] = []
        seen: TypingSet[str] = set()

        for rawName in rawNames.split(","):
            name = rawName.strip()
            if not name or name in seen:
                continue

            seen.add(name)
            names.append(name)

        return names

    return []


def isWorkflowPluginAvailable(
        pluginName: str,
        availabilityCache: Optional[Dict[str, bool]] = None,
) -> bool:
    name = str(pluginName or "").strip()
    if not name:
        return True

    if availabilityCache is not None and name in availabilityCache:
        return availabilityCache[name]

    available = False

    try:
        import importlib.util
        available = importlib.util.find_spec(name) is not None
    except Exception:
        available = False

    if not available:
        try:
            __import__(name)
            available = True
        except Exception:
            available = False

    if availabilityCache is not None:
        availabilityCache[name] = available

    return available


def getMissingWorkflowPluginNames(
        requiredPluginNames: List[str],
        availabilityCache: Optional[Dict[str, bool]] = None,
) -> List[str]:
    missing: List[str] = []
    seen: TypingSet[str] = set()

    for rawPluginName in requiredPluginNames or []:
        pluginName = str(rawPluginName or "").strip()
        if not pluginName or pluginName in seen:
            continue

        seen.add(pluginName)

        if not isWorkflowPluginAvailable(
                pluginName,
                availabilityCache=availabilityCache,
        ):
            missing.append(pluginName)

    return missing


def validateWorkflowRequiredPlugins(
        requiredPluginNames: List[str],
        availabilityCache: Optional[Dict[str, bool]] = None,
) -> None:
    missing = getMissingWorkflowPluginNames(
        requiredPluginNames,
        availabilityCache=availabilityCache,
    )

    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing required plugins for workflow import: %s" % ", ".join(missing),
        )


def readWorkflowTemplateJsonPayload(workflowFile: Any) -> Optional[Any]:
    import json

    try:
        path = Path(str(workflowFile)).expanduser().resolve()
    except Exception:
        return None

    if not path.exists() or not path.is_file():
        return None

    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return None

    if not text:
        return None

    try:
        return json.loads(text)
    except Exception:
        return None


def isScipionWebWorkflowExportPayload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    metadata = payload.get("scipionWeb")
    if not isinstance(metadata, dict):
        return False

    return metadata.get("format") == "scipionweb.workflow.export" and "content" in payload


def getRequiredPluginNamesFromWorkflowPayload(payload: Dict[str, Any]) -> List[str]:
    metadata = payload.get("scipionWeb") or {}
    rawNames = metadata.get("requiredPluginNames") or []

    names: List[str] = []
    seen: TypingSet[str] = set()

    for rawName in rawNames:
        name = str(rawName or "").strip()
        if not name or name in seen:
            continue

        seen.add(name)
        names.append(name)

    return names


def normalizeWorkflowImportErrors(result: Any) -> List[str]:
    if result is None:
        return []

    if isinstance(result, dict):
        rawErrors = result.get("errors") or result.get("error") or result.get("detail")
        if rawErrors is None:
            return []
        if isinstance(rawErrors, list):
            return [str(item) for item in rawErrors if str(item).strip()]
        return [str(rawErrors)] if str(rawErrors).strip() else []

    if isinstance(result, (list, tuple, set)):
        return [str(item) for item in result if str(item).strip()]

    text = str(result).strip()
    return [text] if text else []


def getWorkflowImportSourceProjectId(payload: Any, workflowPayload: Any) -> Optional[str]:
    sourceProjectId = getattr(payload, "sourceProjectId", None)

    if sourceProjectId is None and isinstance(workflowPayload, dict):
        sourceProjectId = workflowPayload.get("sourceProjectId")

        metadata = workflowPayload.get("scipionWeb")
        if sourceProjectId is None and isinstance(metadata, dict):
            sourceProjectId = metadata.get("sourceProjectId")

    if sourceProjectId is None:
        return None

    sourceProjectIdText = str(sourceProjectId).strip()
    return sourceProjectIdText or None


def sortProtocolIds(protocolIds: TypingSet[str]) -> List[str]:
    def sortKey(value: str):
        try:
            return (0, int(value))
        except Exception:
            return (1, str(value))

    return sorted(protocolIds, key=sortKey)


def unwrapWorkflowImportPayload(
        workflowPayload: Any,
        validateWorkflowRequiredPluginsCallback=None,
) -> Any:
    if workflowPayload is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing workflow",
        )

    validatePlugins = validateWorkflowRequiredPluginsCallback or validateWorkflowRequiredPlugins

    if isinstance(workflowPayload, dict):
        metadata = workflowPayload.get("scipionWeb")
        if isinstance(metadata, dict):
            requiredPluginNames = [
                str(name).strip()
                for name in metadata.get("requiredPluginNames", []) or []
                if str(name).strip()
            ]
            validatePlugins(requiredPluginNames)

        if "workflow" in workflowPayload:
            return workflowPayload.get("workflow")

        if "content" in workflowPayload:
            return workflowPayload.get("content")

    return workflowPayload


def getInstalledPluginNamesForWorkflowImport(currentProject) -> TypingSet[str]:
    installedNames: TypingSet[str] = set()

    try:
        from app.backend.api.services.plugin_service import PluginService

        plugins = PluginService().getPlugins(forceRefresh=False)
        for plugin in plugins or []:
            if not isinstance(plugin, dict):
                continue

            if not plugin.get("installed"):
                continue

            for key in ("name", "pipName", "pluginName", "moduleName", "packageName"):
                value = plugin.get(key)
                if value:
                    installedNames.add(str(value).strip())
    except Exception:
        logger.debug("Could not load installed plugin names from PluginService", exc_info=True)

    try:
        domain = currentProject.getDomain()
        rawPlugins = getattr(domain, "getPlugins", lambda: {})() or {}

        if isinstance(rawPlugins, dict):
            for key, plugin in rawPlugins.items():
                if key:
                    installedNames.add(str(key).strip())

                try:
                    pluginName = plugin.getName()
                    if pluginName:
                        installedNames.add(str(pluginName).strip())
                except Exception:
                    pass
    except Exception:
        logger.debug("Could not load installed plugin names from Scipion domain", exc_info=True)

    return {name for name in installedNames if name}


def prepareWorkflowFileForImport(
        workflowFile: Any,
        validateWorkflowRequiredPluginsCallback=None,
) -> Dict[str, Any]:
    import json

    validatePlugins = validateWorkflowRequiredPluginsCallback or validateWorkflowRequiredPlugins

    payload = readWorkflowTemplateJsonPayload(workflowFile)

    # Backward compatibility with previous ScipionWeb wrapper exports.
    if isScipionWebWorkflowExportPayload(payload):
        assert isinstance(payload, dict)

        requiredPluginNames = getRequiredPluginNamesFromWorkflowPayload(payload)
        validatePlugins(requiredPluginNames)

        content = payload.get("content")
        if not isinstance(content, (list, dict)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid ScipionWeb workflow export: content must be a JSON list or object.",
            )

        sourcePath = Path(str(workflowFile)).expanduser().resolve()
        tempPath = sourcePath.parent / (
            ".scipionweb-import-%s.json" % uuid4().hex
        )

        try:
            tempPath.write_text(
                json.dumps(content, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to prepare workflow import file: %s" % e,
            )

        return {
            "workflowFile": str(tempPath),
            "cleanupFile": str(tempPath),
            "wrapped": True,
            "hasScipionWebMetadata": True,
            "requiredPluginNames": requiredPluginNames,
        }

    requiredPluginNames: List[str] = []
    resolvedPath: Optional[Path] = None

    try:
        resolvedPath = Path(str(workflowFile)).expanduser().resolve()
    except Exception:
        resolvedPath = None

    if resolvedPath is not None and resolvedPath.exists() and resolvedPath.is_file():
        try:
            text = resolvedPath.read_text(encoding="utf-8")
            requiredPluginNames = extractRequiredPluginNamesFromWorkflowText(text)
        except Exception:
            requiredPluginNames = []

    validatePlugins(requiredPluginNames)

    return {
        "workflowFile": str(resolvedPath) if resolvedPath is not None else workflowFile,
        "cleanupFile": None,
        "wrapped": False,
        "hasScipionWebMetadata": bool(requiredPluginNames),
        "requiredPluginNames": requiredPluginNames,
    }


def getCurrentWorkflowProtocolIds(currentProject) -> TypingSet[str]:
    try:
        runs = currentProject.getRunsGraph(refresh=True, checkPids=False)
        nodesDict = getattr(runs, "_nodesDict", {}) or {}
    except Exception:
        return set()

    return {
        str(nodeId)
        for nodeId in nodesDict.keys()
        if str(nodeId) != "PROJECT"
    }
