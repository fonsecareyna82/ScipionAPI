import logging
import traceback
from threading import Lock
from typing import List, Dict, Optional, Any
from urllib.parse import urljoin

from packaging.version import parse as parseVersion  # type: ignore

from pyworkflow.config import Config
from scipion.install.plugin_funcs import PluginRepository

from app.backend.api.services.plugin_task_log import appendPluginTaskLog, writePluginTaskStep
from app.utils.scipion_helper import serializeToJson

logger = logging.getLogger(__name__)


class PluginService:
    def __init__(
        self,
        pluginRepository: Optional[PluginRepository] = None,
    ):
        self.pluginRepository = pluginRepository or PluginRepository()
        self._pluginsCache: Optional[List[Dict[str, Any]]] = None
        self._cacheLock = Lock()
        self._logoBaseUrl = "https://scipion.i2pc.es/"

    def clearCache(self) -> None:
        self._pluginsCache = None

    def _buildFullLogo(self, serializedPlugin: Dict[str, Any]) -> str:
        logo = (serializedPlugin.get("logo") or "").lstrip("/")
        return urljoin(self._logoBaseUrl, logo) if logo else ""

    def _isUpdateAvailable(self, latestRelease: Optional[str], pipVersion: Optional[str]) -> bool:
        if not latestRelease or not pipVersion:
            return False
        try:
            return parseVersion(latestRelease) > parseVersion(pipVersion)
        except Exception:
            return False

    def _loadRawPlugins(self) -> Dict[str, Any]:
        try:
            Config.setDomain("pwem")
            Config.getDomain()
            return self.pluginRepository.getPlugins(getPipData=True)
        except Exception as e:
            raise RuntimeError("Failed to retrieve plugins") from e

    def _resolvePluginKeyByPipName(self, pipName: str, rawPlugins: Dict[str, Any]) -> str:
        if pipName in rawPlugins:
            return pipName

        for key, pluginObj in rawPlugins.items():
            try:
                candidate = getattr(pluginObj, "pipName", None)
                if isinstance(candidate, str) and candidate == pipName:
                    return key
            except Exception:
                continue

        raise KeyError(f"Plugin not found: {pipName}")

    def getPlugins(self, forceRefresh: bool = False) -> List[Dict[str, Any]]:
        with self._cacheLock:
            if self._pluginsCache is not None and not forceRefresh:
                return list(self._pluginsCache)

            rawPlugins = self._loadRawPlugins()
            serializedList: List[Dict[str, Any]] = []

            for pluginKey in sorted(rawPlugins.keys(), reverse=True):
                pluginObj = rawPlugins.get(pluginKey)
                if pluginObj is None:
                    continue

                serializedPlugin = serializeToJson(pluginObj)
                serializedPlugin["fullLogo"] = self._buildFullLogo(serializedPlugin)

                isInstalled = False
                try:
                    isInstalled = bool(pluginObj._getPlugin())
                except Exception:
                    isInstalled = False

                serializedPlugin["installed"] = isInstalled

                if isInstalled:
                    latestRelease = getattr(pluginObj, "latestRelease", None)
                    pipVersion = getattr(pluginObj, "pipVersion", None)
                    serializedPlugin["toUpdate"] = self._isUpdateAvailable(latestRelease, pipVersion)
                else:
                    serializedPlugin["toUpdate"] = False

                try:
                    pluginBinaryList = pluginObj.getInstallenv()
                    if pluginBinaryList is not None:
                        binaryList = pluginBinaryList.getPackages()
                        keys = sorted(binaryList.keys())
                        serializedPlugin.setdefault("binaries", {})
                        for k in keys:
                            pVersions = binaryList[k]
                            serializedPlugin["binaries"][k] = {}
                            for binary, version in pVersions:
                                installed = pluginBinaryList._isInstalled(binary, version)
                                serializedPlugin["binaries"][k][f"{binary}-{version}"] = bool(installed)
                except Exception:
                    pass

                serializedList.append(serializedPlugin)

            self._pluginsCache = serializedList
            return list(self._pluginsCache)

    def getPlugin(self, pluginName: str) -> Optional[Dict[str, Any]]:
        plugins = self.getPlugins()
        for plugin in plugins:
            if plugin.get("pipName") == pluginName:
                return plugin
        return None

    def installPlugin(self, pluginName: str, taskId: Optional[str] = None) -> Dict[str, Any]:
        plugin: Optional[Any] = None

        try:
            if taskId:
                writePluginTaskStep(taskId, "Resolving plugin...")

            rawPlugins = self._loadRawPlugins()
            resolvedKey = self._resolvePluginKeyByPipName(pluginName, rawPlugins)
            plugin = rawPlugins[resolvedKey]

            if taskId:
                writePluginTaskStep(taskId, "Installing pip module...")

            installed = plugin.installPipModule()

            if installed:
                if taskId:
                    writePluginTaskStep(taskId, "Installing binaries...")
                plugin.installBin({"args": ["-j", "3"]})
            else:
                if taskId:
                    writePluginTaskStep(taskId, "Pip module reported no installation action.")

            self.clearCache()

            if taskId:
                writePluginTaskStep(taskId, "Plugin installed successfully.")

            return {"installed": "SUCCESS"}

        except Exception:
            logger.exception("Error installing the plugin.")

            if taskId:
                appendPluginTaskLog(taskId, traceback.format_exc())
                writePluginTaskStep(taskId, "Rolling back installation...")

            if plugin is not None:
                try:
                    plugin.uninstallBins()
                except Exception:
                    logger.exception("Error uninstalling binaries during install rollback.")
                    if taskId:
                        appendPluginTaskLog(taskId, traceback.format_exc())

                try:
                    plugin.uninstallPip()
                except Exception:
                    logger.exception("Error uninstalling pip module during install rollback.")
                    if taskId:
                        appendPluginTaskLog(taskId, traceback.format_exc())

            raise

    def uninstallPlugin(self, pluginName: str, taskId: Optional[str] = None) -> Dict[str, Any]:
        try:
            if taskId:
                writePluginTaskStep(taskId, "Resolving plugin...")

            rawPlugins = self._loadRawPlugins()
            resolvedKey = self._resolvePluginKeyByPipName(pluginName, rawPlugins)
            plugin = rawPlugins[resolvedKey]

            isInstalled = False
            try:
                isInstalled = bool(plugin.isInstalled())
            except Exception:
                isInstalled = False

            if isInstalled:
                if taskId:
                    writePluginTaskStep(taskId, "Uninstalling binaries...")
                plugin.uninstallBins()

                if taskId:
                    writePluginTaskStep(taskId, "Uninstalling pip module...")
                plugin.uninstallPip()
            else:
                if taskId:
                    writePluginTaskStep(taskId, "Plugin is not installed. Nothing to do.")

            self.clearCache()

            if taskId:
                writePluginTaskStep(taskId, "Plugin uninstalled successfully.")

            return {"uninstalled": "SUCCESS"}

        except Exception:
            logger.exception("Error uninstalling the plugin.")
            if taskId:
                appendPluginTaskLog(taskId, traceback.format_exc())
            raise