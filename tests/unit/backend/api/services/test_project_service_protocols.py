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
from pyworkflow.object import Object as ScipionObject
from pyworkflow.protocol.params import MultiPointerParam, PointerParam
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)


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


def fakeCastProtocolParamValue(param, value):
    if isinstance(param, FakeIntParam):
        return int(value)

    return value


def patchRuntimeParamCasting(monkeypatch):
    protocolSaveServiceModule = importlib.import_module(
        "app.backend.runtime.protocol_save_service"
    )
    monkeypatch.setattr(
        protocolSaveServiceModule,
        "castProtocolParamValue",
        fakeCastProtocolParamValue,
    )


def patchRuntimePointerTypes(monkeypatch):
    protocolSaveServiceModule = importlib.import_module(
        "app.backend.runtime.protocol_save_service"
    )

    monkeypatch.setattr(
        protocolSaveServiceModule,
        "PointerParam",
        FakePointerParam,
    )
    monkeypatch.setattr(
        protocolSaveServiceModule,
        "MultiPointerParam",
        FakeMultiPointerParam,
    )
    monkeypatch.setattr(
        protocolSaveServiceModule,
        "RelationParam",
        FakeRelationParam,
    )
    monkeypatch.setattr(
        protocolSaveServiceModule,
        "Pointer",
        FakePointer,
    )
    monkeypatch.setattr(
        protocolSaveServiceModule,
        "PointerList",
        FakePointerList,
    )

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


