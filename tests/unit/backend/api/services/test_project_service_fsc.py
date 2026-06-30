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

import importlib

import pytest
from fastapi import HTTPException


class FakeFsc:
    def __init__(self, label="FSC 1"):
        self.label = label

    def clone(self):
        return self

    def getObjLabel(self):
        return self.label

    def getData(self):
        return [
            [0.01, 0.02, 0.03],
            [0.9, 0.5, 0.1],
        ]

    def calculateResolution(self, threshold):
        return 3.5


class FakeFscOutput:
    def __init__(self, items=None):
        self.items = items or []

    def iterItems(self, iterate=False):
        return list(self.items)


class FakeProtocol:
    def __init__(self, outputName, output):
        setattr(self, outputName, output)


class FakeCurrentProject:
    def __init__(self, protocol):
        self.protocol = protocol
        self.lastGetProtocolId = None

    def getProtocol(self, protocolId):
        self.lastGetProtocolId = protocolId
        return self.protocol


@pytest.fixture
def projectServiceModule(authTestEnv):
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule):
    instance = object.__new__(projectServiceModule.ProjectService)
    instance.currentProject = None
    return instance


def test_GetFscRowsServiceUsesPostgresqlReaderWhenAvailable(
    service,
    monkeypatch,
):
    class FakePgReader:
        lastSkipReason = None

        def getFscRows(self):
            return {
                "threshold": 0.143,
                "rows": [
                    {
                        "label": "PG FSC",
                        "resolution": 3.1,
                        "x": [0.01, 0.02],
                        "y": [0.9, 0.2],
                    }
                ],
            }

    monkeypatch.setattr(
        service,
        "_getPostgresqlFscReaderIfAvailable",
        lambda **kwargs: FakePgReader(),
    )

    def failRuntime(**kwargs):
        raise AssertionError("runtime should not be used when PostgreSQL FSC rows are available")

    monkeypatch.setattr(service, "_getScipionProtocolForRuntime", failRuntime)

    result = service.getFscRowsService(
        projectId=1,
        protocolId=10,
        outputName="outputFsc",
        mapper=object(),
    )

    assert result == {
        "threshold": 0.143,
        "rows": [
            {
                "label": "PG FSC",
                "resolution": 3.1,
                "x": [0.01, 0.02],
                "y": [0.9, 0.2],
            }
        ],
    }


def test_GetFscRowsServiceFallsBackToRuntimeWhenPostgresqlReaderHasNoRows(
    service,
    monkeypatch,
):
    class FakePgReader:
        lastSkipReason = "fsc_rows_not_found"

        def getFscRows(self):
            return None

    fscOutput = FakeFscOutput(items=[FakeFsc(label="Half maps")])
    protocol = FakeProtocol("outputFsc", fscOutput)
    mapper = object()
    calls = {}

    monkeypatch.setattr(
        service,
        "_getPostgresqlFscReaderIfAvailable",
        lambda **kwargs: FakePgReader(),
    )

    def fakeRuntimeProtocol(**kwargs):
        calls.update(kwargs)
        return protocol

    monkeypatch.setattr(
        service,
        "_getScipionProtocolForRuntime",
        fakeRuntimeProtocol,
    )

    result = service.getFscRowsService(
        projectId=1,
        protocolId=10,
        outputName="outputFsc",
        mapper=mapper,
    )

    assert result == {
        "threshold": 0.143,
        "rows": [
            {
                "label": "Half maps",
                "resolution": 3.5,
                "x": [0.01, 0.02, 0.03],
                "y": [0.9, 0.5, 0.1],
            }
        ],
    }

    assert calls == {
        "mapper": mapper,
        "projectId": 1,
        "protocolId": 10,
    }


def test_GetFscRowsServiceBuildsRowsWithoutMapper(service):
    fscOutput = FakeFscOutput(items=[FakeFsc(label="Half maps")])
    protocol = FakeProtocol("outputFsc", fscOutput)
    service.currentProject = FakeCurrentProject(protocol)

    result = service.getFscRowsService(
        projectId=1,
        protocolId=10,
        outputName="outputFsc",
    )

    assert result == {
        "threshold": 0.143,
        "rows": [
            {
                "label": "Half maps",
                "resolution": 3.5,
                "x": [0.01, 0.02, 0.03],
                "y": [0.9, 0.5, 0.1],
            }
        ],
    }