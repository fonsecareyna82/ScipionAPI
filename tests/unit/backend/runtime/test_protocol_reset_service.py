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
import inspect
import json
from collections import OrderedDict

import pytest
from fastapi import HTTPException
from pyworkflow.protocol import (
    MODE_RESTART,
    STATUS_FINISHED,
    STATUS_RUNNING,
    STATUS_SAVED,
)

import app.backend.runtime.protocol_reset_service as resetModule
from app.backend.runtime.protocol_reset_service import RuntimeProtocolResetService
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)


class FakeScalar:
    def __init__(self, value=None):
        self.value = value

    def get(self, default=None):
        return default if self.value is None else self.value

    def set(self, value):
        self.value = value


class FakePointerParam:
    pass


class FakeMultiPointerParam:
    pass


class FakeRelationParam:
    pass


class FakePointer:
    pass


class FakePointerList(list):
    pass


class FakeDefinition:
    def __init__(self):
        self.params = [("inputParticles", FakePointerParam())]

    def iterParams(self):
        return list(self.params)


class FakeOutput:
    def __init__(self, name):
        self.name = name


class FakeProtocol:
    def __init__(
            self,
            protocolId,
            protocolStatus,
            outputNames=None,
            pointerTarget=None,
    ):
        self.protocolId = int(protocolId)
        self.status = FakeScalar(protocolStatus)
        self.runMode = FakeScalar()
        self._steps = ["old-step"]
        self._stepsDone = FakeScalar(1)
        self._numberOfSteps = FakeScalar(1)
        self._cpuTime = FakeScalar(9.5)
        self.cleanExecutionCalls = 0
        self.cleanWorkingDirCalls = 0
        self.makeWorkingDirCalls = 0
        self.inputParticles = pointerTarget
        self.definition = FakeDefinition()
        self._outputs = list(outputNames or [])

        for outputName in self._outputs:
            setattr(self, outputName, FakeOutput(outputName))

    def getObjId(self):
        return self.protocolId

    def getStatus(self):
        return self.status.get()

    def setStatus(self, value):
        self.status.set(value)

    def setSaved(self):
        self.setStatus(STATUS_SAVED)

    def getDefinition(self):
        return self.definition

    def iterOutputAttributes(self):
        return [
            (name, getattr(self, name))
            for name in list(self._outputs)
            if hasattr(self, name)
        ]

    def cleanExecutionAttributes(self):
        self.cleanExecutionCalls += 1

    def cleanWorkingDir(self):
        self.cleanWorkingDirCalls += 1

    def makeWorkingDir(self):
        self.makeWorkingDirCalls += 1


class FakeDb:
    def __init__(self):
        self.executeCalls = []

    def execute(self, query, params=None, commit=True):
        self.executeCalls.append({
            "query": query,
            "params": params,
            "commit": commit,
        })


class FakeGraphRepository:
    def __init__(self):
        self.relationSyncCalls = []

    def setProtocolRelationsSynchronized(
            self,
            **kwargs,
    ):
        self.relationSyncCalls.append(
            kwargs
        )

        return True


class FakeMapper:
    def __init__(self, protocolDbIds=None):
        self.protocolDbIds = dict(protocolDbIds or {})
        self.db = FakeDb()
        self.deletedProtocolSteps = []
        self.rowsByProtocolId = {}
        self.updateProtocolCalls = []

    def deleteProtocolSteps(self, projectId, protocolId):
        self.deletedProtocolSteps.append({
            "projectId": int(projectId),
            "protocolId": int(protocolId),
        })

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        return self.rowsByProtocolId.get(int(protocolId))

    def updateProtocol(self, protocolData):
        self.updateProtocolCalls.append(dict(protocolData))
        protocolDbId = int(protocolData["id"])

        for row in self.rowsByProtocolId.values():
            if int(row["id"]) == protocolDbId:
                row.update(protocolData)
                return


class FakeIdentityResolver:
    def __init__(self, mapper, projectId, **kwargs):
        self.mapper = mapper
        self.projectId = int(projectId)

    def resolvePostgresqlProtocolDbIdFromScipionProtocolId(self, protocolId):
        return self.mapper.protocolDbIds.get(int(protocolId))