class FakeDb:
    def __init__(self):
        self.runtimeProtocolIdByDbId = {}
        self.fetchOneCalls = []

    def fetchOne(self, query, params):
        self.fetchOneCalls.append({
            "query": query,
            "params": params,
        })

        if len(params) != 2:
            return None

        projectId, protocolIdCandidate = params
        queryText = " ".join(str(query).split())

        if "FROM protocols" not in queryText:
            return None

        if "AND id = %s" in queryText:
            try:
                protocolDbId = int(protocolIdCandidate)
            except (TypeError, ValueError):
                return None

            runtimeProtocolId = self.runtimeProtocolIdByDbId.get(
                protocolDbId
            )

            if runtimeProtocolId is None:
                return None

            return {
                "id": protocolDbId,
                "protocolId": str(runtimeProtocolId),
            }

        if 'AND "protocolId" = %s' in queryText:
            runtimeProtocolIdText = str(protocolIdCandidate)

            for protocolDbId, runtimeProtocolId in (
                    self.runtimeProtocolIdByDbId.items()
            ):
                if str(runtimeProtocolId) == runtimeProtocolIdText:
                    return {
                        "id": int(protocolDbId),
                        "protocolId": runtimeProtocolIdText,
                    }

        return None


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
    instance._buildProtocolContext = lambda projectId, protocol, mapper=None: {
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


def test_SyncPostgresqlRuntimeProtocolDoesNotReadLegacyRunDb(projectServiceModule, monkeypatch):
    class FakeProtocol:
        def getStatus(self):
            return "finished"

    class FakeMapper:
        def __init__(self):
            self.savedContexts = []

        def getProjectProtocolByProtocolId(self, projectId, protocolId):
            return {"id": 71, "status": "finished", "params": {}}

        def saveProtocol(self, protocolContext):
            self.savedContexts.append(protocolContext)
            return 71

    class FakeStepPersistenceService:
        def buildProtocolStepsForPostgresql(self, protocol):
            return []

    class FakeOutputPersistenceService:
        def shouldSyncProtocolOutputs(self, protocol):
            return False

        def countRuntimeOutputKinds(self, outputs):
            return {}

    def failLegacyLoad(*args, **kwargs):
        raise AssertionError("Regular PostgreSQL runtime sync must not read run.db")

    protocol = FakeProtocol()
    mapper = FakeMapper()
    service = object.__new__(projectServiceModule.ProjectService)
    service.currentProject = object()
    service._resolveScipionProtocolId = lambda mapper, projectId, protocolId: int(protocolId)
    service._getScipionProtocolByRuntimeId = lambda protocolId: protocol
    service._buildProtocolContext = lambda projectId, protocol, mapper: {"projectId": projectId, "values": {}, "info": {"status": protocol.getStatus()}}

    monkeypatch.setattr(projectServiceModule.LegacyRuntimeProtocolLoaderService, "loadProtocolFromRuntimeDb", failLegacyLoad)
    monkeypatch.setattr(projectServiceModule, "RuntimeProtocolStepPersistenceService", FakeStepPersistenceService)
    monkeypatch.setattr(projectServiceModule, "RuntimeProtocolOutputPersistenceService", FakeOutputPersistenceService)
    monkeypatch.setattr(projectServiceModule.logger, "isEnabledFor", lambda level: False)

    result = service.syncPostgresqlRuntimeProtocol(mapper=mapper, projectId=3, protocolId=12, protocol=protocol, registerOutputs=False, syncRelations=False)

    assert result["protocolId"] == "12"
    assert result["protocolStatus"] == "finished"
    assert len(mapper.savedContexts) == 1


def test_GetParentProtocolForPointerUsesPostgresqlRuntimeOnly(projectServiceModule):
    expectedParentProtocol = object()
    loadedProtocolIds = []
    service = object.__new__(projectServiceModule.ProjectService)
    service._resolveScipionProtocolId = lambda mapper, projectId, protocolId: int(protocolId)
    service._getScipionProtocolByRuntimeId = lambda protocolId: loadedProtocolIds.append(int(protocolId)) or expectedParentProtocol

    parentProtocolId, parentProtocol = service._getParentProtocolForPointer(mapper=object(), projectId=344, parentId="40")

    assert parentProtocolId == 40
    assert parentProtocol is expectedParentProtocol
    assert loadedProtocolIds == [40]
    assert not hasattr(service, "_loadProtocolFromRuntimeDb")


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

    class FakeSetOutput(ScipionObject):
        # fakeSetOutput
        def getClassName(self):
            return "SetOfParticles"

    class FakeObjectOutput(ScipionObject):
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

    class FakePluginObjectOutput(ScipionObject):
        def getClassName(self):
            return "CryoloModel"

        def __str__(self):
            return "CryoloModel(path=/tmp/model.h5)"

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
                ("outputCryoloModel", FakePluginObjectOutput()),
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
    outputPersistenceServiceClass = (
        projectServiceModule
        .RuntimeProtocolOutputPersistenceService
    )

    monkeypatch.setattr(
        outputPersistenceServiceClass,
        "resolveProtocolDbIdForOutputPersistence",
        lambda self, mapper, projectId, protocol: 500,
    )

    monkeypatch.setattr(
        outputPersistenceServiceClass,
        "_prepareOutputObjectIdsForPersistence",
        lambda self, **kwargs: {
            "_identitySnapshot": [],
        },
    )

    monkeypatch.setattr(
        outputPersistenceServiceClass,
        "_openRelativeSetMapperForPersistence",
        lambda self, **kwargs: False,
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
            "outputName": "outputCryoloModel",
            "outputClassName": "CryoloModel",
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
        {
            "projectId": 1,
            "protocolDbId": 500,
            "stored": True,
            "includeNestedProperties": True,
            "mapperKind": "tree",
            "outputName": "outputCryoloModel",
            "outputClassName": "CryoloModel",
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
        lambda projectId, protocol, mapper=None: {
            "projectId": projectId,
            "protocolId": protocol.getObjId(),
        },
    )
    runtimeProjectGraphSyncServiceModule = (
        importlib.import_module(
            "app.backend.runtime.project_graph_sync_service"
        )
    )

    monkeypatch.setattr(
        runtimeProjectGraphSyncServiceModule
        .RuntimeProtocolOutputPersistenceService,
        "shouldSyncProtocolOutputs",
        lambda self, protocol: True,
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

    assert result["protocols"] == 1
    assert result["dependencies"] == 0
    assert result["inputRefs"] == 0

    assert result["steps"] == 0
    assert result["stepsProtocols"] == 0
    assert result["stepErrors"] == []

    assert result["outputsDeclared"] == 5
    assert result["outputs"] == 2
    assert result["outputsRemoved"] == 0
    assert result["removedOutputs"] == []
    assert result["outputsMissing"] == 3

    assert result["outputsByKind"] == {
        "flat_set": 1,
        "tree": 1,
    }

    assert result["objects"] == 2
    assert result["sets"] == 1
    assert result["setItems"] == 0

    assert result["outputMissing"] == [
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
    ]

    assert result["outputErrors"] == [
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
    ]

    assert result["outputPreparationWarnings"] == []
    assert result["purgedProtocols"] == 0

    assert result["complete"] is False
    assert len(result["fatalErrors"]) == 5
    assert {
        error["kind"]
        for error in result["fatalErrors"]
    } == {
        "output",
    }

    assert result["relationsDeclared"] == 0
    assert result["relations"] == 0
    assert result["relationsStale"] == 0
    assert result["staleRelations"] == []
    assert result["relationMissing"] == []
    assert result["relationErrors"] == []

    assert mapper.savedProtocolContexts == [
        {
            "projectId": 1,
            "protocolId": 10,
        }
    ]


    assert mapper.deletedProtocolIds is None
    assert result["purgedProtocols"] == 0


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


def test_CastParamValueSupportsEnumLookup(monkeypatch):
    protocolParamModule = importlib.import_module(
        "app.utils.protocol_param"
    )

    monkeypatch.setattr(
        protocolParamModule,
        "EnumParam",
        FakeEnumParam,
    )

    param = FakeEnumParam(
        choices=[
            "Continue",
            "Restart",
        ]
    )

    assert (
        protocolParamModule
        .castProtocolParamValue(
            param,
            "Restart",
        )
        == 1
    )
    assert (
        protocolParamModule
        .castProtocolParamValue(
            param,
            "restart",
        )
        == 1
    )
    assert (
        protocolParamModule
        .castProtocolParamValue(
            param,
            0,
        )
        == 0
    )


def test_CastParamValueSupportsPrimitiveTypes(monkeypatch):
    protocolParamModule = importlib.import_module(
        "app.utils.protocol_param"
    )

    paramTypes = {
        "IntParam": FakeIntParam,
        "FloatParam": FakeFloatParam,
        "BooleanParam": FakeBooleanParam,
        "StringParam": FakeStringParam,
        "EnumParam": FakeEnumParam,
        "CsvList": FakeCsvList,
    }

    for typeName, fakeType in paramTypes.items():
        monkeypatch.setattr(
            protocolParamModule,
            typeName,
            fakeType,
        )

    castValue = (
        protocolParamModule
        .castProtocolParamValue
    )

    assert castValue(FakeIntParam(), "7") == 7
    assert castValue(FakeFloatParam(), "3.5") == 3.5
    assert castValue(FakeBooleanParam(), "yes") is True
    assert castValue(FakeBooleanParam(), "no") is False
    assert castValue(FakeStringParam(), 123) == "123"
    assert castValue(FakeCsvList(), "item") == ["item"]


def test_SaveProtocolCreatesNewProtocolAndPersistsContext(projectServiceModule, service, mapper, monkeypatch):
    patchRuntimeParamCasting(
        monkeypatch
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
    patchRuntimeParamCasting(
        monkeypatch
    )

    protocol = FakeProtocol(objId=10, className="ProtClass")
    protocol.addParam(
        "iterations",
        FakeIntParam(label="Iterations", validationErrors=["must be greater than zero"]),
    )
    service.currentProject.protocols[10] = protocol
    mapper.dbProtocolsByProtocolId[(10, 1)] = {"id": 500, "protocolId": 10}

    monkeypatch.setattr(
        projectServiceModule
        .RuntimeProtocolSaveService,
        "applyPointerParamsToProtocol",
        lambda self, **kwargs: [
            "pointer error",
        ],
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


def test_LaunchProtocolPostgresqlResumeDoesNotUseLegacyRuntimeDb(service, mapper, monkeypatch):
    protocol = FakeProtocol(objId=10, validateErrors=[])
    monkeypatch.setattr(service, "_currentProjectUsesPostgresqlRuntimeMapper", lambda: True)
    monkeypatch.setattr(service, "saveProtocol", lambda *args, **kwargs: (protocol, []))
    monkeypatch.setattr(service, "_preparePostgresqlRuntimePointerOutputsForLaunch", lambda **kwargs: {"prepared": 0, "items": [], "errors": [], "skipped": False})
    monkeypatch.setattr(RuntimeProtocolStatusSyncService, "getStoredElapsedTimeSeconds", lambda self, **kwargs: 0.0)
    mapper.getProjectProtocolByProtocolId = lambda projectId, protocolId: {"status": "scheduled"}

    result = service.launchProtocol(mapper=mapper, projectId=1, protocolId="10", protocolClassName="ProtClass", params={}, executeMode="launch")

    assert service.currentProject.launchedProtocols == [protocol]
    assert result["postgresqlRuntimeLaunch"] is True
    assert result["protocolStatus"] == "scheduled"

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
    monkeypatch.setattr(
        service,
        "saveProtocol",
        lambda *args, **kwargs: (
            protocol,
            [],
        ),
    )

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
    assert exc.value.detail == [
        "protocol validation error",
    ]


@pytest.mark.parametrize(
    "executeMode, expectedRunMode",
    [
        (None, "resume-mode"),
        ("launch", "resume-mode"),
        ("resume", "resume-mode"),
        ("restart", "restart-mode"),
    ],
)
def test_LaunchProtocolRunsProtocolWithExpectedRunMode(
    service,
    mapper,
    monkeypatch,
    executeMode,
    expectedRunMode,
):
    runtimeProtocolLaunchServiceModule = (
        importlib.import_module(
            "app.backend.runtime.protocol_launch_service"
        )
    )

    monkeypatch.setattr(
        runtimeProtocolLaunchServiceModule,
        "MODE_RESUME",
        "resume-mode",
    )
    monkeypatch.setattr(
        runtimeProtocolLaunchServiceModule,
        "MODE_RESTART",
        "restart-mode",
    )

    protocol = FakeProtocol(objId=10, useQueueFlag=True, validateErrors=[])
    monkeypatch.setattr(service, "saveProtocol", lambda *args, **kwargs: (protocol, []))

    monkeypatch.setattr(
        service,
        "syncProjectProtocolsAndDependencies",
        lambda *args, **kwargs: {
            "protocols": 1,
            "dependencies": 0,
        },
    )

    monkeypatch.setattr(
        service,
        "_deletePersistedProtocolOutputsForRuntimeProtocolsFromPostgresql",
        lambda **kwargs: {
            "protocolsCount": len(
                kwargs.get("protocols") or []
            ),
            "setsDeleted": 0,
            "objectsDeleted": 0,
            "items": [],
            "errors": [],
        },
    )

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


def test_DuplicateProtocolUsesPostgresqlRuntimeService(
        projectServiceModule,
        service,
        mapper,
        monkeypatch,
):
    duplicateItems = [
        object(),
        object(),
    ]

    expectedResult = {
        "status": 0,
        "errors": [],
        "duplicated": [],
    }

    duplicateCalls = []

    class FakeDuplicateService:
        def duplicatePostgresqlRuntimeProtocols(
                self,
                **kwargs,
        ):
            duplicateCalls.append(
                kwargs
            )
            return expectedResult

    monkeypatch.setattr(
        projectServiceModule,
        "RuntimeProtocolDuplicateService",
        FakeDuplicateService,
    )

    result = service.duplicateProtocol(
        mapper=mapper,
        projectId=1,
        protocols=duplicateItems,
    )

    assert result is expectedResult
    assert len(duplicateCalls) == 1

    duplicateCall = duplicateCalls[0]

    assert duplicateCall["mapper"] is mapper
    assert duplicateCall["projectId"] == 1
    assert duplicateCall["protocols"] is duplicateItems

    assert set(duplicateCall) == {
        "mapper",
        "projectId",
        "protocols",
        "getScipionProtocolForRuntimeCallback",
        "getScipionObjectIdCallback",
        "resolvePostgresqlProtocolDbIdCallback",
        "saveProtocolCallback",
        "syncPostgresqlRuntimeProtocolCallback",
        "getParentProtocolForPointerCallback",
        "storeProtocolCallback",
        "buildProtocolMutationResultCallback",
    }


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
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500)


def test_StopProtocolUsesPostgresqlRuntimeService(
        projectServiceModule,
        service,
        mapper,
        monkeypatch,
):
    protocolIds = [
        "500",
        "501",
    ]

    expectedResult = {
        "status": 0,
        "errors": [],
        "postgresqlRuntimeStop": True,
    }

    stopCalls = []

    class FakeStopService:
        def stopProtocols(
                self,
                **kwargs,
        ):
            stopCalls.append(kwargs)
            return expectedResult

    monkeypatch.setattr(
        projectServiceModule,
        "RuntimeProtocolStopService",
        FakeStopService,
    )

    result = service.stopProtocol(
        mapper=mapper,
        projectId=1,
        protocolIds=protocolIds,
    )

    assert result is expectedResult
    assert len(stopCalls) == 1

    stopCall = stopCalls[0]

    assert stopCall["mapper"] is mapper
    assert stopCall["projectId"] == 1
    assert stopCall["protocolIds"] is protocolIds
    assert stopCall["currentProject"] is service.currentProject

    assert set(stopCall) == {
        "mapper",
        "projectId",
        "protocolIds",
        "currentProject",
        "getScipionProtocolForRuntimeCallback",
        "buildProtocolMutationResultCallback",
    }


def test_RestartProtocolAllUsesPostgresqlRuntimeService(
        projectServiceModule,
        service,
        mapper,
        monkeypatch,
):
    expectedResult = {
        "status": 0,
        "errors": [],
        "postgresqlRuntimeRestart": True,
    }

    restartCalls = []

    class FakeRestartService:
        def restartProtocolSubworkflow(
                self,
                **kwargs,
        ):
            restartCalls.append(
                kwargs
            )
            return expectedResult

    monkeypatch.setattr(
        projectServiceModule,
        "RuntimeProtocolRestartService",
        FakeRestartService,
    )

    result = service.restartProtocolAll(
        mapper=mapper,
        projectId=1,
        protocolId=500,
    )

    assert result is expectedResult
    assert len(restartCalls) == 1

    restartCall = restartCalls[0]

    assert restartCall["mapper"] is mapper
    assert restartCall["projectId"] == 1
    assert restartCall["protocolId"] == 500

    assert set(restartCall) == {
        "mapper",
        "projectId",
        "protocolId",
        "getPostgresqlRuntimeSubworkflowCallback",
        "workflowProtocolMapToProtocolsCallback",
        "deletePersistedProtocolOutputsForRuntimeProtocolsCallback",
        "clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback",
        "validatePostgresqlRestartSubworkflowCallback",
        "launchPostgresqlRestartSubworkflowCallback",
        "buildProtocolMutationResultCallback",
    }


def test_ContinueProtocolAllUsesPostgresqlRuntimeService(
        projectServiceModule,
        service,
        mapper,
        monkeypatch,
):
    expectedResult = {
        "status": 0,
        "errors": [],
        "postgresqlRuntimeContinue": True,
    }

    continueCalls = []

    class FakeContinueService:
        def continueProtocolSubworkflow(
                self,
                **kwargs,
        ):
            continueCalls.append(
                kwargs
            )
            return expectedResult

    monkeypatch.setattr(
        projectServiceModule,
        "RuntimeProtocolContinueService",
        FakeContinueService,
    )

    result = service.continueProtocolAll(
        mapper=mapper,
        projectId=1,
        protocolId=500,
        currentUser={
            "id": 1,
        },
    )

    assert result is expectedResult
    assert len(continueCalls) == 1

    continueCall = continueCalls[0]

    assert continueCall["mapper"] is mapper
    assert continueCall["projectId"] == 1
    assert continueCall["protocolId"] == 500

    assert set(continueCall) == {
        "mapper",
        "projectId",
        "protocolId",
        "getPostgresqlRuntimeSubworkflowCallback",
        "buildPostgresqlContinuePlanCallback",
        "launchPostgresqlContinueSubworkflowCallback",
        "deletePersistedProtocolOutputsForRuntimeProtocolsCallback",
        "clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback",
        "buildProtocolMutationResultCallback",
    }


def test_ResetProtocolFromUsesPostgresqlRuntimeService(
        projectServiceModule,
        service,
        mapper,
        monkeypatch,
):
    expectedResult = {
        "status": 0,
        "errors": [],
        "postgresqlRuntimeReset": True,
    }

    resetCalls = []

    class FakeResetService:
        def resetProtocolSubworkflow(
                self,
                **kwargs,
        ):
            resetCalls.append(kwargs)
            return expectedResult

    monkeypatch.setattr(
        projectServiceModule,
        "RuntimeProtocolResetService",
        FakeResetService,
    )

    result = service.resetProtocolFrom(
        mapper=mapper,
        projectId=1,
        protocolId=500,
    )

    assert result is expectedResult
    assert len(resetCalls) == 1

    resetCall = resetCalls[0]

    assert resetCall["mapper"] is mapper
    assert resetCall["projectId"] == 1
    assert resetCall["protocolId"] == 500
    assert resetCall["currentProject"] is service.currentProject

    assert set(resetCall) == {
        "mapper",
        "projectId",
        "protocolId",
        "currentProject",
        "getPostgresqlRuntimeSubworkflowCallback",
        "stopPostgresqlProtocolsCallback",
        "deletePersistedProtocolOutputsForRuntimeProtocolsCallback",
        "clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback",
        "buildProtocolMutationResultCallback",
    }


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

    protocolSuggestionsServiceModule = importlib.import_module(
        "app.backend.api.services.protocol_suggestions_service"
    )
    monkeypatch.setattr(
        protocolSuggestionsServiceModule,
        "Config",
        FakeConfig,
    )
    monkeypatch.setattr(
        protocolSuggestionsServiceModule,
        "urlopen",
        fakeUrlopen,
    )

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

    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500)


def test_GetProtocolParamsResolvesPostgresqlProtocolId(service, mapper, monkeypatch):
    protocol = FakeProtocol(objId=10, className="ProtClass")
    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    buildContextCalls = []

    def fakeBuildProtocolContext(projectId, protocolObj, mapperObj):
        buildContextCalls.append({
            "projectId": projectId,
            "protocol": protocolObj,
            "mapper": mapperObj,
        })

        return {
            "info": {
                "projectId": projectId,
                "protocolId": protocolObj.getObjId(),
                "protocolClassName": protocolObj.getClassName(),
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
            "mapper": mapper,
        }
    ]
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500)


def test_SaveProtocolResolvesPostgresqlProtocolIdForExistingProtocol(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    patchRuntimeParamCasting(monkeypatch)

    protocol = FakeProtocol(objId=10, className="ProtClass")
    protocol.addParam("runName", FakeStringParam(label="Run name"))
    protocol.addParam("iterations", FakeIntParam(label="Iterations"))

    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

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
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500)


def test_LaunchProtocolLaunchResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    patchRuntimeParamCasting(monkeypatch)

    runtimeProtocolLaunchServiceModule = importlib.import_module(
        "app.backend.runtime.protocol_launch_service"
    )
    monkeypatch.setattr(
        runtimeProtocolLaunchServiceModule,
        "MODE_RESUME",
        "resume-mode",
    )

    protocol = FakeProtocol(objId=10, className="ProtClass", validateErrors=[])
    protocol.addParam("runName", FakeStringParam(label="Run name"))
    protocol.addParam("iterations", FakeIntParam(label="Iterations"))

    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

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
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500)


def test_LaunchProtocolRestartResolvesPostgresqlProtocolId(
            projectServiceModule,
            service,
            mapper,
            monkeypatch,
    ):
        patchRuntimeParamCasting(monkeypatch)

        runtimeProtocolLaunchServiceModule = importlib.import_module(
            "app.backend.runtime.protocol_launch_service"
        )
        monkeypatch.setattr(
            runtimeProtocolLaunchServiceModule,
            "MODE_RESTART",
            "restart-mode",
        )

        protocol = FakeProtocol(objId=10, className="ProtClass", validateErrors=[])
        protocol.addParam("runName", FakeStringParam(label="Run name"))
        protocol.addParam("iterations", FakeIntParam(label="Iterations"))

        service.currentProject.protocols[10] = protocol
        mapper.db.runtimeProtocolIdByDbId[500] = 10
        cleanupCalls = []

        def fakeDeletePersistedProtocolOutputs(
                mapper,
                projectId,
                protocols,
        ):
            cleanupCalls.append({
                "mapper": mapper,
                "projectId": projectId,
                "protocols": list(protocols),
            })

            return {
                "protocolsCount": len(protocols),
                "setsDeleted": 0,
                "objectsDeleted": 0,
                "items": [],
                "errors": [],
            }

        monkeypatch.setattr(
            service,
            "_deletePersistedProtocolOutputsForRuntimeProtocolsFromPostgresql",
            fakeDeletePersistedProtocolOutputs,
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
        assert mapper.db.fetchOneCalls[0]["params"] == (1, 500)


def test_LaunchProtocolScheduleResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    mapper,
    monkeypatch,
):
    patchRuntimeParamCasting(monkeypatch)

    protocol = FakeProtocol(objId=10, className="ProtClass", validateErrors=[])
    protocol.addParam("runName", FakeStringParam(label="Run name"))
    protocol.addParam("iterations", FakeIntParam(label="Iterations"))

    service.currentProject.protocols[10] = protocol
    mapper.db.runtimeProtocolIdByDbId[500] = 10

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
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500)


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

    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500)
    assert mapper.db.fetchOneCalls[1]["params"] == (1, 501)


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
    assert mapper.db.fetchOneCalls[0]["params"] == (1, 500)
    assert mapper.db.fetchOneCalls[1]["params"] == (1, 999)
    assert mapper.db.fetchOneCalls[2]["params"] == (1, "999")


