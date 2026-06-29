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
import json

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


class FakePointerParam(FakeBaseParam):
    def __init__(self, label="Pointer", choices=None, validationErrors=None, allowsNull=True, condition=None):
        super().__init__(
            label=label,
            choices=choices,
            validationErrors=validationErrors,
            allowsNull=allowsNull,
            condition=condition,
        )
        self.default = FakeValueHolder(None)


class FakeMultiPointerParam(FakeBaseParam):
    pass


class FakeRelationParam(FakeBaseParam):
    pass


class FakePointerAttribute:
    def __init__(self):
        self.extended = None

    def setExtended(self, extended):
        self.extended = extended


class FakePointerList(list):
    def isEmpty(self):
        return len(self) == 0


class FakePointer:
    def __init__(self, protocol, extended=None):
        self.protocol = protocol
        self.extended = extended

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

    def getPlugin(self):
        return None

    def getClassName(self):
        return self._className

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

    def _fixProtParamsConfiguration(self, protocol):
        self.fixedProtocolParams = getattr(self, "fixedProtocolParams", [])
        self.fixedProtocolParams.append(protocol)

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
    # fakeMapper
    def __init__(self):
        self.db = FakeDb()
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


def test_BuildMissingOutputSyncItemsClassifiesMissingOutputs(service):
    declaredOutputs = [
        {
            "outputName": "persistedOutput",
            "outputClassName": "SetOfParticles",
        },
        {
            "outputName": "skippedOutput",
            "outputClassName": "UnsupportedOutput",
        },
        {
            "outputName": "erroredOutput",
            "outputClassName": "SetOfBad",
        },
        {
            "outputName": "missingOutput",
            "outputClassName": "SetOfMissing",
        },
    ]
    persistedOutputs = [
        {
            "outputName": "persistedOutput",
            "outputClassName": "SetOfParticles",
        }
    ]
    skippedOutputs = [
        {
            "outputName": "skippedOutput",
            "outputClassName": "UnsupportedOutput",
            "reason": "unsupported_output_type",
        }
    ]
    outputErrors = [
        {
            "outputName": "erroredOutput",
            "outputClassName": "SetOfBad",
            "error": "broken output",
        }
    ]

    result = service._buildMissingOutputSyncItems(
        protocolId=10,
        declaredOutputs=declaredOutputs,
        persistedOutputs=persistedOutputs,
        skippedOutputs=skippedOutputs,
        outputErrors=outputErrors,
    )

    assert result == [
        {
            "protocolId": "10",
            "outputName": "skippedOutput",
            "outputClassName": "UnsupportedOutput",
            "reason": "unsupported_output_type",
        },
        {
            "protocolId": "10",
            "outputName": "erroredOutput",
            "outputClassName": "SetOfBad",
            "reason": "persistence_error",
            "error": "broken output",
        },
        {
            "protocolId": "10",
            "outputName": "missingOutput",
            "outputClassName": "SetOfMissing",
            "reason": "not_persisted",
        },
    ]

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
                ("emptyOutput", None),
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

    assert report["declared"] == [
        {
            "outputName": "outputParticles",
            "outputClassName": "SetOfParticles",
        },
        {
            "outputName": "outputVolume",
            "outputClassName": "Volume",
        },
        {
            "outputName": "badSet",
            "outputClassName": "SetOfBadThings",
        },
        {
            "outputName": "emptyOutput",
            "outputClassName": "",
        },
        {
            "outputName": "unsupportedOutput",
            "outputClassName": "FakeUnsupportedOutput",
        },
    ]

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
            "outputName": "emptyOutput",
            "outputClassName": "",
            "reason": "empty_output",
        },
        {
            "outputName": "unsupportedOutput",
            "outputClassName": "FakeUnsupportedOutput",
            "reason": "unsupported_output_type",
        },
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
            "declared": [
                {
                    "outputName": "outputParticles",
                    "outputClassName": "SetOfParticles",
                },
                {
                    "outputName": "outputVolume",
                    "outputClassName": "Volume",
                },
                {
                    "outputName": "unsupportedOutput",
                    "outputClassName": "UnsupportedOutput",
                },
                {
                    "outputName": "badOutput",
                    "outputClassName": "SetOfBad",
                },
                {
                    "outputName": "orphanOutput",
                    "outputClassName": "SetOfOrphan",
                },
            ],
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
        "steps": 0,
        "stepsProtocols": 0,
        "stepErrors": [],
        "outputsDeclared": 5,
        "outputs": 2,
        "outputsMissing": 3,
        "outputsByKind": {
            "flat_set": 1,
            "tree": 1,
        },
        "outputMissing": [
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
                "reason": "persistence_error",
                "error": "boom",
            },
            {
                "protocolId": "10",
                "outputName": "orphanOutput",
                "outputClassName": "SetOfOrphan",
                "reason": "not_persisted",
            },
        ],
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