class FakeRuntimeMapper:
    def __init__(self):
        self.deletedRelations = []
        self.storedProtocols = []
        self.commits = 0

    def deleteRelations(self, protocol):
        self.deletedRelations.append(protocol)

    def store(self, protocol):
        self.storedProtocols.append(protocol)

    def commit(self):
        self.commits += 1


class FakeCurrentProject:
    def __init__(self, runtimeMapper=None):
        self.runtimeMapper = runtimeMapper or FakeRuntimeMapper()

    def getPostgresqlRuntimeMapper(self):
        return self.runtimeMapper


def buildResult(message, **extra):
    return {
        "status": 0,
        "errors": [],
        "message": message,
        **extra,
    }


@pytest.fixture
def patchResetTypes(monkeypatch):
    graphRepository = FakeGraphRepository()

    monkeypatch.setattr(
        resetModule,
        "ProtocolGraphRepository",
        lambda: graphRepository,
    )
    monkeypatch.setattr(
        resetModule,
        "ProtocolIdentityResolver",
        FakeIdentityResolver,
    )
    monkeypatch.setattr(resetModule, "PointerParam", FakePointerParam)
    monkeypatch.setattr(resetModule, "MultiPointerParam", FakeMultiPointerParam)
    monkeypatch.setattr(resetModule, "RelationParam", FakeRelationParam)
    monkeypatch.setattr(resetModule, "Pointer", FakePointer)
    monkeypatch.setattr(resetModule, "PointerList", FakePointerList)
    return graphRepository


def callReset(
        *,
        mapper,
        currentProject,
        rootProtocol,
        workflowProtocolMap,
        stopCallback=None,
        cleanupCallback=None,
        refCleanupCallback=None,
):
    return RuntimeProtocolResetService().resetProtocolSubworkflow(
        mapper=mapper,
        projectId=1,
        protocolId=rootProtocol.getObjId(),
        currentProject=currentProject,
        getPostgresqlRuntimeSubworkflowCallback=lambda **kwargs: workflowProtocolMap,
        stopPostgresqlProtocolsCallback=stopCallback or (
            lambda **kwargs: {"status": 0, "errors": []}
        ),
        deletePersistedProtocolOutputsForRuntimeProtocolsCallback=cleanupCallback or (
            lambda **kwargs: {
                "protocolsCount": len(kwargs["protocols"]),
                "setsDeleted": 0,
                "objectsDeleted": 0,
                "items": [],
            }
        ),
        clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=refCleanupCallback or (
            lambda **kwargs: {
                "updated": 0,
                "parentProtocolDbIds": [],
            }
        ),
        buildProtocolMutationResultCallback=buildResult,
    )


def test_ResetServiceDoesNotExecuteDirectPostgresqlQueries():
    source = inspect.getsource(
        RuntimeProtocolResetService
    )

    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source


def test_ResetServiceHasNoLegacyRuntimePath():
    signature = inspect.signature(
        RuntimeProtocolResetService.resetProtocolSubworkflow
    )
    source = inspect.getsource(
        RuntimeProtocolResetService.resetProtocolSubworkflow
    )

    assert "usingPostgresqlRuntime" not in signature.parameters
    assert "getScipionProtocolForRuntimeCallback" not in signature.parameters
    assert "workflowProtocolMapToProtocolsCallback" not in signature.parameters
    assert "getPostgresqlRuntimeSubworkflowCallback" in signature.parameters

    assert "currentProject._getSubworkflow" not in source
    assert "currentProject.resetWorkFlow" not in source
    assert "postgresqlRuntimeReset=False" not in source


