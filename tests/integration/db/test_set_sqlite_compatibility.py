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
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

from pyworkflow.object import Float, Object, Set, String

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetFactory


class CompatibilityItemStub(Object):
    def __init__(self):
        super().__init__()
        self._score = Float()
        self._code = String()


class CompatibilitySetStub(Set):
    ITEM_TYPE = CompatibilityItemStub


class SourceCompatibilitySetStub(Set):
    ITEM_TYPE = CompatibilityItemStub

    def __init__(self, items):
        super().__init__()
        self._integrationItems = list(items)

    def getClassName(self):
        return "CompatibilitySetStub"

    def getObjDict(self, includeClass=False):
        if includeClass:
            return {
                "self": (
                    "CompatibilitySetStub",
                    None,
                ),
            }

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

        return max(
            int(item.getObjId())
            for item in self._integrationItems
        )

    def getFileName(self):
        return None


class ParentProtocolStub:
    def __init__(self, protocolId):
        self.protocolId = int(protocolId)

    def getObjId(self):
        return self.protocolId


CLASSES = {
    "CompatibilitySetStub": CompatibilitySetStub,
    "CompatibilityItemStub": CompatibilityItemStub,
}


def _buildItem(itemId, score, code):
    item = CompatibilityItemStub()

    if itemId is not None:
        item.setObjId(itemId)

    item._score.set(score)
    item._code.set(code)

    return item


def _openPostgresqlIntegrationDb(postgresqlMigratedEnv):
    return PostgresqlDb(
        dbName=postgresqlMigratedEnv["databaseName"],
        user=postgresqlMigratedEnv["databaseUser"],
        password=postgresqlMigratedEnv["databasePass"],
        host=postgresqlMigratedEnv["postgresHost"],
        port=postgresqlMigratedEnv["postgresPort"],
    )


def _loadRuntimeOutputInfo(setMapper, projectId, protocolDbId, outputName):
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


def _openCompatibilitySet(fileName):
    compatibilitySet = CompatibilitySetStub()

    compatibilitySet.setClassesDict(
        CLASSES
    )

    compatibilitySet._mapperPath.set(
        "%s, " % fileName
    )

    compatibilitySet.load()
    compatibilitySet.loadAllProperties()

    return compatibilitySet


def _duplicateSqliteItem(fileName, sourceId, targetId):
    connection = sqlite3.connect(
        str(fileName)
    )

    try:
        cursor = connection.cursor()

        tables = cursor.execute(
            """
            SELECT name
              FROM sqlite_master
             WHERE type = 'table'
               AND name LIKE '%Objects'
             ORDER BY
                   CASE
                       WHEN name = 'Objects'
                       THEN 0
                       ELSE 1
                   END,
                   name
            """
        ).fetchall()

        assert tables

        tableName = str(
            tables[0][0]
        )

        escapedTableName = tableName.replace(
            '"',
            '""',
        )

        columns = [
            str(row[1])
            for row in cursor.execute(
                'PRAGMA table_info("%s")'
                % escapedTableName
            ).fetchall()
        ]

        assert "id" in columns

        quotedColumns = [
            '"%s"' % column.replace('"', '""')
            for column in columns
        ]

        selectColumns = [
            (
                "%s AS \"id\"" % int(targetId)
                if column == "id"
                else '"%s"' % column.replace('"', '""')
            )
            for column in columns
        ]

        insertSql = (
            'INSERT INTO "%s" (%s) '
            'SELECT %s '
            'FROM "%s" '
            'WHERE "id" = ?'
            % (
                escapedTableName,
                ", ".join(quotedColumns),
                ", ".join(selectColumns),
                escapedTableName,
            )
        )

        cursor.execute(
            insertSql,
            (
                int(sourceId),
            ),
        )

        assert cursor.rowcount == 1

        connection.commit()

    finally:
        connection.close()