def test_GetPostgresqlIntegratedAnalyzeContextUsesResolvedProtocolId(
    service,
    monkeypatch,
):
    readerCalls = []
    resolverCalls = []

    class FakeDb:
        pass

    class FakeMapper:
        def __init__(self):
            self.db = FakeDb()

    class FakePostgresqlIntegratedContextReader:
        def __init__(self, db, projectId, protocolId, outputName):
            readerCalls.append({
                "db": db,
                "projectId": projectId,
                "protocolId": protocolId,
                "outputName": outputName,
            })

        def getContext(self):
            return {
                "root": {
                    "projectId": 1,
                    "protocolId": 321,
                    "outputName": "outputTiltSeries",
                }
            }

    readerModule = importlib.import_module(
        "app.backend.viewers.postgresql_integrated_context_reader"
    )

    monkeypatch.setattr(
        readerModule,
        "PostgresqlIntegratedContextReader",
        FakePostgresqlIntegratedContextReader,
    )

    def fakeResolvePostgresqlReaderProtocolId(mapper, projectId, protocolId):
        resolverCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
        })
        return 321

    monkeypatch.setattr(
        service,
        "_resolvePostgresqlReaderProtocolId",
        fakeResolvePostgresqlReaderProtocolId,
    )

    mapper = FakeMapper()

    result = service._getPostgresqlIntegratedAnalyzeContextIfAvailable(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        outputName="outputTiltSeries",
    )

    assert result == {
        "root": {
            "projectId": 1,
            "protocolId": 321,
            "outputName": "outputTiltSeries",
        }
    }

    assert resolverCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 10,
        }
    ]

    assert readerCalls == [
        {
            "db": mapper.db,
            "projectId": 1,
            "protocolId": 321,
            "outputName": "outputTiltSeries",
        }
    ]


