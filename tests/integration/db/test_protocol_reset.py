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
import json
from types import SimpleNamespace
from uuid import uuid4

from pyworkflow.object import String
from pyworkflow.protocol import MODE_RESTART, STATUS_FINISHED, STATUS_SAVED
from pyworkflow.protocol.protocol import Protocol

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper
from app.backend.mapper.postgresql_runtime_mapper import PostgresqlRuntimeMapper
from app.backend.mapper.scipion_object_mapper import ScipionObjectPostgresqlMapper
from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository
from app.backend.runtime.protocol_output_persistence_service import RuntimeProtocolOutputPersistenceService
from app.backend.runtime.protocol_reset_service import RuntimeProtocolResetService


class ResetProtocolStub(Protocol):
    pass


def _openPostgresqlIntegrationDb(postgresqlMigratedEnv):
    return PostgresqlDb(
        dbName=postgresqlMigratedEnv["databaseName"],
        user=postgresqlMigratedEnv["databaseUser"],
        password=postgresqlMigratedEnv["databasePass"],
        host=postgresqlMigratedEnv["postgresHost"],
        port=postgresqlMigratedEnv["postgresPort"],
    )


def _saveProtocol(mapper, projectId, protocolId, parentIds=None, childIds=None):
    return mapper.saveProtocol(
        {
            "info": {
                "protocolId": protocolId,
                "projectId": projectId,
                "protocolClassName": "ResetProtocolStub",
                "status": STATUS_FINISHED,
            },
            "values": {},
            "parentIds": list(parentIds or []),
            "childIds": list(childIds or []),
        }
    )


def _storeProtocolStep(mapper, projectId, protocolDbId, protocolId, name):
    mapper.replaceProtocolSteps(
        projectId=projectId,
        protocolDbId=protocolDbId,
        protocolId=protocolId,
        steps=[
            {
                "index": 0,
                "stepClassName": "FunctionStep",
                "name": name,
                "status": STATUS_FINISHED,
                "prerequisites": [],
                "args": [],
                "argsText": "",
                "resultFiles": [],
                "needsGpu": False,
                "schemaVersion": 2,
            },
        ],
    )


def _storeOutputObject(db, projectId, protocolDbId, outputName, runtimeObjectId, value):
    outputObject = String()
    outputObject.set(value)
    outputObject.setObjId(runtimeObjectId)

    ScipionObjectPostgresqlMapper(db).storeObjectTree(
        projectId=projectId,
        protocolDbId=protocolDbId,
        outputName=outputName,
        scipionObj=outputObject,
    )

    return outputObject


