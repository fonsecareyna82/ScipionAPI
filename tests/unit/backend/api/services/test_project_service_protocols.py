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
    # fakeValueHolder
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeBaseParam:
    # fakeBaseParam
    def __init__(self, label="Param", choices=None, validationErrors=None, allowsNull=True, condition=None):
        self.label = FakeValueHolder(label)
        self.choices = choices or []
        self.validationErrors = validationErrors or []
        self.allowsNull = FakeValueHolder(allowsNull)
        self.condition = FakeValueHolder(condition)
        self.value = None

    def set(self, value):
        self.value = value

    def get(self):
        return self.value

    def validate(self, value):
        return list(self.validationErrors)


class FakeEnumParam(FakeBaseParam):
    pass


class FakeIntParam(FakeBaseParam):
    pass


class FakeFloatParam(FakeBaseParam):
    pass


class FakeBooleanParam(FakeBaseParam):
    pass


class FakeStringParam(FakeBaseParam):
    pass


class FakeCsvList(FakeBaseParam):
    pass


class FakeProtocol:
    # fakeProtocol
    def __init__(self, objId=None, className="ProtClass", useQueueFlag=False, validateErrors=None):
        self._objId = objId
        self._className = className
        self._params = {}
        self._useQueueFlag = useQueueFlag
        self._validateErrors = validateErrors or []
        self._label = None
        self.attributeValues = {}
        self.queueParams = None

        self._objComment = FakeValueHolder("")
        self._useQueue = FakeValueHolder(False)
        self._prerequisites = FakeValueHolder([])
        self.gpuList = FakeValueHolder("")
        self.numberOfThreads = FakeValueHolder(1)
        self.runMode = FakeValueHolder(None)
        self.runName = FakeValueHolder("")

    def addParam(self, name, param):
        self._params[name] = param

    def getParam(self, name):
        return self._params.get(name)

    def setAttributeValue(self, name, value):
        self.attributeValues[name] = value

    def setObjLabel(self, value):
        self._label = value

    def hasObjId(self):
        return self._objId is not None

    def getObjId(self):
        return self._objId

    def setObjId(self, value):
        self._objId = value

    def useQueue(self):
        return self._useQueueFlag

    def setQueueParams(self, queueParams):
        self.queueParams = queueParams

    def _validate(self):
        return list(self._validateErrors)


class FakeDomain:
    # fakeDomain
    def __init__(self, protocolsMap):
        self.protocolsMap = protocolsMap

    def getProtocols(self):
        return self.protocolsMap


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(self):
        self.protocols = {}
        self.protocolFactories = {}
        self.setupProtocols = []
        self.storedProtocols = []
        self.launchedProtocols = []
        self.scheduledProtocols = []
        self.stoppedProtocols = []
        self.copiedProtocolInputs = []
        self.copiedProtocolOutputs = []
        self.deleteProtocolCalls = []
        self.restartWorkflowInjectedErrors = []
        self.resetWorkflowResult = []
        self.failDeleteProtocol = None
        self.failResetWorkflow = None

    def getDomain(self):
        return FakeDomain(self.protocolFactories)

    def newProtocol(self, protClass):
        protocol = protClass()
        return protocol

    def getProtocol(self, protocolId):
        return self.protocols[int(protocolId)]

    def _storeProtocol(self, protocol):
        self.storedProtocols.append(protocol)

    def _setupProtocol(self, protocol):
        if not protocol.hasObjId():
            protocol.setObjId(999)
        self.setupProtocols.append(protocol)

    def launchProtocol(self, protocol):
        self.launchedProtocols.append(protocol)

    def scheduleProtocol(self, protocol):
        self.scheduledProtocols.append(protocol)

    def stopProtocol(self, protocol):
        self.stoppedProtocols.append(protocol)

    def copyProtocol(self, protocols):
        self.copiedProtocolInputs.append(list(protocols))
        return list(self.copiedProtocolOutputs)

    def deleteProtocol(self, *protocols):
        if self.failDeleteProtocol is not None:
            raise self.failDeleteProtocol
        self.deleteProtocolCalls.append(list(protocols))

    def _getSubworkflow(self, protocol):
        return ["wf-a", "wf-b"], ["active-a"]

    def _restartWorkflow(self, errorList, workflowProtocolList):
        errorList.extend(self.restartWorkflowInjectedErrors)

    def resetWorkFlow(self, workflowProtocolList):
        if self.failResetWorkflow is not None:
            raise self.failResetWorkflow
        return self.resetWorkflowResult


