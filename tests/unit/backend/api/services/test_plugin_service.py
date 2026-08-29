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
from pathlib import Path
from threading import Lock

import pytest

import app.backend.api.services.plugin_service as pluginServiceModule
from app.backend.api.services.plugin_service import PluginService


class DummyDevelService:
    def __init__(self, scipionHome: Path, plugins=None):
        self._scipionHome = scipionHome
        self._plugins = plugins or []

    def _getScipionHome(self):
        return self._scipionHome

    def listDevelPlugins(self):
        return list(self._plugins)

    def getDevelPluginByPipName(self, pipName):
        for plugin in self._plugins:
            if plugin.get("pipName") == pipName:
                return plugin
        return None

    def unregisterDevelPlugin(self, pipName):
        self._plugins = [
            plugin
            for plugin in self._plugins
            if plugin.get("pipName") != pipName
        ]


def makeService(tmpPath: Path, plugins=None) -> PluginService:
    service = PluginService.__new__(PluginService)
    service.pluginRepository = None
    service.pluginDevelService = DummyDevelService(tmpPath, plugins=plugins)
    service._pluginsCache = None
    service._rawPluginsCache = None
    service._pluginsRevision = 0
    service._cacheLock = Lock()
    service._logoBaseUrl = "https://scipion.i2pc.es/"
    return service


def test_reads_scipionweb_metadata_from_pyproject(tmp_path):
    pluginPath = tmp_path / "scipion-em-local"
    pluginPath.mkdir()
    (pluginPath / "pyproject.toml").write_text(
        """
[project]
name = "scipion-em-local"
version = "0.1.0"
description = "Project description"

[tool.scipionweb]
categories = ["tomography", "custom-cat"]
display_name = "Local Plugin"
summary = "ScipionWeb summary"
homepage = "https://example.org/local"
logo = "static/logo.png"
""".strip(),
        encoding="utf-8",
    )

    service = makeService(tmp_path)

    metadata = service._readPyprojectMetadata(str(pluginPath))

    assert metadata["name"] == "scipion-em-local"
    assert metadata["version"] == "0.1.0"
    assert metadata["displayName"] == "Local Plugin"
    assert metadata["summary"] == "ScipionWeb summary"
    assert metadata["homePage"] == "https://example.org/local"
    assert metadata["logo"] == "static/logo.png"
    assert metadata["categories"] == ["tomography", "custom-cat"]


def test_user_metadata_overrides_pyproject_metadata(tmp_path):
    pluginPath = tmp_path / "scipion-em-local"
    pluginPath.mkdir()
    (pluginPath / "pyproject.toml").write_text(
        """
[project]
name = "scipion-em-local"
version = "0.1.0"
description = "Project description"

[tool.scipionweb]
categories = ["tomography"]
display_name = "Pyproject Plugin"
summary = "Pyproject summary"
""".strip(),
        encoding="utf-8",
    )

    metadataPath = tmp_path / "web" / "plugin_metadata.json"
    metadataPath.parent.mkdir()
    metadataPath.write_text(
        """
{
  "scipion-em-local": {
    "displayName": "User Plugin",
    "summary": "User summary",
    "categories": ["custom"]
  }
}
""".strip(),
        encoding="utf-8",
    )

    service = makeService(
        tmp_path,
        plugins=[{"pipName": "scipion-em-local", "path": str(pluginPath)}],
    )

    metadata = service._buildLocalMetadata({"pipName": "scipion-em-local", "path": str(pluginPath)})

    assert metadata["displayName"] == "User Plugin"
    assert metadata["summary"] == "User summary"
    assert metadata["categories"] == ["custom"]


