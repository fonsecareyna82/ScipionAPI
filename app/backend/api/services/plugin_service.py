import os
from typing import List, Dict, Optional
from urllib.parse import urljoin

from pyworkflow import Config
from pyworkflow.project import Manager
from scipion.install.plugin_funcs import PluginRepository, NULL_VERSION
from app.utils.scipion_helper import serializeToJson


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
                        logo = serializedPlugin['logo'].lstrip('/')
                        fullLogo = ''
                        if logo:
                            fullLogo = urljoin('https://scipion.i2pc.es/', logo)

                        serializedPlugin['fullLogo'] = fullLogo
                        serializedPlugin['installed'] = False
                        pluginBinaryList = pluginObj.getInstallenv()
                        if pluginBinaryList is not None:
                            binariesInstalled = 0
                            binaryList = pluginBinaryList.getPackages()
                            keys = sorted(binaryList.keys())
                            serializedPlugin.setdefault('binaries', {})
                            for k in keys:
                                pVersions = binaryList[k]
                                serializedPlugin['binaries'][k] = {}
                                for binary, version in pVersions:
                                    installed = pluginBinaryList._isInstalled(binary, version)
                                    serializedPlugin['binaries'][k][binary + '-' + version] = installed
                                    if installed:
                                        binariesInstalled += 1
                            if binariesInstalled:
                                serializedPlugin['installed'] = True
                    else:
                        serializedPlugin = serializeToJson(pluginObj)
                        logo = serializedPlugin['logo'].lstrip('/')
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

    def clearCache(self) -> None:
        """
        Clears the internal plugins cache.
        """
        self._pluginsCache = None