def test_GetIntegratedAnalyzeContextRequiresPostgresqlWhenMapperIsPresent(
    service,
    monkeypatch,
):
    class FakeMapper:
        pass

    class RuntimeShouldNotBeUsed:
        def getProtocol(self, protocolId):
            raise AssertionError("Runtime fallback should not be used")

    service.currentProject = RuntimeShouldNotBeUsed()

    monkeypatch.setattr(
        service,
        "_getPostgresqlIntegratedAnalyzeContextIfAvailable",
        lambda mapper, projectId, protocolId, outputName: None,
    )

    with pytest.raises(HTTPException) as exc:
        service.getIntegratedAnalyzeContextService(
            mapper=FakeMapper(),
            projectId=1,
            protocolId=10,
            outputName="outputTiltSeries",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == (
        "Integrated Analyze Context output is not available in PostgreSQL metadata: "
        "context_not_available"
    )


def test_GetIntegratedAnalyzeContextKeepsLegacyRuntimeFallbackWithoutMapper(
    service,
    monkeypatch,
):
    class FakeTiltSeriesOutput:
        def getClassName(self):
            return "SetOfTiltSeries"

        def getObjId(self):
            return 22

        def getSize(self):
            return 1

        def getTSIds(self):
            return ["TS_001"]

        def getSamplingRate(self):
            return 1.5

        def getDimensions(self):
            return (100, 100, 40)

        def iterItems(self):
            return iter([])

    class FakeProtocol:
        def __init__(self):
            self.outputTiltSeries = FakeTiltSeriesOutput()

        def iterInputAttributes(self):
            return []

        def iterOutputAttributes(self):
            return [("outputTiltSeries", self.outputTiltSeries)]

    class FakeCurrentProjectForIntegratedContext:
        def __init__(self):
            self.protocol = FakeProtocol()

        def getProtocol(self, protocolId):
            assert protocolId == 10
            return self.protocol

    service.currentProject = FakeCurrentProjectForIntegratedContext()

    monkeypatch.setattr(
        service,
        "_getPostgresqlIntegratedAnalyzeContextIfAvailable",
        lambda mapper, projectId, protocolId, outputName: None,
    )

    result = service.getIntegratedAnalyzeContextService(
        mapper=None,
        projectId=1,
        protocolId=10,
        outputName="outputTiltSeries",
    )

    assert result["root"] == {
        "projectId": 1,
        "protocolId": 10,
        "outputName": "outputTiltSeries",
        "outputClass": "SetOfTiltSeries",
    }

    assert result["links"]["tiltSeries"] == {
        "protocolId": 10,
        "outputName": "outputTiltSeries",
        "itemId": 22,
        "label": "outputTiltSeries",
        "status": "available",
    }

    assert result["summaries"]["tiltSeries"]["objectClass"] == "SetOfTiltSeries"
    assert result["summaries"]["tiltSeries"]["objectId"] == 22
    assert result["summaries"]["tiltSeries"]["size"] == 1


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

    def fakeStopProtocol(mapper, projectId, protocolIds):
        calls.append(protocolIds)

    def fakeSyncProjectProtocolsAndDependencies(
        mapper,
        projectId,
        refresh=False,
        checkPid=False,
    ):
        return {
            "protocols": 1,
            "dependencies": 0,
        }

    monkeypatch.setattr(service, "stopProtocol", fakeStopProtocol)
    monkeypatch.setattr(
        service,
        "syncProjectProtocolsAndDependencies",
        fakeSyncProjectProtocolsAndDependencies,
    )

    result = service.launchProtocol(
        mapper=mapper,
        projectId=1,
        protocolId="10",
        protocolClassName="ProtClass",
        params={},
        executeMode="stop",
    )

    assert calls == [["10"]]
    assert result == {
        "protocols": 1,
        "dependencies": 0,
    }


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


def test_RenameProtocolResolvesPostgresqlProtocolId(service, mapper):
    protocol = FakeProtocol(objId=10)
    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    result = service.renameProtocol(
        mapper=mapper,
        projectId=1,
        protocolId=500,
        newName="Renamed protocol",
        newComment="Updated comment",
    )

    assertSuccessEnvelope(result)
    assert protocol.runName.get() == "Renamed protocol"
    assert protocol._objComment == "Updated comment"
    assert service.currentProject.storedProtocols == [protocol]
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")


def test_DuplicateProtocolResolvesPostgresqlProtocolIds(service, mapper, monkeypatch):
    protocolA = FakeProtocol(objId=10)
    protocolB = FakeProtocol(objId=11)
    copiedA = FakeProtocol(objId=110)
    copiedB = FakeProtocol(objId=111)

    service.currentProject.protocols[10] = protocolA
    service.currentProject.protocols[11] = protocolB
    service.currentProject.copiedProtocolOutputs = [copiedA, copiedB]

    mapper.db.runtimeProtocolIdByDbId[500] = 10
    mapper.db.runtimeProtocolIdByDbId[501] = 11

    monkeypatch.setattr(
        service,
        "syncProjectProtocolsAndDependencies",
        lambda mapper, projectId, refresh=False, checkPid=False: {
            "protocols": 2,
            "dependencies": 0,
        },
    )

    class DuplicateItem:
        def __init__(self, itemId):
            self.id = itemId

    result = service.duplicateProtocol(
        mapper=mapper,
        projectId=1,
        protocols=[DuplicateItem("500"), DuplicateItem("501")],
    )

    assertSuccessEnvelope(result)
    assert service.currentProject.copiedProtocolInputs == [[protocolA, protocolB]]
    assert result["duplicated"] == [
        {"sourceId": "500", "newId": "110"},
        {"sourceId": "501", "newId": "111"},
    ]


def test_DeleteProtocolResolvesPostgresqlProtocolIds(service, mapper, monkeypatch):
    protocolA = FakeProtocol(objId=10)
    protocolB = FakeProtocol(objId=11)

    service.currentProject.protocols[10] = protocolA
    service.currentProject.protocols[11] = protocolB

    mapper.db.runtimeProtocolIdByDbId[500] = 10
    mapper.db.runtimeProtocolIdByDbId[501] = 11

    monkeypatch.setattr(
        service,
        "syncProjectProtocolsAndDependencies",
        lambda mapper, projectId, refresh=False, checkPid=False: {
            "protocols": 0,
            "dependencies": 0,
        },
    )

    result = service.deleteProtocol(
        mapper=mapper,
        projectId=1,
        protocols=["500", "501"],
    )

    assert result["status"] == 0
    assert service.currentProject.deleteProtocolCalls == [[protocolA, protocolB]]
    assert mapper.deleteProtocolCalls == [
        {
            "projectId": 1,
            "protocolList": [protocolA, protocolB],
        }
    ]

def test_StopProtocolResolvesPostgresqlProtocolIds(service, mapper):
    protocolA = FakeProtocol(objId=10)
    protocolB = FakeProtocol(objId=11)

    service.currentProject.protocols[10] = protocolA
    service.currentProject.protocols[11] = protocolB

    mapper.db.runtimeProtocolIdByDbId[500] = 10
    mapper.db.runtimeProtocolIdByDbId[501] = 11

    result = service.stopProtocol(
        mapper=mapper,
        projectId=1,
        protocolIds=["500", "501"],
    )

    assertSuccessEnvelope(result)
    assert service.currentProject.stoppedProtocols == [protocolA, protocolB]


def test_RestartProtocolAllResolvesPostgresqlProtocolId(service, mapper, monkeypatch):
    protocol = FakeProtocol(objId=10)
    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    subworkflowCalls = []

    def fakeGetSubworkflow(protocolObj):
        subworkflowCalls.append(protocolObj)
        return [protocol], []

    service.currentProject._getSubworkflow = fakeGetSubworkflow

    cleanupCalls = []

    monkeypatch.setattr(
        service,
        "_deletePersistedProtocolOutputsForRuntimeProtocolsFromPostgresql",
        lambda mapper, projectId, protocols: cleanupCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "protocols": protocols,
        }) or {
            "protocolsCount": len(protocols),
            "setsDeleted": 0,
            "objectsDeleted": 0,
            "items": [],
        },
    )

    result = service.restartProtocolAll(
        mapper=mapper,
        projectId=1,
        protocolId=500,
    )

    assertSuccessEnvelope(result)
    assert subworkflowCalls == [protocol]
    assert cleanupCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocols": [protocol],
        }
    ]
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")


