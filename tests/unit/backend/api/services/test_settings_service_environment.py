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
from types import SimpleNamespace

import app.backend.api.services.settings_service as settingsModule


def test_PatchEnvironmentVariablesPersistsRuntimeOverrideWithoutRewritingScipionConfig(
    monkeypatch,
):
    variable = SimpleNamespace(
        name="TEST_PLUGIN_HOME",
        value="/old/path",
        default="/default/path",
        isDefault=False,
    )

    savedConfigs = []
    writtenCustomEnvironment = {}
    revisionCalls = []
    refreshCalls = []
    reloadCalls = []

    class FakeVariablesRegistry:
        _variables = {
            variable.name: variable,
        }

        @classmethod
        def __iter__(cls):
            for name in sorted(
                cls._variables
            ):
                yield cls._variables[
                    name
                ]

        @classmethod
        def save(
            cls,
            path,
        ):
            savedConfigs.append(
                path
            )

    service = (
        settingsModule
        .SettingsService()
    )

    monkeypatch.setattr(
        settingsModule,
        "VariablesRegistry",
        FakeVariablesRegistry,
    )

    monkeypatch.setattr(
        settingsModule.SettingsService,
        "_warmupEnvironmentRegistry",
        lambda self: None,
    )

    monkeypatch.setattr(
        settingsModule,
        "_readCustomEnvironmentVariables",
        lambda: dict(
            writtenCustomEnvironment
        ),
    )

    monkeypatch.setattr(
        settingsModule,
        "_writeCustomEnvironmentVariablesAtomic",
        lambda values: (
            writtenCustomEnvironment
            .update(values)
        ),
    )

    monkeypatch.setattr(
        settingsModule.pyworkflow.Config,
        "SCIPION_CONFIG",
        "/tmp/scipion.conf",
    )

    monkeypatch.setattr(
        settingsModule,
        "bumpEnvironmentRevision",
        lambda: (
            revisionCalls.append(True)
            or 7
        ),
    )

    monkeypatch.setattr(
        settingsModule,
        "refreshScipionDomainIfNeeded",
        lambda: (
            refreshCalls.append(True)
            or True
        ),
    )

    monkeypatch.setattr(
        settingsModule,
        "triggerBackendReloadIfEnabled",
        lambda: reloadCalls.append(
            True
        ),
    )

    monkeypatch.setenv(
        "TEST_PLUGIN_HOME",
        "/old/path",
    )

    result = (
        service.patchEnvironmentVariables(
            currentUser={
                "role": "admin",
            },
            patch={
                "TEST_PLUGIN_HOME":
                    "/new/path",
            },
        )
    )

    assert (
        variable.value
        == "/new/path"
    )

    assert (
        settingsModule.os.environ[
            "TEST_PLUGIN_HOME"
        ]
        == "/new/path"
    )

    assert (
        writtenCustomEnvironment
        == {
            "TEST_PLUGIN_HOME":
                "/new/path",
        }
    )

    assert savedConfigs == []

    assert revisionCalls == [
        True,
    ]

    assert refreshCalls == [
        True,
    ]

    assert reloadCalls == [
        True,
    ]

    row = next(
        item
        for item in result
        if item["name"]
        == "TEST_PLUGIN_HOME"
    )

    assert (
        row["value"]
        == "/new/path"
    )


def test_ResetEnvironmentVariableRemovesOverrideAndRestoresBase(
    monkeypatch,
):
    variable = SimpleNamespace(
        name="TEST_PLUGIN_HOME",
        value="/web/override",
        default="/default/path",
        isDefault=False,
    )

    customEnvironment = {
        "TEST_PLUGIN_HOME": "/web/override",
    }

    revisionCalls = []
    refreshCalls = []
    reloadCalls = []

    class FakeVariablesRegistry:
        @classmethod
        def __iter__(cls):
            yield variable

    def writeCustomEnvironment(values):
        customEnvironment.clear()
        customEnvironment.update(values)

    service = settingsModule.SettingsService()

    monkeypatch.setattr(
        settingsModule,
        "VariablesRegistry",
        FakeVariablesRegistry,
    )
    monkeypatch.setattr(
        settingsModule.SettingsService,
        "_warmupEnvironmentRegistry",
        lambda self: None,
    )
    monkeypatch.setattr(
        settingsModule,
        "_readCustomEnvironmentVariables",
        lambda: dict(customEnvironment),
    )
    monkeypatch.setattr(
        settingsModule,
        "_writeCustomEnvironmentVariablesAtomic",
        writeCustomEnvironment,
    )
    monkeypatch.setattr(
        settingsModule,
        "_resolveEnvironmentBaseValue",
        lambda name, registeredVariable=None: (
            True,
            "/configured/path",
        ),
    )
    monkeypatch.setattr(
        settingsModule,
        "bumpEnvironmentRevision",
        lambda: revisionCalls.append(True) or 8,
    )
    monkeypatch.setattr(
        settingsModule,
        "refreshScipionDomainIfNeeded",
        lambda: refreshCalls.append(True) or True,
    )
    monkeypatch.setattr(
        settingsModule,
        "triggerBackendReloadIfEnabled",
        lambda: reloadCalls.append(True),
    )

    monkeypatch.setenv(
        "TEST_PLUGIN_HOME",
        "/web/override",
    )

    result = service.resetEnvironmentVariable(
        currentUser={"role": "admin"},
        variableName="TEST_PLUGIN_HOME",
    )

    assert customEnvironment == {}
    assert settingsModule.os.environ[
        "TEST_PLUGIN_HOME"
    ] == "/configured/path"

    assert variable.value == "/configured/path"
    assert variable.isDefault is False

    assert revisionCalls == [True]
    assert refreshCalls == [True]
    assert reloadCalls == [True]

    row = next(
        item
        for item in result
        if item["name"] == "TEST_PLUGIN_HOME"
    )

    assert row["value"] == "/configured/path"
    assert row["isOverride"] is False