class FakeMapper:
    # fakeMapper
    def __init__(self):
        self.dbProtocolsByProtocolId = {}
        self.savedProtocolContexts = []
        self.deleteProtocolCalls = []

    def getProtocolByProtocolId(self, protocolId, projectId):
        return self.dbProtocolsByProtocolId.get((protocolId, projectId))

    def saveProtocol(self, protocolContext):
        self.savedProtocolContexts.append(protocolContext)

    def deleteProtocol(self, projectId, protocolList):
        self.deleteProtocolCalls.append(
            {
                "projectId": projectId,
                "protocolList": protocolList,
            }
        )


@pytest.fixture
def projectServiceModule(authTestEnv):
    # projectServiceModule
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule):
    # service
    instance = object.__new__(projectServiceModule.ProjectService)
    instance.currentProject = FakeCurrentProject()
    instance.tomoList = {}
    instance._buildProtocolContext = lambda projectId, protocol: {
        "projectId": projectId,
        "protocolId": protocol.getObjId(),
        "protocolClassName": getattr(protocol, "_className", "ProtClass"),
        "params": {},
    }
    instance.syncProjectProtocolsAndDependencies = (
        lambda mapper, projectId, refresh=False, checkPid=False: {
            "protocols": 0,
            "dependencies": 0,
        }
    )
    return instance


@pytest.fixture
def mapper():
    # mapper
    return FakeMapper()


def assertSuccessEnvelope(result):
    assert result["status"] == 0
    assert result["errors"] == []


def test_RegisterOutputReturnsPersistenceReport(
    projectServiceModule,
    service,
    monkeypatch,
):
    class FakeDb:
        # fakeDb
        pass

    class FakeMapper:
        # fakeMapper
        def __init__(self):
            self.db = FakeDb()

    class FakeSetOutput:
        # fakeSetOutput
        def getClassName(self):
            return "SetOfParticles"

    class FakeObjectOutput:
        # fakeObjectOutput
        def getClassName(self):
            return "Volume"

    class FakeBadSetOutput:
        # fakeBadSetOutput
        def getClassName(self):
            return "SetOfBadThings"

    class FakeUnsupportedOutput:
        # fakeUnsupportedOutput
        pass

    class FakeProtocolWithOutputs:
        # fakeProtocolWithOutputs
        def getObjId(self):
            return 10

        def iterOutputAttributes(self):
            return [
                ("outputParticles", FakeSetOutput()),
                ("outputVolume", FakeObjectOutput()),
                ("badSet", FakeBadSetOutput()),
                ("unsupportedOutput", FakeUnsupportedOutput()),
            ]

    class FakeScipionSetPostgresqlMapper:
        # fakeScipionSetPostgresqlMapper
        def __init__(self, db):
            self.db = db

        def storeSet(self, projectId, protocolDbId, outputName, scipionSet):
            if outputName == "badSet":
                raise RuntimeError("broken set output")

            return {
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "stored": True,
            }

    class FakeScipionObjectPostgresqlMapper:
        # fakeScipionObjectPostgresqlMapper
        def __init__(self, db):
            self.db = db

        def storeObjectTree(
            self,
            projectId,
            protocolDbId,
            outputName,
            scipionObj,
            includeNestedProperties,
        ):
            return {
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "stored": True,
                "includeNestedProperties": includeNestedProperties,
            }

    mapperPackage = importlib.import_module("app.backend.mapper")

    monkeypatch.setattr(
        mapperPackage,
        "ScipionSetPostgresqlMapper",
        FakeScipionSetPostgresqlMapper,
    )
    monkeypatch.setattr(
        mapperPackage,
        "ScipionObjectPostgresqlMapper",
        FakeScipionObjectPostgresqlMapper,
    )
    monkeypatch.setattr(
        service,
        "_resolveProtocolDbIdForOutputPersistence",
        lambda db, projectId, protocol: 500,
    )

    report = service.registerOutput(
        projectId=1,
        protocol=FakeProtocolWithOutputs(),
        mapper=FakeMapper(),
        returnReport=True,
    )

    assert report["persisted"] == [
        {
            "projectId": 1,
            "protocolDbId": 500,
            "stored": True,
            "mapperKind": "flat_set",
            "outputName": "outputParticles",
            "outputClassName": "SetOfParticles",
        },
        {
            "projectId": 1,
            "protocolDbId": 500,
            "stored": True,
            "includeNestedProperties": True,
            "mapperKind": "tree",
            "outputName": "outputVolume",
            "outputClassName": "Volume",
        },
    ]

    assert report["skipped"] == [
        {
            "outputName": "unsupportedOutput",
            "outputClassName": "FakeUnsupportedOutput",
            "reason": "unsupported_output_type",
        }
    ]

    assert report["errors"] == [
        {
            "outputName": "badSet",
            "outputClassName": "SetOfBadThings",
            "error": "broken set output",
        }
    ]