def test_ContinueProtocolAllResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "MODE_RESUME", "resume-mode")

    protocol = FakeProtocol(objId=10)
    activeProtocol = FakeProtocol(objId=20)

    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    subworkflowCalls = []

    def fakeGetSubworkflow(protocolObj):
        subworkflowCalls.append(protocolObj)
        return [protocol], [activeProtocol]

    service.currentProject._getSubworkflow = fakeGetSubworkflow

    result = service.continueProtocolAll(
        mapper=mapper,
        projectId=1,
        protocolId=500,
        currentUser={"id": 1},
    )

    assertSuccessEnvelope(result)
    assert subworkflowCalls == [protocol]
    assert activeProtocol.runMode.get() == "resume-mode"
    assert service.currentProject.launchedProtocols == [activeProtocol]
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")


def test_ResetProtocolFromResolvesPostgresqlProtocolId(service, mapper, monkeypatch):
    protocol = FakeProtocol(objId=10)

    service.currentProject.protocols[10] = protocol
    service.currentProject.resetWorkflowResult = []
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    subworkflowCalls = []

    def fakeGetSubworkflow(protocolObj):
        subworkflowCalls.append(protocolObj)
        return [protocol], []

    service.currentProject._getSubworkflow = fakeGetSubworkflow

    cleanupCalls = []

    monkeypatch.setattr(
        service,
        "_deletePersistedProtocolOutputsForRuntimeProtocolsFromPostgresql",
        lambda mapper, projectId, protocols: cleanupCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "protocols": protocols,
        }) or {
            "protocolsCount": len(protocols),
            "setsDeleted": 0,
            "objectsDeleted": 0,
            "items": [],
        },
    )

    result = service.resetProtocolFrom(
        mapper=mapper,
        projectId=1,
        protocolId=500,
    )

    assertSuccessEnvelope(result)
    assert subworkflowCalls == [protocol]
    assert cleanupCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocols": [protocol],
        }
    ]
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")


def test_GetNextProtocolSuggestionsResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    protocol = FakeProtocol(objId=10, className="ProtImportMovies")
    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    calledUrls = []

    class FakeResponse:
        def read(self):
            return json.dumps([
                [
                    "ProtLowerScore",
                    3,
                    "Lower score protocol",
                    "scipion-em-lower",
                    "Lower score help",
                ],
                [
                    "ProtHigherScore",
                    9,
                    "Higher score protocol",
                    "scipion-em-higher",
                    "Higher score help",
                ],
            ]).encode("utf-8")

    def fakeUrlopen(url):
        calledUrls.append(url)
        return FakeResponse()

    class FakeConfig:
        SCIPION_STATS_SUGGESTION = "https://example.test/suggestions/%s"

        @staticmethod
        def getDomain():
            return FakeDomain({})

    monkeypatch.setattr(projectServiceModule, "Config", FakeConfig)
    monkeypatch.setattr(projectServiceModule, "urlopen", fakeUrlopen)

    result = service.getNextProtocolSuggestions(
        mapper=mapper,
        projectId=1,
        protocolId=500,
    )

    assert calledUrls == [
        "https://example.test/suggestions/ProtImportMovies",
    ]

    assert result == [
        {
            "protocolName": "Higher score protocol",
            "protocolClass": "ProtHigherScore",
            "help": "Higher score help",
            "installed": "Missing. Available in scipion-em-higher plugin.",
        },
        {
            "protocolName": "Lower score protocol",
            "protocolClass": "ProtLowerScore",
            "help": "Lower score help",
            "installed": "Missing. Available in scipion-em-lower plugin.",
        },
    ]

    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")


