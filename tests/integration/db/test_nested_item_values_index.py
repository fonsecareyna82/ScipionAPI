"""Exercise Set JSON-index migrations and logical legacy reads on PostgreSQL."""
import os
import shutil
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.exc import DataError

from app.backend.mapper.postgresql_set_runtime_mapper import PostgresqlSetRuntimeMapper
from app.backend.mapper.postgresql import PostgresqlDb

FULL_INDEX = "idx_scipion_set_table_items_values_gin"
NESTED_INDEX = "idx_scipion_set_table_items_nested_values_gin"
ROOT_INDEX = "idx_scipion_set_items_values_gin"


def _command(env, schema, *arguments):
    processEnv = os.environ.copy()
    separator = "&" if "?" in env["databaseUrl"] else "?"
    processEnv["DATABASE_URL"] = (
        env["databaseUrl"] + separator + "options=-csearch_path=" + schema
    )
    result = subprocess.run(
        [shutil.which("alembic"), *arguments], cwd=env["rootDir"],
        env=processEnv, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def logicalIndexLab(postgresqlMigratedEnv):
    env = postgresqlMigratedEnv
    engine = create_engine(URL.create(
        "postgresql+psycopg2", username=env["databaseUser"],
        password=env["databasePass"], host=env["postgresHost"],
        port=int(env["postgresPort"]), database=env["databaseName"],
    ))
    schema = "nested_index_test_" + uuid4().hex
    try:
        with engine.connect() as connection:
            try:
                connection.exec_driver_sql('CREATE SCHEMA "' + schema + '"')
                # Exclude public: migration retries must never drop an application
                # index if its namesake does not exist in this private test schema.
                connection.exec_driver_sql('SET search_path TO "' + schema + '"')
                connection.exec_driver_sql('''CREATE TABLE scipion_set_table_items (
                    "tableId" integer NOT NULL, "scipionItemId" integer NOT NULL,
                    "parentItemId" integer, "values" jsonb NOT NULL,
                    UNIQUE ("tableId", "scipionItemId"))''')
                connection.exec_driver_sql('''INSERT INTO scipion_set_table_items VALUES
                    (11,1,NULL,'{"_score":1,"_flag":false,"_word":"é","_null":null}'),
                    (11,2,NULL,'{"_score":2.5}'),
                    (12,1,42,'{"_score":1,"_mixed":1,"_complex":[1],"_flag":false,"_word":"é"}'),
                    (12,2,NULL,'{"_score":2.5,"_mixed":"text","_complex":{"a":1},"_null":null}'),
                    (13,1,43,'{"_score":"unrelated"}')''')
                connection.exec_driver_sql('''CREATE INDEX idx_scipion_set_table_items_values_gin
                    ON scipion_set_table_items USING gin ("values")''')
                connection.commit()
                _command(env, schema, "stamp", "0267ba193cae")
                yield connection, schema, env
            finally:
                connection.rollback()
                connection.exec_driver_sql('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
                connection.commit()
    finally:
        engine.dispose()


def _rows(connection):
    return connection.exec_driver_sql('''SELECT * FROM scipion_set_table_items
        ORDER BY "tableId", "scipionItemId"''').all()


def _indexes(connection):
    return {row["name"]: row for row in connection.exec_driver_sql('''
        SELECT c.relname AS name, i.indisvalid AS valid,
               pg_get_expr(i.indpred, i.indrelid) AS predicate
        FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
        WHERE i.indrelid='scipion_set_table_items'::regclass
    ''').mappings()}


def _migrate(lab, direction):
    connection, schema, env = lab
    connection.commit()
    _command(env, schema, direction, "41c8d93e7a62" if direction == "upgrade" else "0267ba193cae")


def test_ConcurrentNestedIndexMigrationPreservesRowsAndCanBeReversed(logicalIndexLab):
    connection, _, _ = logicalIndexLab
    before = _rows(connection)
    _migrate(logicalIndexLab, "upgrade")
    indexes = _indexes(connection)
    assert FULL_INDEX not in indexes
    assert indexes[NESTED_INDEX]["valid"]
    assert indexes[NESTED_INDEX]["predicate"] == '("parentItemId" IS NOT NULL)'
    assert _rows(connection) == before
    _migrate(logicalIndexLab, "downgrade")
    indexes = _indexes(connection)
    assert NESTED_INDEX not in indexes
    assert indexes[FULL_INDEX]["valid"]
    assert indexes[FULL_INDEX]["predicate"] is None
    assert _rows(connection) == before


def test_ConcurrentMigrationRebuildsInvalidIndexLeftByFailedBuild(logicalIndexLab):
    connection, _, _ = logicalIndexLab
    before = _rows(connection)
    connection.commit()
    connection.execution_options(isolation_level="AUTOCOMMIT")
    try:
        with pytest.raises(DataError):
            connection.exec_driver_sql('CREATE INDEX CONCURRENTLY ' + NESTED_INDEX
                + ' ON scipion_set_table_items ((("values" ->> \'_word\')::integer))')
    finally:
        connection.rollback()
        connection.execution_options(isolation_level="READ COMMITTED")
    indexes = _indexes(connection)
    assert not indexes[NESTED_INDEX]["valid"]
    assert indexes[FULL_INDEX]["valid"]
    _migrate(logicalIndexLab, "upgrade")
    assert _indexes(connection)[NESTED_INDEX]["valid"]
    assert _rows(connection) == before


def test_LogicalDynamicFieldsIncludeNullParentsAndKeepTypeValidation(logicalIndexLab):
    connection, _, _ = logicalIndexLab
    _migrate(logicalIndexLab, "upgrade")
    before = _rows(connection)

    class Reader:
        def fetchAll(self, query, params):
            self.query, self.params = query, params
            return connection.exec_driver_sql(query, params).mappings().all()

    reader = Reader()
    def resolve(tableId, field):
        scope = SimpleNamespace(
            db=reader, _scopeId=tableId, _scopeColumn="tableId",
            _itemsTable=PostgresqlSetRuntimeMapper.LOGICAL_ITEMS_TABLE,
            LOGICAL_ITEMS_TABLE=PostgresqlSetRuntimeMapper.LOGICAL_ITEMS_TABLE,
            _dynamicFieldValueTypes={},
        )
        return PostgresqlSetRuntimeMapper._resolveDynamicFieldValueType(scope, field)

    for tableId in (11, 12):
        assert resolve(tableId, "_score") == "float"
        assert resolve(tableId, "_flag") == "boolean"
        assert resolve(tableId, "_word") == "text"
        assert resolve(tableId, "_missing") is None
        assert resolve(tableId, "_null") is None
    assert resolve(13, "_score") == "text"
    with pytest.raises(ValueError, match="Inconsistent"):
        resolve(12, "_mixed")
    with pytest.raises(ValueError, match="not scalar"):
        resolve(12, "_complex")
    assert '"parentItemId" IS NOT NULL' in reader.query
    assert '"parentItemId" IS NULL' in reader.query
    assert "UNION ALL" in reader.query
    assert _rows(connection) == before


def test_NestedDynamicLookupCanUsePartialGinWithoutLosingNullParentRows(logicalIndexLab):
    connection, _, _ = logicalIndexLab
    _migrate(logicalIndexLab, "upgrade")
    connection.exec_driver_sql('''INSERT INTO scipion_set_table_items
        SELECT 12, n, 42, '{"_ordinary":1}'::jsonb FROM generate_series(100,2099) n''')
    connection.exec_driver_sql("ANALYZE scipion_set_table_items")
    connection.exec_driver_sql("SET enable_seqscan=off")
    connection.exec_driver_sql("SET jit=off")

    class Reader:
        def fetchAll(self, query, params):
            self.query, self.params = query, params
            return connection.exec_driver_sql(query, params).mappings().all()

    reader = Reader()
    scope = SimpleNamespace(
        db=reader, _scopeId=12, _scopeColumn="tableId",
        _itemsTable=PostgresqlSetRuntimeMapper.LOGICAL_ITEMS_TABLE,
        LOGICAL_ITEMS_TABLE=PostgresqlSetRuntimeMapper.LOGICAL_ITEMS_TABLE,
        _dynamicFieldValueTypes={},
    )
    assert PostgresqlSetRuntimeMapper._resolveDynamicFieldValueType(scope, "_missing") is None
    plan = connection.exec_driver_sql("EXPLAIN (FORMAT JSON) " + reader.query, reader.params).scalar_one()

    def indexNames(node):
        result = [node["Index Name"]] if "Index Name" in node else []
        for child in node.get("Plans", []):
            result.extend(indexNames(child))
        return result

    assert NESTED_INDEX in indexNames(plan[0]["Plan"])
    assert PostgresqlSetRuntimeMapper._resolveDynamicFieldValueType(scope, "_score") == "float"


def test_DropNestedGinMigrationPreservesRowsAndCanBeReversed(logicalIndexLab):
    connection, schema, env = logicalIndexLab
    _migrate(logicalIndexLab, "upgrade")
    before = _rows(connection)
    connection.commit()
    _command(env, schema, "upgrade", "9d064ee31b1b")
    indexes = _indexes(connection)
    assert NESTED_INDEX not in indexes
    assert FULL_INDEX not in indexes
    assert _rows(connection) == before
    connection.commit()
    _command(env, schema, "downgrade", "41c8d93e7a62")
    indexes = _indexes(connection)
    assert indexes[NESTED_INDEX]["valid"]
    assert indexes[NESTED_INDEX]["predicate"] == '("parentItemId" IS NOT NULL)'
    assert _rows(connection) == before


@pytest.fixture
def canonicalIndexLab(postgresqlMigratedEnv):
    env = postgresqlMigratedEnv
    engine = create_engine(URL.create(
        "postgresql+psycopg2", username=env["databaseUser"],
        password=env["databasePass"], host=env["postgresHost"],
        port=int(env["postgresPort"]), database=env["databaseName"],
    ))
    schema = "root_index_test_" + uuid4().hex
    try:
        with engine.connect() as connection:
            try:
                connection.exec_driver_sql('CREATE SCHEMA "' + schema + '"')
                connection.exec_driver_sql('SET search_path TO "' + schema + '"')
                connection.exec_driver_sql('''CREATE TABLE scipion_set_items (
                    "setId" integer NOT NULL, "scipionItemId" integer NOT NULL,
                    "values" jsonb NOT NULL,
                    CONSTRAINT ux_scipion_set_items_set_item UNIQUE ("setId", "scipionItemId"))''')
                connection.exec_driver_sql('''INSERT INTO scipion_set_items VALUES
                    (11,1,'{"_score":1,"_word":"é"}'),
                    (11,2,'{"_score":2.5}'),
                    (12,1,'{"_score":3}')''')
                connection.exec_driver_sql('''CREATE INDEX idx_scipion_set_items_values_gin
                    ON scipion_set_items USING gin ("values")''')
                connection.commit()
                _command(env, schema, "stamp", "9d064ee31b1b")
                yield connection, schema, env
            finally:
                connection.rollback()
                connection.exec_driver_sql('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
                connection.commit()
    finally:
        engine.dispose()


def _canonicalRows(connection):
    return connection.exec_driver_sql('''SELECT * FROM scipion_set_items
        ORDER BY "setId", "scipionItemId"''').all()


def _canonicalIndexes(connection):
    return {row["name"]: row for row in connection.exec_driver_sql('''
        SELECT c.relname AS name, i.indisvalid AS valid,
               pg_get_expr(i.indpred, i.indrelid) AS predicate
        FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
        WHERE i.indrelid='scipion_set_items'::regclass
    ''').mappings()}


def test_DropCanonicalGinPreservesRowsAndCanBeReversed(canonicalIndexLab):
    connection, schema, env = canonicalIndexLab
    before = _canonicalRows(connection)
    connection.commit()
    _command(env, schema, "upgrade", "b75a4e291c0f")
    indexes = _canonicalIndexes(connection)
    assert ROOT_INDEX not in indexes
    assert indexes["ux_scipion_set_items_set_item"]["valid"]
    assert _canonicalRows(connection) == before
    connection.commit()
    _command(env, schema, "downgrade", "9d064ee31b1b")
    indexes = _canonicalIndexes(connection)
    assert indexes[ROOT_INDEX]["valid"]
    assert indexes[ROOT_INDEX]["predicate"] is None
    assert _canonicalRows(connection) == before


def test_CanonicalGinDowngradeRebuildsInvalidIndex(canonicalIndexLab):
    connection, schema, env = canonicalIndexLab
    before = _canonicalRows(connection)
    connection.commit()
    _command(env, schema, "upgrade", "b75a4e291c0f")
    connection.execution_options(isolation_level="AUTOCOMMIT")
    try:
        with pytest.raises(DataError):
            connection.exec_driver_sql('CREATE INDEX CONCURRENTLY ' + ROOT_INDEX
                + ' ON scipion_set_items ((("values" ->> \'_word\')::integer))')
    finally:
        connection.rollback()
        connection.execution_options(isolation_level="READ COMMITTED")
    assert not _canonicalIndexes(connection)[ROOT_INDEX]["valid"]
    connection.commit()
    _command(env, schema, "downgrade", "9d064ee31b1b")
    assert _canonicalIndexes(connection)[ROOT_INDEX]["valid"]
    assert _canonicalRows(connection) == before


def test_MigratedRuntimeHasNoItemJsonGin(postgresqlMigratedEnv):
    env = postgresqlMigratedEnv
    db = PostgresqlDb(
        dbName=env["databaseName"], user=env["databaseUser"],
        password=env["databasePass"], host=env["postgresHost"], port=int(env["postgresPort"]),
    )
    try:
        rows = db.fetchAll('''SELECT c.relname AS name, i.indisvalid AS valid,
            pg_get_expr(i.indpred,i.indrelid) AS predicate
            FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
            JOIN pg_am am ON am.oid=c.relam
            WHERE i.indrelid IN ('scipion_set_items'::regclass,'scipion_set_table_items'::regclass)
              AND am.amname='gin' ''')
    finally:
        db.close()
    indexes = {row["name"]: row for row in rows}
    assert ROOT_INDEX not in indexes
    assert NESTED_INDEX not in indexes
    assert FULL_INDEX not in indexes