def test_get_plugins_includes_missing_devel_plugins(tmp_path, monkeypatch):
    pluginPath = tmp_path / "scipion-em-local"
    pluginPath.mkdir()
    (pluginPath / "pyproject.toml").write_text(
        """
[project]
name = "scipion-em-local"
version = "0.2.0"
description = "Local plugin description"

[tool.scipionweb]
categories = ["tomography"]
display_name = "Local Plugin"
summary = "Local plugin summary"
""".strip(),
        encoding="utf-8",
    )

    service = makeService(
        tmp_path,
        plugins=[
            {
                "pipName": "scipion-em-local",
                "path": str(pluginPath),
                "installedAt": "2026-06-01T10:00:00",
                "updatedAt": "2026-06-01T11:00:00",
            }
        ],
    )

    monkeypatch.setattr(service, "_loadRawPlugins", lambda forceRefresh=False: {})
    monkeypatch.setattr(service, "_loadPackageMetadata", lambda pipName: {})
    monkeypatch.setattr(
        service,
        "_resolveCategories",
        lambda pipName, metadata=None: {
            "categories": (metadata or {}).get("categories") or ["unclassified"],
            "categoryData": [
                {
                    "id": ((metadata or {}).get("categories") or ["unclassified"])[0],
                    "title": "Tomography",
                    "description": "Test category",
                }
            ],
        },
    )

    plugins = service.getPlugins(forceRefresh=True)

    assert len(plugins) == 1
    plugin = plugins[0]
    assert plugin["pipName"] == "scipion-em-local"
    assert plugin["name"] == "Local Plugin"
    assert plugin["summary"] == "Local plugin summary"
    assert plugin["pipVersion"] == "0.2.0"
    assert plugin["installed"] is True
    assert plugin["devel"] is True
    assert plugin["installMode"] == "devel"
    assert plugin["localPath"] == str(pluginPath)
    assert plugin["categories"] == ["tomography"]


def test_existing_repository_plugins_are_not_duplicated_by_devel_manifest(tmp_path, monkeypatch):
    pluginPath = tmp_path / "scipion-em-local"
    pluginPath.mkdir()

    service = makeService(
        tmp_path,
        plugins=[{"pipName": "scipion-em-local", "path": str(pluginPath)}],
    )

    serializedList = [{"pipName": "scipion-em-local", "name": "Catalog Plugin"}]
    seenPipNames = {"scipion-em-local"}

    monkeypatch.setattr(service, "_buildMissingDevelPluginEntry", lambda develPlugin: {"pipName": develPlugin["pipName"]})

    service._appendMissingDevelPlugins(serializedList, seenPipNames)

    assert serializedList == [{"pipName": "scipion-em-local", "name": "Catalog Plugin"}]


class DummyCatalogPlugin:
    latestRelease = "1.0.0"
    pipVersion = "1.0.0"

    def isInstalled(self):
        raise AssertionError(
            "PluginInfo installation state must not be used"
        )

    def _getPlugin(self):
        return None

    def getInstallenv(self):
        return None


def test_get_plugins_uses_pip_installation_state(tmp_path, monkeypatch):
    service = makeService(tmp_path)
    plugin = DummyCatalogPlugin()

    monkeypatch.setattr(
        service,
        "_getPluginsRevision",
        lambda: 0,
    )

    monkeypatch.setattr(
        service,
        "_loadRawPlugins",
        lambda forceRefresh=False: {
            "scipion-em-test": plugin,
        },
    )

    monkeypatch.setattr(
        pluginServiceModule,
        "serializeToJson",
        lambda pluginObj: {
            "pipName": "scipion-em-test",
            "name": "Test Plugin",
        },
    )

    monkeypatch.setattr(
        service,
        "_resolveCategories",
        lambda pipName, metadata=None: {
            "categories": [
                "unclassified",
            ],
            "categoryData": [],
        },
    )

    monkeypatch.setattr(
        service,
        "_getInstalledPipVersions",
        lambda: {
            "scipion-em-test": "1.0.0",
        },
    )

    plugins = service.getPlugins(
        forceRefresh=True
    )

    assert len(plugins) == 1
    assert plugins[0]["pipName"] == "scipion-em-test"
    assert plugins[0]["installed"] is True
    assert plugins[0]["pipVersion"] == "1.0.0"