def test_PostgresqlResetCleansOwnedRuntimeStateAndPreservesExternalParent(
        postgresqlIntegrationDb,
        postgresqlMigratedEnv,
        tmp_path,
        monkeypatch,
):
    writerMapper = PostgresqlFlatMapper(postgresqlIntegrationDb)

    originalResolveProtocolClass = PostgresqlRuntimeMapper._resolveProtocolClass

    def resolveProtocolClass(runtimeMapper, className):
        if className == "ResetProtocolStub":
            return ResetProtocolStub

        return originalResolveProtocolClass(runtimeMapper, className)

    monkeypatch.setattr(
        PostgresqlRuntimeMapper,
        "_resolveProtocolClass",
        resolveProtocolClass,
    )

    suffix = uuid4().hex
    userId = None
    projectId = None
    resetDb = None
    observerDb = None
    runtimeMapper = None
    observerRuntimeMapper = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-reset-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Reset",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL reset %s" % suffix,
            description="PostgreSQL reset integration test.",
            status="active",
        )

        parentProtocolId = 2
        childProtocolId = 3

        parentProtocolDbId = _saveProtocol(
            mapper=writerMapper,
            projectId=projectId,
            protocolId=parentProtocolId,
            childIds=[childProtocolId],
        )

        childProtocolDbId = _saveProtocol(
            mapper=writerMapper,
            projectId=projectId,
            protocolId=childProtocolId,
            parentIds=[parentProtocolId],
        )

        _storeProtocolStep(
            mapper=writerMapper,
            projectId=projectId,
            protocolDbId=parentProtocolDbId,
            protocolId=parentProtocolId,
            name="parentStep",
        )

        _storeProtocolStep(
            mapper=writerMapper,
            projectId=projectId,
            protocolDbId=childProtocolDbId,
            protocolId=childProtocolId,
            name="childStep",
        )

        parentOutputName = "outputParent"
        childOutputName = "outputChild"

        parentOutputRuntimeId = 1_300_002
        childOutputRuntimeId = 1_300_003

        _storeOutputObject(
            db=postgresqlIntegrationDb,
            projectId=projectId,
            protocolDbId=parentProtocolDbId,
            outputName=parentOutputName,
            runtimeObjectId=parentOutputRuntimeId,
            value="PARENT_OUTPUT",
        )

        _storeOutputObject(
            db=postgresqlIntegrationDb,
            projectId=projectId,
            protocolDbId=childProtocolDbId,
            outputName=childOutputName,
            runtimeObjectId=childOutputRuntimeId,
            value="CHILD_OUTPUT",
        )

        graphRepository = ProtocolGraphRepository()

        assert graphRepository.setProtocolRelationsSynchronized(
            mapper=writerMapper,
            projectId=projectId,
            protocolId=parentProtocolId,
            synchronized=True,
        )

        assert graphRepository.setProtocolRelationsSynchronized(
            mapper=writerMapper,
            projectId=projectId,
            protocolId=childProtocolId,
            synchronized=True,
        )

        postgresqlIntegrationDb.execute(
            """
            INSERT INTO protocol_input_refs (
                "projectId",
                "protocolDbId",
                "protocolId",
                "inputName",
                "itemIndex",
                "parentProtocolDbId",
                "parentProtocolId",
                "parentOutputName",
                "objectClassName",
                "objectId"
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                projectId,
                childProtocolDbId,
                str(childProtocolId),
                "inputParent",
                0,
                parentProtocolDbId,
                str(parentProtocolId),
                parentOutputName,
                "String",
                str(parentOutputRuntimeId),
            ),
        )

        runtimeMetadata = {
            "cpuTimeSeconds": 91.5,
            "elapsedTimeSeconds": 183.0,
            "pid": 98765,
            "jobIds": [
                "111",
                "222",
            ],
            "elapsedUpdatedAtEpochSeconds": 12345.0,
            "finalSyncPending": True,
        }

        writerMapper.updateProtocol(
            {
                "id": childProtocolDbId,
                "params": json.dumps(
                    {
                        "_scipionWebRuntime": runtimeMetadata,
                    },
                    ensure_ascii=False,
                ),
            }
        )

        parentBefore = postgresqlIntegrationDb.fetchOne(
            """
            SELECT id,
                   "protocolId",
                   status,
                   "relationsSynchronized"
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
            """,
            (
                projectId,
                str(parentProtocolId),
            ),
        )

        childBefore = postgresqlIntegrationDb.fetchOne(
            """
            SELECT id,
                   "protocolId",
                   status,
                   params,
                   "relationsSynchronized"
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
            """,
            (
                projectId,
                str(childProtocolId),
            ),
        )

        assert parentBefore is not None
        assert childBefore is not None

        assert int(parentBefore["id"]) == parentProtocolDbId
        assert int(childBefore["id"]) == childProtocolDbId
        assert parentBefore["relationsSynchronized"] is True
        assert childBefore["relationsSynchronized"] is True

        assert childBefore["params"]["_scipionWebRuntime"]["cpuTimeSeconds"] == 91.5
        assert childBefore["params"]["_scipionWebRuntime"]["elapsedTimeSeconds"] == 183.0
        assert childBefore["params"]["_scipionWebRuntime"]["pid"] == 98765
        assert childBefore["params"]["_scipionWebRuntime"]["jobIds"] == [
            "111",
            "222",
        ]

        resetDb = _openPostgresqlIntegrationDb(postgresqlMigratedEnv)
        resetMapper = PostgresqlFlatMapper(resetDb)

        runtimeMapper = PostgresqlRuntimeMapper(
            flatMapper=resetMapper,
            projectId=projectId,
            dictClasses={
                "ResetProtocolStub": ResetProtocolStub,
            },
        )

        childProtocol = runtimeMapper.selectRuntimeProtocolById(
            childProtocolId
        )

        assert childProtocol is not None
        assert isinstance(childProtocol, ResetProtocolStub)
        assert childProtocol.getObjId() == childProtocolId
        assert str(childProtocol.getStatus()).strip().lower() == str(STATUS_FINISHED).strip().lower()

        childOutputObject = String()
        childOutputObject.set("CHILD_OUTPUT")
        childOutputObject.setObjId(childOutputRuntimeId)

        childProtocol.outputChild = childOutputObject
        childProtocol._outputs = [
            childOutputName,
        ]

        childProtocol.iterOutputAttributes = lambda: [
            (
                childOutputName,
                childProtocol.outputChild,
            )
        ]

        childProtocol.getDefinition = lambda: SimpleNamespace(
            iterParams=lambda: []
        )

        executionOperations = []
        workingDirectoryOperations = []

        childProtocol.cleanExecutionAttributes = lambda: executionOperations.append(
            "cleanExecution"
        )

        childProtocol.cleanWorkingDir = lambda: workingDirectoryOperations.append(
            "clean"
        )

        childProtocol.makeWorkingDir = lambda: workingDirectoryOperations.append(
            "make"
        )

        currentProject = SimpleNamespace(
            path=str(tmp_path),
            getPostgresqlRuntimeMapper=lambda: runtimeMapper,
        )

        subworkflowCalls = []

        def getPostgresqlRuntimeSubworkflow(**kwargs):
            subworkflowCalls.append(
                {
                    "projectId": kwargs["projectId"],
                    "protocolId": kwargs["protocolId"],
                }
            )

            return {
                str(childProtocolId): (
                    childProtocol,
                    0,
                ),
            }

        outputPersistenceService = RuntimeProtocolOutputPersistenceService()

        def deletePersistedOutputs(**kwargs):
            return outputPersistenceService.deletePersistedProtocolOutputsForRuntimeProtocols(
                mapper=kwargs["mapper"],
                projectId=kwargs["projectId"],
                protocols=kwargs["protocols"],
                getCurrentProjectPathCallback=lambda: str(tmp_path),
            )

        def clearChildInputRefObjectIds(**kwargs):
            parentProtocolDbIds = []

            for protocol in kwargs["protocols"]:
                protocolRow = kwargs["mapper"].getProjectProtocolByProtocolId(
                    projectId=kwargs["projectId"],
                    protocolId=protocol.getObjId(),
                )

                assert protocolRow is not None

                parentProtocolDbIds.append(
                    int(protocolRow["id"])
                )

            return graphRepository.clearInputRefObjectIdsForParentProtocolDbIds(
                mapper=kwargs["mapper"],
                projectId=kwargs["projectId"],
                parentProtocolDbIds=parentProtocolDbIds,
            )

        def failStop(**kwargs):
            raise AssertionError(
                "Finished PostgreSQL protocol must not be stopped during reset."
            )

        def buildMutationResult(message, **extra):
            return {
                "status": 0,
                "errors": [],
                "message": message,
                **extra,
            }

        resetService = RuntimeProtocolResetService()

        resetInfo = resetService.resetProtocolSubworkflow(
            mapper=resetMapper,
            projectId=projectId,
            protocolId=childProtocolId,
            currentProject=currentProject,
            getPostgresqlRuntimeSubworkflowCallback=getPostgresqlRuntimeSubworkflow,
            stopPostgresqlProtocolsCallback=failStop,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback=deletePersistedOutputs,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=clearChildInputRefObjectIds,
            buildProtocolMutationResultCallback=buildMutationResult,
        )

        assert subworkflowCalls == [
            {
                "projectId": projectId,
                "protocolId": childProtocolId,
            },
        ]

        assert resetInfo["status"] == 0
        assert resetInfo["errors"] == []
        assert resetInfo["message"] == "Protocol subtree reset successfully"
        assert resetInfo["protocolsCount"] == 1
        assert resetInfo["dependenciesCount"] == 0
        assert resetInfo["postgresqlRuntimeReset"] is True
        assert resetInfo["parentProtocolsModified"] is False
        assert resetInfo["postgresqlStop"] is None

        cleanupInfo = resetInfo["postgresqlCleanup"]

        assert cleanupInfo["protocolsCount"] == 1
        assert cleanupInfo["setsDeleted"] == 0
        assert cleanupInfo["objectsDeleted"] >= 1
        assert cleanupInfo["fileErrors"] == []

        resetItems = resetInfo["postgresqlReset"]["items"]

        assert len(resetItems) == 1

        resetItem = resetItems[0]

        assert resetItem["protocolId"] == str(childProtocolId)
        assert resetItem["protocolDbId"] == childProtocolDbId
        assert resetItem["level"] == 0
        assert str(resetItem["statusBefore"]).strip().lower() == str(STATUS_FINISHED).strip().lower()
        assert str(resetItem["statusAfter"]).strip().lower() == str(STATUS_SAVED).strip().lower()
        assert resetItem["runMode"] == "restart"
        assert resetItem["stepsDeleted"] is True
        assert resetItem["outputsDetached"] is True
        assert resetItem["workingDirectoryCleaned"] is True
        assert resetItem["parentProtocolsModified"] is False

        assert resetItem["runtimeMetadata"] == {
            "protocolId": str(childProtocolId),
            "cpuTimeSeconds": 0.0,
            "elapsedTimeSeconds": 0.0,
            "pid": None,
            "jobIds": [],
        }

        assert resetInfo["postgresqlReset"]["skipped"] == []

        assert executionOperations == [
            "cleanExecution",
        ]

        assert workingDirectoryOperations == [
            "clean",
            "make",
        ]

        assert not hasattr(
            childProtocol,
            childOutputName,
        )

        assert childProtocol._outputs == []
        assert childProtocol.getRunMode() == MODE_RESTART
        assert str(childProtocol.getStatus()).strip().lower() == str(STATUS_SAVED).strip().lower()

        runtimeMapper.close()
        runtimeMapper = None

        resetDb.close()
        resetDb = None

        observerDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        observerMapper = PostgresqlFlatMapper(
            observerDb
        )

        observerObjectMapper = ScipionObjectPostgresqlMapper(
            observerDb
        )

        parentAfter = observerDb.fetchOne(
            """
            SELECT id,
                   "protocolId",
                   status,
                   params,
                   "relationsSynchronized"
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
            """,
            (
                projectId,
                str(parentProtocolId),
            ),
        )

        childAfter = observerDb.fetchOne(
            """
            SELECT id,
                   "protocolId",
                   status,
                   params,
                   "relationsSynchronized"
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
            """,
            (
                projectId,
                str(childProtocolId),
            ),
        )

        assert parentAfter is not None
        assert childAfter is not None

        assert int(parentAfter["id"]) == parentProtocolDbId
        assert parentAfter["protocolId"] == str(parentProtocolId)
        assert str(parentAfter["status"]).strip().lower() == str(STATUS_FINISHED).strip().lower()
        assert parentAfter["relationsSynchronized"] is True

        assert int(childAfter["id"]) == childProtocolDbId
        assert childAfter["protocolId"] == str(childProtocolId)
        assert str(childAfter["status"]).strip().lower() == str(STATUS_SAVED).strip().lower()
        assert childAfter["relationsSynchronized"] is False

        childRuntimeMetadata = childAfter["params"][
            "_scipionWebRuntime"
        ]

        assert childRuntimeMetadata["cpuTimeSeconds"] == 0.0
        assert childRuntimeMetadata["elapsedTimeSeconds"] == 0.0
        assert childRuntimeMetadata["pid"] is None
        assert childRuntimeMetadata["jobIds"] == []

        assert "elapsedUpdatedAtEpochSeconds" not in childRuntimeMetadata
        assert "finalSyncPending" not in childRuntimeMetadata

        parentSteps = observerMapper.listProtocolSteps(
            projectId=projectId,
            protocolId=parentProtocolId,
        )

        childSteps = observerMapper.listProtocolSteps(
            projectId=projectId,
            protocolId=childProtocolId,
        )

        assert len(parentSteps) == 1
        assert parentSteps[0]["name"] == "parentStep"
        assert childSteps == []

        parentOutputRows = observerObjectMapper.getStoredObjectTree(
            projectId=projectId,
            protocolDbId=parentProtocolDbId,
            outputName=parentOutputName,
        )

        childOutputRows = observerObjectMapper.getStoredObjectTree(
            projectId=projectId,
            protocolDbId=childProtocolDbId,
            outputName=childOutputName,
        )

        assert len(parentOutputRows) == 1
        assert parentOutputRows[0]["scipionObjId"] == parentOutputRuntimeId
        assert parentOutputRows[0]["value"] == "PARENT_OUTPUT"

        assert childOutputRows == []

        inputRefRows = observerDb.fetchAll(
            """
            SELECT
                "protocolDbId",
                "protocolId",
                "inputName",
                "itemIndex",
                "parentProtocolDbId",
                "parentProtocolId",
                "parentOutputName",
                "objectClassName",
                "objectId"
              FROM protocol_input_refs
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
             ORDER BY "inputName", "itemIndex"
            """,
            (
                projectId,
                childProtocolDbId,
            ),
        )

        assert len(inputRefRows) == 1

        inputRef = inputRefRows[0]

        assert inputRef["protocolDbId"] == childProtocolDbId
        assert inputRef["protocolId"] == str(childProtocolId)
        assert inputRef["inputName"] == "inputParent"
        assert inputRef["itemIndex"] == 0
        assert inputRef["parentProtocolDbId"] == parentProtocolDbId
        assert inputRef["parentProtocolId"] == str(parentProtocolId)
        assert inputRef["parentOutputName"] == parentOutputName
        assert inputRef["objectClassName"] == "String"
        assert inputRef["objectId"] == str(parentOutputRuntimeId)

        observerRuntimeMapper = PostgresqlRuntimeMapper(
            flatMapper=observerMapper,
            projectId=projectId,
            dictClasses={
                "ResetProtocolStub": ResetProtocolStub,
            },
        )

        rehydratedChildProtocol = observerRuntimeMapper.selectRuntimeProtocolById(
            childProtocolId
        )

        assert rehydratedChildProtocol is not None
        assert isinstance(
            rehydratedChildProtocol,
            ResetProtocolStub,
        )

        assert rehydratedChildProtocol.getObjId() == childProtocolId
        assert rehydratedChildProtocol.getRunMode() == MODE_RESTART
        assert str(rehydratedChildProtocol.getStatus()).strip().lower() == str(STATUS_SAVED).strip().lower()

    finally:
        if observerRuntimeMapper is not None:
            observerRuntimeMapper.close()

        if runtimeMapper is not None:
            runtimeMapper.close()

        if observerDb is not None:
            observerDb.close()

        if resetDb is not None:
            resetDb.close()

        if projectId is not None and userId is not None:
            writerMapper.deleteProject(
                projectId=projectId,
                ownerId=userId,
            )

        if userId is not None:
            postgresqlIntegrationDb.execute(
                "DELETE FROM users WHERE id = %s",
                (
                    userId,
                ),
            )