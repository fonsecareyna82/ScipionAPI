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

    monkeypatch.setattr(service, "_loadRawPlugins", lambda: {})
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
        lambda: {
            "scipion-em-test": plugin,
        },
    )

    monkeypatch.setattr(
        service,
        "clearCache",
        lambda: clearCacheCalls.append(True),
    )

    monkeypatch.setattr(
        pluginServiceModule.importlibMetadata,
        "distribution",
        lambda pipName: object(),
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
        lambda: {
            "scipion-em-test": plugin,
        },
    )

    monkeypatch.setattr(
        service,
        "clearCache",
        lambda: clearCacheCalls.append(True),
    )

    def distributionNotFound(pipName):
        raise pluginServiceModule.importlibMetadata.PackageNotFoundError(pipName)

    monkeypatch.setattr(
        pluginServiceModule.importlibMetadata,
        "distribution",
        distributionNotFound,
    )

    result = service.uninstallPlugin("scipion-em-test")

    assert result == {
        "uninstalled": "SUCCESS",
    }

    assert plugin.uninstallBinsCalls == 1
    assert plugin.uninstallPipCalls == 1
    assert service.pluginDevelService.listDevelPlugins() == []
    assert clearCacheCalls == [True]