class DummyInstalledPlugin:
    def __init__(self):
        self.uninstallBinsCalls = 0
        self.uninstallPipCalls = 0

    def isInstalled(self):
        return True

    def uninstallBins(self):
        self.uninstallBinsCalls += 1

    def uninstallPip(self):
        self.uninstallPipCalls += 1


def test_uninstall_plugin_fails_if_pip_package_remains_installed(tmp_path, monkeypatch):
    service = makeService(tmp_path)
    plugin = DummyInstalledPlugin()
    clearCacheCalls = []

    monkeypatch.setattr(
        service,
        "_loadRawPlugins",
        lambda forceRefresh=False: {
            "scipion-em-test": plugin,
        },
    )

    monkeypatch.setattr(
        service,
        "clearCache",
        lambda: clearCacheCalls.append(True),
    )

    monkeypatch.setattr(
        service,
        "_getInstalledPipVersions",
        lambda: {
            "scipion-em-test": "1.0.0",
        },
    )

    with pytest.raises(
        RuntimeError,
        match="Plugin pip package is still installed after uninstall",
    ):
        service.uninstallPlugin("scipion-em-test")

    assert plugin.uninstallBinsCalls == 1
    assert plugin.uninstallPipCalls == 1
    assert clearCacheCalls == []


def test_uninstall_plugin_refreshes_after_confirmed_pip_removal(tmp_path, monkeypatch):
    service = makeService(
        tmp_path,
        plugins=[
            {
                "pipName": "scipion-em-test",
                "path": str(tmp_path / "scipion-em-test"),
            }
        ],
    )
    plugin = DummyInstalledPlugin()
    clearCacheCalls = []

    monkeypatch.setattr(
        service,
        "_loadRawPlugins",
        lambda forceRefresh=False: {
            "scipion-em-test": plugin,
        },
    )

    monkeypatch.setattr(
        service,
        "clearCache",
        lambda: clearCacheCalls.append(True),
    )

    installedState = {
        "installed": True,
    }

    def uninstallPip():
        plugin.uninstallPipCalls += 1
        installedState["installed"] = False

    def getInstalledPipVersions():
        if installedState["installed"]:
            return {
                "scipion-em-test": "1.0.0",
            }

        return {}

    monkeypatch.setattr(
        service,
        "_getInstalledPipVersions",
        getInstalledPipVersions,
    )

    monkeypatch.setattr(
        plugin,
        "uninstallPip",
        uninstallPip,
    )

    result = service.uninstallPlugin("scipion-em-test")

    assert result == {
        "uninstalled": "SUCCESS",
    }

    assert plugin.uninstallBinsCalls == 1
    assert plugin.uninstallPipCalls == 1
    assert service.pluginDevelService.listDevelPlugins() == []
    assert clearCacheCalls == [True]


def test_get_plugins_refreshes_installation_state_without_reloading_remote_catalog(tmp_path, monkeypatch):
    service = makeService(tmp_path)
    plugin = DummyCatalogPlugin()

    service._rawPluginsCache = {
        "scipion-em-test": plugin,
    }

    monkeypatch.setattr(
        service,
        "_getPluginsRevision",
        lambda: 0,
    )

    monkeypatch.setattr(
        pluginServiceModule,
        "serializeToJson",
        lambda pluginObj: {
            "pipName": "scipion-em-test",
            "name": "Test Plugin",
        },
    )

    monkeypatch.setattr(
        service,
        "_resolveCategories",
        lambda pipName, metadata=None: {
            "categories": [
                "unclassified",
            ],
            "categoryData": [],
        },
    )

    installedVersion = {
        "value": None,
    }

    def getInstalledPipVersions():
        version = installedVersion["value"]

        if version is None:
            return {}

        return {
            "scipion-em-test": version,
        }

    monkeypatch.setattr(
        service,
        "_getInstalledPipVersions",
        getInstalledPipVersions,
    )

    plugins = service.getPlugins()

    assert plugins[0]["installed"] is False

    installedVersion["value"] = "1.2.3"
    service._pluginsCache = None

    plugins = service.getPlugins()

    assert plugins[0]["installed"] is True
    assert plugins[0]["pipVersion"] == "1.2.3"

    installedVersion["value"] = None
    service._pluginsCache = None

    plugins = service.getPlugins()

    assert plugins[0]["installed"] is False
    assert plugins[0]["pipVersion"] == ""


