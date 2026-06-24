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


class FakeCurrentProject:
    def __init__(self):
        self.protocols = {}

    def getProtocol(self, protocolId):
        return self.protocols[int(protocolId)]


class FakeDb:
    def __init__(self):
        self.runtimeProtocolIdByDbId = {}
        self.fetchOneCalls = []

    def fetchOne(self, query, params):
        self.fetchOneCalls.append({
            "query": query,
            "params": params,
        })

        if len(params) < 3:
            return None

        protocolDbId = params[1]
        runtimeProtocolId = self.runtimeProtocolIdByDbId.get(int(protocolDbId))
        if runtimeProtocolId is None:
            return None

        return {
            "protocolId": runtimeProtocolId,
        }


class FakeMapper:
    def __init__(self):
        self.db = FakeDb()
        self.listProtocolStepsResult = []
        self.updateProtocolStepStatusCalls = []
        self.updateProtocolStepStatusResult = None

    def listProtocolSteps(self, projectId, protocolId):
        return self.listProtocolStepsResult

    def updateProtocolStepStatus(self, **kwargs):
        self.updateProtocolStepStatusCalls.append(kwargs)
        return self.updateProtocolStepStatusResult


class FakeValueHolder:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeStep:
    def __init__(self, index, objId, raiseGetObjId=False):
        self._index = index
        self._objId = objId
        self.raiseGetObjId = raiseGetObjId
        self.status = None

    def getObjId(self):
        if self.raiseGetObjId:
            raise RuntimeError("getObjId failed")
        return self._objId

    def setStatus(self, status):
        self.status = status


class FakeProtocolWithSteps:
    def __init__(self, steps):
        self.steps = steps
        self.updateStepsCalls = []
        self.failLoadSteps = None
        self.failUpdateSteps = None

    @staticmethod
    def _resolveStepObjId(step):
        objId = getattr(step, "_objId", None)
        if hasattr(objId, "get"):
            return objId.get()
        return objId

    def loadSteps(self):
        if self.failLoadSteps is not None:
            raise self.failLoadSteps
        return self.steps

    def _updateSteps(self, callback, where=None):
        if self.failUpdateSteps is not None:
            raise self.failUpdateSteps

        self.updateStepsCalls.append({"where": where})

        for step in self.steps:
            if where == "id='%s'" % self._resolveStepObjId(step):
                callback(step)


@pytest.fixture
def projectServiceModule(authTestEnv):
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule):
    instance = object.__new__(projectServiceModule.ProjectService)
    instance.currentProject = FakeCurrentProject()
    instance.tomoList = {}
    return instance


@pytest.fixture
def mapper():
    return FakeMapper()


def test_ListProtocolStepsDelegatesToMapper(service, mapper):
    mapper.listProtocolStepsResult = [
        {"index": 1, "name": "resumeStep", "status": "finished"},
    ]

    result = service.listProtocolStepsService(mapper, projectId=1, protocolId=10)

    assert result == [{"index": 1, "name": "resumeStep", "status": "finished"}]


def test_UpdateProtocolStepStatusUpdatesScipionAndPostgres(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "STATUS_FINISHED", "finished")

    stepA = FakeStep(index=1, objId=101)
    stepB = FakeStep(index=2, objId=102)
    protocol = FakeProtocolWithSteps([stepA, stepB])
    service.currentProject.protocols[10] = protocol
    mapper.updateProtocolStepStatusResult = {
        "index": 2,
        "name": "processStep",
        "status": "finished",
    }

    result = service.updateProtocolStepStatusService(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        stepIndex=2,
        stepStatus="finished",
    )

    assert result == mapper.updateProtocolStepStatusResult
    assert protocol.updateStepsCalls == [{"where": "id='102'"}]
    assert stepA.status is None
    assert stepB.status == "finished"
    assert mapper.updateProtocolStepStatusCalls == [
        {
            "projectId": 1,
            "protocolId": 10,
            "stepIndex": 2,
            "stepStatus": "finished",
        },
    ]


def test_UpdateProtocolStepStatusResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "STATUS_FINISHED", "finished")

    step = FakeStep(index=2, objId=102)
    protocol = FakeProtocolWithSteps([step])

    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10
    mapper.updateProtocolStepStatusResult = {
        "index": 2,
        "name": "processStep",
        "status": "finished",
    }

    result = service.updateProtocolStepStatusService(
        mapper=mapper,
        projectId=1,
        protocolId=500,
        stepIndex=2,
        stepStatus="finished",
    )

    assert result == mapper.updateProtocolStepStatusResult
    assert protocol.updateStepsCalls == [{"where": "id='102'"}]
    assert step.status == "finished"

    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")
    assert mapper.updateProtocolStepStatusCalls == [
        {
            "projectId": 1,
            "protocolId": 10,
            "stepIndex": 2,
            "stepStatus": "finished",
        },
    ]


def test_UpdateProtocolStepStatusAcceptsObjIdHolderFallback(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "STATUS_NEW", "new")

    step = FakeStep(
        index=3,
        objId=FakeValueHolder(333),
        raiseGetObjId=True,
    )
    protocol = FakeProtocolWithSteps([step])
    service.currentProject.protocols[10] = protocol
    mapper.updateProtocolStepStatusResult = {"index": 3, "status": "new"}

    result = service.updateProtocolStepStatusService(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        stepIndex=3,
        stepStatus="new",
    )

    assert result == {"index": 3, "status": "new"}
    assert protocol.updateStepsCalls == [{"where": "id='333'"}]
    assert step.status == "new"


def test_UpdateProtocolStepStatusRejectsInvalidStatus(service, mapper):
    with pytest.raises(HTTPException) as exc:
        service.updateProtocolStepStatusService(
            mapper=mapper,
            projectId=1,
            protocolId=10,
            stepIndex=1,
            stepStatus="running",
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "Invalid step status. Allowed values: new, finished"


def test_UpdateProtocolStepStatusRaisesWhenCurrentProjectIsMissing(service, mapper):
    service.currentProject = None

    with pytest.raises(HTTPException) as exc:
        service.updateProtocolStepStatusService(
            mapper=mapper,
            projectId=1,
            protocolId=10,
            stepIndex=1,
            stepStatus="finished",
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == "No current Scipion project loaded"


def test_UpdateProtocolStepStatusRaisesWhenProtocolIsMissing(service, mapper):
    with pytest.raises(HTTPException) as exc:
        service.updateProtocolStepStatusService(
            mapper=mapper,
            projectId=1,
            protocolId=99,
            stepIndex=1,
            stepStatus="finished",
        )

    assert exc.value.status_code == 404
    assert str(exc.value.detail).startswith("Protocol not found in Scipion runtime: 99")


def test_UpdateProtocolStepStatusRaisesWhenStepIsMissing(service, mapper):
    protocol = FakeProtocolWithSteps([FakeStep(index=1, objId=101)])
    service.currentProject.protocols[10] = protocol

    with pytest.raises(HTTPException) as exc:
        service.updateProtocolStepStatusService(
            mapper=mapper,
            projectId=1,
            protocolId=10,
            stepIndex=2,
            stepStatus="finished",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Step not found: 2"


def test_UpdateProtocolStepStatusRaisesWhenPostgresRowIsMissing(service, mapper):
    protocol = FakeProtocolWithSteps([FakeStep(index=1, objId=101)])
    service.currentProject.protocols[10] = protocol

    with pytest.raises(HTTPException) as exc:
        service.updateProtocolStepStatusService(
            mapper=mapper,
            projectId=1,
            protocolId=10,
            stepIndex=1,
            stepStatus="finished",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Protocol step not found in PostgreSQL: 1"