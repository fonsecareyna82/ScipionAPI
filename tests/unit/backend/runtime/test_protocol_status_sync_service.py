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
# * All comments concerning this program package may be sent to the
# * e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)


class FakeMapper:
    def __init__(self):
        self.row = {
            "id": 10,
            "status": "running",
            "params": {},
        }

    def getProjectProtocolByProtocolId(
            self,
            projectId,
            protocolId,
    ):
        return dict(self.row)

    def updateProtocol(self, values):
        if "status" in values:
            self.row["status"] = values["status"]

        if "params" in values:
            self.row["params"] = values["params"]


class FakeProjectProtocol:
    def getDbPath(self):
        return "logs/run.db"

    def getWorkingDir(self):
        return "Runs/001_TestProtocol"


class FakeRuntimeProtocol:
    def getStatus(self):
        return "finished"

    def getElapsedTime(self):
        return None


def test_TerminalProtocolSyncEnablesRelationsAndUsesRuntimeProtocol(
        monkeypatch,
):
    service = RuntimeProtocolStatusSyncService()
    mapper = FakeMapper()

    projectProtocol = FakeProjectProtocol()
    runtimeProtocol = FakeRuntimeProtocol()

    callbackArgs = {}

    monkeypatch.setattr(
        service,
        "loadRuntimeProtocolFromRunDb",
        lambda **kwargs: runtimeProtocol,
    )

    def syncRuntimeProtocolCallback(**kwargs):
        callbackArgs.update(kwargs)

        mapper.row["status"] = "finished"

        return {
            "protocols": 1,
            "outputs": 1,
            "relations": 1,
        }

    result = service.syncProtocolStatusFromRunDb(
        mapper=mapper,
        projectId=3,
        protocolId=1298,
        protocol=projectProtocol,
        getCurrentProjectPathCallback=(
            lambda: "/tmp/scipion-project"
        ),
        syncRuntimeProtocolCallback=(
            syncRuntimeProtocolCallback
        ),
    )

    assert result["transitionedToTerminal"] is True

    assert callbackArgs["protocolId"] == 1298
    assert callbackArgs["registerOutputs"] is True
    assert callbackArgs["syncRelations"] is True

    assert (
            callbackArgs["protocol"]
            is runtimeProtocol
    )