def test_load_raw_plugins_falls_back_to_cached_catalog(tmp_path):
    service = makeService(tmp_path)

    cachedPlugin = object()

    service._rawPluginsCache = {
        "scipion-em-test": cachedPlugin,
    }

    class FailingRepository:
        def getPlugins(self, getPipData=False):
            raise ConnectionError(
                "remote catalog unavailable"
            )

    service.pluginRepository = FailingRepository()

    plugins = service._loadRawPlugins(
        forceRefresh=True
    )

    assert plugins == {
        "scipion-em-test": cachedPlugin,
    }



class DummyBinaryTarget:
    def __init__(self, default=False):
        self.default = default

    def isDefault(self):
        return self.default


class DummyBinaryEnvironment:
    def __init__(self):
        self.installed = {
            ("imod", "4.11.25"): False,
            ("imod", "5.1.9"): True,
            ("teamtomoBRT", "0.1.2"): False,
        }

        self.targets = {
            "imod-4.11.25": DummyBinaryTarget(False),
            "imod-5.1.9": DummyBinaryTarget(True),
            "teamtomoBRT-0.1.2": DummyBinaryTarget(False),
        }

    def getPackages(self):
        return {
            "imod": [
                ("imod", "4.11.25"),
                ("imod", "5.1.9"),
            ],
            "teamtomoBRT": [
                ("teamtomoBRT", "0.1.2"),
            ],
        }

    def _isInstalled(self, binaryName, version):
        return self.installed.get(
            (
                str(binaryName),
                str(version),
            ),
            False,
        )

    def hasTarget(self, target):
        return target in self.targets

    def getTarget(self, target):
        return self.targets[target]


class DummyBinaryPlugin:
    latestRelease = "1.0.0"

    def __init__(self):
        self.environment = DummyBinaryEnvironment()
        self.installBinCalls = []
        self.uninstallBinsCalls = []

    def getInstallenv(self):
        return self.environment

    def installBin(self, args):
        self.installBinCalls.append(args)

        target = args["args"][0]

        for binaryName, version in self.environment.installed:
            expectedTarget = (
                f"{binaryName}-{version}"
                if version
                else binaryName
            )

            if expectedTarget == target:
                self.environment.installed[
                    (
                        binaryName,
                        version,
                    )
                ] = True

    def uninstallBins(self, binaryTargets):
        self.uninstallBinsCalls.append(
            list(binaryTargets)
        )

        for target in binaryTargets:
            for binaryName, version in self.environment.installed:
                expectedTarget = (
                    f"{binaryName}-{version}"
                    if version
                    else binaryName
                )

                if expectedTarget == target:
                    self.environment.installed[
                        (
                            binaryName,
                            version,
                        )
                    ] = False


def test_get_plugins_exposes_structured_binary_targets(
        tmp_path,
        monkeypatch,
):
    service = makeService(tmp_path)
    plugin = DummyBinaryPlugin()

    monkeypatch.setattr(
        service,
        "_getPluginsRevision",
        lambda: 0,
    )

    monkeypatch.setattr(
        service,
        "_loadRawPlugins",
        lambda forceRefresh=False: {
            "scipion-em-test": plugin,
        },
    )

    monkeypatch.setattr(
        pluginServiceModule,
        "serializeToJson",
        lambda pluginObj: {
            "pipName": "scipion-em-test",
            "name": "Test Plugin",
        },
    )

    monkeypatch.setattr(
        service,
        "_resolveCategories",
        lambda pipName, metadata=None: {
            "categories": [],
            "categoryData": [],
        },
    )

    monkeypatch.setattr(
        service,
        "_getInstalledPipVersions",
        lambda: {
            "scipion-em-test": "1.0.0",
        },
    )

    plugins = service.getPlugins(
        forceRefresh=True
    )

    assert plugins[0]["binaries"] == [
        {
            "name": "imod",
            "version": "4.11.25",
            "target": "imod-4.11.25",
            "installed": False,
            "default": False,
        },
        {
            "name": "imod",
            "version": "5.1.9",
            "target": "imod-5.1.9",
            "installed": True,
            "default": True,
        },
        {
            "name": "teamtomoBRT",
            "version": "0.1.2",
            "target": "teamtomoBRT-0.1.2",
            "installed": False,
            "default": False,
        },
    ]


