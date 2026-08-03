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
import os
from pathlib import Path

import app.backend.project.postgresql_project as projectModule
import app.backend.runtime.postgresql_protocol_worker as workerModule

from app.backend.project.postgresql_project import PostgresqlProject


class FakeProtocol:
    def __init__(self, protocolId, scheduleLog):
        self.protocolId = protocolId
        self.scheduleLog = scheduleLog

    def getObjId(self):
        return self.protocolId

    def getScheduleLog(self):
        return self.scheduleLog


class FakeProcess:
    def __init__(self, pid=54321, returnCode=0):
        self.pid = pid
        self.returnCode = returnCode
        self.waitCalls = 0

    def wait(self):
        self.waitCalls += 1
        return self.returnCode


def test_StartPostgresqlProtocolWorkerLaunchesDetachedCoordinator(tmp_path, monkeypatch):
    projectPath = tmp_path / "project"
    projectPath.mkdir()
    protocol = FakeProtocol(41, "Runs/000041_FakeProtocol/logs/schedule.log")
    project = PostgresqlProject.__new__(PostgresqlProject)
    project.path = str(projectPath)
    project.postgresqlProjectId = 344
    process = FakeProcess()
    calls = {}

    def buildCommand(**kwargs):
        calls["commandArgs"] = kwargs
        return ["python", "-m", "app.backend.runtime.postgresql_protocol_worker", "--project-id", "344", "--protocol-id", "41"]

    def popen(command, **kwargs):
        calls["command"] = command
        calls["cwd"] = kwargs["cwd"]
        calls["env"] = kwargs["env"]
        calls["stdin"] = kwargs["stdin"]
        calls["stdoutPath"] = kwargs["stdout"].name
        calls["sameLog"] = kwargs["stderr"] is kwargs["stdout"]
        calls["startNewSession"] = kwargs["start_new_session"]
        return process

    monkeypatch.setattr(workerModule, "buildPostgresqlWorkerCommand", buildCommand)
    monkeypatch.setattr(projectModule.subprocess, "Popen", popen)

    pid = project._startPostgresqlProtocolWorker(protocol=protocol, runMode="restart", wait=False)

    moduleRoot = str(Path(projectModule.__file__).resolve().parents[3])
    assert pid == 54321
    assert process.waitCalls == 0
    assert calls["commandArgs"] == {"projectId": 344, "protocolId": 41, "runMode": "restart"}
    assert calls["cwd"] == moduleRoot
    assert calls["startNewSession"] is True
    assert calls["stdin"] is projectModule.subprocess.DEVNULL
    assert calls["sameLog"] is True
    assert calls["stdoutPath"] == str(projectPath / "Runs/000041_FakeProtocol/logs/schedule.log")
    assert calls["env"]["PYTHONPATH"].split(os.pathsep)[0] == moduleRoot