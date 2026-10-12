"""Real PostgreSQL coverage for schemas growing after the first Set item."""

import pytest
from pyworkflow.object import Integer, Object, String

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


@pytest.fixture
def schemaMapper(postgresqlIntegrationDb):
    db = postgresqlIntegrationDb
    db.execute('''CREATE TEMP TABLE scipion_sets (
        id BIGINT PRIMARY KEY, "itemClassName" TEXT, properties JSONB,
        "updatedAt" TIMESTAMPTZ
    )''')
    db.execute('''CREATE TEMP TABLE scipion_set_tables (
        id BIGINT PRIMARY KEY, "setId" BIGINT, "tableKind" TEXT,
        "itemClassName" TEXT, properties JSONB, "updatedAt" TIMESTAMPTZ
    )''')
    db.execute('''CREATE TEMP TABLE scipion_set_columns (
        id BIGSERIAL PRIMARY KEY, "setId" BIGINT, "labelProperty" TEXT,
        "columnName" TEXT, "className" TEXT, "valueType" TEXT,
        position INTEGER, indexed BOOLEAN,
        CONSTRAINT ux_scipion_set_columns_set_label UNIQUE ("setId", "labelProperty"),
        CONSTRAINT ux_scipion_set_columns_set_column UNIQUE ("setId", "columnName")
    )''')
    db.execute('''CREATE TEMP TABLE scipion_set_table_columns (
        id BIGSERIAL PRIMARY KEY, "tableId" BIGINT, "labelProperty" TEXT,
        "columnName" TEXT, "className" TEXT, "valueType" TEXT,
        position INTEGER, indexed BOOLEAN, properties JSONB,
        CONSTRAINT ux_scipion_set_table_columns_table_label UNIQUE ("tableId", "labelProperty"),
        CONSTRAINT ux_scipion_set_table_columns_table_column UNIQUE ("tableId", "columnName")
    )''')
    db.execute('''CREATE TEMP TABLE scipion_set_properties (
        "setId" BIGINT, key TEXT, value TEXT,
        CONSTRAINT ux_scipion_set_properties_set_key UNIQUE ("setId", key)
    )''')
    db.execute('INSERT INTO scipion_sets (id) VALUES (31)')
    db.execute('''INSERT INTO scipion_set_tables (id, "setId", "tableKind")
                  VALUES (71, 31, 'root'), (72, 31, 'child')''')
    return ScipionSetPostgresqlMapper(db=db)


def item(includeOptional):
    result = Object()
    result._optional = None
    result._name = String("particle")
    if includeOptional:
        result._optional = Object()
        result._optional._value = Integer(185)
    return result


def synchronize(mapper, scope, value):
    with mapper.db.transaction():
        if scope == "root":
            mapper.synchronizeRuntimeItemSchema(31, 71, value)
        else:
            mapper.synchronizeRuntimeLogicalItemSchema(72, value)


def columns(mapper, scope):
    stored = (mapper.getStoredSetColumns(31) if scope == "root"
              else mapper.getStoredSetTableColumns(72))
    return {column["labelProperty"]: {
        key: column[key] for key in ("columnName", "position", "indexed")
    } for column in stored}


@pytest.mark.parametrize("scope", ["root", "child"])
def test_LateOptionalFieldsPreserveAliasesAndRemainAfterSparseItems(schemaMapper, scope):
    mapper = schemaMapper
    synchronize(mapper, scope, item(False))
    initial = columns(mapper, scope)
    synchronize(mapper, scope, item(True))
    expanded = columns(mapper, scope)
    assert "_optional._value" in expanded
    assert all(expanded[label] == value for label, value in initial.items())
    assert len({value["columnName"] for value in expanded.values()}) == len(expanded)
    assert expanded["_optional._value"]["position"] > max(
        value["position"] for value in initial.values())
    synchronize(mapper, scope, item(False))
    assert columns(mapper, scope) == expanded
    if scope == "root":
        logical = mapper.getStoredSetTableColumns(71)
        assert {column["labelProperty"]: {
            key: column[key] for key in ("columnName", "position", "indexed")
        } for column in logical} == expanded


@pytest.mark.parametrize("scope", ["root", "child"])
def test_SchemaGrowthRollsBackWithCallerTransaction(schemaMapper, scope):
    mapper = schemaMapper
    synchronize(mapper, scope, item(False))
    initial = columns(mapper, scope)
    initialLogical = mapper.getStoredSetTableColumns(71)
    with pytest.raises(RuntimeError, match="injected schema failure"):
        with mapper.db.transaction():
            synchronize(mapper, scope, item(True))
            raise RuntimeError("injected schema failure")
    assert columns(mapper, scope) == initial
    assert mapper.getStoredSetTableColumns(71) == initialLogical
    synchronize(mapper, scope, item(True))
    assert "_optional._value" in columns(mapper, scope)
