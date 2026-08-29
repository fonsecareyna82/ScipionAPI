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
import json
from pathlib import Path

import app.backend.project.postgresql_project as projectModule
import app.backend.runtime.postgresql_protocol_worker as workerModule

from app.backend.project.postgresql_project import PostgresqlProject


class FakeProtocol:
    def __init__(
            self,
            protocolId,
            scheduleLog,
            queueName=None,
            queueParams=None,
    ):
        self.protocolId = protocolId
        self.scheduleLog = scheduleLog
        self.queueName = queueName
        self.queueParams = queueParams
        self.pid = 0

    def getObjId(self):
        return self.protocolId

    def getScheduleLog(self):
        return self.scheduleLog

    def useQueue(self):
        return self.queueParams is not None

    def hasQueueParams(self):
        return self.queueParams is not None

    def getQueueParams(self):
        return self.queueName, dict(
            self.queueParams or {}
        )

    def setPid(
            self,
            pid,
    ):
        self.pid = int(
            pid
        )

    def getPid(self):
        return self.pid


class FakeProcess:
    def __init__(self, pid=54321, returnCode=0):
        self.pid = pid
        self.returnCode = returnCode
        self.waitCalls = 0

    def wait(self):
        self.waitCalls += 1
        return self.returnCode


class FakeFlatMapper:
    def __init__(self):
        self.updateProtocolCalls = []

    def getProjectProtocolByProtocolId(
            self,
            projectId,
            protocolId,
    ):
        return {
            "id": 91,
            "params": {},
        }

    def updateProtocol(
            self,
            protocolData,
    ):
        self.updateProtocolCalls.append(
            protocolData
        )


def test_StartPostgresqlProtocolWorkerLaunchesDetachedCoordinator(tmp_path, monkeypatch):
    projectPath = tmp_path / "project"
    projectPath.mkdir()
    protocol = FakeProtocol(41, "Runs/000041_FakeProtocol/logs/schedule.log")
    project = PostgresqlProject.__new__(PostgresqlProject)
    project.path = str(projectPath)
    project.postgresqlProjectId = 344
    project.postgresqlFlatMapper = (
        FakeFlatMapper()
    )
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

    bindingsPath = str(
        tmp_path
        / "software"
        / "bindings"
    )

    monkeypatch.setattr(
        projectModule.pw.Config,
        "getBindingsFolder",
        lambda: bindingsPath,
    )

    pid = project._startPostgresqlProtocolWorker(protocol=protocol, runMode="restart", wait=False)

    moduleRoot = str(Path(projectModule.__file__).resolve().parents[3])
    assert pid == 54321
    assert (
            protocol.getPid()
            == 54321
    )

    assert (
            len(
                project
                .postgresqlFlatMapper
                .updateProtocolCalls
            )
            == 1
    )

    processMetadataUpdate = (
        project
        .postgresqlFlatMapper
        .updateProtocolCalls[0]
    )

    storedParams = json.loads(
        processMetadataUpdate[
            "params"
        ]
    )

    assert (
            storedParams[
                "_scipionWebRuntime"
            ]["pid"]
            == 54321
    )

    assert (
            storedParams[
                "_scipionWebRuntime"
            ]["jobIds"]
            == []
    )
    assert process.waitCalls == 0
    assert calls["commandArgs"] == {"projectId": 344, "protocolId": 41, "runMode": "restart"}
    assert calls["cwd"] == moduleRoot
    assert calls["startNewSession"] is True
    assert calls["stdin"] is projectModule.subprocess.DEVNULL
    assert calls["sameLog"] is True
    assert calls["stdoutPath"] == str(projectPath / "Runs/000041_FakeProtocol/logs/schedule.log")
    pythonPathEntries = calls["env"]["PYTHONPATH"].split(
        os.pathsep
    )

    assert pythonPathEntries[0] == moduleRoot
    assert pythonPathEntries[1] == bindingsPath


def test_StartPostgresqlProtocolWorkerForwardsTransientQueueOverride(
        tmp_path,
        monkeypatch,
):
    projectPath = tmp_path / "project"
    projectPath.mkdir()

    protocol = FakeProtocol(
        41,
        "Runs/000041_FakeProtocol/logs/schedule.log",
        queueName="gpu",
        queueParams={
            "JOB_TIME": "72",
            "JOB_MEMORY": "64000",
        },
    )

    project = PostgresqlProject.__new__(
        PostgresqlProject
    )

    project.path = str(
        projectPath
    )

    project.postgresqlProjectId = 344

    project.postgresqlFlatMapper = (
        FakeFlatMapper()
    )

    process = FakeProcess()
    calls = {}

    def buildCommand(**kwargs):
        calls["commandArgs"] = kwargs

        return [
            "python",
            "-m",
            "app.backend.runtime.postgresql_protocol_worker",
        ]

    def popen(command, **kwargs):
        calls["command"] = command
        return process

    monkeypatch.setattr(
        workerModule,
        "buildPostgresqlWorkerCommand",
        buildCommand,
    )

    monkeypatch.setattr(
        projectModule.subprocess,
        "Popen",
        popen,
    )

    project._startPostgresqlProtocolWorker(
        protocol=protocol,
        runMode="resume",
        wait=False,
    )

    assert calls["commandArgs"] == {
        "projectId": 344,
        "protocolId": 41,
        "runMode": "resume",
        "queueName": "gpu",
        "queueParams": {
            "JOB_TIME": "72",
            "JOB_MEMORY": "64000",
        },
    }