def test_SyncProjectProtocolsAndDependenciesReportsOutputPersistence(
    projectServiceModule,
    service,
    monkeypatch,
):
    service.syncProjectProtocolsAndDependencies = (
        projectServiceModule.ProjectService.syncProjectProtocolsAndDependencies.__get__(
            service,
            projectServiceModule.ProjectService,
        )
    )

    class FakeProtocolNode:
        # fakeProtocolNode
        def __init__(self, protocol):
            self.run = protocol
            self._parents = []

    class FakeRunsGraph:
        # fakeRunsGraph
        def __init__(self, protocol):
            self._nodesDict = {
                "PROJECT": object(),
                "10": FakeProtocolNode(protocol),
            }

    class FakeCurrentProjectForSync:
        # fakeCurrentProjectForSync
        def __init__(self, protocol):
            self.protocol = protocol

        def getRunsGraph(self, refresh=False, checkPids=False):
            return FakeRunsGraph(self.protocol)

    class FakeProtocolForSync:
        # fakeProtocolForSync
        def getObjId(self):
            return 10

        def iterInputAttributes(self):
            return []

    class FakeSyncMapper:
        # fakeSyncMapper
        def __init__(self):
            self.savedProtocolContexts = []
            self.deletedProtocolIds = None
            self.savedEdges = None
            self.savedInputRefs = None

        def saveProtocol(self, protocolContext):
            self.savedProtocolContexts.append(protocolContext)
            return 500

        def deleteProjectProtocolsNotInProtocolIds(self, projectId, protocolIds):
            self.deletedProtocolIds = {
                "projectId": projectId,
                "protocolIds": protocolIds,
            }

        def replaceProjectProtocolDependencies(self, projectId, edges):
            self.savedEdges = {
                "projectId": projectId,
                "edges": edges,
            }
            return len(edges)

        def replaceProjectProtocolInputRefs(self, projectId, inputRefs):
            self.savedInputRefs = {
                "projectId": projectId,
                "inputRefs": inputRefs,
            }
            return len(inputRefs)

    protocol = FakeProtocolForSync()
    service.currentProject = FakeCurrentProjectForSync(protocol)

    monkeypatch.setattr(
        service,
        "_buildProtocolContext",
        lambda projectId, protocol: {
            "projectId": projectId,
            "protocolId": protocol.getObjId(),
        },
    )
    monkeypatch.setattr(
        service,
        "_shouldRegisterProtocolOutputs",
        lambda protocol: True,
    )
    monkeypatch.setattr(
        service,
        "registerOutput",
        lambda projectId, protocol, mapper, returnReport=False: {
            "persisted": [
                {
                    "mapperKind": "flat_set",
                    "outputName": "outputParticles",
                },
                {
                    "mapperKind": "tree",
                    "outputName": "outputVolume",
                },
            ],
            "skipped": [
                {
                    "outputName": "unsupportedOutput",
                    "outputClassName": "UnsupportedOutput",
                    "reason": "unsupported_output_type",
                }
            ],
            "errors": [
                {
                    "outputName": "badOutput",
                    "outputClassName": "SetOfBad",
                    "error": "boom",
                }
            ],
        },
    )

    mapper = FakeSyncMapper()

    result = service.syncProjectProtocolsAndDependencies(
        mapper=mapper,
        projectId=1,
        refresh=True,
        checkPid=True,
    )

    assert result == {
        "protocols": 1,
        "dependencies": 0,
        "inputRefs": 0,
        "outputs": 2,
        "outputsByKind": {
            "flat_set": 1,
            "tree": 1,
        },
        "outputErrors": [
            {
                "protocolId": "10",
                "outputName": "unsupportedOutput",
                "outputClassName": "UnsupportedOutput",
                "reason": "unsupported_output_type",
            },
            {
                "protocolId": "10",
                "outputName": "badOutput",
                "outputClassName": "SetOfBad",
                "error": "boom",
            },
        ],
    }

    assert mapper.savedProtocolContexts == [
        {
            "projectId": 1,
            "protocolId": 10,
        }
    ]
    assert mapper.deletedProtocolIds == {
        "projectId": 1,
        "protocolIds": ["10"],
    }