def test_GetProtocolParamsResolvesPostgresqlProtocolId(service, mapper, monkeypatch):
    protocol = FakeProtocol(objId=10, className="ProtClass")
    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    buildContextCalls = []

    def fakeBuildProtocolContext(projectId, protocolObj):
        buildContextCalls.append({
            "projectId": projectId,
            "protocol": protocolObj,
        })
        return {
            "info": {
                "projectId": projectId,
                "protocolId": protocolObj.getObjId(),
                "protocolClassName": "ProtClass",
            },
            "form": {
                "sections": [],
            },
            "values": {},
        }

    monkeypatch.setattr(service, "_buildProtocolContext", fakeBuildProtocolContext)

    result = service.getProtocolParams(
        mapper=mapper,
        projectId=1,
        protocolId=500,
    )

    assert result == {
        "info": {
            "projectId": 1,
            "protocolId": 10,
            "protocolClassName": "ProtClass",
        },
        "form": {
            "sections": [],
        },
        "values": {},
    }

    assert service.currentProject.fixedProtocolParams == [protocol]
    assert buildContextCalls == [
        {
            "projectId": 1,
            "protocol": protocol,
        }
    ]
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")

def test_SaveProtocolResolvesPostgresqlProtocolIdForExistingProtocol(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "IntParam", FakeIntParam)
    monkeypatch.setattr(projectServiceModule, "StringParam", FakeStringParam)
    monkeypatch.setattr(projectServiceModule, "EnumParam", FakeEnumParam)
    monkeypatch.setattr(projectServiceModule, "CsvList", FakeCsvList)

    protocol = FakeProtocol(objId=10, className="ProtClass")
    protocol.addParam("runName", FakeStringParam(label="Run name"))
    protocol.addParam("iterations", FakeIntParam(label="Iterations"))

    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    monkeypatch.setattr(
        service,
        "applyParamsToProtocol",
        lambda mapper=None, projectId=None, protocol=None, params=None: [],
    )

    savedProtocol, errors = service.saveProtocol(
        mapper=mapper,
        projectId=1,
        protocolId=500,
        protocolClassName="ProtClass",
        params={
            "runName": "Edited protocol",
            "iterations": "7",
        },
        setToSave=False,
    )

    assert errors == []
    assert savedProtocol is protocol
    assert protocol.runName.get() == "Edited protocol"
    assert protocol.attributeValues["iterations"] == 7
    assert service.currentProject.storedProtocols == [protocol]
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")


def test_LaunchProtocolLaunchResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "IntParam", FakeIntParam)
    monkeypatch.setattr(projectServiceModule, "StringParam", FakeStringParam)
    monkeypatch.setattr(projectServiceModule, "EnumParam", FakeEnumParam)
    monkeypatch.setattr(projectServiceModule, "CsvList", FakeCsvList)
    monkeypatch.setattr(projectServiceModule, "MODE_RESUME", "resume-mode")

    protocol = FakeProtocol(objId=10, className="ProtClass", validateErrors=[])
    protocol.addParam("runName", FakeStringParam(label="Run name"))
    protocol.addParam("iterations", FakeIntParam(label="Iterations"))

    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    monkeypatch.setattr(
        service,
        "applyParamsToProtocol",
        lambda mapper=None, projectId=None, protocol=None, params=None: [],
    )

    service.launchProtocol(
        mapper=mapper,
        projectId=1,
        protocolId=500,
        protocolClassName="ProtClass",
        params={
            "runName": "Launch protocol",
            "iterations": "7",
        },
        executeMode="launch",
    )

    assert protocol.runName.get() == "Launch protocol"
    assert protocol.attributeValues["iterations"] == 7
    assert protocol.runMode.get() == "resume-mode"
    assert service.currentProject.storedProtocols == [protocol]
    assert service.currentProject.launchedProtocols == [protocol]
    assert service.currentProject.scheduledProtocols == []
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")


