import importlib.metadata as importlibMetadata
import json
import logging
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from time import monotonic
from threading import Lock
from typing import List, Dict, Optional, Any
from urllib.parse import urljoin

from packaging.version import parse as parseVersion  # type: ignore
from packaging.utils import canonicalize_name

from pyworkflow.config import Config
from scipion.install.plugin_funcs import PluginRepository

from app.backend.api.services.plugin_devel_service import PluginDevelService
from app.backend.api.services.plugin_task_log import (
    appendPluginTaskLog,
    writePluginTaskMessage,
    writePluginTaskStep,
)
from app.backend.api.services.plugins_revision import getPluginsRevision
from app.backend.api.services.scipion_domain_refresh_service import refreshScipionDomain
from app.utils.scipion_helper import serializeToJson
from app.backend.resources import getPluginCategoryIds, getPluginCategoryData, getPluginCategoriesCatalog

logger = logging.getLogger(__name__)


class PluginService:
    def __init__(
        self,
        pluginRepository: Optional[PluginRepository] = None,
        pluginDevelService: Optional[PluginDevelService] = None,
    ):
        self.pluginRepository = pluginRepository or PluginRepository()
        self.pluginDevelService = pluginDevelService or PluginDevelService()
        self._pluginsCache: Optional[List[Dict[str, Any]]] = None
        self._rawPluginsCache: Optional[Dict[str, Any]] = None
        self._pluginsRevision = self._getPluginsRevision()
        self._cacheLock = Lock()
        self._logoBaseUrl = "https://scipion.i2pc.es/"

    @staticmethod
    def _getPluginsRevision() -> int:
        try:
            return int(getPluginsRevision() or 0)
        except Exception:
            return 0

    @staticmethod
    def _isPipPackageInstalled(pipName: str) -> bool:
        try:
            importlibMetadata.distribution(pipName)
            return True

        except importlibMetadata.PackageNotFoundError:
            return False

    @staticmethod
    def _getPipPackageVersion(pipName: str) -> Optional[str]:
        try:
            return str(
                importlibMetadata.version(
                    pipName
                )
            )

        except importlibMetadata.PackageNotFoundError:
            return None

    @staticmethod
    def _getInstalledPipVersions() -> Optional[Dict[str, str]]:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "list",
                    "--format=json",
                    "--disable-pip-version-check",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
                cwd=sys.prefix,
            )
            packages = json.loads(result.stdout or "[]")
        except Exception:
            logger.exception("Could not query installed pip packages from current environment.")
            return None

        versions: Dict[str, str] = {}

        for package in packages:
            if not isinstance(package, dict):
                continue

            name = str(package.get("name") or "").strip()
            version = str(package.get("version") or "").strip()

            if name:
                versions[canonicalize_name(name)] = version

        return versions

    def _getFreshPipPackageVersion(self, pipName: str) -> Optional[str]:
        installedVersions = self._getInstalledPipVersions()

        if installedVersions is None:
            return self._getPipPackageVersion(pipName)

        return installedVersions.get(canonicalize_name(pipName))

    def clearCache(self, reloadRepository: bool = True) -> None:
        with self._cacheLock:
            self._pluginsCache = None
            self._pluginsRevision = self._getPluginsRevision()

            if not reloadRepository:
                return

            try:
                refreshScipionDomain(
                    force=True
                )
            except Exception:
                logger.exception(
                    "Could not refresh Scipion domain after plugin change."
                )

            try:
                self.pluginRepository = PluginRepository()
            except Exception:
                logger.exception(
                    "Could not recreate PluginRepository after plugin change."
                )

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

    def _normalizePipName(self, pipName: str) -> str:
        return str(pipName or "").strip().lower()

    def _loadRawPlugins(self, forceRefresh: bool = False) -> Dict[str, Any]:
        if self._rawPluginsCache is not None and not forceRefresh:
            return dict(self._rawPluginsCache)

        try:
            rawPlugins = self.pluginRepository.getPlugins(getPipData=True)

            self._rawPluginsCache = dict(
                rawPlugins or {}
            )

            return dict(
                self._rawPluginsCache
            )

        except Exception as e:
            if self._rawPluginsCache is not None:
                logger.warning(
                    "Could not refresh remote plugin catalog. Reusing cached catalog.",
                    exc_info=True,
                )

                return dict(
                    self._rawPluginsCache
                )

            logger.exception(
                "Error retrieving plugins."
            )

            raise RuntimeError(
                "Failed to retrieve plugins"
            ) from e

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

    @staticmethod
    def _buildBinaryTarget(binaryName: str, version: str) -> str:
        cleanName = str(binaryName or "").strip()
        cleanVersion = str(version or "").strip()

        if not cleanName:
            return ""

        return (
            f"{cleanName}-{cleanVersion}"
            if cleanVersion
            else cleanName
        )

    def _getPluginBinaryDescriptors(
            self,
            pluginObj: Any,
    ) -> List[Dict[str, Any]]:
        try:
            environment = pluginObj.getInstallenv()
        except Exception:
            logger.debug(
                "Could not load plugin binary environment.",
                exc_info=True,
            )
            return []

        if environment is None:
            return []

        try:
            packages = environment.getPackages() or {}
        except Exception:
            logger.debug(
                "Could not read plugin binary packages.",
                exc_info=True,
            )
            return []

        binaries: List[Dict[str, Any]] = []

        for packageName in sorted(packages.keys()):
            packageVersions = packages.get(packageName) or []

            for binaryName, version in packageVersions:
                cleanName = str(binaryName or "").strip()
                cleanVersion = str(version or "").strip()
                target = self._buildBinaryTarget(
                    cleanName,
                    cleanVersion,
                )

                if not target:
                    continue

                installed = False

                try:
                    installed = bool(
                        environment._isInstalled(
                            binaryName,
                            version,
                        )
                    )
                except Exception:
                    logger.debug(
                        "Could not determine binary installation state: %s",
                        target,
                        exc_info=True,
                    )

                default = False

                try:
                    if environment.hasTarget(target):
                        default = bool(
                            environment
                            .getTarget(target)
                            .isDefault()
                        )
                except Exception:
                    logger.debug(
                        "Could not determine default binary target: %s",
                        target,
                        exc_info=True,
                    )

                binaries.append({
                    "name": cleanName,
                    "version": cleanVersion,
                    "target": target,
                    "installed": installed,
                    "default": default,
                })

        return binaries

    def _resolvePluginBinaryTarget(
            self,
            pluginName: str,
            binaryTarget: str,
    ):
        cleanTarget = str(
            binaryTarget or ""
        ).strip()

        if not cleanTarget:
            raise ValueError(
                "Binary target is required"
            )

        rawPlugins = self._loadRawPlugins(
            forceRefresh=True
        )

        resolvedKey = self._resolvePluginKeyByPipName(
            pluginName,
            rawPlugins,
        )

        plugin = rawPlugins[resolvedKey]

        environment = plugin.getInstallenv()

        if environment is None:
            raise KeyError(
                f"Plugin has no binaries: {pluginName}"
            )

        packages = (
            environment.getPackages()
            or {}
        )

        for packageName in sorted(
                packages.keys()
        ):
            packageVersions = (
                packages.get(packageName)
                or []
            )

            for binaryName, version in packageVersions:
                target = self._buildBinaryTarget(
                    binaryName,
                    version,
                )

                if target != cleanTarget:
                    continue

                return (
                    plugin,
                    environment,
                    str(binaryName or "").strip(),
                    str(version or "").strip(),
                )

        raise KeyError(
            f"Binary target not found for plugin {pluginName}: {cleanTarget}"
        )

    def _loadPackageMetadata(self, pipName: str) -> Dict[str, str]:
        try:
            metadata = importlibMetadata.metadata(pipName)
        except importlibMetadata.PackageNotFoundError:
            return {}
        except Exception:
            logger.debug("Could not read package metadata for %s", pipName, exc_info=True)
            return {}

        return {
            "name": metadata.get("Name", "") or "",
            "version": metadata.get("Version", "") or "",
            "summary": metadata.get("Summary", "") or "",
            "author": metadata.get("Author", "") or "",
            "email": metadata.get("Author-email", "") or "",
            "homePage": metadata.get("Home-page", "") or "",
        }

    def _splitTomlComment(self, line: str) -> str:
        inSingle = False
        inDouble = False
        escaped = False
        out = []

        for ch in line:
            if escaped:
                out.append(ch)
                escaped = False
                continue

            if ch == "\\" and inDouble:
                out.append(ch)
                escaped = True
                continue

            if ch == "'" and not inDouble:
                inSingle = not inSingle
                out.append(ch)
                continue

            if ch == '"' and not inSingle:
                inDouble = not inDouble
                out.append(ch)
                continue

            if ch == "#" and not inSingle and not inDouble:
                break

            out.append(ch)

        return "".join(out).strip()

    def _parseTomlScalar(self, value: str) -> Any:
        text = value.strip().rstrip(",").strip()
        if not text:
            return ""

        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            return text[1:-1]

        if text.startswith("[") and text.endswith("]"):
            return re.findall(r"['\"]([^'\"]+)['\"]", text)

        return text

    def _readPyprojectMetadata(self, pluginPath: Optional[str]) -> Dict[str, Any]:
        if not pluginPath:
            return {}

        pyprojectPath = Path(pluginPath).expanduser() / "pyproject.toml"
        if not pyprojectPath.exists():
            return {}

        try:
            text = pyprojectPath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            logger.debug("Could not read pyproject metadata: %s", pyprojectPath, exc_info=True)
            return {}

        sections: Dict[str, Dict[str, Any]] = {}
        currentSection = ""

        for rawLine in text.splitlines():
            line = self._splitTomlComment(rawLine)
            if not line:
                continue

            if line.startswith("[") and line.endswith("]"):
                currentSection = line.strip("[]").strip()
                sections.setdefault(currentSection, {})
                continue

            if not currentSection or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue

            sections.setdefault(currentSection, {})[key] = self._parseTomlScalar(value)

        project = sections.get("project", {})
        scipionweb = sections.get("tool.scipionweb", {})

        rawCategories = scipionweb.get("categories") or scipionweb.get("category") or []
        if isinstance(rawCategories, str):
            categories = [rawCategories]
        elif isinstance(rawCategories, list):
            categories = [str(x).strip() for x in rawCategories if str(x).strip()]
        else:
            categories = []

        return {
            "name": project.get("name") or "",
            "version": project.get("version") or "",
            "summary": scipionweb.get("summary") or project.get("description") or "",
            "displayName": scipionweb.get("display_name") or scipionweb.get("title") or "",
            "homePage": scipionweb.get("homepage") or scipionweb.get("home_page") or "",
            "logo": scipionweb.get("logo") or scipionweb.get("icon") or "",
            "categories": categories,
        }

    def _loadUserPluginMetadata(self) -> Dict[str, Dict[str, Any]]:
        try:
            metadataPath = self.pluginDevelService._getScipionHome() / "web" / "plugin_metadata.json"
        except Exception:
            return {}

        if not metadataPath.exists():
            return {}

        try:
            raw = json.loads(metadataPath.read_text(encoding="utf-8") or "{}")
        except Exception:
            logger.debug("Could not read plugin metadata file: %s", metadataPath, exc_info=True)
            return {}

        if not isinstance(raw, dict):
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        for pipName, metadata in raw.items():
            if isinstance(metadata, dict):
                result[self._normalizePipName(str(pipName))] = metadata
        return result

    def _coerceCategoryIds(self, rawValue: Any) -> List[str]:
        if rawValue is None:
            return []

        values = rawValue if isinstance(rawValue, list) else [rawValue]
        result: List[str] = []
        seen = set()

        for value in values:
            text = str(value or "").strip().lower()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)

        return result

    def _humanizeCategoryId(self, categoryId: str) -> str:
        return " ".join(part.capitalize() for part in re.split(r"[_\-]+", categoryId) if part) or categoryId

    def _buildCategoryDataFromIds(self, categoryIds: List[str]) -> List[Dict[str, Any]]:
        catalog = getPluginCategoriesCatalog()
        data: List[Dict[str, Any]] = []

        for categoryId in categoryIds:
            if categoryId in catalog:
                category = catalog[categoryId]
                data.append({
                    "id": categoryId,
                    "title": category.get("title", self._humanizeCategoryId(categoryId)),
                    "description": category.get("description", ""),
                })
            else:
                data.append({
                    "id": categoryId,
                    "title": self._humanizeCategoryId(categoryId),
                    "description": "Custom plugin category",
                })

        return data

    def _resolveCategories(self, pipName: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        metadata = metadata or {}
        categoryIds = self._coerceCategoryIds(metadata.get("categories"))

        if categoryIds:
            return {
                "categories": categoryIds,
                "categoryData": self._buildCategoryDataFromIds(categoryIds),
            }

        return {
            "categories": getPluginCategoryIds(pipName),
            "categoryData": getPluginCategoryData(pipName),
        }

    def _buildLocalMetadata(self, develPlugin: Dict[str, Any]) -> Dict[str, Any]:
        pipName = str(develPlugin.get("pipName") or "").strip()
        pluginPath = str(develPlugin.get("path") or "").strip()

        packageMetadata = self._loadPackageMetadata(pipName) if pipName else {}
        pyprojectMetadata = self._readPyprojectMetadata(pluginPath)
        userMetadata = self._loadUserPluginMetadata().get(self._normalizePipName(pipName), {})

        metadata: Dict[str, Any] = {}
        metadata.update(packageMetadata)
        metadata.update({k: v for k, v in pyprojectMetadata.items() if v not in (None, "", [])})
        metadata.update({k: v for k, v in userMetadata.items() if v not in (None, "", [])})
        return metadata

    def _buildMissingDevelPluginEntry(self, develPlugin: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        pipName = str(develPlugin.get("pipName") or "").strip()
        if not pipName:
            return None

        pluginPath = str(develPlugin.get("path") or "").strip()
        metadata = self._buildLocalMetadata(develPlugin)
        version = str(metadata.get("version") or "").strip()
        displayName = str(metadata.get("displayName") or metadata.get("name") or pipName).strip()
        summary = str(metadata.get("summary") or "Local devel plugin").strip()
        logo = str(metadata.get("logo") or "").strip()
        categoryInfo = self._resolveCategories(pipName, metadata)

        return {
            "author": metadata.get("author", ""),
            "binVersions": [],
            "compatibleReleases": {},
            "dirName": Path(pluginPath).name if pluginPath else pipName,
            "email": metadata.get("email", ""),
            "homePage": metadata.get("homePage", ""),
            "latestRelease": version or "local",
            "name": displayName,
            "pipName": pipName,
            "pipVersion": version or "local",
            "pluginEnv": "",
            "pluginSourceUrl": pluginPath,
            "remote": False,
            "summary": summary,
            "icon": logo,
            "iconUrl": logo,
            "fullLogo": self._buildFullLogo({"logo": logo}) if logo else "",
            "installed": True,
            "toUpdate": False,
            "installMode": "devel",
            "localPath": pluginPath,
            "devel": True,
            "develInstalledAt": develPlugin.get("installedAt", ""),
            "develUpdatedAt": develPlugin.get("updatedAt", ""),
            "binaries": [],
            "categories": categoryInfo["categories"],
            "categoryData": categoryInfo["categoryData"],
            "source": "devel",
        }

    def _appendMissingDevelPlugins(self, serializedList: List[Dict[str, Any]], seenPipNames: set) -> None:
        for develPlugin in self.pluginDevelService.listDevelPlugins():
            pipName = str(develPlugin.get("pipName") or "").strip()
            normalized = self._normalizePipName(pipName)
            if not normalized or normalized in seenPipNames:
                continue

            entry = self._buildMissingDevelPluginEntry(develPlugin)
            if not entry:
                continue

            seenPipNames.add(normalized)
            serializedList.append(entry)

    def _applyDevelMetadata(self, serializedPlugin: Dict[str, Any]) -> None:
        pipName = str(serializedPlugin.get("pipName") or "").strip()
        if not pipName:
            serializedPlugin["installMode"] = "standard"
            serializedPlugin["localPath"] = ""
            serializedPlugin["devel"] = False
            return

        develPlugin = self.pluginDevelService.getDevelPluginByPipName(pipName)
        if not develPlugin:
            serializedPlugin["installMode"] = "standard"
            serializedPlugin["localPath"] = ""
            serializedPlugin["devel"] = False
            return

        serializedPlugin["installMode"] = "devel"
        serializedPlugin["localPath"] = develPlugin.get("path", "")
        serializedPlugin["devel"] = True
        serializedPlugin["develInstalledAt"] = develPlugin.get("installedAt", "")
        serializedPlugin["develUpdatedAt"] = develPlugin.get("updatedAt", "")

    def getPlugins(self, forceRefresh: bool = False) -> List[Dict[str, Any]]:
        currentRevision = self._getPluginsRevision()

        if currentRevision != self._pluginsRevision:
            self.clearCache(
                reloadRepository=False
            )

        with self._cacheLock:
            if self._pluginsCache is not None and not forceRefresh:
                return list(self._pluginsCache)

            rawPlugins = self._loadRawPlugins(
                forceRefresh=forceRefresh
            )
            serializedList: List[Dict[str, Any]] = []
            seenPipNames = set()

            installedPipVersions = self._getInstalledPipVersions()

            for pluginKey in sorted(rawPlugins.keys(), reverse=True):
                pluginObj = rawPlugins.get(pluginKey)
                if pluginObj is None:
                    continue

                serializedPlugin = serializeToJson(pluginObj)
                serializedPlugin["fullLogo"] = self._buildFullLogo(serializedPlugin)
                pipName = str(serializedPlugin.get("pipName") or pluginKey).strip()
                categoryInfo = self._resolveCategories(pipName)
                serializedPlugin["categories"] = categoryInfo["categories"]
                serializedPlugin["categoryData"] = categoryInfo["categoryData"]

                # if 'tomography' not in categories:
                #     continue
                # serializedPlugin["categories"] = ['tomography']
                # serializedPlugin["categoryData"] = [{'description': 'Tomograms, tilt series and subtomogram workflows', 'id': 'tomography', 'title': 'Tomography'}]

                if installedPipVersions is None:
                    installedPipVersion = self._getPipPackageVersion(pipName)
                else:
                    installedPipVersion = installedPipVersions.get(canonicalize_name(pipName))

                isInstalled = installedPipVersion is not None

                serializedPlugin["installed"] = isInstalled

                if isInstalled:
                    serializedPlugin["pipVersion"] = installedPipVersion

                    latestRelease = getattr(
                        pluginObj,
                        "latestRelease",
                        None,
                    )

                    serializedPlugin["toUpdate"] = self._isUpdateAvailable(
                        latestRelease,
                        installedPipVersion,
                    )

                else:
                    serializedPlugin["pipVersion"] = ""
                    serializedPlugin["toUpdate"] = False

                self._applyDevelMetadata(serializedPlugin)

                serializedPlugin["binaries"] = (
                    self._getPluginBinaryDescriptors(
                        pluginObj
                    )
                    if isInstalled
                    else []
                )

                seenPipNames.add(self._normalizePipName(pipName))
                serializedList.append(serializedPlugin)

            self._appendMissingDevelPlugins(serializedList, seenPipNames)
            serializedList.sort(key=lambda plugin: str(plugin.get("pipName") or plugin.get("name") or "").lower(), reverse=True)

            self._pluginsCache = serializedList
            self._pluginsRevision = self._getPluginsRevision()

            return list(self._pluginsCache)

    def getPlugin(self, pluginName: str) -> Optional[Dict[str, Any]]:
        plugins = self.getPlugins()
        for plugin in plugins:
            if plugin.get("pipName") == pluginName:
                return plugin
        return None

    def installPlugin(
            self,
            pluginName: str,
            taskId: Optional[str] = None,
            skipBinaries: bool = False,
    ) -> Dict[str, Any]:
        plugin: Optional[Any] = None
        startedAt = monotonic()

        try:
            if taskId:
                writePluginTaskMessage(
                    taskId,
                    (
                        f"Installation requested: plugin={pluginName} "
                        f"skipBinaries={bool(skipBinaries)}"
                    ),
                )

                writePluginTaskStep(
                    taskId,
                    "Resolving plugin...",
                )

            rawPlugins = self._loadRawPlugins(
                forceRefresh=True
            )

            resolvedKey = self._resolvePluginKeyByPipName(
                pluginName,
                rawPlugins,
            )

            plugin = rawPlugins[resolvedKey]

            if taskId:
                writePluginTaskMessage(
                    taskId,
                    f"Plugin resolved: key={resolvedKey}",
                )

                writePluginTaskStep(
                    taskId,
                    "Installing pip module...",
                )

            pipStartedAt = monotonic()

            installed = plugin.installPipModule()

            pipElapsed = monotonic() - pipStartedAt

            if taskId:
                writePluginTaskMessage(
                    taskId,
                    (
                        "Pip installation stage completed "
                        f"in {pipElapsed:.2f}s "
                        f"(installationAction={bool(installed)})."
                    ),
                )

            if installed:
                if skipBinaries:
                    if taskId:
                        writePluginTaskStep(
                            taskId,
                            "Skipping binaries installation.",
                        )

                        writePluginTaskMessage(
                            taskId,
                            "Binary installation was disabled for this task.",
                        )

                else:
                    if taskId:
                        writePluginTaskStep(
                            taskId,
                            "Installing binaries...",
                        )

                        writePluginTaskMessage(
                            taskId,
                            "Starting plugin binary installation with 3 parallel jobs.",
                        )

                    binariesStartedAt = monotonic()

                    plugin.installBin({
                        "args": [
                            "-j",
                            "3",
                        ]
                    })

                    binariesElapsed = (
                            monotonic()
                            - binariesStartedAt
                    )

                    if taskId:
                        writePluginTaskMessage(
                            taskId,
                            (
                                "Binaries installation completed "
                                f"in {binariesElapsed:.2f}s."
                            ),
                        )

            else:
                if taskId:
                    writePluginTaskMessage(
                        taskId,
                        "Pip module reported no installation action.",
                    )

            if taskId:
                writePluginTaskStep(
                    taskId,
                    "Refreshing plugin catalog...",
                )

            self.clearCache()

            totalElapsed = (
                    monotonic()
                    - startedAt
            )

            if taskId:
                writePluginTaskStep(
                    taskId,
                    "Plugin installed successfully.",
                )

                writePluginTaskMessage(
                    taskId,
                    (
                        f"Installation completed successfully "
                        f"in {totalElapsed:.2f}s."
                    ),
                )

            return {
                "installed": "SUCCESS",
                "skipBinaries": bool(skipBinaries),
            }

        except Exception as error:
            totalElapsed = (
                    monotonic()
                    - startedAt
            )

            logger.exception(
                "Error installing the plugin."
            )

            if taskId:
                writePluginTaskMessage(
                    taskId,
                    (
                        f"Installation failed after "
                        f"{totalElapsed:.2f}s: "
                        f"{error.__class__.__name__}: {error}"
                    ),
                )

                appendPluginTaskLog(
                    taskId,
                    traceback.format_exc(),
                )

                writePluginTaskStep(
                    taskId,
                    "Rolling back installation...",
                )

            if plugin is not None:
                if not skipBinaries:
                    try:
                        plugin.uninstallBins()

                        if taskId:
                            writePluginTaskMessage(
                                taskId,
                                "Binary rollback completed.",
                            )

                    except Exception:
                        logger.exception(
                            "Error uninstalling binaries during install rollback."
                        )

                        if taskId:
                            writePluginTaskMessage(
                                taskId,
                                "Binary rollback failed.",
                            )

                            appendPluginTaskLog(
                                taskId,
                                traceback.format_exc(),
                            )

                try:
                    plugin.uninstallPip()

                    if taskId:
                        writePluginTaskMessage(
                            taskId,
                            "Pip rollback completed.",
                        )

                except Exception:
                    logger.exception(
                        "Error uninstalling pip module during install rollback."
                    )

                    if taskId:
                        writePluginTaskMessage(
                            taskId,
                            "Pip rollback failed.",
                        )

                        appendPluginTaskLog(
                            taskId,
                            traceback.format_exc(),
                        )

            raise

    def installPluginBinary(
            self,
            pluginName: str,
            binaryTarget: str,
            taskId: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self._getFreshPipPackageVersion(pluginName) is None:
            raise RuntimeError(
                f"Plugin is not installed: {pluginName}"
            )

        if taskId:
            writePluginTaskStep(
                taskId,
                "Resolving binary target...",
            )

        (
            plugin,
            environment,
            binaryName,
            version,
        ) = self._resolvePluginBinaryTarget(
            pluginName,
            binaryTarget,
        )

        cleanTarget = self._buildBinaryTarget(
            binaryName,
            version,
        )

        if environment._isInstalled(
                binaryName,
                version,
        ):
            if taskId:
                writePluginTaskStep(
                    taskId,
                    f"Binary {cleanTarget} is already installed.",
                )

            self.clearCache(
                reloadRepository=False
            )

            return {
                "installed": "SUCCESS",
                "pluginName": pluginName,
                "binaryTarget": cleanTarget,
                "alreadyInstalled": True,
            }

        if taskId:
            writePluginTaskStep(
                taskId,
                f"Installing binary {cleanTarget}...",
            )

        plugin.installBin({
            "args": [
                cleanTarget,
                "-j",
                "3",
            ]
        })

        if not environment._isInstalled(
                binaryName,
                version,
        ):
            raise RuntimeError(
                f"Binary is still not installed after installation: {cleanTarget}"
            )

        self.clearCache(
            reloadRepository=False
        )

        if taskId:
            writePluginTaskStep(
                taskId,
                f"Binary {cleanTarget} installed successfully.",
            )

        return {
            "installed": "SUCCESS",
            "pluginName": pluginName,
            "binaryTarget": cleanTarget,
            "alreadyInstalled": False,
        }

    def uninstallPluginBinary(
            self,
            pluginName: str,
            binaryTarget: str,
            taskId: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self._getFreshPipPackageVersion(pluginName) is None:
            raise RuntimeError(
                f"Plugin is not installed: {pluginName}"
            )

        if taskId:
            writePluginTaskStep(
                taskId,
                "Resolving binary target...",
            )

        (
            plugin,
            environment,
            binaryName,
            version,
        ) = self._resolvePluginBinaryTarget(
            pluginName,
            binaryTarget,
        )

        cleanTarget = self._buildBinaryTarget(
            binaryName,
            version,
        )

        if not environment._isInstalled(
                binaryName,
                version,
        ):
            if taskId:
                writePluginTaskStep(
                    taskId,
                    f"Binary {cleanTarget} is not installed.",
                )

            self.clearCache(
                reloadRepository=False
            )

            return {
                "uninstalled": "SUCCESS",
                "pluginName": pluginName,
                "binaryTarget": cleanTarget,
                "alreadyUninstalled": True,
            }

        if taskId:
            writePluginTaskStep(
                taskId,
                f"Uninstalling binary {cleanTarget}...",
            )

        plugin.uninstallBins([
            cleanTarget,
        ])

        if environment._isInstalled(
                binaryName,
                version,
        ):
            raise RuntimeError(
                f"Binary is still installed after uninstall: {cleanTarget}"
            )

        self.clearCache(
            reloadRepository=False
        )

        if taskId:
            writePluginTaskStep(
                taskId,
                f"Binary {cleanTarget} uninstalled successfully.",
            )

        return {
            "uninstalled": "SUCCESS",
            "pluginName": pluginName,
            "binaryTarget": cleanTarget,
            "alreadyUninstalled": False,
        }

    def uninstallPlugin(self, pluginName: str, taskId: Optional[str] = None) -> Dict[str, Any]:
        try:
            if taskId:
                writePluginTaskStep(taskId, "Resolving plugin...")

            rawPlugins = self._loadRawPlugins(
                forceRefresh=True
            )
            resolvedKey = self._resolvePluginKeyByPipName(pluginName, rawPlugins)
            plugin = rawPlugins[resolvedKey]

            isInstalled = self._getFreshPipPackageVersion(pluginName) is not None

            if isInstalled:
                if taskId:
                    writePluginTaskStep(taskId, "Uninstalling binaries...")
                plugin.uninstallBins()

                if taskId:
                    writePluginTaskStep(taskId, "Uninstalling pip module...")

                plugin.uninstallPip()

                if taskId:
                    writePluginTaskStep(taskId, "Verifying pip module removal...")

                if self._getFreshPipPackageVersion(pluginName) is not None:
                    raise RuntimeError(
                        "Plugin pip package is still installed after uninstall: %s"
                        % pluginName
                    )
            else:
                if taskId:
                    writePluginTaskStep(taskId, "Plugin is not installed. Nothing to do.")

            self.pluginDevelService.unregisterDevelPlugin(pluginName)
            self.clearCache()

            if taskId:
                writePluginTaskStep(taskId, "Plugin uninstalled successfully.")

            return {"uninstalled": "SUCCESS"}

        except Exception:
            logger.exception("Error uninstalling the plugin.")
            if taskId:
                appendPluginTaskLog(taskId, traceback.format_exc())
            raise
