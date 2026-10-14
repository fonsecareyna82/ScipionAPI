"""Child-table lookup index and redundant item index cleanup are reversible."""
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from tests.integration.db.test_nested_item_values_index import _command

CHILD_LOOKUP_INDEX = "idx_scipion_set_tables_set_parent"
REDUNDANT_INDEXES = {
    "ix_scipion_set_items_id": "scipion_set_items",
    "idx_scipion_set_items_set": "scipion_set_items",
    "idx_scipion_set_table_items_table": "scipion_set_table_items",
}
KEPT_INDEXES = {
    "ux_scipion_set_items_set_item": "scipion_set_items",
    "ux_scipion_set_table_items_table_item": "scipion_set_table_items",
    "idx_scipion_set_tables_set": "scipion_set_tables",
}


@pytest.fixture
def indexLab(postgresqlMigratedEnv):
    env = postgresqlMigratedEnv
    engine = create_engine(URL.create(
        "postgresql+psycopg2", username=env["databaseUser"],
        password=env["databasePass"], host=env["postgresHost"],
        port=int(env["postgresPort"]), database=env["databaseName"],
    ))
    schema = "set_index_cleanup_test_" + uuid4().hex
    try:
        with engine.connect() as connection:
            try:
                connection.exec_driver_sql('CREATE SCHEMA "' + schema + '"')
                # Exclude public so nothing here can touch application indexes.
                connection.exec_driver_sql('SET search_path TO "' + schema + '"')
                connection.exec_driver_sql('''CREATE TABLE scipion_set_items (
                    id serial PRIMARY KEY, "setId" integer NOT NULL, "scipionItemId" integer NOT NULL,
                    "values" jsonb NOT NULL,
                    CONSTRAINT ux_scipion_set_items_set_item UNIQUE ("setId", "scipionItemId"))''')
                connection.exec_driver_sql('CREATE INDEX ix_scipion_set_items_id ON scipion_set_items (id)')
                connection.exec_driver_sql('CREATE INDEX idx_scipion_set_items_set ON scipion_set_items ("setId")')
                connection.exec_driver_sql('''CREATE TABLE scipion_set_tables (
                    id serial PRIMARY KEY, "setId" integer NOT NULL, "parentItemId" integer,
                    "tableKind" text NOT NULL)''')
                connection.exec_driver_sql('CREATE INDEX idx_scipion_set_tables_set ON scipion_set_tables ("setId")')
                connection.exec_driver_sql('''CREATE TABLE scipion_set_table_items (
                    id serial PRIMARY KEY, "tableId" integer NOT NULL, "scipionItemId" integer NOT NULL,
                    "values" jsonb NOT NULL,
                    CONSTRAINT ux_scipion_set_table_items_table_item UNIQUE ("tableId", "scipionItemId"))''')
                connection.exec_driver_sql(
                    'CREATE INDEX idx_scipion_set_table_items_table ON scipion_set_table_items ("tableId")')
                connection.exec_driver_sql('''INSERT INTO scipion_set_items ("setId", "scipionItemId", "values")
                    VALUES (1, 1, '{"_a": 1}'), (1, 2, '{"_a": 2}'), (2, 1, '{}')''')
                connection.exec_driver_sql('''INSERT INTO scipion_set_tables ("setId", "parentItemId", "tableKind")
                    SELECT 1, NULL, 'root' UNION ALL
                    SELECT 1, g, 'child' FROM generate_series(1, 300) g''')
                connection.exec_driver_sql('''INSERT INTO scipion_set_table_items ("tableId", "scipionItemId", "values")
                    VALUES (2, 1, '{"_b": "é"}'), (3, 1, '{}')''')
                connection.commit()
                _command(env, schema, "stamp", "b75a4e291c0f")
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


def _rows(connection):
    return [connection.exec_driver_sql('SELECT * FROM %s ORDER BY id' % table).all()
            for table in ("scipion_set_items", "scipion_set_tables", "scipion_set_table_items")]


def test_UpgradeIndexesChildLookupDropsRedundantIndexesAndReverses(indexLab):
    connection, schema, env = indexLab
    before = _rows(connection)
    connection.commit()
    _command(env, schema, "upgrade", "6b00be24a501")
    indexes = _indexes(connection)
    assert indexes[CHILD_LOOKUP_INDEX]["valid"]
    assert indexes[CHILD_LOOKUP_INDEX]["table"] == "scipion_set_tables"
    assert not set(REDUNDANT_INDEXES) & set(indexes)
    assert all(indexes[name]["valid"] and indexes[name]["table"] == table
               for name, table in KEPT_INDEXES.items())
    assert _rows(connection) == before
    connection.exec_driver_sql("ANALYZE scipion_set_tables")
    connection.exec_driver_sql("SET enable_seqscan = off")
    plan = connection.exec_driver_sql('''EXPLAIN SELECT id FROM scipion_set_tables
        WHERE "setId" = 1 AND "parentItemId" = 250 AND "tableKind" = 'child' ''').scalars().all()
    assert any(CHILD_LOOKUP_INDEX in line for line in plan)
    connection.commit()
    _command(env, schema, "downgrade", "b75a4e291c0f")
    indexes = _indexes(connection)
    assert CHILD_LOOKUP_INDEX not in indexes
    assert all(indexes[name]["valid"] and indexes[name]["table"] == table
               for name, table in dict(REDUNDANT_INDEXES, **KEPT_INDEXES).items())
    assert _rows(connection) == before


def test_UpgradeRebuildsAnInvalidChildLookupIndexLeftByAFailedRun(indexLab):
    connection, schema, env = indexLab
    connection.execution_options(isolation_level="AUTOCOMMIT")
    try:
        # A unique build over duplicate keys fails and leaves an invalid index.
        with pytest.raises(Exception):
            connection.exec_driver_sql('CREATE UNIQUE INDEX CONCURRENTLY ' + CHILD_LOOKUP_INDEX
                                       + ' ON scipion_set_tables ("setId")')
    finally:
        connection.rollback()
        connection.execution_options(isolation_level="READ COMMITTED")
    assert not _indexes(connection)[CHILD_LOOKUP_INDEX]["valid"]
    connection.commit()
    _command(env, schema, "upgrade", "6b00be24a501")
    assert _indexes(connection)[CHILD_LOOKUP_INDEX]["valid"]
