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

from pyworkflow.object import Object, Set, String

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper
from app.backend.mapper.scipion_object_mapper import ScipionObjectPostgresqlMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.project_integrity_service import RuntimeProjectIntegrityService


class IntegrityItem(Object):
    def __init__(self):
        super().__init__()
        self._value = String()


class IntegritySet(Set):
    ITEM_TYPE = IntegrityItem


class SourceIntegritySet(Set):
    ITEM_TYPE = IntegrityItem

    def __init__(self, items):
        super().__init__()
        self._integrationItems = list(items)

    def getClassName(self):
        return "IntegritySet"

    def getObjDict(self, includeClass=False):
        if includeClass:
            return {"self": ("IntegritySet", None)}

        return {}

    def iterItems(self, iterate=False):
        return iter(self._integrationItems)

    def getSize(self):
        return len(self._integrationItems)

    def getFirstItem(self):
        return self._integrationItems[0] if self._integrationItems else None

    def getLastItem(self):
        return self._integrationItems[-1] if self._integrationItems else None

    def getMaxId(self):
        if not self._integrationItems:
            return 0

        return max(int(item.getObjId()) for item in self._integrationItems)

    def getFileName(self):
        return None


def _openPostgresqlIntegrationDb(postgresqlMigratedEnv):
    return PostgresqlDb(
        dbName=postgresqlMigratedEnv["databaseName"],
        user=postgresqlMigratedEnv["databaseUser"],
        password=postgresqlMigratedEnv["databasePass"],
        host=postgresqlMigratedEnv["postgresHost"],
        port=postgresqlMigratedEnv["postgresPort"],
    )


def _buildItem(itemId, value):
    item = IntegrityItem()
    item.setObjId(itemId)
    item._value.set(value)
    return item


def _storeProtocolStep(mapper, projectId, protocolDbId, protocolId):
    mapper.replaceProtocolSteps(
        projectId=projectId,
        protocolDbId=protocolDbId,
        protocolId=protocolId,
        steps=[
            {
                "index": 0,
                "stepClassName": "FunctionStep",
                "name": "integrityStep",
                "status": "finished",
                "prerequisites": [],
                "args": [],
                "argsText": "",
                "resultFiles": [],
                "needsGpu": False,
                "schemaVersion": 2,
            },
        ],
    )