def test_LaunchProtocolRestartResolvesPostgresqlProtocolId(
            projectServiceModule,
            service,
            mapper,
            monkeypatch,
    ):
        monkeypatch.setattr(projectServiceModule, "IntParam", FakeIntParam)
        monkeypatch.setattr(projectServiceModule, "StringParam", FakeStringParam)
        monkeypatch.setattr(projectServiceModule, "EnumParam", FakeEnumParam)
        monkeypatch.setattr(projectServiceModule, "CsvList", FakeCsvList)
        monkeypatch.setattr(projectServiceModule, "MODE_RESTART", "restart-mode")

        protocol = FakeProtocol(objId=10, className="ProtClass", validateErrors=[])
        protocol.addParam("runName", FakeStringParam(label="Run name"))
        protocol.addParam("iterations", FakeIntParam(label="Iterations"))

        service.currentProject.protocols[10] = protocol
        mapper.db.runtimeProtocolIdByDbId[500] = 10

        monkeypatch.setattr(
            service,
            "applyParamsToProtocol",
            lambda mapper=None, projectId=None, protocol=None, params=None: [],
        )

        cleanupCalls = []

        monkeypatch.setattr(
            service,
            "_deletePersistedProtocolOutputsForRuntimeProtocolsFromPostgresql",
            lambda mapper, projectId, protocols: cleanupCalls.append({
                "mapper": mapper,
                "projectId": projectId,
                "protocols": protocols,
            }) or {
                                                     "protocolsCount": len(protocols),
                                                     "setsDeleted": 0,
                                                     "objectsDeleted": 0,
                                                     "items": [],
                                                 },
        )

        service.launchProtocol(
            mapper=mapper,
            projectId=1,
            protocolId=500,
            protocolClassName="ProtClass",
            params={
                "runName": "Restart protocol",
                "iterations": "9",
            },
            executeMode="restart",
        )

        assert protocol.runName.get() == "Restart protocol"
        assert protocol.attributeValues["iterations"] == 9
        assert protocol.runMode.get() == "restart-mode"
        assert service.currentProject.storedProtocols == [protocol]
        assert service.currentProject.launchedProtocols == [protocol]
        assert service.currentProject.scheduledProtocols == []
        assert cleanupCalls == [
            {
                "mapper": mapper,
                "projectId": 1,
                "protocols": [protocol],
            }
        ]
        assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")

def test_LaunchProtocolScheduleResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "IntParam", FakeIntParam)
    monkeypatch.setattr(projectServiceModule, "StringParam", FakeStringParam)
    monkeypatch.setattr(projectServiceModule, "EnumParam", FakeEnumParam)
    monkeypatch.setattr(projectServiceModule, "CsvList", FakeCsvList)

    protocol = FakeProtocol(objId=10, className="ProtClass", validateErrors=[])
    protocol.addParam("runName", FakeStringParam(label="Run name"))
    protocol.addParam("iterations", FakeIntParam(label="Iterations"))

    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    monkeypatch.setattr(
        service,
        "applyParamsToProtocol",
        lambda mapper=None, projectId=None, protocol=None, params=None: [],
    )

    service.launchProtocol(
        mapper=mapper,
        projectId=1,
        protocolId=500,
        protocolClassName="ProtClass",
        params={
            "runName": "Schedule protocol",
            "iterations": "11",
        },
        executeMode="schedule",
    )

    assert protocol.runName.get() == "Schedule protocol"
    assert protocol.attributeValues["iterations"] == 11
    assert protocol.runMode.get() is None
    assert service.currentProject.storedProtocols == [protocol]
    assert service.currentProject.scheduledProtocols == [protocol]
    assert service.currentProject.launchedProtocols == []
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")


def test_ExportWorkflowProtocolsResolvesPostgresqlProtocolIds(service, mapper):
    protocolA = FakeProtocol(objId=10, className="ProtA")
    protocolB = FakeProtocol(objId=11, className="ProtB")

    service.currentProject.protocols[10] = protocolA
    service.currentProject.protocols[11] = protocolB

    mapper.db.runtimeProtocolIdByDbId[500] = 10
    mapper.db.runtimeProtocolIdByDbId[501] = 11

    exportedProtocolLists = []

    def fakeGetProtocolsJson(protocolList):
        exportedProtocolLists.append(protocolList)
        return [
            {
                "protocol": "exported-a",
            },
            {
                "protocol": "exported-b",
            },
        ]

    service.currentProject.getProtocolsJson = fakeGetProtocolsJson

    class FakeExportPayload:
        includeUpstream = False
        protocolIds = ["500", "501"]

    result = service.exportWorkflowProtocolsService(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 1},
        payload=FakeExportPayload(),
    )

    assert exportedProtocolLists == [[protocolA, protocolB]]
    assert result["sourceProjectId"] == 1
    assert result["protocolIds"] == ["500", "501"]
    assert result["workflow"] == [
        {
            "protocol": "exported-a",
        },
        {
            "protocol": "exported-b",
        },
    ]

    assert result["scipionWeb"]["sourceProjectId"] == 1
    assert result["scipionWeb"]["sourceProtocolIds"] == ["500", "501"]
    assert result["scipionWeb"]["protocolPlugins"][0]["protocolId"] == "10"
    assert result["scipionWeb"]["protocolPlugins"][1]["protocolId"] == "11"

    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")
    assert mapper.db.fetchOneCalls[1]["params"] == (1, 501, "501")