def test_ImportWorkflowProtocolsSanitizesExternalReferences(
    service,
    mapper,
    monkeypatch,
):
    loadedJsonPayloads = []
    importedProtocolA = FakeProtocol(
        objId=20,
    )
    importedProtocolB = FakeProtocol(
        objId=21,
    )

    def fakeLoadProtocols(jsonStr):
        loadedJsonPayloads.append(
            json.loads(jsonStr)
        )

        return {
            "1": importedProtocolA,
            "2": importedProtocolB,
        }

    service.currentProject.loadProtocols = (
        fakeLoadProtocols
    )

    syncCalls = []

    def fakeSyncImportedProtocols(
            mapper,
            projectId,
            protocols,
            pointerParamsByProtocolId,
    ):
        syncCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "protocols": list(protocols),
            "pointerParamsByProtocolId": (
                pointerParamsByProtocolId
            ),
        })

        return {
            "protocols": 2,
            "dependencies": 1,
            "inputRefs": 1,
            "reports": [],
        }

    monkeypatch.setattr(
        service,
        "_syncImportedPostgresqlRuntimeProtocols",
        fakeSyncImportedProtocols,
    )

    class FakeImportPayload:
        mode = "append"
        sourceProjectId = 999
        workflow = [
            {
                "object.id": "1",
                "inputFromCopiedProtocol": (
                    "1.outputParticles"
                ),
                "inputFromExternalProtocol": (
                    "99.outputParticles"
                ),
                "params": {
                    "validPointer": (
                        "2.outputVolume"
                    ),
                    "invalidPointer": (
                        "100.outputCoordinates"
                    ),
                },
            },
            {
                "object.id": "2",
                "inputFromFirstProtocol": (
                    "1.outputParticles"
                ),
            },
        ]

    result = (
        service
        .importWorkflowProtocolsService(
            mapper=mapper,
            projectId=1,
            currentUser={
                "id": 1,
            },
            payload=FakeImportPayload(),
        )
    )

    assert result == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "created": [
            {
                "sourceId": "1",
                "newId": "20",
            },
            {
                "sourceId": "2",
                "newId": "21",
            },
        ],
        "protocolsCount": 2,
        "dependenciesCount": 1,
        "inputRefsCount": 1,
        "syncReports": [],
    }

    assert loadedJsonPayloads == [
        [
            {
                "object.id": "1",
                "inputFromCopiedProtocol": (
                    "1.outputParticles"
                ),
                "params": {
                    "validPointer": (
                        "2.outputVolume"
                    ),
                },
            },
            {
                "object.id": "2",
                "inputFromFirstProtocol": (
                    "1.outputParticles"
                ),
            },
        ]
    ]

    assert syncCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocols": [
                importedProtocolA,
                importedProtocolB,
            ],
            "pointerParamsByProtocolId": {},
        }
    ]


