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
import importlib.metadata
import os
import socket
import sys
import types

# app.workers.task_queue transitively imports app.backend.database, which
# requires DATABASE_URL to be set at import time. Locally this is normally
# populated by task_queue.py's own load_dotenv(scipion_home/.env), but a
# fresh CI checkout has no scipion_home/.env, so it must be set explicitly
# here before the import below. The tests in this module never touch the
# database, so a placeholder value is sufficient (SQLAlchemy engines are
# lazy and do not connect at import/construction time).
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://test:test@localhost/test",
)

from pyworkflow.plugin import Domain

import app.workers.task_queue as taskQueueModule


def test_ReportNodeCapabilitiesReturnsGpusAndInstalledPlugins(monkeypatch):
    settingsServiceModule = types.ModuleType(
        "app.backend.api.services.settings_service"
    )
    settingsServiceModule._getNvidiaGpuResources = lambda: [
        {"index": 0, "name": "RTX 4090", "memoryTotalBytes": 25000000000},
    ]

    monkeypatch.setitem(
        sys.modules,
        "app.backend.api.services.settings_service",
        settingsServiceModule,
    )

    monkeypatch.setattr(
        Domain,
        "getPlugins",
        classmethod(lambda cls: {"warp": object(), "relion": object()}),
    )

    def fakeVersion(pluginName):
        if pluginName == "warp":
            return "3.6.3"
        raise importlib.metadata.PackageNotFoundError(pluginName)

    monkeypatch.setattr(
        importlib.metadata,
        "version",
        fakeVersion,
    )

    result = taskQueueModule.report_node_capabilities(state=None)

    assert result["hostname"] == socket.gethostname()
    assert result["gpuCount"] == 1
    assert result["gpus"] == [{"index": 0, "name": "RTX 4090", "memoryTotalBytes": 25000000000}]
    assert result["plugins"] == [
        {"pipName": "relion", "name": "relion", "pipVersion": ""},
        {"pipName": "warp", "name": "warp", "pipVersion": "3.6.3"},
    ]


def test_ReportNodeCapabilitiesReturnsErrorPayloadWhenGpuLookupFails(monkeypatch):
    settingsServiceModule = types.ModuleType(
        "app.backend.api.services.settings_service"
    )

    def raiseError():
        raise RuntimeError("nvidia-smi not found")

    settingsServiceModule._getNvidiaGpuResources = raiseError

    monkeypatch.setitem(
        sys.modules,
        "app.backend.api.services.settings_service",
        settingsServiceModule,
    )

    result = taskQueueModule.report_node_capabilities(state=None)

    assert result["hostname"] == socket.gethostname()
    assert "nvidia-smi not found" in result["error"]


def test_ReportNodeCapabilitiesToleratesLocalPluginRegistryFailure(monkeypatch):
    settingsServiceModule = types.ModuleType(
        "app.backend.api.services.settings_service"
    )
    settingsServiceModule._getNvidiaGpuResources = lambda: []

    monkeypatch.setitem(
        sys.modules,
        "app.backend.api.services.settings_service",
        settingsServiceModule,
    )

    def raiseError(cls):
        raise RuntimeError("plugin registry unavailable")

    monkeypatch.setattr(
        Domain,
        "getPlugins",
        classmethod(raiseError),
    )

    result = taskQueueModule.report_node_capabilities(state=None)

    assert result["hostname"] == socket.gethostname()
    assert result["gpuCount"] == 0
    assert result["plugins"] == []
    assert "error" not in result


def test_ListInstalledPluginsFromLocalDomainRegistryNeverImportsPluginService(monkeypatch):
    # This is the exact regression this module guards against: a control
    # command that touches the network-backed PluginRepository can wedge
    # the whole worker, since control commands run synchronously on the
    # worker's control channel. plugin_service must never be imported here.
    monkeypatch.setattr(
        Domain,
        "getPlugins",
        classmethod(lambda cls: {}),
    )

    sys.modules.pop("app.backend.api.services.plugin_service", None)

    taskQueueModule._listInstalledPluginsFromLocalDomainRegistry()

    assert "app.backend.api.services.plugin_service" not in sys.modules
