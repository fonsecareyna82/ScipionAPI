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
from types import SimpleNamespace
from uuid import uuid4

from pyworkflow.object import String
from pyworkflow.protocol import MODE_RESTART, STATUS_FINISHED, STATUS_SCHEDULED
from pyworkflow.protocol.protocol import Protocol

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper
from app.backend.mapper.postgresql_runtime_mapper import PostgresqlRuntimeMapper
from app.backend.mapper.scipion_object_mapper import ScipionObjectPostgresqlMapper
from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository
from app.backend.runtime.protocol_output_persistence_service import RuntimeProtocolOutputPersistenceService
from app.backend.runtime.protocol_postgresql_restart_launcher_service import RuntimePostgresqlRestartLauncherService
import app.backend.runtime.protocol_postgresql_restart_launcher_service as restartLauncherModule


class RestartProtocolStub(Protocol):
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
                "protocolClassName": "RestartProtocolStub",
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


def test_PostgresqlRestartCleansChildRuntimeStateWithoutMutatingParent(
        postgresqlIntegrationDb,
        postgresqlMigratedEnv,
        tmp_path,
        monkeypatch,
):
    writerMapper = PostgresqlFlatMapper(postgresqlIntegrationDb)

    originalResolveProtocolClass = PostgresqlRuntimeMapper._resolveProtocolClass

    def resolveProtocolClass(runtimeMapper, className):
        if className == "RestartProtocolStub":
            return RestartProtocolStub

        return originalResolveProtocolClass(runtimeMapper, className)

    monkeypatch.setattr(
        PostgresqlRuntimeMapper,
        "_resolveProtocolClass",
        resolveProtocolClass,
    )

    suffix = uuid4().hex
    userId = None
    projectId = None
    restartDb = None
    observerDb = None
    runtimeMapper = None
    observerRuntimeMapper = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-restart-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Restart",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL restart %s" % suffix,
            description="PostgreSQL restart integration test.",
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

        parentOutputRuntimeId = 1_100_002
        childOutputRuntimeId = 1_100_003

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

        restartDb = _openPostgresqlIntegrationDb(postgresqlMigratedEnv)
        restartMapper = PostgresqlFlatMapper(restartDb)

        runtimeMapper = PostgresqlRuntimeMapper(
            flatMapper=restartMapper,
            projectId=projectId,
            dictClasses={
                "RestartProtocolStub": RestartProtocolStub,
            },
        )

        childProtocol = runtimeMapper.selectRuntimeProtocolById(childProtocolId)

        assert childProtocol is not None
        assert isinstance(childProtocol, RestartProtocolStub)
        assert childProtocol.getObjId() == childProtocolId
        assert str(childProtocol.getStatus()).strip().lower() == str(STATUS_FINISHED).strip().lower()

        childProtocol.iterOutputAttributes = lambda: []
        childProtocol.getDefinition = lambda: SimpleNamespace(iterParams=lambda: [])
        childProtocol.isInteractive = lambda: False

        workingDirectoryOperations = []

        childProtocol.cleanWorkingDir = lambda: workingDirectoryOperations.append("clean")
        childProtocol.makeWorkingDir = lambda: workingDirectoryOperations.append("make")

        currentProject = SimpleNamespace(
            path=str(tmp_path),
            getPostgresqlRuntimeMapper=lambda: runtimeMapper,
        )

        workflowProtocolMap = {
            str(childProtocolId): (
                childProtocol,
                0,
            ),
        }

        restartService = RuntimePostgresqlRestartLauncherService()

        validationInfo = restartService.validateRestartSubworkflow(
            mapper=restartMapper,
            projectId=projectId,
            workflowProtocolMap=workflowProtocolMap,
            currentProject=currentProject,
        )

        assert validationInfo["errors"] == []
        assert validationInfo["protocolsCount"] == 1
        assert validationInfo["protocolDbIds"] == [childProtocolDbId]
        assert validationInfo["parentProtocolsModified"] is False
        assert validationInfo["runtimeStructures"][str(childProtocolId)] == {
            "outputNames": [],
            "pointerParams": [],
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
            return {
                "updated": 0,
                "parentProtocolDbIds": [],
            }

        popenCalls = []

        class FakeProcess:
            pid = 43210

        def fakePopen(command, **kwargs):
            popenCalls.append(
                {
                    "command": list(command),
                    "kwargs": dict(kwargs),
                }
            )

            return FakeProcess()

        monkeypatch.setattr(
            restartLauncherModule.subprocess,
            "Popen",
            fakePopen,
        )

        launchInfo = restartService.launchRestartSubworkflow(
            mapper=restartMapper,
            projectId=projectId,
            workflowProtocolMap=workflowProtocolMap,
            currentProject=currentProject,
            validationInfo=validationInfo,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback=deletePersistedOutputs,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=clearChildInputRefObjectIds,
        )

        assert launchInfo["errors"] == []
        assert launchInfo["protocolsCount"] == 1
        assert len(launchInfo["prepared"]) == 1
        assert len(launchInfo["launched"]) == 1

        assert launchInfo["prepared"][0]["protocolId"] == str(childProtocolId)
        assert launchInfo["prepared"][0]["protocolDbId"] == childProtocolDbId
        assert launchInfo["prepared"][0]["level"] == 0
        assert launchInfo["prepared"][0]["interactive"] is False

        assert launchInfo["launched"][0]["protocolId"] == str(childProtocolId)
        assert launchInfo["launched"][0]["coordinatorPid"] == 43210
        assert launchInfo["launched"][0]["launched"] is True

        assert launchInfo["outputCleanup"]["protocolsCount"] == 1
        assert launchInfo["outputCleanup"]["setsDeleted"] == 0
        assert launchInfo["outputCleanup"]["objectsDeleted"] >= 1
        assert launchInfo["outputCleanup"]["fileErrors"] == []

        assert launchInfo["inputRefCleanup"] == {
            "updated": 0,
            "parentProtocolDbIds": [],
        }

        assert workingDirectoryOperations == [
            "clean",
            "make",
        ]

        assert childProtocol.getRunMode() == MODE_RESTART
        assert str(childProtocol.getStatus()).strip().lower() == str(STATUS_SCHEDULED).strip().lower()

        assert len(popenCalls) == 1

        workerCommand = popenCalls[0]["command"]

        assert "--project-id" in workerCommand
        assert "--protocol-id" in workerCommand

        projectIdIndex = workerCommand.index("--project-id")
        protocolIdIndex = workerCommand.index("--protocol-id")

        assert workerCommand[projectIdIndex + 1] == str(projectId)
        assert workerCommand[protocolIdIndex + 1] == str(childProtocolId)
        assert str(childProtocolDbId) != workerCommand[protocolIdIndex + 1]

        runtimeMapper.close()
        runtimeMapper = None

        restartDb.close()
        restartDb = None

        observerDb = _openPostgresqlIntegrationDb(postgresqlMigratedEnv)
        observerMapper = PostgresqlFlatMapper(observerDb)
        observerObjectMapper = ScipionObjectPostgresqlMapper(observerDb)

        parentAfter = observerDb.fetchOne(
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

        childAfter = observerDb.fetchOne(
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
        assert str(childAfter["status"]).strip().lower() == str(STATUS_SCHEDULED).strip().lower()
        assert childAfter["relationsSynchronized"] is False

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

        observerRuntimeMapper = PostgresqlRuntimeMapper(
            flatMapper=observerMapper,
            projectId=projectId,
            dictClasses={
                "RestartProtocolStub": RestartProtocolStub,
            },
        )

        rehydratedChildProtocol = observerRuntimeMapper.selectRuntimeProtocolById(childProtocolId)

        assert rehydratedChildProtocol is not None
        assert isinstance(rehydratedChildProtocol, RestartProtocolStub)
        assert rehydratedChildProtocol.getObjId() == childProtocolId
        assert rehydratedChildProtocol.getRunMode() == MODE_RESTART
        assert str(rehydratedChildProtocol.getStatus()).strip().lower() == str(STATUS_SCHEDULED).strip().lower()

    finally:
        if observerRuntimeMapper is not None:
            observerRuntimeMapper.close()

        if runtimeMapper is not None:
            runtimeMapper.close()

        if observerDb is not None:
            observerDb.close()

        if restartDb is not None:
            restartDb.close()

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