def test_PostgresqlGetFileNameMaterializesDisposableSqliteAndNeverBecomesAuthoritative(
        postgresqlIntegrationDb,
        postgresqlMigratedEnv,
        tmp_path,
):
    writerMapper = PostgresqlFlatMapper(
        postgresqlIntegrationDb
    )

    suffix = uuid4().hex

    userId = None
    projectId = None
    runtimeDb = None
    verifierDb = None
    runtimeSet = None
    materializer = None
    materializedPath = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-sqlite-compatibility-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="SQLite Compatibility",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL SQLite compatibility %s" % suffix,
            description="PostgreSQL runtime Set SQLite compatibility integration test.",
            status="active",
        )

        protocolId = 2

        protocolDbId = writerMapper.saveProtocol(
            {
                "info": {
                    "protocolId": protocolId,
                    "projectId": projectId,
                    "protocolClassName": "IntegrationCompatibilityProtocol",
                    "status": "running",
                },
                "values": {},
                "parentIds": [],
                "childIds": [],
            }
        )

        outputName = "outputCompatibilityItems"

        sourceSet = SourceCompatibilitySetStub(
            [
                _buildItem(
                    itemId=1,
                    score=0.25,
                    code="ITEM_01",
                ),
                _buildItem(
                    itemId=2,
                    score=0.75,
                    code="ITEM_02",
                ),
            ]
        )

        sourceSet.setObjId(
            1_400_001
        )

        setMapper = ScipionSetPostgresqlMapper(
            postgresqlIntegrationDb
        )

        storeResult = setMapper.storeSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
            scipionSet=sourceSet,
        )

        assert storeResult["itemsCount"] == 2
        assert storeResult["maxItemId"] == 2
        assert storeResult["runtimeObjectId"] == 1_400_001

        runtimeDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        runtimeSetMapper = ScipionSetPostgresqlMapper(
            runtimeDb
        )

        outputInfo = _loadRuntimeOutputInfo(
            setMapper=runtimeSetMapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
        )

        runtimeSetFactory = PostgresqlRuntimeSetFactory()

        runtimeSet = runtimeSetFactory.build(
            db=runtimeDb,
            parent=ParentProtocolStub(
                protocolId
            ),
            outputName=outputName,
            outputInfo=outputInfo,
            classes=CLASSES,
            cache=False,
        )

        assert runtimeSet.isPostgresqlRuntimeOutput()
        assert runtimeSet.getObjId() == 1_400_001
        assert runtimeSet.getSize() == 2

        projectDirectory = (
            tmp_path
            / "project"
        )

        projectDirectory.mkdir()

        materializedPath = runtimeSet.getFileName()

        assert materializedPath is not None
        assert Path(materializedPath).is_file()

        materializer = runtimeSet._postgresqlSqliteMaterializer

        managedRoot = os.path.realpath(
            materializer._getManagedRootDirectory()
        )

        workerDirectory = os.path.realpath(
            materializer._getCurrentWorkerDirectory()
        )

        materializedRealPath = os.path.realpath(
            materializedPath
        )

        assert os.path.commonpath(
            (
                managedRoot,
                materializedRealPath,
            )
        ) == managedRoot

        assert os.path.commonpath(
            (
                workerDirectory,
                materializedRealPath,
            )
        ) == workerDirectory

        assert os.path.commonpath(
            (
                os.path.realpath(projectDirectory),
                materializedRealPath,
            )
        ) != os.path.realpath(projectDirectory)

        firstCompatibilitySet = _openCompatibilitySet(
            materializedPath
        )

        try:
            sqliteItems = [
                {
                    "id": item.getObjId(),
                    "score": item._score.get(),
                    "code": item._code.get(),
                }
                for item in firstCompatibilitySet.iterItems(
                    orderBy="id",
                    direction="ASC",
                )
            ]

            assert sqliteItems == [
                {
                    "id": 1,
                    "score": 0.25,
                    "code": "ITEM_01",
                },
                {
                    "id": 2,
                    "score": 0.75,
                    "code": "ITEM_02",
                },
            ]

        finally:
            firstCompatibilitySet.close()

        _duplicateSqliteItem(
            fileName=materializedPath,
            sourceId=2,
            targetId=999,
        )

        contaminatedCompatibilitySet = _openCompatibilitySet(
            materializedPath
        )

        try:
            contaminatedIds = [
                item.getObjId()
                for item in contaminatedCompatibilitySet.iterItems(
                    orderBy="id",
                    direction="ASC",
                )
            ]

            assert contaminatedIds == [
                1,
                2,
                999,
            ]

        finally:
            contaminatedCompatibilitySet.close()

        postgresqlAfterSqliteMutation = runtimeSetMapper.getStoredSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
        )

        assert postgresqlAfterSqliteMutation is not None

        assert [
            item["scipionItemId"]
            for item in postgresqlAfterSqliteMutation["items"]
        ] == [
            1,
            2,
        ]

        assert all(
            item["scipionItemId"] != 999
            for item in postgresqlAfterSqliteMutation["items"]
        )

        assert runtimeSet.getSize() == 2

        runtimeSet.enableAppend()

        authoritativeItem = _buildItem(
            itemId=None,
            score=0.95,
            code="ITEM_03",
        )

        runtimeSet.append(
            authoritativeItem
        )

        assert authoritativeItem.getObjId() == 3
        assert runtimeSet.getSize() == 3

        refreshedMaterializedPath = runtimeSet.getFileName()

        assert refreshedMaterializedPath == materializedPath
        assert Path(refreshedMaterializedPath).is_file()

        refreshedCompatibilitySet = _openCompatibilitySet(
            refreshedMaterializedPath
        )

        try:
            refreshedItems = [
                {
                    "id": item.getObjId(),
                    "score": item._score.get(),
                    "code": item._code.get(),
                }
                for item in refreshedCompatibilitySet.iterItems(
                    orderBy="id",
                    direction="ASC",
                )
            ]

            assert refreshedItems == [
                {
                    "id": 1,
                    "score": 0.25,
                    "code": "ITEM_01",
                },
                {
                    "id": 2,
                    "score": 0.75,
                    "code": "ITEM_02",
                },
                {
                    "id": 3,
                    "score": 0.95,
                    "code": "ITEM_03",
                },
            ]

            assert all(
                item["id"] != 999
                for item in refreshedItems
            )

        finally:
            refreshedCompatibilitySet.close()

        releaseInfo = materializer.releaseRuntimeSet(
            runtimeSet
        )

        assert releaseInfo["removed"] is True
        assert not Path(materializedPath).exists()

        runtimeSet.close()
        runtimeSet = None

        runtimeDb.close()
        runtimeDb = None

        verifierDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        verifierSetMapper = ScipionSetPostgresqlMapper(
            verifierDb
        )

        verifiedStoredSet = verifierSetMapper.getStoredSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
        )

        assert verifiedStoredSet is not None

        assert [
            item["scipionItemId"]
            for item in verifiedStoredSet["items"]
        ] == [
            1,
            2,
            3,
        ]

        assert verifiedStoredSet["items"][2]["values"]["_score"] == 0.95
        assert verifiedStoredSet["items"][2]["values"]["_code"] == "ITEM_03"

        assert all(
            item["scipionItemId"] != 999
            for item in verifiedStoredSet["items"]
        )

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

        elif materializedPath is not None:
            for suffix in (
                    "",
                    "-journal",
                    "-wal",
                    "-shm",
            ):
                candidatePath = "%s%s" % (
                    materializedPath,
                    suffix,
                )

                if os.path.isfile(candidatePath):
                    os.remove(candidatePath)

        if verifierDb is not None:
            verifierDb.close()

        if runtimeDb is not None:
            runtimeDb.close()

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