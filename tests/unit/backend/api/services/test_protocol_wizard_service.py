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


class FakeValueHolder:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeParam:
    def __init__(self, label="Param", validationErrors=None):
        self.label = FakeValueHolder(label)
        self.validationErrors = validationErrors or []
        self.value = None

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def validate(self, value):
        return list(self.validationErrors)


class FakeProtocol:
    def __init__(self, objId=None, className="ProtClass"):
        self._objId = objId
        self._className = className
        self._params = {}
        self.attributeValues = {}
        self.label = None

    def addParam(self, name, param):
        self._params[name] = param

    def getParam(self, name):
        return self._params.get(name)

    def getObjId(self):
        return self._objId

    def getClassName(self):
        return self._className

    def setObjLabel(self, value):
        self.label = value

    def setAttributeValue(self, name, value):
        self.attributeValues[name] = value


class FakeProtocolFactory:
    def __init__(self, protocol):
        self.protocol = protocol

    def __call__(self):
        return self.protocol


class FakeDomain:
    def __init__(self, protocols=None, wizards=None):
        self.protocols = protocols or {}
        self.wizards = wizards or {}

    def getProtocols(self):
        return self.protocols

    def getWizards(self):
        return self.wizards


class FakeCurrentProject:
    def __init__(self):
        self.protocols = {}
        self.protocolFactories = {}
        self.fixedProtocolParams = []
        self.createdProtocols = []

    def getDomain(self):
        return FakeDomain(protocols=self.protocolFactories)

    def getProtocol(self, protocolId):
        return self.protocols[int(protocolId)]

    def newProtocol(self, protClass):
        protocol = protClass()
        self.createdProtocols.append(protocol)
        return protocol

    def _fixProtParamsConfiguration(self, protocol):
        self.fixedProtocolParams.append(protocol)


class FakeMapper:
    pass


class FakeProjectService:
    def __init__(self, currentProject):
        self.currentProject = currentProject
        self.runtimeProtocolIdByDbId = {}
        self.runtimeCalls = []
        self.castParamValueCalls = []
        self.applyParamsToProtocolCalls = []
        self.getProjectByIdCalls = []
        self.projectRow = {"id": 1}

    def _getScipionProtocolForRuntime(self, mapper, projectId, protocolId):
        self.runtimeCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
        })

        runtimeProtocolId = self.runtimeProtocolIdByDbId.get(int(protocolId), int(protocolId))
        return self.currentProject.protocols[int(runtimeProtocolId)]

    def castParamValue(self, param, value):
        self.castParamValueCalls.append({
            "param": param,
            "value": value,
        })

        if isinstance(value, str) and value.isdigit():
            return int(value)

        return value

    def applyParamsToProtocol(self, mapper, projectId, protocol, params):
        self.applyParamsToProtocolCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "protocol": protocol,
            "params": dict(params or {}),
        })
        return []

    def getProjectById(self, mapper, projectId, currentUser, refresh=False, checkPid=False):
        self.getProjectByIdCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
            "refresh": refresh,
            "checkPid": checkPid,
        })
        return self.projectRow


class FakePayload:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeWizardClass:
    pass


@pytest.fixture
def protocolWizardServiceModule(authTestEnv):
    return importlib.import_module("app.backend.api.services.protocol_wizard_service")


@pytest.fixture
def currentProject():
    return FakeCurrentProject()


@pytest.fixture
def projectService(currentProject):
    return FakeProjectService(currentProject)


@pytest.fixture
def wizardService(protocolWizardServiceModule, currentProject, projectService):
    return protocolWizardServiceModule.ProtocolWizardService(
        currentProject=currentProject,
        projectService=projectService,
    )


@pytest.fixture
def mapper():
    return FakeMapper()


def test_SanitizeWizardFormValuesDropsEmptyValues(wizardService):
    result = wizardService._sanitizeWizardFormValues({
        "noneValue": None,
        "blankValue": "",
        "spacesValue": "   ",
        "zeroValue": 0,
        "falseValue": False,
        "textValue": "value",
    })

    assert result == {
        "zeroValue": 0,
        "falseValue": False,
        "textValue": "value",
    }


def test_BuildWizardReadyProtocolResolvesPostgresqlProtocolId(
    wizardService,
    currentProject,
    projectService,
    mapper,
):
    protocol = FakeProtocol(objId=10, className="ProtWizardTarget")
    iterationsParam = FakeParam(label="Iterations")
    protocol.addParam("iterations", iterationsParam)

    currentProject.protocols[10] = protocol
    projectService.runtimeProtocolIdByDbId[500] = 10

    result = wizardService._buildWizardReadyProtocol(
        protocolId=500,
        protocolClassName="ProtWizardTarget",
        formValues={
            "iterations": 7,
        },
        mapper=mapper,
        projectId=1,
    )

    assert result is protocol
    assert currentProject.fixedProtocolParams == [protocol]
    assert iterationsParam.get() == 7
    assert protocol.attributeValues["iterations"] == 7

    assert projectService.runtimeCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 500,
        }
    ]

    assert projectService.applyParamsToProtocolCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocol": protocol,
            "params": {
                "iterations": 7,
            },
        }
    ]


