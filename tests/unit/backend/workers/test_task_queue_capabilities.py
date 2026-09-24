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
import socket
import sys
import types

import app.workers.task_queue as taskQueueModule


def test_ReportNodeCapabilitiesReturnsGpusAndInstalledPlugins(monkeypatch):
    settingsServiceModule = types.ModuleType(
        "app.backend.api.services.settings_service"
    )
    settingsServiceModule._getNvidiaGpuResources = lambda: [
        {"index": 0, "name": "RTX 4090", "memoryTotalBytes": 25000000000},
    ]

    class FakePluginService:
        def getPlugins(self):
            return [
                {"pipName": "scipion-em-warp", "name": "warp", "installed": True, "pipVersion": "3.6.3"},
                {"pipName": "scipion-em-relion", "name": "relion", "installed": False, "pipVersion": ""},
            ]

    pluginServiceModule = types.ModuleType(
        "app.backend.api.services.plugin_service"
    )
    pluginServiceModule.PluginService = FakePluginService

    monkeypatch.setitem(
        sys.modules,
        "app.backend.api.services.settings_service",
        settingsServiceModule,
    )
    monkeypatch.setitem(
        sys.modules,
        "app.backend.api.services.plugin_service",
        pluginServiceModule,
    )

    result = taskQueueModule.report_node_capabilities(state=None)

    assert result["hostname"] == socket.gethostname()
    assert result["gpuCount"] == 1
    assert result["gpus"] == [{"index": 0, "name": "RTX 4090", "memoryTotalBytes": 25000000000}]
    assert result["plugins"] == [
        {"pipName": "scipion-em-warp", "name": "warp", "pipVersion": "3.6.3"},
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


def test_ReportNodeCapabilitiesToleratesPluginServiceFailure(monkeypatch):
    settingsServiceModule = types.ModuleType(
        "app.backend.api.services.settings_service"
    )
    settingsServiceModule._getNvidiaGpuResources = lambda: []

    class BrokenPluginService:
        def getPlugins(self):
            raise RuntimeError("plugin repository unavailable")

    pluginServiceModule = types.ModuleType(
        "app.backend.api.services.plugin_service"
    )
    pluginServiceModule.PluginService = BrokenPluginService

    monkeypatch.setitem(
        sys.modules,
        "app.backend.api.services.settings_service",
        settingsServiceModule,
    )
    monkeypatch.setitem(
        sys.modules,
        "app.backend.api.services.plugin_service",
        pluginServiceModule,
    )

    result = taskQueueModule.report_node_capabilities(state=None)

    assert result["hostname"] == socket.gethostname()
    assert result["gpuCount"] == 0
    assert result["plugins"] == []
    assert "error" not in result