def test_ResetValidationUsesStrictScipionProtocolIdentity():
    class IdentityMapperStub:
        def __init__(self):
            self.scipionLookups = []
            self.dbLookups = []

        def getProjectProtocolByProtocolId(self, projectId, protocolId):
            self.scipionLookups.append({
                "projectId": projectId,
                "protocolId": protocolId,
            })
            return None

        def getProjectProtocolByDbId(self, projectId, protocolDbId):
            self.dbLookups.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return {
                "id": 31,
                "protocolId": "99",
            }

    class CurrentProjectStub:
        def getPostgresqlRuntimeMapper(self):
            return object()

    protocol = FakeProtocol(
        31,
        STATUS_FINISHED,
    )
    mapper = IdentityMapperStub()

    result = RuntimeProtocolResetService()._validatePostgresqlSubworkflow(
        mapper=mapper,
        projectId=7,
        workflowProtocolMap={
            "31": (
                protocol,
                0,
            ),
        },
        currentProject=CurrentProjectStub(),
    )

    assert result["resetItems"] == []
    assert result["errors"] == [
        {
            "protocolId": "31",
            "error": "Protocol was not found in PostgreSQL",
        },
    ]

    assert mapper.scipionLookups == [
        {
            "projectId": 7,
            "protocolId": "31",
        },
    ]
    assert mapper.dbLookups == []


def test_PostgresqlResetStopsActiveProtocolsAndResetsSubtree(
        monkeypatch,
        patchResetTypes,
):
    mapper = FakeMapper({10: 110, 11: 111, 12: 112})
    runtimeMapper = FakeRuntimeMapper()
    currentProject = FakeCurrentProject(runtimeMapper)

    parentProtocol = FakeProtocol(
        1,
        STATUS_FINISHED,
        outputNames=["outputParent"],
    )
    rootProtocol = FakeProtocol(
        10,
        STATUS_RUNNING,
        outputNames=["outputRoot"],
        pointerTarget=parentProtocol,
    )
    childProtocol = FakeProtocol(
        11,
        STATUS_FINISHED,
        outputNames=["outputChild"],
        pointerTarget=rootProtocol,
    )
    savedProtocol = FakeProtocol(
        12,
        STATUS_SAVED,
        outputNames=["outputSaved"],
        pointerTarget=childProtocol,
    )

    workflowProtocolMap = OrderedDict([
        ("12", (savedProtocol, 2)),
        ("11", (childProtocol, 1)),
        ("10", (rootProtocol, 0)),
    ])

    stopCalls = []
    cleanupCalls = []
    refCleanupCalls = []
    metadataCalls = []

    def resetRuntimeMetadata(
            statusService,
            *,
            mapper,
            projectId,
            protocolId,
    ):
        metadataCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
        })
        return {
            "protocolId": str(protocolId),
            "cpuTimeSeconds": 0.0,
            "elapsedTimeSeconds": 0.0,
            "pid": None,
            "jobIds": [],
        }

    monkeypatch.setattr(
        RuntimeProtocolStatusSyncService,
        "resetProtocolRuntimeMetadata",
        resetRuntimeMetadata,
    )

    result = callReset(
        mapper=mapper,
        currentProject=currentProject,
        rootProtocol=rootProtocol,
        workflowProtocolMap=workflowProtocolMap,
        stopCallback=lambda **kwargs: (
            stopCalls.append(kwargs)
            or {"status": 0, "errors": []}
        ),
        cleanupCallback=lambda **kwargs: (
            cleanupCalls.append(kwargs)
            or {
                "protocolsCount": len(kwargs["protocols"]),
                "setsDeleted": 2,
                "objectsDeleted": 0,
                "items": [],
            }
        ),
        refCleanupCallback=lambda **kwargs: (
            refCleanupCalls.append(kwargs)
            or {
                "updated": 2,
                "parentProtocolDbIds": [110, 111],
            }
        ),
    )

    assert result["status"] == 0
    assert result["protocolsCount"] == 2
    assert result["postgresqlRuntimeReset"] is True
    assert result["parentProtocolsModified"] is False
    for legacyField in (
            "postgresqlOnly",
            "usesProjectSqlite",
            "usesRunDb",
            "usesStepsSqlite",
    ):
        assert legacyField not in result

    assert stopCalls == [{
        "mapper": mapper,
        "projectId": 1,
        "protocolIds": ["10"],
    }]
    assert cleanupCalls[0]["protocols"] == [rootProtocol, childProtocol]
    assert refCleanupCalls[0]["protocols"] == [rootProtocol, childProtocol]

    assert runtimeMapper.deletedRelations == [rootProtocol, childProtocol]
    assert runtimeMapper.storedProtocols == [rootProtocol, childProtocol]
    assert runtimeMapper.commits == 2
    assert mapper.deletedProtocolSteps == [
        {"projectId": 1, "protocolId": 10},
        {"projectId": 1, "protocolId": 11},
    ]
    assert mapper.db.executeCalls == []

    assert patchResetTypes.relationSyncCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 10,
            "synchronized": False,
        },
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 11,
            "synchronized": False,
        },
    ]
    assert [call["protocolId"] for call in metadataCalls] == [10, 11]

    for protocol in (rootProtocol, childProtocol):
        assert protocol.getStatus() == STATUS_SAVED
        assert protocol.runMode.get() == MODE_RESTART
        assert protocol._steps == []
        assert protocol._stepsDone.get() == 0
        assert protocol._numberOfSteps.get() == 0
        assert protocol._cpuTime.get() == 0
        assert protocol.cleanExecutionCalls == 1
        assert protocol.cleanWorkingDirCalls == 1
        assert protocol.makeWorkingDirCalls == 1
        assert protocol._outputs == []
        assert isinstance(protocol.inputParticles, FakePointer)

    assert not hasattr(rootProtocol, "outputRoot")
    assert not hasattr(childProtocol, "outputChild")

    # Parent outside the reset subtree remains immutable.
    assert parentProtocol.getStatus() == STATUS_FINISHED
    assert hasattr(parentProtocol, "outputParent")
    assert parentProtocol._outputs == ["outputParent"]
    assert parentProtocol.cleanExecutionCalls == 0
    assert parentProtocol not in runtimeMapper.storedProtocols

    # An already-saved descendant is not mutated.
    assert savedProtocol.getStatus() == STATUS_SAVED
    assert hasattr(savedProtocol, "outputSaved")
    assert savedProtocol.cleanExecutionCalls == 0
    assert result["postgresqlReset"]["skipped"] == [{
        "protocolId": "12",
        "protocolDbId": 112,
        "level": 2,
        "status": str(STATUS_SAVED),
        "reason": "protocol_already_saved",
    }]


