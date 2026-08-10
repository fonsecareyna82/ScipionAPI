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
from pathlib import Path
from uuid import uuid4

from pyworkflow.object import Float, Object, Set, String

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.postgresql_observability_service import RuntimePostgresqlObservabilityService
from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetFactory


class ObservabilityItem(Object):
    def __init__(self):
        super().__init__()
        self._score = Float()
        self._code = String()


class ObservabilitySet(Set):
    ITEM_TYPE = ObservabilityItem


class SourceObservabilitySet(Set):
    ITEM_TYPE = ObservabilityItem

    def __init__(self, items):
        super().__init__()
        self._integrationItems = list(items)

    def getClassName(self):
        return "ObservabilitySet"

    def getObjDict(self, includeClass=False):
        if includeClass:
            return {
                "self": (
                    "ObservabilitySet",
                    None,
                ),
            }

        return {}

    def iterItems(self, iterate=False):
        return iter(
            self._integrationItems
        )

    def getSize(self):
        return len(
            self._integrationItems
        )

    def getFirstItem(self):
        return (
            self._integrationItems[0]
            if self._integrationItems
            else None
        )

    def getLastItem(self):
        return (
            self._integrationItems[-1]
            if self._integrationItems
            else None
        )

    def getMaxId(self):
        if not self._integrationItems:
            return 0

        return max(
            int(item.getObjId())
            for item in self._integrationItems
        )

    def getFileName(self):
        return None


class ParentProtocolStub:
    def __init__(self, protocolId):
        self.protocolId = int(
            protocolId
        )

    def getObjId(self):
        return self.protocolId


def _openPostgresqlIntegrationDb(postgresqlMigratedEnv):
    return PostgresqlDb(
        dbName=postgresqlMigratedEnv["databaseName"],
        user=postgresqlMigratedEnv["databaseUser"],
        password=postgresqlMigratedEnv["databasePass"],
        host=postgresqlMigratedEnv["postgresHost"],
        port=postgresqlMigratedEnv["postgresPort"],
    )


def _buildItem(itemId, score, code):
    item = ObservabilityItem()

    item.setObjId(
        itemId
    )

    item._score.set(
        score
    )

    item._code.set(
        code
    )

    return item


def _loadRuntimeOutputInfo(
        setMapper,
        projectId,
        protocolDbId,
        outputName,
):
    storedSet = setMapper.getStoredSet(
        projectId=projectId,
        protocolDbId=protocolDbId,
        outputName=outputName,
    )

    assert storedSet is not None

    objectTree = setMapper.getStoredObjectTree(
        projectId=projectId,
        protocolDbId=protocolDbId,
        outputName=outputName,
    )

    rootObject = next(
        row
        for row in objectTree
        if row["path"] == outputName
    )

    return {
        "setId": int(storedSet["id"]),
        "rootObjectId": int(storedSet["objectId"]),
        "runtimeObjectId": int(rootObject["scipionObjId"]),
        "projectId": projectId,
        "protocolDbId": protocolDbId,
        "outputName": outputName,
        "setClassName": storedSet["setClassName"],
        "itemClassName": storedSet["itemClassName"],
        "properties": storedSet["properties"],
    }