def test_ImportWorkflowProtocolsKeepsReferencesForSameProject(
    service,
    mapper,
    monkeypatch,
):
    loadedJsonPayloads = []
    importedProtocol = FakeProtocol(
        objId=20,
    )

    def fakeLoadProtocols(jsonStr):
        loadedJsonPayloads.append(
            json.loads(jsonStr)
        )

        return {
            "1": importedProtocol,
        }

    service.currentProject.loadProtocols = (
        fakeLoadProtocols
    )

    syncCalls = []

    def fakeSyncImportedProtocols(
            mapper,
            projectId,
            protocols,
            pointerParamsByProtocolId,
    ):
        syncCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "protocols": list(protocols),
            "pointerParamsByProtocolId": (
                pointerParamsByProtocolId
            ),
        })

        return {
            "protocols": 1,
            "dependencies": 1,
            "inputRefs": 1,
            "reports": [],
        }

    monkeypatch.setattr(
        service,
        "_syncImportedPostgresqlRuntimeProtocols",
        fakeSyncImportedProtocols,
    )

    class FakeImportPayload:
        mode = "append"
        sourceProjectId = 1
        workflow = [
            {
                "object.id": "1",
                "inputFromExistingSameProjectProtocol": (
                    "99.outputParticles"
                ),
                "inputFromCopiedProtocol": (
                    "1.outputParticles"
                ),
            },
        ]

    result = (
        service
        .importWorkflowProtocolsService(
            mapper=mapper,
            projectId=1,
            currentUser={
                "id": 1,
            },
            payload=FakeImportPayload(),
        )
    )

    assert result == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "created": [
            {
                "sourceId": "1",
                "newId": "20",
            },
        ],
        "protocolsCount": 1,
        "dependenciesCount": 1,
        "inputRefsCount": 1,
        "syncReports": [],
    }

    assert loadedJsonPayloads == [
        [
            {
                "object.id": "1",
                "inputFromExistingSameProjectProtocol": (
                    "99.outputParticles"
                ),
                "inputFromCopiedProtocol": (
                    "1.outputParticles"
                ),
            },
        ]
    ]

    assert syncCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocols": [
                importedProtocol,
            ],
            "pointerParamsByProtocolId": {},
        }
    ]