def test_CastParamValueSupportsEnumLookup(projectServiceModule, service, monkeypatch):
    monkeypatch.setattr(projectServiceModule, "EnumParam", FakeEnumParam)

    param = FakeEnumParam(choices=["Continue", "Restart"])

    assert service.castParamValue(param, "Restart") == 1
    assert service.castParamValue(param, "restart") == 1
    assert service.castParamValue(param, 0) == 0


def test_CastParamValueSupportsPrimitiveTypes(projectServiceModule, service, monkeypatch):
    monkeypatch.setattr(projectServiceModule, "IntParam", FakeIntParam)
    monkeypatch.setattr(projectServiceModule, "FloatParam", FakeFloatParam)
    monkeypatch.setattr(projectServiceModule, "BooleanParam", FakeBooleanParam)
    monkeypatch.setattr(projectServiceModule, "StringParam", FakeStringParam)
    monkeypatch.setattr(projectServiceModule, "EnumParam", FakeEnumParam)
    monkeypatch.setattr(projectServiceModule, "CsvList", FakeCsvList)

    assert service.castParamValue(FakeIntParam(), "7") == 7
    assert service.castParamValue(FakeFloatParam(), "3.5") == 3.5
    assert service.castParamValue(FakeBooleanParam(), "yes") is True
    assert service.castParamValue(FakeBooleanParam(), "no") is False
    assert service.castParamValue(FakeStringParam(), 123) == "123"
    assert service.castParamValue(FakeCsvList(), "item") == ["item"]


