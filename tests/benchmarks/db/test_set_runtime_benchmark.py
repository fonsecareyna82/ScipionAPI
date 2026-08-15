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
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest

from pyworkflow.object import Integer, Object, Set, String

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.postgresql_observability_service import RuntimePostgresqlObservabilityService
from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetFactory


RUN_BENCHMARKS = os.getenv("SCIPIONAPI_RUN_BENCHMARKS") == "1"


def _getBenchmarkSizes():
    value = os.getenv("SCIPIONAPI_BENCHMARK_SET_SIZES", "10000,100000")
    sizes = [int(item.strip()) for item in value.split(",") if item.strip()]

    if not sizes or any(size <= 0 for size in sizes):
        raise ValueError("SCIPIONAPI_BENCHMARK_SET_SIZES must contain positive integers")

    return sizes


BENCHMARK_SIZES = _getBenchmarkSizes()

pytestmark = pytest.mark.skipif(
    not RUN_BENCHMARKS,
    reason="Set SCIPIONAPI_RUN_BENCHMARKS=1 to run PostgreSQL benchmarks.",
)


class BenchmarkItem(Object):
    def __init__(self):
        super().__init__()
        self._value = Integer()
        self._code = String()


class BenchmarkSet(Set):
    ITEM_TYPE = BenchmarkItem


class ParentProtocolStub:
    def __init__(self, protocolId):
        self.protocolId = int(protocolId)

    def getObjId(self):
        return self.protocolId


CLASSES = {
    "BenchmarkSet": BenchmarkSet,
    "BenchmarkItem": BenchmarkItem,
}


def _openPostgresqlIntegrationDb(postgresqlMigratedEnv):
    return PostgresqlDb(
        dbName=postgresqlMigratedEnv["databaseName"],
        user=postgresqlMigratedEnv["databaseUser"],
        password=postgresqlMigratedEnv["databasePass"],
        host=postgresqlMigratedEnv["postgresHost"],
        port=postgresqlMigratedEnv["postgresPort"],
    )


def _buildItem(itemId):
    item = BenchmarkItem()
    item.setObjId(itemId)
    item._value.set(itemId * 2)
    item._code.set("ITEM_%07d" % itemId)
    return item


def _openSqliteSet(fileName):
    result = BenchmarkSet()
    result.setClassesDict(CLASSES)
    result._mapperPath.set("%s, " % fileName)
    result.load()
    result.loadAllProperties()
    return result


def _iterateSet(setObject):
    itemsCount = 0
    idsSum = 0
    valuesSum = 0
    codeLengthSum = 0

    for item in setObject.iterItems(orderBy="id", direction="ASC"):
        itemsCount += 1
        idsSum += int(item.getObjId())
        valuesSum += int(item._value.get())
        codeLengthSum += len(str(item._code.get()))

    return {
        "itemsCount": itemsCount,
        "idsSum": idsSum,
        "valuesSum": valuesSum,
        "codeLengthSum": codeLengthSum,
    }


def _itemsPerSecond(itemsCount, elapsedSeconds):
    if elapsedSeconds <= 0:
        return None

    return float(itemsCount) / float(elapsedSeconds)


def _explainRuntimeSetRead(db, runtimeSet):
    mapper = runtimeSet._getMapper()

    mapper._refreshReadSchema()

    query = mapper._buildItemsSelectQuery()

    orderSql, orderParams = mapper._buildOrderBy(
        "id",
        "ASC",
    )

    params = [
        mapper._scopeId,
    ]

    if orderSql:
        query += "\n ORDER BY " + orderSql
        params.extend(orderParams)

    row = db.fetchOne(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)\n" + query,
        tuple(params),
    )

    planValue = next(
        iter(row.values())
    )

    if isinstance(planValue, str):
        planValue = json.loads(planValue)

    if isinstance(planValue, list):
        return planValue[0]

    return planValue