def test_ApplyParamsToProtocolResolvesPostgresqlPointerParentId(
    service,
    mapper,
    monkeypatch,
):
    patchRuntimePointerTypes(
        monkeypatch
    )

    monkeypatch.setattr(
        service,
        "_resolveParentOutputForRuntimePointer",
        lambda **kwargs: {
            "exists": True,
            "source": "scipion_runtime",
            "hasRuntimeAttribute": True,
            "parentProtocolReadOnly": True,
        },
    )

    parentProtocol = FakeProtocol(
        objId=10,
        className="ParentProtocol",
    )
    parentProtocol.outputParticles = object()

    protocol = FakeProtocol(
        objId=20,
        className="ChildProtocol",
    )

    pointerParam = FakePointerParam(
        label="Input particles"
    )
    protocol.addParam(
        "inputParticles",
        pointerParam,
    )

    service.currentProject.protocols[10] = (
        parentProtocol
    )
    mapper.db.runtimeProtocolIdByDbId[500] = 10

    errors = service.applyParamsToProtocol(
        mapper=mapper,
        projectId=1,
        protocol=protocol,
        params={
            "inputParticles": (
                "500.outputParticles"
            ),
        },
    )

    assert errors == []
    assert (
        pointerParam.default.get()
        == "10.outputParticles"
    )
    assert (
        protocol.inputParticles.protocol
        is parentProtocol
    )
    assert (
        protocol.inputParticles.extended
        == "outputParticles"
    )

    fetchParams = [
        call["params"]
        for call in mapper.db.fetchOneCalls
    ]

    assert (1, 500) in fetchParams