def test_PostgresqlResetStopsBeforeDestructiveCleanup(
        patchResetTypes,
):
    mapper = FakeMapper({10: 110})
    runtimeMapper = FakeRuntimeMapper()
    currentProject = FakeCurrentProject(runtimeMapper)
    protocol = FakeProtocol(
        10,
        STATUS_RUNNING,
        outputNames=["outputParticles"],
    )
    cleanupCalls = []
    refCleanupCalls = []

    with pytest.raises(HTTPException) as error:
        callReset(
            mapper=mapper,
            currentProject=currentProject,
            rootProtocol=protocol,
            workflowProtocolMap={"10": (protocol, 0)},
            stopCallback=lambda **kwargs: {
                "status": 1,
                "errors": ["worker could not be stopped"],
            },
            cleanupCallback=lambda **kwargs: cleanupCalls.append(kwargs),
            refCleanupCallback=lambda **kwargs: refCleanupCalls.append(kwargs),
        )

    assert error.value.status_code == 500
    assert error.value.detail == ["worker could not be stopped"]
    assert cleanupCalls == []
    assert refCleanupCalls == []
    assert runtimeMapper.deletedRelations == []
    assert runtimeMapper.storedProtocols == []
    assert mapper.deletedProtocolSteps == []
    assert mapper.db.executeCalls == []
    assert protocol.getStatus() == STATUS_RUNNING
    assert hasattr(protocol, "outputParticles")


def test_PostgresqlResetValidatesWholeSubworkflowBeforeMutation(
        patchResetTypes,
):
    mapper = FakeMapper({10: 110})
    runtimeMapper = FakeRuntimeMapper()
    currentProject = FakeCurrentProject(runtimeMapper)
    rootProtocol = FakeProtocol(
        10,
        STATUS_FINISHED,
        outputNames=["outputRoot"],
    )
    missingProtocol = FakeProtocol(
        11,
        STATUS_FINISHED,
        outputNames=["outputMissing"],
    )
    stopCalls = []
    cleanupCalls = []

    with pytest.raises(HTTPException) as error:
        callReset(
            mapper=mapper,
            currentProject=currentProject,
            rootProtocol=rootProtocol,
            workflowProtocolMap={
                "10": (rootProtocol, 0),
                "11": (missingProtocol, 1),
            },
            stopCallback=lambda **kwargs: stopCalls.append(kwargs),
            cleanupCallback=lambda **kwargs: cleanupCalls.append(kwargs),
        )

    assert error.value.status_code == 422
    assert error.value.detail == [{
        "protocolId": "11",
        "error": "Protocol was not found in PostgreSQL",
    }]
    assert stopCalls == []
    assert cleanupCalls == []
    assert runtimeMapper.storedProtocols == []
    assert mapper.deletedProtocolSteps == []
    assert hasattr(rootProtocol, "outputRoot")
    assert hasattr(missingProtocol, "outputMissing")


