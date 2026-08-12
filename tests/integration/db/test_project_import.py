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

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper
from app.backend.runtime.project_import_service import RuntimeProjectImportService
from app.backend.runtime.project_lifecycle_service import RuntimeProjectLifecycleService


def _openPostgresqlIntegrationDb(postgresqlMigratedEnv):
    return PostgresqlDb(
        dbName=postgresqlMigratedEnv["databaseName"],
        user=postgresqlMigratedEnv["databaseUser"],
        password=postgresqlMigratedEnv["databasePass"],
        host=postgresqlMigratedEnv["postgresHost"],
        port=postgresqlMigratedEnv["postgresPort"],
    )


def _createLegacySqlite(fileName):
    fileName = Path(fileName)
    fileName.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        str(fileName)
    )

    try:
        connection.execute(
            """
            CREATE TABLE legacy_marker (
                id INTEGER PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        connection.execute(
            """
            INSERT INTO legacy_marker (
                id,
                value
            )
            VALUES (?, ?)
            """,
            (
                1,
                "LEGACY",
            ),
        )

        connection.commit()

    finally:
        connection.close()


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


def test_MaterializeProjectRebasesExternalRelativeSymlink(tmp_path):
    sourcePath = tmp_path / "source-project"
    targetPath = tmp_path / "projects" / "imported-project"

    sourceLink = (
        sourcePath
        / "Runs"
        / "000174_ProtImportTs"
        / "extra"
        / "tilt10.mrc"
    )

    externalFile = (
        tmp_path
        / "external-data"
        / "tilt10.mrc"
    )

    sourceLink.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    externalFile.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    externalFile.write_bytes(
        b"EXTERNAL_TILT_DATA"
    )

    relativeTarget = os.path.relpath(
        externalFile,
        start=sourceLink.parent,
    )

    sourceLink.symlink_to(
        relativeTarget
    )

    assert sourceLink.is_symlink()
    assert sourceLink.exists()
    assert sourceLink.resolve() == externalFile.resolve()

    RuntimeProjectImportService._materializeProject(
        sourcePath=sourcePath,
        targetPath=targetPath,
    )

    importedLink = (
        targetPath
        / sourceLink.relative_to(sourcePath)
    )

    assert importedLink.is_symlink()
    assert importedLink.exists()

    assert importedLink.resolve() == externalFile.resolve()

    assert importedLink.read_bytes() == (
        b"EXTERNAL_TILT_DATA"
    )


def test_MaterializeProjectRebasesInternalRelativeSymlink(tmp_path):
    sourcePath = tmp_path / "source-project"
    targetPath = tmp_path / "projects" / "imported-project"

    sourceFile = (
        sourcePath
        / "Uploads"
        / "data"
        / "tilt10.mrc"
    )

    sourceLink = (
        sourcePath
        / "Runs"
        / "000174_ProtImportTs"
        / "extra"
        / "tilt10.mrc"
    )

    sourceFile.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    sourceLink.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    sourceFile.write_bytes(
        b"INTERNAL_TILT_DATA"
    )

    relativeTarget = os.path.relpath(
        sourceFile,
        start=sourceLink.parent,
    )

    sourceLink.symlink_to(
        relativeTarget
    )

    assert sourceLink.is_symlink()
    assert sourceLink.exists()
    assert sourceLink.resolve() == sourceFile.resolve()

    RuntimeProjectImportService._materializeProject(
        sourcePath=sourcePath,
        targetPath=targetPath,
    )

    importedLink = (
        targetPath
        / sourceLink.relative_to(sourcePath)
    )

    importedFile = (
        targetPath
        / sourceFile.relative_to(sourcePath)
    )

    assert importedFile.is_file()

    assert importedLink.is_symlink()
    assert importedLink.exists()

    assert importedLink.resolve() == importedFile.resolve()

    assert importedLink.resolve() != sourceFile.resolve()

    assert importedLink.read_bytes() == (
        b"INTERNAL_TILT_DATA"
    )


def test_LegacyProjectImportCreatesPostgresqlRuntimeAndRemovesOnlyManagedSqlite(
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
    observerDb = None

    projectsPath = (
        tmp_path
        / "projects"
    )

    projectsPath.mkdir()

    sourcePath = tmp_path / f"legacy-source-{suffix}"

    sourcePath.mkdir()

    targetPath = projectsPath / f"imported-{suffix}"

    sourceProjectSqlite = (
        sourcePath
        / "project.sqlite"
    )

    sourceSettingsSqlite = (
        sourcePath
        / "settings.sqlite"
    )

    sourceRunDb = (
        sourcePath
        / "Runs"
        / "000041_LegacyParent"
        / "run.db"
    )

    sourcePayload = (
        sourcePath
        / "Runs"
        / "000041_LegacyParent"
        / "extra"
        / "payload.txt"
    )

    _createLegacySqlite(
        sourceProjectSqlite
    )

    _createLegacySqlite(
        sourceSettingsSqlite
    )

    _createLegacySqlite(
        sourceRunDb
    )

    sourcePayload.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    sourcePayload.write_text(
        "LEGACY_PAYLOAD",
        encoding="utf-8",
    )

    try:
        userId = writerMapper.insertUser(
            email="postgresql-import-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Import",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        lifecycleService = RuntimeProjectLifecycleService()

        migrationCalls = []

        def migrateProject(projectIdValue, projectPathValue):
            projectIdValue = int(
                projectIdValue
            )

            projectPath = Path(
                projectPathValue
            )

            migrationCalls.append(
                {
                    "projectId": projectIdValue,
                    "projectPath": str(
                        projectPath
                    ),
                }
            )

            assert projectPath == targetPath
            assert projectPath.is_dir()

            assert (
                projectPath
                / "project.sqlite"
            ).is_file()

            assert (
                projectPath
                / "settings.sqlite"
            ).is_file()

            assert (
                projectPath
                / "Runs"
                / "000041_LegacyParent"
                / "run.db"
            ).is_file()

            assert (
                projectPath
                / "Runs"
                / "000041_LegacyParent"
                / "extra"
                / "payload.txt"
            ).read_text(
                encoding="utf-8"
            ) == "LEGACY_PAYLOAD"

            parentProtocolId = 41
            childProtocolId = 84

            parentProtocolDbId = writerMapper.saveProtocol(
                {
                    "info": {
                        "protocolId": parentProtocolId,
                        "projectId": projectIdValue,
                        "protocolClassName": "LegacyParentProtocol",
                        "status": "finished",
                    },
                    "values": {
                        "legacyValue": "PARENT",
                    },
                    "parentIds": [],
                    "childIds": [
                        childProtocolId,
                    ],
                }
            )

            childProtocolDbId = writerMapper.saveProtocol(
                {
                    "info": {
                        "protocolId": childProtocolId,
                        "projectId": projectIdValue,
                        "protocolClassName": "LegacyChildProtocol",
                        "status": "finished",
                    },
                    "values": {
                        "legacyValue": "CHILD",
                    },
                    "parentIds": [
                        parentProtocolId,
                    ],
                    "childIds": [],
                }
            )

            _storeProtocolStep(
                mapper=writerMapper,
                projectId=projectIdValue,
                protocolDbId=parentProtocolDbId,
                protocolId=parentProtocolId,
                name="legacyParentStep",
            )

            _storeProtocolStep(
                mapper=writerMapper,
                projectId=projectIdValue,
                protocolDbId=childProtocolDbId,
                protocolId=childProtocolId,
                name="legacyChildStep",
            )

            writerMapper.replaceProjectProtocolDependencies(
                projectId=projectIdValue,
                edges=[
                    (
                        parentProtocolDbId,
                        childProtocolDbId,
                    ),
                ],
            )

            nextProtocolIdFloor = (
                writerMapper
                .ensureProjectProtocolIdFloor(
                    projectId=projectIdValue,
                    nextProtocolId=(
                        childProtocolId
                        + 1
                    ),
                )
            )

            projectDatabaseCleanup = (
                lifecycleService
                .removeLegacyProjectDatabase(
                    projectPath=projectPath,
                    projectDbPath=(
                        projectPath
                        / "project.sqlite"
                    ),
                )
            )

            runDatabaseCleanup = (
                lifecycleService
                .removeLegacyRunDatabases(
                    projectPath=projectPath,
                )
            )

            return {
                "protocols": 2,
                "dependencies": 1,
                "parentProtocolId": parentProtocolId,
                "childProtocolId": childProtocolId,
                "parentProtocolDbId": parentProtocolDbId,
                "childProtocolDbId": childProtocolDbId,
                "nextProtocolIdFloor": nextProtocolIdFloor,
                "projectDatabaseCleanup": projectDatabaseCleanup,
                "runDatabaseCleanup": runDatabaseCleanup,
                "postgresqlOnly": True,
            }

        importService = RuntimeProjectImportService()

        importInfo = importService.importProject(
            mapper=writerMapper,
            ownerId=userId,
            sourcePath=sourcePath,
            targetPath=targetPath,
            projectsPath=projectsPath,
            description="Legacy PostgreSQL integration import.",
            statusValue="active",
            migrateProjectCallback=migrateProject,
        )

        projectId = int(
            importInfo["projectId"]
        )

        assert importInfo["materialization"] == "managed-copy"
        assert importInfo["projectPath"] == str(
            targetPath
        )

        assert migrationCalls == [
            {
                "projectId": projectId,
                "projectPath": str(
                    targetPath
                ),
            },
        ]

        migrationInfo = importInfo[
            "migration"
        ]

        assert migrationInfo["protocols"] == 2
        assert migrationInfo["dependencies"] == 1
        assert migrationInfo["postgresqlOnly"] is True

        assert migrationInfo[
            "projectDatabaseCleanup"
        ]["projectSqliteRemoved"] is True

        assert migrationInfo[
            "projectDatabaseCleanup"
        ]["settingsSqliteRemoved"] is True

        assert migrationInfo[
            "runDatabaseCleanup"
        ]["legacyRunDatabasesRemoved"] is True

        assert migrationInfo[
            "runDatabaseCleanup"
        ]["remaining"] == []

        # --------------------------------------------------------------
        # The original legacy project is immutable.
        # Import works on a managed copy.
        # --------------------------------------------------------------

        assert sourceProjectSqlite.is_file()
        assert sourceSettingsSqlite.is_file()
        assert sourceRunDb.is_file()

        assert sourcePayload.read_text(
            encoding="utf-8"
        ) == "LEGACY_PAYLOAD"

        # --------------------------------------------------------------
        # The imported project no longer contains authoritative
        # project-level or protocol-level SQLite databases.
        # --------------------------------------------------------------

        assert targetPath.is_dir()

        assert not (
            targetPath
            / "project.sqlite"
        ).exists()

        assert not (
            targetPath
            / "settings.sqlite"
        ).exists()

        assert not (
            targetPath
            / "Runs"
            / "000041_LegacyParent"
            / "run.db"
        ).exists()

        # Ordinary project data survives migration.
        importedPayload = (
            targetPath
            / "Runs"
            / "000041_LegacyParent"
            / "extra"
            / "payload.txt"
        )

        assert importedPayload.is_file()

        assert importedPayload.read_text(
            encoding="utf-8"
        ) == "LEGACY_PAYLOAD"

        # --------------------------------------------------------------
        # Close the writer-side view and prove the migrated runtime
        # survives through a completely independent PostgreSQL
        # connection.
        # --------------------------------------------------------------

        observerDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        observerMapper = PostgresqlFlatMapper(
            observerDb
        )

        projectRow = observerDb.fetchOne(
            """
            SELECT id,
                   "ownerId",
                   name,
                   description,
                   status
              FROM projects
             WHERE id = %s
            """,
            (
                projectId,
            ),
        )

        assert projectRow is not None
        assert int(projectRow["id"]) == projectId
        assert int(projectRow["ownerId"]) == userId
        assert projectRow["name"] == str(targetPath)
        assert projectRow["description"] == "Legacy PostgreSQL integration import."
        assert projectRow["status"] == "active"

        parentProtocol = (
            observerMapper
            .getProjectProtocolByProtocolId(
                projectId=projectId,
                protocolId=41,
            )
        )

        childProtocol = (
            observerMapper
            .getProjectProtocolByProtocolId(
                projectId=projectId,
                protocolId=84,
            )
        )

        assert parentProtocol is not None
        assert childProtocol is not None

        assert parentProtocol["protocolId"] == "41"
        assert parentProtocol["protocolClassName"] == "LegacyParentProtocol"
        assert parentProtocol["status"] == "finished"
        assert parentProtocol["params"]["legacyValue"] == "PARENT"
        assert parentProtocol["parentIds"] == []
        assert parentProtocol["childIds"] == [
            84,
        ]

        assert childProtocol["protocolId"] == "84"
        assert childProtocol["protocolClassName"] == "LegacyChildProtocol"
        assert childProtocol["status"] == "finished"
        assert childProtocol["params"]["legacyValue"] == "CHILD"
        assert childProtocol["parentIds"] == [
            41,
        ]
        assert childProtocol["childIds"] == []

        parentSteps = (
            observerMapper
            .listProtocolSteps(
                projectId=projectId,
                protocolId=41,
            )
        )

        childSteps = (
            observerMapper
            .listProtocolSteps(
                projectId=projectId,
                protocolId=84,
            )
        )

        assert len(parentSteps) == 1
        assert parentSteps[0]["name"] == "legacyParentStep"

        assert len(childSteps) == 1
        assert childSteps[0]["name"] == "legacyChildStep"

        dependencies = (
            observerMapper
            .listProjectProtocolDependencies(
                projectId=projectId
            )
        )

        assert len(dependencies) == 1

        assert dependencies[0][
            "parentProtocolDbId"
        ] == int(
            parentProtocol["id"]
        )

        assert dependencies[0][
            "childProtocolDbId"
        ] == int(
            childProtocol["id"]
        )

        # --------------------------------------------------------------
        # Imported legacy protocol ids must not collide with future
        # PostgreSQL-owned protocol ids.
        # --------------------------------------------------------------

        nextProtocolId = (
            observerMapper
            .allocateProjectProtocolId(
                projectId
            )
        )

        assert nextProtocolId == 85

    finally:
        if observerDb is not None:
            observerDb.close()

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

        if targetPath.exists():
            import shutil

            shutil.rmtree(
                targetPath
            )