def _explainQuery(db, query, params):
    row = db.fetchOne(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)\n" + query,
        tuple(params),
    )

    planValue = next(iter(row.values()))

    if isinstance(planValue, str):
        planValue = json.loads(planValue)

    if isinstance(planValue, list):
        return planValue[0]

    return planValue


def _explainRuntimeSetIndexReview(db, runtimeSet, itemId):
    mapper = runtimeSet._getMapper()

    mapper._refreshReadSchema()

    scopeColumn = mapper._scopeColumn
    itemsTable = mapper._itemsTable
    scopeId = mapper._scopeId

    countPlan = _explainQuery(
        db,
        """
        SELECT COUNT(*) AS count
          FROM {itemsTable}
         WHERE "{scopeColumn}" = %s
        """.format(
            itemsTable=itemsTable,
            scopeColumn=scopeColumn,
        ),
        (scopeId,),
    )

    maxIdPlan = _explainQuery(
        db,
        """
        SELECT MAX("scipionItemId") AS "maxItemId"
          FROM {itemsTable}
         WHERE "{scopeColumn}" = %s
        """.format(
            itemsTable=itemsTable,
            scopeColumn=scopeColumn,
        ),
        (scopeId,),
    )

    selectByIdQuery = (
        mapper._buildItemsSelectQuery()
        + """
           AND "scipionItemId" = %s
         LIMIT 1
        """
    )

    selectByIdPlan = _explainQuery(
        db,
        selectByIdQuery,
        (
            scopeId,
            int(itemId),
        ),
    )

    return {
        "count": countPlan,
        "maxId": maxIdPlan,
        "selectById": selectByIdPlan,
    }


def _assertIterationResult(result, itemsCount):
    expectedIdsSum = itemsCount * (itemsCount + 1) // 2

    assert result["itemsCount"] == itemsCount
    assert result["idsSum"] == expectedIdsSum
    assert result["valuesSum"] == expectedIdsSum * 2
    assert result["codeLengthSum"] == itemsCount * 12