def test_ProjectServiceDoesNotExposeLegacySetPointerParam(
    service,
):
    assert not hasattr(
        service,
        "setPointerParam",
    )


def test_ApplyParamsToProtocolResolvesPostgresqlMultiPointerParentIds(
    service,
    mapper,
    monkeypatch,
):
    patchRuntimePointerTypes(
        monkeypatch
    )

    monkeypatch.setattr(
        service,
        "_resolveParentOutputForRuntimePointer",
        lambda **kwargs: {
            "exists": True,
            "source": "scipion_runtime",
            "hasRuntimeAttribute": True,
            "parentProtocolReadOnly": True,
        },
    )

    parentProtocolA = FakeProtocol(
        objId=10,
        className="ParentProtocolA",
    )
    parentProtocolA.outputParticles = object()

    parentProtocolB = FakeProtocol(
        objId=11,
        className="ParentProtocolB",
    )
    parentProtocolB.outputClasses = object()

    protocol = FakeProtocol(
        objId=20,
        className="ChildProtocol",
    )

    multiPointerParam = FakeMultiPointerParam(
        label="Input sets"
    )
    protocol.addParam(
        "inputSets",
        multiPointerParam,
    )

    service.currentProject.protocols[10] = (
        parentProtocolA
    )
    service.currentProject.protocols[11] = (
        parentProtocolB
    )

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
    assert len(protocol.inputSets) == 2
    assert (
        protocol.inputSets[0].protocol
        is parentProtocolA
    )
    assert (
        protocol.inputSets[0].extended
        == "outputParticles"
    )
    assert (
        protocol.inputSets[1].protocol
        is parentProtocolB
    )
    assert (
        protocol.inputSets[1].extended
        == "outputClasses"
    )

    fetchParams = [
        call["params"]
        for call in mapper.db.fetchOneCalls
    ]

    assert (1, 500) in fetchParams
    assert (1, 501) in fetchParams