def test_SaveProtocolCreatesNewProtocolAndPersistsContext(projectServiceModule, service, mapper, monkeypatch):
    monkeypatch.setattr(projectServiceModule, "IntParam", FakeIntParam)
    monkeypatch.setattr(projectServiceModule, "FloatParam", FakeFloatParam)
    monkeypatch.setattr(projectServiceModule, "BooleanParam", FakeBooleanParam)
    monkeypatch.setattr(projectServiceModule, "StringParam", FakeStringParam)
    monkeypatch.setattr(projectServiceModule, "EnumParam", FakeEnumParam)
    monkeypatch.setattr(projectServiceModule, "CsvList", FakeCsvList)
    monkeypatch.setattr(
        service,
        "applyParamsToProtocol",
        lambda mapper=None, projectId=None, protocol=None, params=None: [],
    )
    monkeypatch.setattr(
        service,
        "_buildProtocolContext",
        lambda projectId, protocol: {
            "projectId": projectId,
            "protocolId": protocol.getObjId(),
            "label": protocol._label,
            "runName": protocol.runName.get(),
            "comment": protocol._objComment.get(),
        },
    )

    def fakeSyncProjectProtocolsAndDependencies(mapperObj, projectId, refresh=False, checkPid=False):
        for protocolObj in service.currentProject.setupProtocols:
            mapperObj.saveProtocol(service._buildProtocolContext(projectId, protocolObj))
        return {"protocols": len(service.currentProject.setupProtocols), "dependencies": 0}

    monkeypatch.setattr(
        service,
        "syncProjectProtocolsAndDependencies",
        fakeSyncProjectProtocolsAndDependencies,
    )

    def buildProtocol():
        protocol = FakeProtocol(objId=None, className="ProtClass")
        protocol.addParam("runName", FakeStringParam(label="Run name"))
        protocol.addParam("iterations", FakeIntParam(label="Iterations"))
        return protocol

    service.currentProject.protocolFactories["ProtClass"] = buildProtocol

    protocol, errors = service.saveProtocol(
        mapper=mapper,
        projectId=1,
        protocolId=None,
        protocolClassName="ProtClass",
        params={
            "runName": "My protocol",
            "iterations": "5",
            "_objComment": "comment",
        },
    )

    assert errors == []
    assert protocol.getObjId() == 999
    assert protocol._label is None
    assert protocol.runName.get() == "My protocol"
    assert protocol.attributeValues["runName"] == "My protocol"
    assert protocol.attributeValues["iterations"] == 5
    assert protocol._objComment.get() == "comment"
    assert len(service.currentProject.setupProtocols) == 1
    assert mapper.savedProtocolContexts == [
        {
            "projectId": 1,
            "protocolId": 999,
            "label": None,
            "runName": "My protocol",
            "comment": "comment",
        }
    ]


def test_SaveProtocolAggregatesValidationAndPointerErrors(projectServiceModule, service, mapper, monkeypatch):
    monkeypatch.setattr(projectServiceModule, "IntParam", FakeIntParam)
    monkeypatch.setattr(projectServiceModule, "StringParam", FakeStringParam)
    monkeypatch.setattr(projectServiceModule, "EnumParam", FakeEnumParam)
    monkeypatch.setattr(projectServiceModule, "CsvList", FakeCsvList)

    protocol = FakeProtocol(objId=10, className="ProtClass")
    protocol.addParam(
        "iterations",
        FakeIntParam(label="Iterations", validationErrors=["must be greater than zero"]),
    )
    service.currentProject.protocols[10] = protocol
    mapper.dbProtocolsByProtocolId[(10, 1)] = {"id": 500, "protocolId": 10}

    monkeypatch.setattr(
        service,
        "applyParamsToProtocol",
        lambda mapper=None, projectId=None, protocol=None, params=None: ["pointer error"],
    )

    def fakeSyncProjectProtocolsAndDependencies(mapperObj, projectId, refresh=False, checkPid=False):
        for protocolObj in service.currentProject.storedProtocols:
            mapperObj.saveProtocol(service._buildProtocolContext(projectId, protocolObj))
        return {"protocols": len(service.currentProject.storedProtocols), "dependencies": 0}

    monkeypatch.setattr(
        service,
        "syncProjectProtocolsAndDependencies",
        fakeSyncProjectProtocolsAndDependencies,
    )

    _, errors = service.saveProtocol(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        protocolClassName="ProtClass",
        params={"iterations": "3"},
    )

    assert errors == [
        "**Iterations** must be greater than zero",
        "pointer error",
    ]
    assert len(service.currentProject.storedProtocols) == 1