def test_install_plugin_binary_executes_only_requested_target(
        tmp_path,
        monkeypatch,
):
    service = makeService(tmp_path)
    plugin = DummyBinaryPlugin()
    clearCacheCalls = []

    monkeypatch.setattr(
        service,
        "_getFreshPipPackageVersion",
        lambda pipName: "1.0.0",
    )

    monkeypatch.setattr(
        service,
        "_loadRawPlugins",
        lambda forceRefresh=False: {
            "scipion-em-test": plugin,
        },
    )

    monkeypatch.setattr(
        service,
        "clearCache",
        lambda reloadRepository=True: clearCacheCalls.append(
            reloadRepository
        ),
    )

    result = service.installPluginBinary(
        "scipion-em-test",
        "imod-4.11.25",
    )

    assert result == {
        "installed": "SUCCESS",
        "pluginName": "scipion-em-test",
        "binaryTarget": "imod-4.11.25",
        "alreadyInstalled": False,
    }

    assert plugin.installBinCalls == [
        {
            "args": [
                "imod-4.11.25",
                "-j",
                "3",
            ]
        }
    ]

    assert plugin.environment._isInstalled(
        "imod",
        "4.11.25",
    ) is True

    assert clearCacheCalls == [
        False,
    ]


def test_uninstall_plugin_binary_removes_only_requested_target(
        tmp_path,
        monkeypatch,
):
    service = makeService(tmp_path)
    plugin = DummyBinaryPlugin()
    clearCacheCalls = []

    monkeypatch.setattr(
        service,
        "_getFreshPipPackageVersion",
        lambda pipName: "1.0.0",
    )

    monkeypatch.setattr(
        service,
        "_loadRawPlugins",
        lambda forceRefresh=False: {
            "scipion-em-test": plugin,
        },
    )

    monkeypatch.setattr(
        service,
        "clearCache",
        lambda reloadRepository=True: clearCacheCalls.append(
            reloadRepository
        ),
    )

    result = service.uninstallPluginBinary(
        "scipion-em-test",
        "imod-5.1.9",
    )

    assert result == {
        "uninstalled": "SUCCESS",
        "pluginName": "scipion-em-test",
        "binaryTarget": "imod-5.1.9",
        "alreadyUninstalled": False,
    }

    assert plugin.uninstallBinsCalls == [
        [
            "imod-5.1.9",
        ]
    ]

    assert plugin.environment._isInstalled(
        "imod",
        "5.1.9",
    ) is False

    assert clearCacheCalls == [
        False,
    ]


def test_plugin_binary_operation_rejects_unknown_target(
        tmp_path,
        monkeypatch,
):
    service = makeService(tmp_path)
    plugin = DummyBinaryPlugin()

    monkeypatch.setattr(
        service,
        "_getFreshPipPackageVersion",
        lambda pipName: "1.0.0",
    )

    monkeypatch.setattr(
        service,
        "_loadRawPlugins",
        lambda forceRefresh=False: {
            "scipion-em-test": plugin,
        },
    )

    with pytest.raises(
        KeyError,
        match="Binary target not found",
    ):
        service.installPluginBinary(
            "scipion-em-test",
            "relion-5.0",
        )

    assert plugin.installBinCalls == []


