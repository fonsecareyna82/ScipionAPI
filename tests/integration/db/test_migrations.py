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
import shutil
import subprocess

from app.backend.mapper.postgresql import PostgresqlDb


REQUIRED_POSTGRESQL_RUNTIME_TABLES = {
    "alembic_version",
    "projects",
    "protocols",
    "protocol_steps",
    "project_object_id_counters",
    "scipion_object_types",
    "scipion_object_type_properties",
    "scipion_objects",
    "scipion_relations",
    "scipion_sets",
    "scipion_set_columns",
    "scipion_set_items",
    "scipion_set_properties",
    "scipion_set_tables",
    "scipion_set_table_columns",
    "scipion_set_table_items",
}


def test_PostgresqlMigrationsCreateRuntimeSchema(
        postgresqlIntegrationEnv,
):
    processEnv = os.environ.copy()

    processEnv.update({
        "DATABASE_URL": postgresqlIntegrationEnv["databaseUrl"],
        "DATABASE_NAME": postgresqlIntegrationEnv["databaseName"],
        "DATABASE_USER": postgresqlIntegrationEnv["databaseUser"],
        "DATABASE_PASS": postgresqlIntegrationEnv["databasePass"],
        "POSTGRES_HOST": postgresqlIntegrationEnv["postgresHost"],
        "POSTGRES_PORT": str(postgresqlIntegrationEnv["postgresPort"]),
    })

    alembicExecutable = shutil.which("alembic")

    assert alembicExecutable is not None, (
        "Alembic executable was not found in the current test environment."
    )

    migrationResult = subprocess.run(
        [
            alembicExecutable,
            "upgrade",
            "head",
        ],
        cwd=postgresqlIntegrationEnv["rootDir"],
        env=processEnv,
        capture_output=True,
        text=True,
    )

    assert migrationResult.returncode == 0, (
        "Alembic migration failed.\n"
        "stdout:\n%s\n"
        "stderr:\n%s"
        % (
            migrationResult.stdout,
            migrationResult.stderr,
        )
    )

    db = PostgresqlDb(
        dbName=postgresqlIntegrationEnv["databaseName"],
        user=postgresqlIntegrationEnv["databaseUser"],
        password=postgresqlIntegrationEnv["databasePass"],
        host=postgresqlIntegrationEnv["postgresHost"],
        port=postgresqlIntegrationEnv["postgresPort"],
    )

    try:
        rows = db.fetchAll(
            """
            SELECT table_name AS "tableName"
              FROM information_schema.tables
             WHERE table_schema = 'public'
            """
        )

    finally:
        db.close()

    existingTables = {
        str(row["tableName"])
        for row in rows
    }

    missingTables = sorted(
        REQUIRED_POSTGRESQL_RUNTIME_TABLES
        - existingTables
    )

    assert not missingTables, (
        "PostgreSQL runtime schema is incomplete. "
        "Missing tables: %s"
        % ", ".join(missingTables)
    )