def test_BuildWizardReadyProtocolCreatesNewProtocolWhenProtocolIdIsMissing(
    wizardService,
    currentProject,
    projectService,
    mapper,
):
    protocol = FakeProtocol(objId=None, className="ProtNewWizardTarget")
    runNameParam = FakeParam(label="Run name")
    protocol.addParam("runName", runNameParam)

    currentProject.protocolFactories["ProtNewWizardTarget"] = FakeProtocolFactory(protocol)

    result = wizardService._buildWizardReadyProtocol(
        protocolId=None,
        protocolClassName="ProtNewWizardTarget",
        formValues={
            "runName": "New protocol",
        },
        mapper=mapper,
        projectId=1,
    )

    assert result is protocol
    assert currentProject.createdProtocols == [protocol]
    assert currentProject.fixedProtocolParams == [protocol]
    assert runNameParam.get() == "New protocol"
    assert protocol.attributeValues["runName"] == "New protocol"
    assert protocol.label == "New protocol"
    assert projectService.runtimeCalls == []


def test_BuildWizardReadyProtocolRaisesWhenNewProtocolClassIsMissing(
    wizardService,
    mapper,
):
    with pytest.raises(HTTPException) as exc:
        wizardService._buildWizardReadyProtocol(
            protocolId=None,
            protocolClassName="MissingProtocol",
            formValues={},
            mapper=mapper,
            projectId=1,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Protocol class 'MissingProtocol' not found"


def test_ExecuteProtocolWizardResolvesPostgresqlProtocolId(
    protocolWizardServiceModule,
    wizardService,
    currentProject,
    projectService,
    mapper,
    monkeypatch,
):
    protocol = FakeProtocol(objId=10, className="ProtWizardTarget")
    iterationsParam = FakeParam(label="Iterations")
    protocol.addParam("iterations", iterationsParam)

    currentProject.protocols[10] = protocol
    projectService.runtimeProtocolIdByDbId[500] = 10

    descriptor = {
        "id": "tests.FakeWizardClass",
        "kind": "compute",
        "targetParams": ["boxSize"],
    }

    monkeypatch.setattr(
        wizardService,
        "_resolveWizardDescriptorForParam",
        lambda protocol, paramName, wizardId: descriptor,
    )
    monkeypatch.setattr(
        wizardService,
        "_getWizardClassById",
        lambda wizardId: FakeWizardClass,
    )

    handlerCalls = []

    def fakeExecuteWizardHandler(
        kind,
        wizardClass,
        protocol,
        paramName,
        descriptor,
        wizardInputs,
        currentProject,
        projectId,
    ):
        handlerCalls.append({
            "kind": kind,
            "wizardClass": wizardClass,
            "protocol": protocol,
            "paramName": paramName,
            "descriptor": descriptor,
            "wizardInputs": wizardInputs,
            "currentProject": currentProject,
            "projectId": projectId,
        })
        return {
            "paramUpdates": {
                "boxSize": 128,
            },
            "message": "Box size computed",
            "preview": {
                "enabled": True,
            },
        }

    monkeypatch.setattr(
        protocolWizardServiceModule,
        "executeWizardHandler",
        fakeExecuteWizardHandler,
    )

    payload = FakePayload(
        protocolId=500,
        protocolClassName="ProtWizardTarget",
        formValues={
            "iterations": 7,
        },
        paramName="boxSize",
        wizardId="tests.FakeWizardClass",
        wizardInputs={
            "diameter": 180,
        },
    )

    result = wizardService.executeProtocolWizard(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 1},
        payload=payload,
    )

    assert result == {
        "success": True,
        "wizardId": "tests.FakeWizardClass",
        "kind": "compute",
        "paramUpdates": {
            "boxSize": 128,
        },
        "message": "Box size computed",
        "preview": {
            "enabled": True,
        },
    }

    assert projectService.getProjectByIdCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "currentUser": {"id": 1},
            "refresh": False,
            "checkPid": False,
        }
    ]

    assert projectService.runtimeCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 500,
        }
    ]

    assert currentProject.fixedProtocolParams == [protocol]
    assert iterationsParam.get() == 7
    assert protocol.attributeValues["iterations"] == 7

    assert handlerCalls == [
        {
            "kind": "compute",
            "wizardClass": FakeWizardClass,
            "protocol": protocol,
            "paramName": "boxSize",
            "descriptor": descriptor,
            "wizardInputs": {
                "diameter": 180,
            },
            "currentProject": currentProject,
            "projectId": 1,
        }
    ]


def test_ExecuteProtocolWizardReturns404WhenProjectDoesNotExist(
    wizardService,
    projectService,
    mapper,
):
    projectService.projectRow = None

    payload = FakePayload(
        protocolId=500,
        protocolClassName="ProtWizardTarget",
        formValues={},
        paramName="boxSize",
        wizardId="tests.FakeWizardClass",
        wizardInputs={},
    )

    with pytest.raises(HTTPException) as exc:
        wizardService.executeProtocolWizard(
            mapper=mapper,
            projectId=1,
            currentUser={"id": 1},
            payload=payload,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Project not found"