def test_ExportWorkflowProtocolsRaisesWhenPostgresqlProtocolIdCannotBeResolved(service, mapper):
    protocol = FakeProtocol(objId=10, className="ProtA")
    service.currentProject.protocols[10] = protocol

    mapper.db.runtimeProtocolIdByDbId[500] = 10

    class FakeExportPayload:
        includeUpstream = False
        protocolIds = ["500", "999"]

    with pytest.raises(HTTPException) as exc:
        service.exportWorkflowProtocolsService(
            mapper=mapper,
            projectId=1,
            currentUser={"id": 1},
            payload=FakeExportPayload(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Protocol(s) not found: 999"
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")
    assert mapper.db.fetchOneCalls[1]["params"] == (1, 999, "999")


def test_ImportWorkflowProtocolsSanitizesExternalReferences(service, mapper, monkeypatch):
    loadedJsonPayloads = []

    def fakeLoadProtocols(jsonStr):
        loadedJsonPayloads.append(json.loads(jsonStr))
        return None

    service.currentProject.loadProtocols = fakeLoadProtocols

    workflowIds = [
        {"10"},
        {"10", "20", "21"},
    ]

    monkeypatch.setattr(
        service,
        "_getCurrentWorkflowProtocolIds",
        lambda: workflowIds.pop(0),
    )

    monkeypatch.setattr(
        service,
        "syncProjectProtocolsAndDependencies",
        lambda mapper, projectId, refresh=False, checkPid=False: {
            "protocols": 3,
            "dependencies": 2,
        },
    )

    class FakeImportPayload:
        mode = "append"
        sourceProjectId = 999
        workflow = [
            {
                "object.id": "1",
                "inputFromCopiedProtocol": "1.outputParticles",
                "inputFromExternalProtocol": "99.outputParticles",
                "params": {
                    "validPointer": "2.outputVolume",
                    "invalidPointer": "100.outputCoordinates",
                },
            },
            {
                "object.id": "2",
                "inputFromFirstProtocol": "1.outputParticles",
            },
        ]

    result = service.importWorkflowProtocolsService(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 1},
        payload=FakeImportPayload(),
    )

    assert result == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "created": [
            {"newId": "20"},
            {"newId": "21"},
        ],
        "protocolsCount": 3,
        "dependenciesCount": 2,
    }

    assert loadedJsonPayloads == [
        [
            {
                "object.id": "1",
                "inputFromCopiedProtocol": "1.outputParticles",
                "params": {
                    "validPointer": "2.outputVolume",
                },
            },
            {
                "object.id": "2",
                "inputFromFirstProtocol": "1.outputParticles",
            },
        ]
    ]


def test_ImportWorkflowProtocolsKeepsReferencesForSameProject(service, mapper, monkeypatch):
    loadedJsonPayloads = []

    def fakeLoadProtocols(jsonStr):
        loadedJsonPayloads.append(json.loads(jsonStr))
        return None

    service.currentProject.loadProtocols = fakeLoadProtocols

    workflowIds = [
        {"10"},
        {"10", "20"},
    ]

    monkeypatch.setattr(
        service,
        "_getCurrentWorkflowProtocolIds",
        lambda: workflowIds.pop(0),
    )

    monkeypatch.setattr(
        service,
        "syncProjectProtocolsAndDependencies",
        lambda mapper, projectId, refresh=False, checkPid=False: {
            "protocols": 2,
            "dependencies": 1,
        },
    )

    class FakeImportPayload:
        mode = "append"
        sourceProjectId = 1
        workflow = [
            {
                "object.id": "1",
                "inputFromExistingSameProjectProtocol": "99.outputParticles",
                "inputFromCopiedProtocol": "1.outputParticles",
            },
        ]

    result = service.importWorkflowProtocolsService(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 1},
        payload=FakeImportPayload(),
    )

    assert result == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "created": [
            {"newId": "20"},
        ],
        "protocolsCount": 2,
        "dependenciesCount": 1,
    }

    assert loadedJsonPayloads == [
        [
            {
                "object.id": "1",
                "inputFromExistingSameProjectProtocol": "99.outputParticles",
                "inputFromCopiedProtocol": "1.outputParticles",
            },
        ]
    ]


def test_ApplyParamsToProtocolResolvesPostgresqlPointerParentId(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "PointerParam", FakePointerParam)
    monkeypatch.setattr(projectServiceModule, "MultiPointerParam", FakeMultiPointerParam)
    monkeypatch.setattr(projectServiceModule, "RelationParam", FakeRelationParam)

    parentProtocol = FakeProtocol(objId=10, className="ParentProtocol")
    parentProtocol.outputParticles = object()

    protocol = FakeProtocol(objId=20, className="ChildProtocol")
    pointerParam = FakePointerParam(label="Input particles")
    protocol.addParam("inputParticles", pointerParam)
    protocol.inputParticles = FakePointerAttribute()

    service.currentProject.protocols[10] = parentProtocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    errors = service.applyParamsToProtocol(
        mapper=mapper,
        projectId=1,
        protocol=protocol,
        params={
            "inputParticles": "500.outputParticles",
        },
    )

    assert errors == []
    assert pointerParam.get() == "10.outputParticles"
    assert pointerParam.default.get() == "10.outputParticles"
    assert protocol.attributeValues["inputParticles"] is parentProtocol
    assert protocol.inputParticles.extended == "outputParticles"
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")

