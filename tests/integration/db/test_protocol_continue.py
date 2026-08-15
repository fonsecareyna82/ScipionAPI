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
from pyworkflow.protocol import MODE_RESUME, STATUS_FINISHED, STATUS_SAVED, STATUS_SCHEDULED
from pyworkflow.protocol.protocol import Protocol

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper
from app.backend.mapper.postgresql_runtime_mapper import PostgresqlRuntimeMapper
from app.backend.mapper.scipion_object_mapper import ScipionObjectPostgresqlMapper
from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository
from app.backend.runtime.protocol_postgresql_continue_launcher_service import (
    CONTINUE_ACTION_RESUME,
    RuntimePostgresqlContinueLauncherService,
)


class ContinueProtocolStub(Protocol):
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
                "protocolClassName": "ContinueProtocolStub",
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


def test_PostgresqlContinueResumesStreamingProtocolWithoutDestroyingRuntimeState(
        postgresqlIntegrationDb,
        postgresqlMigratedEnv,
        tmp_path,
        monkeypatch,
):
    writerMapper = PostgresqlFlatMapper(postgresqlIntegrationDb)

    originalResolveProtocolClass = PostgresqlRuntimeMapper._resolveProtocolClass

    def resolveProtocolClass(runtimeMapper, className):
        if className == "ContinueProtocolStub":
            return ContinueProtocolStub

        return originalResolveProtocolClass(runtimeMapper, className)

    monkeypatch.setattr(
        PostgresqlRuntimeMapper,
        "_resolveProtocolClass",
        resolveProtocolClass,
    )

    suffix = uuid4().hex
    userId = None
    projectId = None
    continueDb = None
    observerDb = None
    runtimeMapper = None
    observerRuntimeMapper = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-continue-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Continue",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL continue %s" % suffix,
            description="PostgreSQL continue integration test.",
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

        parentOutputRuntimeId = 1_200_002
        childOutputRuntimeId = 1_200_003

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

        parentStepsBefore = writerMapper.listProtocolSteps(
            projectId=projectId,
            protocolId=parentProtocolId,
        )

        childStepsBefore = writerMapper.listProtocolSteps(
            projectId=projectId,
            protocolId=childProtocolId,
        )
        childStepEventBefore = childStepsBefore[0]["event"]


        assert len(parentStepsBefore) == 1
        assert len(childStepsBefore) == 1
        assert parentStepsBefore[0]["name"] == "parentStep"
        assert childStepsBefore[0]["name"] == "childStep"

        continueDb = _openPostgresqlIntegrationDb(postgresqlMigratedEnv)
        continueMapper = PostgresqlFlatMapper(continueDb)

        runtimeMapper = PostgresqlRuntimeMapper(
            flatMapper=continueMapper,
            projectId=projectId,
            dictClasses={
                "ContinueProtocolStub": ContinueProtocolStub,
            },
        )

        childProtocol = runtimeMapper.selectRuntimeProtocolById(childProtocolId)

        assert childProtocol is not None
        assert isinstance(childProtocol, ContinueProtocolStub)
        assert childProtocol.getObjId() == childProtocolId
        assert str(childProtocol.getStatus()).strip().lower() == str(STATUS_FINISHED).strip().lower()

        childProtocol.worksInStreaming = lambda: True
        childProtocol.isSaved = lambda: False
        childProtocol.isScheduled = lambda: False
        childProtocol.isInteractive = lambda: False

        workingDirectoryOperations = []

        childProtocol.cleanWorkingDir = lambda: workingDirectoryOperations.append("clean")
        childProtocol.makeWorkingDir = lambda: workingDirectoryOperations.append("make")

        enqueueCalls = []

        def enqueueProtocolTask(
                protocol,
                runMode,
                wait=False,
        ):
            enqueueCalls.append({
                "protocol": protocol,
                "runMode": runMode,
                "wait": wait,
            })

            return "celery-continue-task-1"

        currentProject = SimpleNamespace(
            path=str(tmp_path),
            getPostgresqlRuntimeMapper=(
                lambda: runtimeMapper
            ),
            _enqueuePostgresqlProtocolTask=(
                enqueueProtocolTask
            ),
        )

        workflowProtocolMap = {
            str(childProtocolId): (
                childProtocol,
                0,
            ),
        }

        continueService = RuntimePostgresqlContinueLauncherService()

        plan = continueService.buildContinuePlan(
            mapper=continueMapper,
            projectId=projectId,
            workflowProtocolMap=workflowProtocolMap,
            currentProject=currentProject,
        )

        assert plan["errors"] == []
        assert plan["summary"]["protocolsCount"] == 1
        assert plan["summary"]["actionableCount"] == 1
        assert plan["summary"]["restartProtocolIds"] == []
        assert plan["summary"]["resumeProtocolIds"] == [str(childProtocolId)]
        assert plan["summary"]["skipped"] == []
        assert plan["summary"]["parentProtocolsModified"] is False

        assert len(plan["entries"]) == 1

        entry = plan["entries"][0]

        assert entry["protocol"] is childProtocol
        assert entry["protocolId"] == childProtocolId
        assert entry["protocolDbId"] == childProtocolDbId
        assert entry["level"] == 0
        assert entry["action"] == CONTINUE_ACTION_RESUME
        assert entry["reason"] == "streaming_execution_exists"

        def failOutputCleanup(**kwargs):
            raise AssertionError(
                "PostgreSQL resume must not delete persisted outputs."
            )

        def failInputRefCleanup(**kwargs):
            raise AssertionError(
                "PostgreSQL resume must not clear child input reference object ids."
            )

        launchInfo = continueService.launchContinueSubworkflow(
            mapper=continueMapper,
            projectId=projectId,
            currentProject=currentProject,
            plan=plan,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback=failOutputCleanup,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=failInputRefCleanup,
        )

        assert launchInfo["errors"] == []
        assert launchInfo["protocolsCount"] == 1
        assert launchInfo["preparedCount"] == 1
        assert launchInfo["restartedCount"] == 0
        assert launchInfo["resumedCount"] == 1
        assert launchInfo["skippedCount"] == 0
        assert launchInfo["restartOutputCleanup"] is None
        assert launchInfo["restartInputRefCleanup"] is None
        assert launchInfo["parentProtocolsModified"] is False

        assert len(launchInfo["prepared"]) == 1

        preparedItem = launchInfo["prepared"][0]

        assert preparedItem["protocolId"] == str(childProtocolId)
        assert preparedItem["protocolDbId"] == childProtocolDbId
        assert preparedItem["level"] == 0
        assert preparedItem["action"] == CONTINUE_ACTION_RESUME
        assert preparedItem["outputsPreserved"] is True
        assert preparedItem["workingDirectoryPreserved"] is True
        assert preparedItem["stepsPrepared"] == 1
        assert preparedItem["parentProtocolsModified"] is False

        assert len(launchInfo["launched"]) == 1

        launchedItem = launchInfo["launched"][0]

        assert (
                launchedItem["protocolId"]
                == str(childProtocolId)
        )

        assert (
                launchedItem["protocolDbId"]
                == childProtocolDbId
        )

        assert (
                launchedItem["action"]
                == CONTINUE_ACTION_RESUME
        )

        assert launchedItem["launched"] is True

        assert (
                launchedItem["taskId"]
                == "celery-continue-task-1"
        )

        assert (
                launchedItem["outputsPreserved"]
                is True
        )

        assert (
                launchedItem["workingDirectoryPreserved"]
                is True
        )

        assert workingDirectoryOperations == [
            "make",
        ]

        assert childProtocol.getRunMode() == MODE_RESUME
        assert str(childProtocol.getStatus()).strip().lower() == str(STATUS_SCHEDULED).strip().lower()

        assert enqueueCalls == [{
            "protocol": childProtocol,
            "runMode": CONTINUE_ACTION_RESUME,
            "wait": False,
        }]

        runtimeMapper.close()
        runtimeMapper = None

        continueDb.close()
        continueDb = None

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

        parentStepRows = observerDb.fetchAll(
            """
            SELECT "stepIndex",
                   name,
                   status,
                   event
              FROM protocol_steps
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
             ORDER BY "stepIndex"
            """,
            (
                projectId,
                parentProtocolDbId,
            ),
        )

        childStepRows = observerDb.fetchAll(
            """
            SELECT "stepIndex",
                   name,
                   status,
                   event
              FROM protocol_steps
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
             ORDER BY "stepIndex"
            """,
            (
                projectId,
                childProtocolDbId,
            ),
        )

        assert childStepRows[0]["event"] == childStepEventBefore
        assert len(parentStepRows) == 1
        assert parentStepRows[0]["name"] == "parentStep"
        assert str(parentStepRows[0]["status"]).strip().lower() == str(STATUS_FINISHED).strip().lower()

        assert len(childStepRows) == 1
        assert childStepRows[0]["name"] == "childStep"
        assert str(childStepRows[0]["status"]).strip().lower() == str(STATUS_FINISHED).strip().lower()

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

        assert len(childOutputRows) == 1
        assert childOutputRows[0]["scipionObjId"] == childOutputRuntimeId
        assert childOutputRows[0]["value"] == "CHILD_OUTPUT"

        observerRuntimeMapper = PostgresqlRuntimeMapper(
            flatMapper=observerMapper,
            projectId=projectId,
            dictClasses={
                "ContinueProtocolStub": ContinueProtocolStub,
            },
        )

        rehydratedChildProtocol = observerRuntimeMapper.selectRuntimeProtocolById(
            childProtocolId
        )

        assert rehydratedChildProtocol is not None
        assert isinstance(rehydratedChildProtocol, ContinueProtocolStub)
        assert rehydratedChildProtocol.getObjId() == childProtocolId
        assert rehydratedChildProtocol.getRunMode() == MODE_RESUME
        assert str(rehydratedChildProtocol.getStatus()).strip().lower() == str(STATUS_SCHEDULED).strip().lower()

    finally:
        if observerRuntimeMapper is not None:
            observerRuntimeMapper.close()

        if runtimeMapper is not None:
            runtimeMapper.close()

        if observerDb is not None:
            observerDb.close()

        if continueDb is not None:
            continueDb.close()

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