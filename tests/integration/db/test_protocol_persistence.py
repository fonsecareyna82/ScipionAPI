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
from uuid import uuid4

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper


def _openPostgresqlIntegrationDb(
        postgresqlMigratedEnv,
):
    return PostgresqlDb(
        dbName=postgresqlMigratedEnv["databaseName"],
        user=postgresqlMigratedEnv["databaseUser"],
        password=postgresqlMigratedEnv["databasePass"],
        host=postgresqlMigratedEnv["postgresHost"],
        port=postgresqlMigratedEnv["postgresPort"],
    )


def test_ProtocolAndStepsPersistAcrossPostgresqlConnections(
        postgresqlIntegrationDb,
        postgresqlMigratedEnv,
):
    writerMapper = PostgresqlFlatMapper(
        postgresqlIntegrationDb
    )

    suffix = uuid4().hex

    userId = None
    projectId = None
    readerDb = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-integration-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Integration",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL integration %s" % suffix,
            description="Runtime persistence integration test.",
            status="active",
        )

        protocolId = 2

        protocolDbId = writerMapper.saveProtocol(
            {
                "info": {
                    "protocolId": protocolId,
                    "projectId": projectId,
                    "protocolClassName": "IntegrationProtocol",
                    "status": "scheduled",
                },
                "values": {
                    "threshold": 0.25,
                },
                "parentIds": [],
                "childIds": [],
            }
        )

        writerMapper.replaceProtocolSteps(
            projectId=projectId,
            protocolDbId=protocolDbId,
            protocolId=protocolId,
            steps=[
                {
                    "index": 0,
                    "stepClassName": "FunctionStep",
                    "name": "prepareStep",
                    "status": "finished",
                    "prerequisites": [],
                    "args": [
                        "input.star",
                    ],
                    "argsText": "input.star",
                    "resultFiles": [
                        "prepared.star",
                    ],
                    "needsGpu": False,
                    "schemaVersion": 2,
                },
                {
                    "index": 1,
                    "stepClassName": "FunctionStep",
                    "name": "processStep",
                    "status": "running",
                    "prerequisites": [
                        0,
                    ],
                    "args": [
                        "prepared.star",
                    ],
                    "argsText": "prepared.star",
                    "resultFiles": [],
                    "needsGpu": True,
                    "schemaVersion": 2,
                },
            ],
        )

        readerDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        readerMapper = PostgresqlFlatMapper(
            readerDb
        )

        storedProtocol = readerMapper.getProtocolByProtocolId(
            protocolId=protocolId,
            projectId=projectId,
        )

        storedSteps = readerMapper.listProtocolSteps(
            projectId=projectId,
            protocolId=protocolId,
        )

        assert storedProtocol is not None
        assert int(storedProtocol["id"]) == protocolDbId
        assert int(storedProtocol["projectId"]) == projectId
        assert storedProtocol["protocolId"] == str(protocolId)
        assert storedProtocol["protocolClassName"] == "IntegrationProtocol"
        assert storedProtocol["status"] == "scheduled"
        assert storedProtocol["params"] == {
            "threshold": 0.25,
        }
        assert storedProtocol["parentIds"] == []
        assert storedProtocol["childIds"] == []

        assert len(storedSteps) == 2

        assert storedSteps[0]["index"] == 0
        assert storedSteps[0]["stepClassName"] == "FunctionStep"
        assert storedSteps[0]["name"] == "prepareStep"
        assert storedSteps[0]["status"] == "finished"
        assert storedSteps[0]["prerequisites"] == []
        assert storedSteps[0]["args"] == [
            "input.star",
        ]
        assert storedSteps[0]["argsText"] == "input.star"
        assert storedSteps[0]["resultFiles"] == [
            "prepared.star",
        ]
        assert storedSteps[0]["needsGpu"] is False
        assert storedSteps[0]["schemaVersion"] == 2

        assert storedSteps[1]["index"] == 1
        assert storedSteps[1]["stepClassName"] == "FunctionStep"
        assert storedSteps[1]["name"] == "processStep"
        assert storedSteps[1]["status"] == "running"
        assert storedSteps[1]["prerequisites"] == [
            0,
        ]
        assert storedSteps[1]["args"] == [
            "prepared.star",
        ]
        assert storedSteps[1]["argsText"] == "prepared.star"
        assert storedSteps[1]["resultFiles"] == []
        assert storedSteps[1]["needsGpu"] is True
        assert storedSteps[1]["schemaVersion"] == 2

    finally:
        if readerDb is not None:
            readerDb.close()

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
