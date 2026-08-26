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