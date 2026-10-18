"""The foreign keys that cascading deletes look up get their own indexes, reversibly."""
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from tests.integration.db.test_nested_item_values_index import _command

INDEXES = {
    "idx_scipion_objects_protocol_db_id": "scipion_objects",
    "idx_scipion_sets_protocol_db_id": "scipion_sets",
    "idx_scipion_sets_object_id": "scipion_sets",
    "idx_protocol_steps_protocol_db_id": "protocol_steps",
}


@pytest.fixture
def indexLab(postgresqlMigratedEnv):
    env = postgresqlMigratedEnv
    engine = create_engine(URL.create(
        "postgresql+psycopg2", username=env["databaseUser"],
        password=env["databasePass"], host=env["postgresHost"],
        port=int(env["postgresPort"]), database=env["databaseName"],
    ))
    schema = "cascade_index_test_" + uuid4().hex
    try:
        with engine.connect() as connection:
            try:
                connection.exec_driver_sql('CREATE SCHEMA "' + schema + '"')
                # Exclude public so nothing here can touch application indexes.
                connection.exec_driver_sql('SET search_path TO "' + schema + '"')
                connection.exec_driver_sql('''CREATE TABLE scipion_objects (
                    id serial PRIMARY KEY, "projectId" integer NOT NULL, "protocolDbId" integer NOT NULL)''')
                connection.exec_driver_sql('''CREATE TABLE scipion_sets (
                    id serial PRIMARY KEY, "projectId" integer NOT NULL, "protocolDbId" integer NOT NULL,
                    "objectId" integer)''')
                connection.exec_driver_sql('''CREATE TABLE protocol_steps (
                    id serial PRIMARY KEY, "projectId" integer NOT NULL, "protocolDbId" integer NOT NULL)''')
                connection.commit()
                _command(env, schema, "stamp", "6b00be24a501")
                yield connection, schema, env
            finally:
                connection.rollback()
                connection.exec_driver_sql('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
                connection.commit()
    finally:
        engine.dispose()


def _indexes(connection):
    return {row["name"]: row for row in connection.exec_driver_sql('''
        SELECT c.relname AS name, t.relname AS "table", i.indisvalid AS valid
          FROM pg_index i
          JOIN pg_class c ON c.oid = i.indexrelid
          JOIN pg_class t ON t.oid = i.indrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = current_schema()''').mappings()}


def test_UpgradeIndexesTheCascadeLookupsAndReverses(indexLab):
    connection, schema, env = indexLab
    _command(env, schema, "upgrade", "7a1c2e9d4f30")
    indexes = _indexes(connection)
    assert all(indexes[name]["valid"] and indexes[name]["table"] == table for name, table in INDEXES.items())
    connection.commit()
    _command(env, schema, "downgrade", "6b00be24a501")
    assert not set(INDEXES) & set(_indexes(connection))