def test_PostgresqlIntegrityCheckerDetectsSemanticCorruptionWithoutRepair(
        postgresqlIntegrationDb,
        postgresqlMigratedEnv,
):
    writerMapper = PostgresqlFlatMapper(postgresqlIntegrationDb)
    suffix = uuid4().hex

    userId = None
    projectId = None
    auditDb = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-integrity-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Integrity",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL integrity %s" % suffix,
            description="PostgreSQL integrity checker integration test.",
            status="active",
        )

        parentProtocolId = 2
        childProtocolId = 3

        parentProtocolDbId = writerMapper.saveProtocol(
            {
                "info": {
                    "protocolId": parentProtocolId,
                    "projectId": projectId,
                    "protocolClassName": "IntegrityParentProtocol",
                    "status": "finished",
                },
                "values": {},
                "parentIds": [],
                "childIds": [childProtocolId],
            }
        )

        childProtocolDbId = writerMapper.saveProtocol(
            {
                "info": {
                    "protocolId": childProtocolId,
                    "projectId": projectId,
                    "protocolClassName": "IntegrityChildProtocol",
                    "status": "finished",
                },
                "values": {},
                "parentIds": [parentProtocolId],
                "childIds": [],
            }
        )

        _storeProtocolStep(
            mapper=writerMapper,
            projectId=projectId,
            protocolDbId=childProtocolDbId,
            protocolId=childProtocolId,
        )

        parentOutputName = "outputParent"
        parentRuntimeObjectId = 1_600_002

        parentOutput = String()
        parentOutput.set("PARENT_OUTPUT")
        parentOutput.setObjId(parentRuntimeObjectId)

        objectMapper = ScipionObjectPostgresqlMapper(postgresqlIntegrationDb)

        objectMapper.storeObjectTree(
            projectId=projectId,
            protocolDbId=parentProtocolDbId,
            outputName=parentOutputName,
            scipionObj=parentOutput,
        )

        parentObjectTree = objectMapper.getStoredObjectTree(
            projectId=projectId,
            protocolDbId=parentProtocolDbId,
            outputName=parentOutputName,
        )

        parentRootObject = next(
            row
            for row in parentObjectTree
            if row["path"] == parentOutputName
        )

        childOutputName = "outputItems"

        sourceSet = SourceIntegritySet(
            [
                _buildItem(1, "ITEM_01"),
                _buildItem(2, "ITEM_02"),
            ]
        )

        sourceSet.setObjId(1_600_003)

        setMapper = ScipionSetPostgresqlMapper(postgresqlIntegrationDb)

        storeResult = setMapper.storeSet(
            projectId=projectId,
            protocolDbId=childProtocolDbId,
            outputName=childOutputName,
            scipionSet=sourceSet,
        )

        setId = int(storeResult["setId"])

        rootTable = postgresqlIntegrationDb.fetchOne(
            """
            SELECT id
              FROM scipion_set_tables
             WHERE "setId" = %s
               AND "tableKind" = 'root'
            """,
            (setId,),
        )

        assert rootTable is not None

        rootTableId = int(rootTable["id"])

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
                str(parentRuntimeObjectId),
            ),
        )

        integrityService = RuntimeProjectIntegrityService()

        healthyReport = integrityService.checkProject(
            mapper=writerMapper,
            projectId=projectId,
        )

        assert healthyReport["healthy"] is True
        assert healthyReport["issuesCount"] == 0
        assert healthyReport["issues"] == []
        assert healthyReport["issueCounts"] == {}
        assert healthyReport["readOnly"] is True

        # --------------------------------------------------------------
        # Introduce semantic corruptions that remain legal at the SQL
        # constraint level. The checker must detect them, not repair them.
        # --------------------------------------------------------------

        postgresqlIntegrationDb.execute(
            """
            UPDATE protocol_steps
               SET "protocolId" = %s
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
            """,
            (
                "999",
                projectId,
                childProtocolDbId,
            ),
        )

        postgresqlIntegrationDb.execute(
            """
            UPDATE protocol_input_refs
               SET "parentProtocolId" = %s
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND "inputName" = %s
            """,
            (
                "999",
                projectId,
                childProtocolDbId,
                "inputParent",
            ),
        )

        postgresqlIntegrationDb.execute(
            """
            UPDATE scipion_sets
               SET properties = jsonb_set(
                       properties,
                       '{itemsCount}',
                       '99'::jsonb,
                       TRUE
                   )
             WHERE id = %s
            """,
            (setId,),
        )

        postgresqlIntegrationDb.execute(
            """
            UPDATE scipion_sets
               SET "objectId" = %s
             WHERE id = %s
            """,
            (
                int(parentRootObject["id"]),
                setId,
            ),
        )

        postgresqlIntegrationDb.execute(
            """
            UPDATE scipion_set_tables
               SET "parentItemId" = %s
             WHERE id = %s
            """,
            (
                999,
                rootTableId,
            ),
        )

        auditDb = _openPostgresqlIntegrationDb(postgresqlMigratedEnv)
        auditMapper = PostgresqlFlatMapper(auditDb)

        corruptedReport = RuntimeProjectIntegrityService().checkProject(
            mapper=auditMapper,
            projectId=projectId,
        )

        assert corruptedReport["healthy"] is False
        assert corruptedReport["issuesCount"] >= 5
        assert corruptedReport["readOnly"] is True

        detectedCodes = {
            issue["code"]
            for issue in corruptedReport["issues"]
        }

        assert {
            "protocol_step_identity_mismatch",
            "input_ref_identity_mismatch",
            "set_counter_mismatch",
            "set_owner_mismatch",
            "logical_root_table_invalid",
        }.issubset(detectedCodes)

        assert corruptedReport["issueCounts"]["protocol_step_identity_mismatch"] == 1
        assert corruptedReport["issueCounts"]["set_owner_mismatch"] == 1
        assert corruptedReport["issueCounts"]["logical_root_table_invalid"] == 1

        # --------------------------------------------------------------
        # Detection only: every corruption must still exist after audit.
        # --------------------------------------------------------------

        corruptedStep = auditDb.fetchOne(
            """
            SELECT "protocolId"
              FROM protocol_steps
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
            """,
            (
                projectId,
                childProtocolDbId,
            ),
        )

        assert corruptedStep["protocolId"] == "999"

        corruptedInputRef = auditDb.fetchOne(
            """
            SELECT "parentProtocolId"
              FROM protocol_input_refs
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND "inputName" = %s
            """,
            (
                projectId,
                childProtocolDbId,
                "inputParent",
            ),
        )

        assert corruptedInputRef["parentProtocolId"] == "999"

        corruptedSet = auditDb.fetchOne(
            """
            SELECT "objectId",
                   properties
              FROM scipion_sets
             WHERE id = %s
            """,
            (setId,),
        )

        assert int(corruptedSet["objectId"]) == int(parentRootObject["id"])
        assert int(corruptedSet["properties"]["itemsCount"]) == 99

        corruptedRootTable = auditDb.fetchOne(
            """
            SELECT "parentItemId"
              FROM scipion_set_tables
             WHERE id = %s
            """,
            (rootTableId,),
        )

        assert int(corruptedRootTable["parentItemId"]) == 999

    finally:
        if auditDb is not None:
            auditDb.close()

        if projectId is not None and userId is not None:
            writerMapper.deleteProject(
                projectId=projectId,
                ownerId=userId,
            )

        if userId is not None:
            postgresqlIntegrationDb.execute(
                "DELETE FROM users WHERE id = %s",
                (userId,),
            )