def test_SetPointerParamResolvesPostgresqlPointerParentId(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "PointerParam", FakePointerParam)

    parentProtocol = FakeProtocol(objId=10, className="ParentProtocol")
    protocol = FakeProtocol(objId=20, className="ChildProtocol")

    pointerParam = FakePointerParam(label="Input volume")
    protocol.addParam("inputVolume", pointerParam)

    service.currentProject.protocols[10] = parentProtocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    service.setPointerParam(
        mapper=mapper,
        projectId=1,
        protocol=protocol,
        key="inputVolume",
        value={
            "editableValue": "500.outputVolume",
        },
        parentId=500,
    )

    assert pointerParam.get() == "10.outputVolume"
    assert pointerParam.default.get() == "10.outputVolume"
    assert protocol.attributeValues["inputVolume"] is parentProtocol
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")

def test_ApplyParamsToProtocolResolvesPostgresqlMultiPointerParentIds(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "PointerParam", FakePointerParam)
    monkeypatch.setattr(projectServiceModule, "MultiPointerParam", FakeMultiPointerParam)
    monkeypatch.setattr(projectServiceModule, "RelationParam", FakeRelationParam)
    monkeypatch.setattr(projectServiceModule, "PointerList", FakePointerList)
    monkeypatch.setattr(projectServiceModule, "Pointer", FakePointer)

    parentProtocolA = FakeProtocol(objId=10, className="ParentProtocolA")
    parentProtocolB = FakeProtocol(objId=11, className="ParentProtocolB")

    protocol = FakeProtocol(objId=20, className="ChildProtocol")
    multiPointerParam = FakeMultiPointerParam(label="Input sets")
    protocol.addParam("inputSets", multiPointerParam)

    service.currentProject.protocols[10] = parentProtocolA
    service.currentProject.protocols[11] = parentProtocolB

    mapper.db.runtimeProtocolIdByDbId[500] = 10
    mapper.db.runtimeProtocolIdByDbId[501] = 11

    errors = service.applyParamsToProtocol(
        mapper=mapper,
        projectId=1,
        protocol=protocol,
        params={
            "inputSets": [
                "500.outputParticles",
                "501.outputClasses",
            ],
        },
    )

    assert errors == []
    assert len(protocol.attributeValues["inputSets"]) == 2
    assert protocol.attributeValues["inputSets"][0].protocol is parentProtocolA
    assert protocol.attributeValues["inputSets"][0].extended == "outputParticles"
    assert protocol.attributeValues["inputSets"][1].protocol is parentProtocolB
    assert protocol.attributeValues["inputSets"][1].extended == "outputClasses"
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500, "500")
    assert mapper.db.fetchOneCalls[1]["params"] == (1, 501, "501")


def test_GetNewProtocolParamsCacheIsScopedByProject(
    projectServiceModule,
    service,
    monkeypatch,
):
    projectServiceModule._newProtocolCache.clear()

    class FakeProtocolClass:
        pass

    service.currentProject.protocolFactories = {
        "ProtClass": FakeProtocolClass,
    }

    buildCalls = []

    def fakeBuildProtocolContext(projectId, protocol):
        buildCalls.append(projectId)
        return {
            "info": {
                "projectId": projectId,
                "protocolClassName": "ProtClass",
            },
            "form": {},
            "values": {},
        }

    monkeypatch.setattr(
        service,
        "_buildProtocolContext",
        fakeBuildProtocolContext,
    )

    first = service.getNewProtocolParams(1, "ProtClass")
    second = service.getNewProtocolParams(2, "ProtClass")

    assert first["info"]["projectId"] == 1
    assert second["info"]["projectId"] == 2
    assert buildCalls == [1, 2]

def test_DuplicateProtocolWrapsCopyErrorAsHttpException(service, mapper):
    protocol = FakeProtocol(objId=10)
    service.currentProject.protocols[10] = protocol

    def fakeCopyProtocol(protocols):
        raise RuntimeError("copy failed")

    service.currentProject.copyProtocol = fakeCopyProtocol

    class DuplicateItem:
        def __init__(self, itemId):
            self.id = itemId

    with pytest.raises(HTTPException) as exc:
        service.duplicateProtocol(
            mapper=mapper,
            projectId=1,
            protocols=[DuplicateItem("10")],
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == "Failed to duplicate protocols: copy failed"