class DummyInstallPlugin:
    def __init__(self):
        self.installPipCalls = 0
        self.installBinCalls = []
        self.uninstallBinsCalls = 0
        self.uninstallPipCalls = 0

    def installPipModule(self):
        self.installPipCalls += 1
        return True

    def installBin(self, args):
        self.installBinCalls.append(args)

    def uninstallBins(self):
        self.uninstallBinsCalls += 1

    def uninstallPip(self):
        self.uninstallPipCalls += 1


def test_uninstall_plugin_ignores_stale_in_process_metadata(tmp_path, monkeypatch):
    service = makeService(
        tmp_path,
        plugins=[
            {
                "pipName": "scipion-em-test",
                "path": str(tmp_path / "scipion-em-test"),
            }
        ],
    )
    plugin = DummyInstalledPlugin()
    clearCacheCalls = []

    monkeypatch.setattr(
        service,
        "_loadRawPlugins",
        lambda forceRefresh=False: {
            "scipion-em-test": plugin,
        },
    )

    monkeypatch.setattr(
        service,
        "_getInstalledPipVersions",
        lambda: {},
    )

    monkeypatch.setattr(
        pluginServiceModule.importlibMetadata,
        "distribution",
        lambda pipName: object(),
    )

    monkeypatch.setattr(
        service,
        "clearCache",
        lambda: clearCacheCalls.append(True),
    )

    result = service.uninstallPlugin("scipion-em-test")

    assert result == {"uninstalled": "SUCCESS"}
    assert plugin.uninstallBinsCalls == 0
    assert plugin.uninstallPipCalls == 0
    assert service.pluginDevelService.listDevelPlugins() == []
    assert clearCacheCalls == [True]


def test_install_plugin_reports_detailed_task_progress(
        tmp_path,
        monkeypatch,
):
    service = makeService(tmp_path)

    plugin = DummyInstallPlugin()

    taskSteps = []
    taskMessages = []

    monkeypatch.setattr(
        service,
        "_loadRawPlugins",
        lambda forceRefresh=False: {
            "scipion-em-test": plugin,
        },
    )

    monkeypatch.setattr(
        service,
        "clearCache",
        lambda: None,
    )

    monkeypatch.setattr(
        pluginServiceModule,
        "writePluginTaskStep",
        lambda taskId, step: taskSteps.append(step),
    )

    monkeypatch.setattr(
        pluginServiceModule,
        "writePluginTaskMessage",
        lambda taskId, message: taskMessages.append(message),
    )

    result = service.installPlugin(
        "scipion-em-test",
        taskId="task-1",
        skipBinaries=False,
    )

    assert result == {
        "installed": "SUCCESS",
        "skipBinaries": False,
    }

    assert plugin.installPipCalls == 1

    assert plugin.installBinCalls == [{
        "args": [
            "-j",
            "3",
        ]
    }]

    assert taskSteps == [
        "Resolving plugin...",
        "Installing pip module...",
        "Installing binaries...",
        "Refreshing plugin catalog...",
        "Plugin installed successfully.",
    ]

    assert any(
        message.startswith(
            "Installation requested:"
        )
        for message in taskMessages
    )

    assert any(
        message.startswith(
            "Pip installation stage completed in "
        )
        for message in taskMessages
    )

    assert any(
        message.startswith(
            "Binaries installation completed in "
        )
        for message in taskMessages
    )

    assert any(
        message.startswith(
            "Installation completed successfully in "
        )
        for message in taskMessages
    )



def test_clear_cache_can_skip_domain_refresh(
        tmp_path,
        monkeypatch,
):
    service = makeService(
        tmp_path
    )

    refreshCalls = []
    recreatedRepository = object()

    monkeypatch.setattr(
        pluginServiceModule,
        "refreshScipionDomain",
        lambda force=False:
        refreshCalls.append(force),
    )

    monkeypatch.setattr(
        pluginServiceModule,
        "PluginRepository",
        lambda: recreatedRepository,
    )

    service.clearCache(
        refreshDomain=False
    )

    assert refreshCalls == []

    assert (
        service.pluginRepository
        is recreatedRepository
    )