def test_PostgresqlObservabilityMeasuresRealRuntimeSetOperations(
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
    runtimeSet = None
    materializer = None
    materializedPath = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-observability-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Observability",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL observability %s" % suffix,
            description="PostgreSQL observability integration test.",
            status="active",
        )

        protocolId = 2

        protocolDbId = writerMapper.saveProtocol(
            {
                "info": {
                    "protocolId": protocolId,
                    "projectId": projectId,
                    "protocolClassName": "ObservabilityProtocol",
                    "status": "finished",
                },
                "values": {},
                "parentIds": [],
                "childIds": [],
            }
        )

        sourceSet = SourceObservabilitySet(
            [
                _buildItem(
                    1,
                    0.25,
                    "ITEM_01",
                ),
                _buildItem(
                    2,
                    0.50,
                    "ITEM_02",
                ),
                _buildItem(
                    3,
                    0.75,
                    "ITEM_03",
                ),
            ]
        )

        sourceSet.setObjId(
            1_700_001
        )

        outputName = "outputObservedItems"

        ScipionSetPostgresqlMapper(
            postgresqlIntegrationDb
        ).storeSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
            scipionSet=sourceSet,
        )

        readerDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        readerDb.resetQueryStats()

        observability = RuntimePostgresqlObservabilityService()

        readerSetMapper = ScipionSetPostgresqlMapper(
            readerDb
        )

        with observability.measure(
                operation="set_snapshot_load",
                db=readerDb,
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
        ) as snapshotMetric:
            outputInfo = _loadRuntimeOutputInfo(
                setMapper=readerSetMapper,
                projectId=projectId,
                protocolDbId=protocolDbId,
                outputName=outputName,
            )

            snapshotMetric["setId"] = outputInfo["setId"]

        assert snapshotMetric["success"] is True
        assert snapshotMetric["durationSeconds"] >= 0.0
        assert snapshotMetric["queryCount"] > 0
        assert snapshotMetric["failedQueryCount"] == 0
        assert snapshotMetric["querySeconds"] >= 0.0

        runtimeSetFactory = PostgresqlRuntimeSetFactory()

        with observability.measure(
                operation="runtime_set_hydration",
                db=readerDb,
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
        ) as hydrationMetric:
            runtimeSet = runtimeSetFactory.build(
                db=readerDb,
                parent=ParentProtocolStub(
                    protocolId
                ),
                outputName=outputName,
                outputInfo=outputInfo,
                classes={
                    "ObservabilitySet": ObservabilitySet,
                    "ObservabilityItem": ObservabilityItem,
                },
                cache=False,
            )

            hydrationMetric["itemsCount"] = runtimeSet.getSize()

        assert hydrationMetric["success"] is True
        assert hydrationMetric["itemsCount"] == 3
        assert hydrationMetric["durationSeconds"] >= 0.0
        assert hydrationMetric["queryCount"] > 0
        assert hydrationMetric["failedQueryCount"] == 0

        with observability.measure(
                operation="sqlite_compatibility_materialization",
                db=readerDb,
                projectId=projectId,
                protocolId=protocolId,
                outputName=outputName,
        ) as materializationMetric:
            materializedPath = runtimeSet.getFileName()

            materializationMetric["itemsCount"] = runtimeSet.getSize()
            materializationMetric["materialized"] = True

        assert materializationMetric["success"] is True
        assert materializationMetric["itemsCount"] == 3
        assert materializationMetric["materialized"] is True
        assert materializationMetric["durationSeconds"] >= 0.0
        assert materializationMetric["queryCount"] > 0
        assert materializationMetric["failedQueryCount"] == 0

        assert materializedPath is not None
        assert Path(materializedPath).is_file()

        materializer = runtimeSet._postgresqlSqliteMaterializer

        aggregateStats = readerDb.getQueryStats()

        measuredQueries = (
            snapshotMetric["queryCount"]
            + hydrationMetric["queryCount"]
            + materializationMetric["queryCount"]
        )

        assert aggregateStats["queryCount"] == measuredQueries
        assert aggregateStats["failedQueryCount"] == 0
        assert aggregateStats["querySeconds"] >= 0.0
        assert aggregateStats["maxQuerySeconds"] >= 0.0

        releaseInfo = materializer.releaseRuntimeSet(
            runtimeSet
        )

        assert releaseInfo["removed"] is True
        assert not Path(materializedPath).exists()

        runtimeSet.close()
        runtimeSet = None

    finally:
        if runtimeSet is not None:
            if materializer is not None:
                try:
                    materializer.releaseRuntimeSet(
                        runtimeSet
                    )
                except Exception:
                    pass

            runtimeSet.close()

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