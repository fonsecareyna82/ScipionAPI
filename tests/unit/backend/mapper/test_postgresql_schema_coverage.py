"""Schema coverage uses current columns and keeps custom normalization."""

from types import SimpleNamespace

import pytest

from app.backend.mapper.postgresql_set_runtime_mapper import PostgresqlSetRuntimeMapper


def scope(columns, ready=True):
    calls = []
    instance = SimpleNamespace(_columns=columns, _itemSchemaReady=ready)

    def synchronize(item):
        calls.append(item)
        return {'columns': {'_a': {}, '_b': {}}}

    instance.itemSchemaSynchronizer = synchronize
    instance._replaceColumns = lambda columns: setattr(instance, '_columns', columns)
    return instance, calls


def ensure(instance, schema):
    return PostgresqlSetRuntimeMapper._ensureItemSchema(
        instance, item='current-item', serialized={'_schema': schema},
    )


def test_CoverageSeesLiveColumnChangesAndSynchronizesMissingPaths():
    instance, calls = scope({'_a': {}, '_b': {}})
    schema = {'self': ('Object',), '_a': ('Integer', 1), '_b': ('String', 'b')}
    ensure(instance, schema)
    assert calls == []
    instance._columns.pop('_b')
    ensure(instance, schema)
    assert calls == ['current-item']
    ensure(instance, schema)
    assert calls == ['current-item']


def test_EmptyFirstSchemaStillRequiresSynchronization():
    instance, calls = scope({}, ready=False)
    ensure(instance, {})
    assert calls == ['current-item']
    assert instance._itemSchemaReady


def test_NonStringSchemaKeysRetainStringNormalization():
    instance, calls = scope({'3': {}})
    ensure(instance, {3: ('Integer', 42)})
    assert calls == []


def test_CustomColumnMappingKeepsItsIterationContract():
    class CustomColumns(dict):
        def __iter__(self):
            return iter(('_a', '_b'))

    instance, calls = scope(CustomColumns({'_a': {}}))
    ensure(instance, {'_a': ('Integer', 1), '_b': ('Integer', 2)})
    assert calls == []


def test_IncompleteSynchronizationStillRaisesForMissingPaths():
    instance, calls = scope({'_a': {}})
    with pytest.raises(RuntimeError, match='missingPaths=.*_missing'):
        ensure(instance, {'_a': ('Integer', 1), '_missing': ('Integer', 2)})
    assert calls == ['current-item']
