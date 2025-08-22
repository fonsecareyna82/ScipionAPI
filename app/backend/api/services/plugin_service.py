import subprocess

import logging
from typing import List, Dict, Optional
from urllib.parse import urljoin

from pyworkflow import Config
from pyworkflow.project import Manager
from scipion.install.plugin_funcs import PluginRepository
from app.utils.scipion_helper import serializeToJson

logger = logging.getLogger(__name__)


class PluginService:
    """
    Manages loading and serialization of plugins.
    """

    def __init__(
        self,
        pluginRepository: Optional[PluginRepository] = None,
        projectManager: Optional[Manager] = None,
    ):
        # Use injected repository or default one
        self.pluginRepository = pluginRepository or PluginRepository()
        # Use injected manager or default project manager
        self.projectManager = projectManager or Manager()
        # Internal cache for serialized plugins
        self._pluginsCache: Optional[List[Dict]] = None

    def getPlugins(self, forceRefresh: bool = False) -> List[Dict]:
        """
        Returns the list of serialized plugins.
        If forceRefresh is True, reloads from the repository.
        """
        if self._pluginsCache is None or forceRefresh:
            try:
                # Fetch raw plugin objects including pip metadata
                rawPlugins = self.pluginRepository.getPlugins(getPipData=True)
                Config.setDomain("pwem")
                Config.getDomain()
            except Exception as e:
                # Raise a clear error when retrieval fails
                raise RuntimeError("Failed to retrieve plugins") from e

            serializedList: List[Dict] = []
            # Sort plugin names in reverse order and serialize each
            for pluginName in sorted(rawPlugins.keys(), reverse=True):
                pluginObj = rawPlugins[pluginName]
                if pluginObj is not None:
                    if pluginObj._getPlugin():
                        serializedPlugin = serializeToJson(pluginObj)
                        serializedPlugin['installed'] = True
                        serializedPlugin['toUpdate'] = False
                        if pluginObj.latestRelease != pluginObj.pipVersion:
                            serializedPlugin['toUpdate'] = True
                        logo = serializedPlugin['logo'].lstrip('/')
                        # https://scipion.i2pc.es/uploads/packages/scipion_logo.png
                        fullLogo = ''
                        if logo:
                            fullLogo = urljoin('https://scipion.i2pc.es/', logo)
                        serializedPlugin['fullLogo'] = fullLogo
                        pluginBinaryList = pluginObj.getInstallenv()
                        if pluginBinaryList is not None:
                            binaryList = pluginBinaryList.getPackages()
                            keys = sorted(binaryList.keys())
                            serializedPlugin.setdefault('binaries', {})
                            for k in keys:
                                pVersions = binaryList[k]
                                serializedPlugin['binaries'][k] = {}
                                for binary, version in pVersions:
                                    installed = pluginBinaryList._isInstalled(binary, version)
                                    serializedPlugin['binaries'][k][binary + '-' + version] = installed

                    else:
                        serializedPlugin = serializeToJson(pluginObj)
                        logo = serializedPlugin['logo'].lstrip('/')
                        # https://scipion.i2pc.es/uploads/packages/scipion_logo.png
                        fullLogo = ''
                        if logo:
                            fullLogo = urljoin('https://scipion.i2pc.es/', logo)

                        serializedPlugin['fullLogo'] = fullLogo
                        serializedPlugin['installed'] = False

                    serializedList.append(serializedPlugin)

            # Cache the result for subsequent calls
            self._pluginsCache = serializedList

        # Return a shallow copy to avoid external mutation
        return list(self._pluginsCache)

    def getPlugin(self, pluginName):
        plugins = self.getPlugins()
        for plugin in plugins:
            if plugin['pipName'] == pluginName:
                return plugin
        return None

    def clearCache(self) -> None:
        """
        Clears the internal plugins cache.
        """
        self._pluginsCache = None

    # def installPlugin(self, pluginName) -> dict:
    #     status = 'SUCCESS'
    #
    #     try:
    #         result = subprocess.run(
    #             ['./scipion3', 'installp', '-p', pluginName],
    #             capture_output=True,
    #             text=True
    #         )
    #         if result.returncode != 0:
    #             logger.error(f"Error installing plugin '{pluginName}': {result.stderr}")
    #             status = 'FAILURE'
    #         else:
    #             logger.info(f"Plugin '{pluginName}' installed successfully: {result.stdout}")
    #
    #     except Exception as e:
    #         logger.exception(f"Exception during plugin installation: {e}")
    #         status = 'FAILURE'
    #
    #     self.clearCache()
    #     self.getPlugins(forceRefresh=True)
    #
    #     return {'installed': status}

    def installPlugin(self, pluginName) -> dict:
        plugin = self.pluginRepository.getPlugins(getPipData=True)[pluginName]
        status = 'SUCCESS'
        # installing the plugin
        try:
            installed = plugin.installPipModule()
            if installed:
                plugin.installBin()
        except Exception as e:  # Rollback the installation
            plugin.uninstallBins()
            plugin.uninstallPip()
            logger.exception("Error installing the plugin.")
            status = 'FAILURE'
        self.clearCache()
        self.getPlugins(forceRefresh=True)
        return {'installed': status}

    def uninstallPlugin(self, pluginName) -> dict:
        plugin = self.pluginRepository.getPlugins()[pluginName]
        pluginClassName = plugin.getPluginClass().name
        status = 'SUCCESS'
        # installing the plugin
        try:
            if plugin.isInstalled():
                plugin.uninstallBins()
                plugin.uninstallPip()
        except Exception as e:
            logger.exception("Error uninstalling the plugin.")
            status = 'FAILURE'
        self.clearCache()
        self.getPlugins(forceRefresh=True)
        return {'uninstalled': status}