def test_GetNewProtocolParamsCacheIsScopedByProject(
    service,
    monkeypatch,
):
    protocolServiceModule = importlib.import_module(
        "app.backend.api.services.protocol_service"
    )

    protocolServiceModule._newProtocolCache.clear()

    monkeypatch.setattr(
        protocolServiceModule,
        "getPluginsRevision",
        lambda: 1,
    )
    monkeypatch.setattr(
        protocolServiceModule,
        "_lastNewProtocolRevision",
        1,
    )

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

def test_PreserveStoredProtocolParamsInRuntimeContext(
        service,
):
    runtimeMetadataKey = (
        RuntimeProtocolStatusSyncService
        .RUNTIME_METADATA_KEY
    )

    protocolContext = {
        "info": {
            "protocolId": 9,
            "runName": "Old runtime name",
        },
        "values": {
            "threshold": 1.0,
            "numberOfThreads": 4,
            runtimeMetadataKey: {
                "status": "finished",
            },
        },
    }

    storedRow = {
        "params": {
            "threshold": 2.5,
            "numberOfThreads": 12,
            "runName": "Edited protocol",
        },
    }

    result = (
        service
        ._preserveStoredProtocolParamsInRuntimeContext(
            protocolContext=protocolContext,
            storedRow=storedRow,
        )
    )

    assert result["values"]["threshold"] == 2.5
    assert (
        result["values"]["numberOfThreads"]
        == 12
    )
    assert (
        result["values"][runtimeMetadataKey]
        == {
            "status": "finished",
        }
    )
    assert (
        result["info"]["runName"]
        == "Edited protocol"
    )


def test_PreserveRuntimePointerParamsInProtocolContext(
        service,
):
    class FakeProtocol:
        def __init__(self):
            self.params = {
                "inputParticles": object.__new__(PointerParam),
                "inputVolumes": object.__new__(MultiPointerParam),
            }

        def getParam(self, paramName):
            return self.params.get(paramName)

    protocolContext = {
        "info": {
            "protocolId": 9,
        },
        "values": {
            "threshold": 1.0,
            "inputParticles": "300001.outputParticles",
            "inputVolumes": [
                "300002.outputVolume",
                "300003.outputVolume",
            ],
        },
    }

    storedRow = {
        "params": {
            "threshold": 2.5,
            "inputParticles": None,
            "inputVolumes": [],
        },
    }

    result = service._preserveStoredProtocolParamsInRuntimeContext(
        protocolContext=protocolContext,
        storedRow=storedRow,
        protocol=FakeProtocol(),
    )

    assert result["values"]["threshold"] == 2.5
    assert result["values"]["inputParticles"] == "300001.outputParticles"
    assert result["values"]["inputVolumes"] == [
        "300002.outputVolume",
        "300003.outputVolume",
    ]