def test_LaunchProtocolRejectsUnknownExecuteMode(service, mapper):
    with pytest.raises(HTTPException) as exc:
        service.launchProtocol(
            mapper=mapper,
            projectId=1,
            protocolId="10",
            protocolClassName="ProtClass",
            params={},
            executeMode="invalid-mode",
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "Unknown executeMode: invalid-mode"


def test_LaunchProtocolStopDelegatesToStopProtocol(service, mapper, monkeypatch):
    calls = []

    monkeypatch.setattr(
        service,
        "stopProtocol",
        lambda mapper, projectId, protocolIds: calls.append(protocolIds),
    )

    service.launchProtocol(
        mapper=mapper,
        projectId=1,
        protocolId="10",
        protocolClassName="ProtClass",
        params={},
        executeMode="stop",
    )

    assert calls == [["10"]]


def test_LaunchProtocolRaises422WhenValidationFails(service, mapper, monkeypatch):
    protocol = FakeProtocol(objId=10, validateErrors=["protocol validation error"])
    monkeypatch.setattr(service, "saveProtocol", lambda *args, **kwargs: (protocol, ["save error"]))

    with pytest.raises(HTTPException) as exc:
        service.launchProtocol(
            mapper=mapper,
            projectId=1,
            protocolId="10",
            protocolClassName="ProtClass",
            params={},
            executeMode="launch",
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == ["save error", "protocol validation error"]


@pytest.mark.parametrize(
    "executeMode, expectedRunMode",
    [
        ("launch", "resume-mode"),
        ("restart", "restart-mode"),
    ],
)
def test_LaunchProtocolRunsProtocolWithExpectedRunMode(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
    executeMode,
    expectedRunMode,
):
    monkeypatch.setattr(projectServiceModule, "MODE_RESUME", "resume-mode")
    monkeypatch.setattr(projectServiceModule, "MODE_RESTART", "restart-mode")

    protocol = FakeProtocol(objId=10, useQueueFlag=True, validateErrors=[])
    monkeypatch.setattr(service, "saveProtocol", lambda *args, **kwargs: (protocol, []))

    service.launchProtocol(
        mapper=mapper,
        projectId=1,
        protocolId="10",
        protocolClassName="ProtClass",
        params={
            "_queueName": "gpu",
            "_queueParams": {"threads": 4},
        },
        executeMode=executeMode,
    )

    assert protocol.queueParams == ["gpu", {"threads": 4}]
    assert protocol.runMode.get() == expectedRunMode
    assert service.currentProject.launchedProtocols == [protocol]


def test_LaunchProtocolSchedulesProtocol(service, mapper, monkeypatch):
    protocol = FakeProtocol(objId=10, validateErrors=[])
    monkeypatch.setattr(service, "saveProtocol", lambda *args, **kwargs: (protocol, []))

    service.launchProtocol(
        mapper=mapper,
        projectId=1,
        protocolId="10",
        protocolClassName="ProtClass",
        params={},
        executeMode="schedule",
    )

    assert service.currentProject.scheduledProtocols == [protocol]
    assert service.currentProject.launchedProtocols == []


def test_RenameProtocolStoresAnnotation(service):
    protocol = FakeProtocol(objId=10)
    service.currentProject.protocols[10] = protocol

    result = service.renameProtocol(
        mapper=None,
        projectId=None,
        protocolId=10,
        newName="Renamed protocol",
        newComment="Updated comment",
    )

    assertSuccessEnvelope(result)
    assert protocol._label is None
    assert protocol.runName.get() == "Renamed protocol"
    assert protocol._objComment == "Updated comment"
    assert service.currentProject.storedProtocols == [protocol]


def test_DuplicateProtocolCopiesAndPersists(service, mapper, monkeypatch):
    protocolA = FakeProtocol(objId=10)
    protocolB = FakeProtocol(objId=11)
    copiedA = FakeProtocol(objId=110)
    copiedB = FakeProtocol(objId=111)

    service.currentProject.protocols[10] = protocolA
    service.currentProject.protocols[11] = protocolB
    service.currentProject.copiedProtocolOutputs = [copiedA, copiedB]

    monkeypatch.setattr(
        service,
        "_buildProtocolContext",
        lambda projectId, protocol: {
            "projectId": projectId,
            "protocolId": protocol.getObjId(),
        },
    )

    def fakeSyncProjectProtocolsAndDependencies(mapperObj, projectId, refresh=False, checkPid=False):
        for protocolObj in service.currentProject.copiedProtocolOutputs:
            mapperObj.saveProtocol(service._buildProtocolContext(projectId, protocolObj))
        return {
            "protocols": len(service.currentProject.copiedProtocolOutputs),
            "dependencies": 0,
        }

    monkeypatch.setattr(
        service,
        "syncProjectProtocolsAndDependencies",
        fakeSyncProjectProtocolsAndDependencies,
    )

    class DuplicateItem:
        def __init__(self, itemId):
            self.id = itemId

    result = service.duplicateProtocol(
        mapper=mapper,
        projectId=1,
        protocols=[DuplicateItem("10"), DuplicateItem("11")],
    )

    assertSuccessEnvelope(result)
    assert result["protocolsCount"] == 2
    assert result["dependenciesCount"] == 0
    assert service.currentProject.copiedProtocolInputs == [[protocolA, protocolB]]
    assert mapper.savedProtocolContexts == [
        {"projectId": 1, "protocolId": 110},
        {"projectId": 1, "protocolId": 111},
    ]


def test_DeleteProtocolDelegatesToCurrentProjectAndMapper(service, mapper):
    protocolA = FakeProtocol(objId=10)
    protocolB = FakeProtocol(objId=11)
    service.currentProject.protocols[10] = protocolA
    service.currentProject.protocols[11] = protocolB

    service.deleteProtocol(
        mapper=mapper,
        projectId=1,
        protocols=["10", "11"],
    )

    assert service.currentProject.deleteProtocolCalls == [[protocolA, protocolB]]
    assert mapper.deleteProtocolCalls == [
        {
            "projectId": 1,
            "protocolList": [protocolA, protocolB],
        }
    ]


def test_DeleteProtocolWrapsUnexpectedErrorAsHttpException(service, mapper):
    protocolA = FakeProtocol(objId=10)
    service.currentProject.protocols[10] = protocolA
    service.currentProject.failDeleteProtocol = RuntimeError("delete failed")

    with pytest.raises(HTTPException) as exc:
        service.deleteProtocol(
            mapper=mapper,
            projectId=1,
            protocols=["10"],
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == "delete failed"


def test_RestartProtocolAllReturnsCollectedErrors(service):
    protocol = FakeProtocol(objId=10)
    service.currentProject.protocols[10] = protocol
    service.currentProject.restartWorkflowInjectedErrors = ["cannot restart", "blocked"]

    with pytest.raises(HTTPException) as exc:
        service.restartProtocolAll(
            mapper=None,
            projectId=None,
            protocolId=10,
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == ["cannot restart", "blocked"]


def test_ContinueProtocolAllLaunchesActiveProtocolsInResumeMode(projectServiceModule, service, mapper, monkeypatch):
    monkeypatch.setattr(projectServiceModule, "MODE_RESUME", "resume-mode")

    protocol = FakeProtocol(objId=10)
    activeProtocol = FakeProtocol(objId=20)

    service.currentProject.protocols[10] = protocol
    service.currentProject._getSubworkflow = lambda protocolObj: (["wf-a", "wf-b"], [activeProtocol])

    result = service.continueProtocolAll(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        currentUser={"id": 1},
    )

    assertSuccessEnvelope(result)
    assert activeProtocol.runMode.get() == "resume-mode"
    assert service.currentProject.launchedProtocols == [activeProtocol]


def test_ResetProtocolFromReturnsSuccessWhenWorkflowResets(service):
    protocol = FakeProtocol(objId=10)
    service.currentProject.protocols[10] = protocol
    service.currentProject.resetWorkflowResult = []

    result = service.resetProtocolFrom(
        mapper=None,
        projectId=None,
        protocolId=10,
    )

    assertSuccessEnvelope(result)


def test_StopProtocolStopsEachProtocol(service):
    protocolA = FakeProtocol(objId=10)
    protocolB = FakeProtocol(objId=11)
    service.currentProject.protocols[10] = protocolA
    service.currentProject.protocols[11] = protocolB

    result = service.stopProtocol(
        mapper=None,
        projectId=None,
        protocolIds=["10", "11"],
    )

    assertSuccessEnvelope(result)
    assert service.currentProject.stoppedProtocols == [protocolA, protocolB]