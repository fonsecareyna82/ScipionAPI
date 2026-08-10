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
        postgresqlMigratedEnv,
):
    db = PostgresqlDb(
        dbName=postgresqlMigratedEnv["databaseName"],
        user=postgresqlMigratedEnv["databaseUser"],
        password=postgresqlMigratedEnv["databasePass"],
        host=postgresqlMigratedEnv["postgresHost"],
        port=postgresqlMigratedEnv["postgresPort"],
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