@pytest.mark.parametrize("itemsCount", BENCHMARK_SIZES)
def test_PostgresqlSetRuntimeBenchmark(postgresqlIntegrationDb, postgresqlMigratedEnv, tmp_path, itemsCount):
    writerMapper = PostgresqlFlatMapper(postgresqlIntegrationDb)
    observability = RuntimePostgresqlObservabilityService()
    suffix = uuid4().hex

    userId = None
    projectId = None
    sourceSet = None
    sqliteReadSet = None
    readerDb = None
    runtimeSet = None
    materializer = None
    materializedPath = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-benchmark-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Benchmark",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL benchmark %s" % suffix,
            description="PostgreSQL Set runtime benchmark.",
            status="active",
        )

        protocolId = 2

        protocolDbId = writerMapper.saveProtocol(
            {
                "info": {
                    "protocolId": protocolId,
                    "projectId": projectId,
                    "protocolClassName": "BenchmarkProtocol",
                    "status": "finished",
                },
                "values": {},
                "parentIds": [],
                "childIds": [],
            }
        )

        sqlitePath = tmp_path / f"benchmark-{itemsCount}.sqlite"

        sqliteWriteStartedAt = time.perf_counter()

        sourceSet = BenchmarkSet(filename=str(sqlitePath))
        sourceSet.setClassesDict(CLASSES)
        sourceSet.setObjId(1_800_000 + itemsCount)

        for itemId in range(1, itemsCount + 1):
            sourceSet.append(_buildItem(itemId))

        sourceSet.write()
        sourceSet.close()
        sourceSet = None

        sqliteWriteSeconds = time.perf_counter() - sqliteWriteStartedAt

        sqliteOpenStartedAt = time.perf_counter()
        sqliteReadSet = _openSqliteSet(sqlitePath)
        sqliteOpenSeconds = time.perf_counter() - sqliteOpenStartedAt

        sqliteReadStartedAt = time.perf_counter()
        sqliteIteration = _iterateSet(sqliteReadSet)
        sqliteReadSeconds = time.perf_counter() - sqliteReadStartedAt

        _assertIterationResult(sqliteIteration, itemsCount)

        sqliteReadSet.close()
        sqliteReadSet = None

        sourceSet = _openSqliteSet(sqlitePath)
        sourceSet.setObjId(1_800_000 + itemsCount)

        postgresqlIntegrationDb.resetQueryStats()

        setMapper = ScipionSetPostgresqlMapper(postgresqlIntegrationDb)
        outputName = "outputItems"

        with observability.measure(
            operation="benchmark_set_store",
            db=postgresqlIntegrationDb,
            projectId=projectId,
            protocolId=protocolId,
            itemsCount=itemsCount,
            batchSize=1000,
        ) as postgresqlStoreMetric:
            storeResult = setMapper.storeSet(
                projectId=projectId,
                protocolDbId=protocolDbId,
                outputName=outputName,
                scipionSet=sourceSet,
                batchSize=1000,
            )

        assert storeResult["itemsCount"] == itemsCount
        assert storeResult["maxItemId"] == itemsCount

        sourceSet.close()
        sourceSet = None

        readerDb = _openPostgresqlIntegrationDb(postgresqlMigratedEnv)
        readerDb.resetQueryStats()

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

        outputInfo = {
            "setId": int(storeResult["setId"]),
            "rootObjectId": int(storeResult["rootObjectId"]),
            "runtimeObjectId": int(rootObject["scipionObjId"]),
            "projectId": projectId,
            "protocolDbId": protocolDbId,
            "outputName": outputName,
            "setClassName": storeResult["setClassName"],
            "itemClassName": storeResult["itemClassName"],
            "properties": storeResult["properties"],
        }

        runtimeSetFactory = PostgresqlRuntimeSetFactory()

        with observability.measure(
            operation="benchmark_runtime_set_hydration",
            db=readerDb,
            projectId=projectId,
            protocolId=protocolId,
            itemsCount=itemsCount,
        ) as hydrationMetric:
            runtimeSet = runtimeSetFactory.build(
                db=readerDb,
                parent=ParentProtocolStub(protocolId),
                outputName=outputName,
                outputInfo=outputInfo,
                classes=CLASSES,
                cache=False,
            )

        assert runtimeSet.getSize() == itemsCount

        with observability.measure(
            operation="benchmark_postgresql_full_iteration",
            db=readerDb,
            projectId=projectId,
            protocolId=protocolId,
            itemsCount=itemsCount,
        ) as postgresqlReadMetric:
            postgresqlIteration = _iterateSet(runtimeSet)

        _assertIterationResult(postgresqlIteration, itemsCount)

        if itemsCount == max(BENCHMARK_SIZES):
            explainPlanBeforeAnalyze = _explainRuntimeSetRead(
                readerDb,
                runtimeSet,
            )

            print()
            print(
                "SCIPIONAPI_POSTGRESQL_SET_EXPLAIN_BEFORE_ANALYZE=%s"
                % json.dumps(
                    {
                        "itemsCount": itemsCount,
                        "plan": explainPlanBeforeAnalyze,
                    },
                    sort_keys=True,
                    default=str,
                )
            )

            readerDb.execute(
                "ANALYZE scipion_set_items"
            )

            explainPlanAfterAnalyze = _explainRuntimeSetRead(
                readerDb,
                runtimeSet,
            )

            print()
            print(
                "SCIPIONAPI_POSTGRESQL_SET_EXPLAIN_AFTER_ANALYZE=%s"
                % json.dumps(
                    {
                        "itemsCount": itemsCount,
                        "plan": explainPlanAfterAnalyze,
                    },
                    sort_keys=True,
                    default=str,
                )
            )

            indexReview = _explainRuntimeSetIndexReview(
                readerDb,
                runtimeSet,
                itemsCount // 2,
            )

            print()
            print(
                "SCIPIONAPI_POSTGRESQL_SET_INDEX_REVIEW=%s"
                % json.dumps(
                    {
                        "itemsCount": itemsCount,
                        "plans": indexReview,
                    },
                    sort_keys=True,
                    default=str,
                )
            )

        with observability.measure(
            operation="benchmark_sqlite_materialization",
            db=readerDb,
            projectId=projectId,
            protocolId=protocolId,
            itemsCount=itemsCount,
        ) as materializationMetric:
            materializedPath = runtimeSet.getFileName()

        assert Path(materializedPath).is_file()

        with observability.measure(
            operation="benchmark_sqlite_materialization_cached",
            db=readerDb,
            projectId=projectId,
            protocolId=protocolId,
            itemsCount=itemsCount,
        ) as cachedMaterializationMetric:
            cachedMaterializedPath = runtimeSet.getFileName()

        assert cachedMaterializedPath == materializedPath

        materializer = runtimeSet._postgresqlSqliteMaterializer

        result = {
            "itemsCount": itemsCount,
            "batchSize": 1000,
            "sqlite": {
                "writeSeconds": sqliteWriteSeconds,
                "openSeconds": sqliteOpenSeconds,
                "readSeconds": sqliteReadSeconds,
                "readItemsPerSecond": _itemsPerSecond(itemsCount, sqliteReadSeconds),
            },
            "postgresql": {
                "storeSeconds": postgresqlStoreMetric["durationSeconds"],
                "storeQueryCount": postgresqlStoreMetric["queryCount"],
                "storeQuerySeconds": postgresqlStoreMetric["querySeconds"],
                "hydrationSeconds": hydrationMetric["durationSeconds"],
                "hydrationQueryCount": hydrationMetric["queryCount"],
                "hydrationQuerySeconds": hydrationMetric["querySeconds"],
                "readSeconds": postgresqlReadMetric["durationSeconds"],
                "readQueryCount": postgresqlReadMetric["queryCount"],
                "readQuerySeconds": postgresqlReadMetric["querySeconds"],
                "readItemsPerSecond": _itemsPerSecond(itemsCount, postgresqlReadMetric["durationSeconds"]),
                "materializationSeconds": materializationMetric["durationSeconds"],
                "materializationQueryCount": materializationMetric["queryCount"],
                "materializationQuerySeconds": materializationMetric["querySeconds"],
                "cachedMaterializationSeconds": cachedMaterializationMetric["durationSeconds"],
                "cachedMaterializationQueryCount": cachedMaterializationMetric["queryCount"],
                "cachedMaterializationQuerySeconds": cachedMaterializationMetric["querySeconds"],
            },
        }

        if sqliteReadSeconds > 0:
            result["postgresql"]["readVsSqliteRatio"] = postgresqlReadMetric["durationSeconds"] / sqliteReadSeconds

        print()
        print("SCIPIONAPI_POSTGRESQL_SET_BENCHMARK=%s" % json.dumps(result, sort_keys=True))

        releaseInfo = materializer.releaseRuntimeSet(runtimeSet)

        assert releaseInfo["removed"] is True
        assert not Path(materializedPath).exists()

        runtimeSet.close()
        runtimeSet = None

    finally:
        if runtimeSet is not None:
            if materializer is not None:
                try:
                    materializer.releaseRuntimeSet(runtimeSet)
                except Exception:
                    pass

            runtimeSet.close()

        if sourceSet is not None:
            sourceSet.close()

        if sqliteReadSet is not None:
            sqliteReadSet.close()

        if readerDb is not None:
            readerDb.close()

        if projectId is not None and userId is not None:
            writerMapper.deleteProject(projectId=projectId, ownerId=userId)

        if userId is not None:
            postgresqlIntegrationDb.execute("DELETE FROM users WHERE id = %s", (userId,))