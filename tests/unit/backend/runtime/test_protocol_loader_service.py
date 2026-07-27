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
import app.backend.runtime.protocol_loader_service as loader_module

from app.backend.runtime.protocol_loader_service import (
    RuntimeProtocolLoaderService,
)


class FakeProject:
    path = "/tmp/scipion-project"


class FakeProtocol:
    def getDbPath(self):
        return "logs/run.db"

    def getWorkingDir(self):
        return "Runs/001_TestProtocol"


def test_LoadProtocolFromRuntimeDbUsesProvidedProtocol(
        monkeypatch,
):
    service = RuntimeProtocolLoaderService()
    protocol = FakeProtocol()

    monkeypatch.setattr(
        os.path,
        "exists",
        lambda path: False,
    )

    def failFallback(protocolId):
        raise AssertionError(
            "SQLite fallback must not be queried"
        )

    result = service.loadProtocolFromRuntimeDb(
        protocolId=1298,
        currentProject=FakeProject(),
        getProtocolByRuntimeIdCallback=failFallback,
        protocol=protocol,
    )

    assert result is protocol


def test_LoadProtocolFromRuntimeDbSearchesImportedSource(
        monkeypatch,
        tmp_path,
):
    service = RuntimeProtocolLoaderService()
    protocol = FakeProtocol()

    managedProject = (
        tmp_path
        / "managed"
    )

    sourceProject = (
        tmp_path
        / "source"
    )

    sourceRunDb = (
        sourceProject
        / "Runs"
        / "001_TestProtocol"
        / "logs"
        / "run.db"
    )

    sourceRunDb.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    sourceRunDb.touch()

    runtimeProtocol = object()
    calls = []

    def fakeGetProtocolFromDb(
            projectPath,
            runDbPath,
            protocolId,
            chdir=False,
    ):
        calls.append({
            "projectPath": projectPath,
            "runDbPath": runDbPath,
            "protocolId": protocolId,
            "chdir": chdir,
        })

        return runtimeProtocol

    monkeypatch.setattr(
        loader_module,
        "getProtocolFromDb",
        fakeGetProtocolFromDb,
    )

    result = service.loadProtocolFromRuntimeDb(
        protocolId=1298,
        currentProject=FakeProject(),
        getProtocolByRuntimeIdCallback=(
            lambda protocolId: protocol
        ),
        protocol=protocol,
        projectPaths=[
            managedProject,
            sourceProject,
        ],
    )

    assert result is runtimeProtocol

    assert calls == [{
        "projectPath": str(
            sourceProject
        ),
        "runDbPath": str(
            sourceRunDb
        ),
        "protocolId": 1298,
        "chdir": False,
    }]