def test_PostgresqlResetSkipsSubworkflowAlreadySaved(
        patchResetTypes,
):
    mapper = FakeMapper({10: 110, 11: 111})
    runtimeMapper = FakeRuntimeMapper()
    currentProject = FakeCurrentProject(runtimeMapper)
    rootProtocol = FakeProtocol(10, STATUS_SAVED)
    childProtocol = FakeProtocol(11, STATUS_SAVED)
    stopCalls = []
    cleanupCalls = []
    refCleanupCalls = []

    result = callReset(
        mapper=mapper,
        currentProject=currentProject,
        rootProtocol=rootProtocol,
        workflowProtocolMap={
            "10": (rootProtocol, 0),
            "11": (childProtocol, 1),
        },
        stopCallback=lambda **kwargs: stopCalls.append(kwargs),
        cleanupCallback=lambda **kwargs: cleanupCalls.append(kwargs),
        refCleanupCallback=lambda **kwargs: refCleanupCalls.append(kwargs),
    )

    assert result["status"] == 0
    assert result["protocolsCount"] == 0
    assert result["postgresqlStop"] is None
    assert result["postgresqlReset"]["items"] == []
    assert result["postgresqlReset"]["skipped"] == [
        {
            "protocolId": "10",
            "protocolDbId": 110,
            "level": 0,
            "status": str(STATUS_SAVED),
            "reason": "protocol_already_saved",
        },
        {
            "protocolId": "11",
            "protocolDbId": 111,
            "level": 1,
            "status": str(STATUS_SAVED),
            "reason": "protocol_already_saved",
        },
    ]
    assert stopCalls == []
    assert cleanupCalls == []
    assert refCleanupCalls == []
    assert runtimeMapper.storedProtocols == []


def test_ResetProtocolRuntimeMetadataClearsExecutionState():
    mapper = FakeMapper()
    metadataKey = RuntimeProtocolStatusSyncService.RUNTIME_METADATA_KEY

    mapper.rowsByProtocolId[10] = {
        "id": 110,
        "projectId": 1,
        "protocolId": "10",
        "status": str(STATUS_SAVED),
        "params": {
            "threshold": 2.5,
            metadataKey: {
                "cpuTimeSeconds": 21.0,
                "elapsedTimeSeconds": 92.5,
                RuntimeProtocolStatusSyncService.ELAPSED_UPDATED_AT_KEY: 12345.0,
                RuntimeProtocolStatusSyncService.FINAL_SYNC_PENDING_KEY: True,
                "pid": 4321,
                "jobIds": ["77", "78"],
                "customMetadata": "preserved",
            },
        },
    }

    result = (
        RuntimeProtocolStatusSyncService()
        .resetProtocolRuntimeMetadata(
            mapper=mapper,
            projectId=1,
            protocolId=10,
        )
    )

    params = json.loads(mapper.rowsByProtocolId[10]["params"])
    metadata = params[metadataKey]

    assert params["threshold"] == 2.5
    assert metadata["cpuTimeSeconds"] == 0.0
    assert metadata["elapsedTimeSeconds"] == 0.0
    assert metadata["pid"] is None
    assert metadata["jobIds"] == []
    assert (
        RuntimeProtocolStatusSyncService.ELAPSED_UPDATED_AT_KEY
        not in metadata
    )
    assert (
        RuntimeProtocolStatusSyncService.FINAL_SYNC_PENDING_KEY
        not in metadata
    )
    assert metadata["customMetadata"] == "preserved"
    assert result == {
        "protocolId": "10",
        "cpuTimeSeconds": 0.0,
        "elapsedTimeSeconds": 0.0,
        "pid": None,
        "jobIds": [],
    }