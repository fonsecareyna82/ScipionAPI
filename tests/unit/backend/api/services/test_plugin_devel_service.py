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

from app.backend.api.services import (
    plugin_devel_service as develModule,
)
from app.backend.api.services.plugin_devel_service import (
    PluginDevelService,
)


def test_RunCommandWritesDirectlyToLogWithoutStdoutPipe(
        tmp_path,
        monkeypatch,
):
    logPath = tmp_path / "plugin-task.log"
    logPath.touch()

    captured = {}

    class FakeProcess:
        def wait(self):
            captured["waited"] = True
            return 0

    def fakePopen(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)

        return FakeProcess()

    monkeypatch.setattr(
        develModule,
        "getPluginTaskLogPath",
        lambda taskId: logPath,
    )

    monkeypatch.setattr(
        develModule,
        "appendPluginTaskLog",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        develModule.subprocess,
        "Popen",
        fakePopen,
    )

    service = PluginDevelService()

    service._runCommand(
        [
            "scipion",
            "installp",
            "--devel",
        ],
        cwd=tmp_path,
        taskId="task-123",
    )

    assert captured["stdout"] is not (
        develModule.subprocess.PIPE
    )

    assert captured["stderr"] is (
        develModule.subprocess.STDOUT
    )

    assert Path(
        captured["stdout"].name
    ) == logPath

    assert captured["waited"] is True
    assert captured["stdout"].closed is True


def test_InstallDevelPluginAddsNoBinWhenSkippingBinaries(
        tmp_path,
        monkeypatch,
):
    pluginPath = (
        tmp_path
        / "scipion-em-test"
    )
    pluginPath.mkdir()

    (
        pluginPath
        / "pyproject.toml"
    ).write_text(
        """
[project]
name = "scipion-em-test"
version = "1.0.0"
""".strip(),
        encoding="utf-8",
    )

    captured = {}

    service = PluginDevelService(
        manifestPath=(
            tmp_path
            / "devel_plugins.json"
        )
    )

    monkeypatch.setattr(
        service,
        "_resolveScipionCommand",
        lambda: [
            "scipion3",
        ],
    )

    def fakeRunCommand(
            command,
            cwd,
            taskId,
    ):
        captured["command"] = list(
            command
        )
        captured["cwd"] = cwd

    monkeypatch.setattr(
        service,
        "_runCommand",
        fakeRunCommand,
    )

    service.installDevelPlugin(
        str(pluginPath),
        skipBinaries=True,
    )

    assert captured["command"] == [
        "scipion3",
        "installp",
        "-p",
        str(pluginPath),
        "--devel",
        "--noBin",
    ]


def test_InstallDevelPluginDoesNotAddNoBinByDefault(
        tmp_path,
        monkeypatch,
):
    pluginPath = (
        tmp_path
        / "scipion-em-test"
    )
    pluginPath.mkdir()

    (
        pluginPath
        / "pyproject.toml"
    ).write_text(
        """
[project]
name = "scipion-em-test"
version = "1.0.0"
""".strip(),
        encoding="utf-8",
    )

    captured = {}

    service = PluginDevelService(
        manifestPath=(
            tmp_path
            / "devel_plugins.json"
        )
    )

    monkeypatch.setattr(
        service,
        "_resolveScipionCommand",
        lambda: [
            "scipion3",
        ],
    )

    def fakeRunCommand(
            command,
            cwd,
            taskId,
    ):
        captured["command"] = list(
            command
        )

    monkeypatch.setattr(
        service,
        "_runCommand",
        fakeRunCommand,
    )

    service.installDevelPlugin(
        str(pluginPath),
        skipBinaries=False,
    )

    assert captured["command"] == [
        "scipion3",
        "installp",
        "-p",
        str(pluginPath),
        "--devel",
    ]

def test_DevelInstallerPrefersScipion3FromCurrentPythonEnvironment(monkeypatch, tmp_path):
    from types import SimpleNamespace

    runtime_bin = tmp_path / "active-conda-env" / "bin"
    runtime_bin.mkdir(parents=True)
    current_scipion = runtime_bin / "scipion3"
    current_scipion.touch()
    current_scipion.chmod(0o755)

    monkeypatch.delenv("SCIPIONAPI_SCIPION_EXECUTABLE", raising=False)
    monkeypatch.delenv("SCIPION_EXECUTABLE", raising=False)
    monkeypatch.setattr(develModule, "sys", SimpleNamespace(executable=str(runtime_bin / "python"), prefix=str(runtime_bin.parent)))
    monkeypatch.setattr(develModule.shutil, "which", lambda name: "/other-conda-env/bin/" + name)

    assert PluginDevelService()._resolveScipionCommand() == [str(current_scipion)]


def test_DevelInstallerPrefersScipionFromCurrentPythonEnvironment(monkeypatch, tmp_path):
    from types import SimpleNamespace

    runtime_bin = tmp_path / "active-conda-env" / "bin"
    runtime_bin.mkdir(parents=True)
    current_scipion = runtime_bin / "scipion"
    current_scipion.touch()
    current_scipion.chmod(0o755)

    monkeypatch.delenv("SCIPIONAPI_SCIPION_EXECUTABLE", raising=False)
    monkeypatch.delenv("SCIPION_EXECUTABLE", raising=False)
    monkeypatch.setattr(develModule, "sys", SimpleNamespace(executable=str(runtime_bin / "python"), prefix=str(runtime_bin.parent)))
    monkeypatch.setattr(develModule.shutil, "which", lambda name: "/other-conda-env/bin/" + name)

    assert PluginDevelService()._resolveScipionCommand() == [str(current_scipion)]
