"""Private graph reuse preserves the independent serialization contract."""

from datetime import datetime
from decimal import Decimal

import pytest
from pyworkflow.object import Boolean, Float, Integer, Object, Pointer, String

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


def mapper(reference=False):
    instance = ScipionSetPostgresqlMapper(db=object())
    if reference:
        instance._reusePlainItemGraph = lambda *args: None
    return instance


def item():
    obj = Object()
    obj.setObjId(13)
    obj._number = Integer(42)
    obj._text = String('  é: a, b\n"quoted"\\N  ')
    obj._fraction = Float(1.2345678901234567)
    obj._enabled = Boolean(False)
    obj._nested = Object()
    obj._nested._empty = String()
    return obj


def test_PlainGraphReusesOnlyThisItemsPrivateDictionaries():
    obj = item()
    actual = mapper()
    original = actual._reusePlainItemGraph
    used = []

    def observe(graph, *args):
        result = original(graph, *args)
        assert result is not None
        assert result[0] is graph[0]
        assert result[1] is graph[1]
        used.append(result)
        return result

    actual._reusePlainItemGraph = observe
    expected = mapper(reference=True).serializeRuntimeItem(obj)
    first = actual.serializeRuntimeItem(obj)
    assert first == expected
    obj._dynamic = Integer(99)
    second = actual.serializeRuntimeItem(obj)
    assert len(used) == 2
    assert first['values'] is not second['values']
    assert first['_schema'] is not second['_schema']
    assert '_dynamic' not in first['values']
    assert second['values']['_dynamic'] == 99
    assert obj._number.get() == 42


@pytest.mark.parametrize('fields', [0, 1, 2, 3])
def test_SmallGraphsKeepTheEstablishedRoute(fields):
    obj = Object()
    obj.setObjId(13)
    for index in range(fields):
        setattr(obj, '_field%s' % index, Integer(index))
    instance = mapper()

    def unexpected(*args):
        raise AssertionError('Small graphs must not pay graph-reuse checks')

    instance._reusePlainItemGraph = unexpected
    assert instance.serializeRuntimeItem(obj) == mapper(reference=True).serializeRuntimeItem(obj)


@pytest.mark.parametrize('value', [
    b'bytes', datetime(2025, 1, 2), Decimal('1.234'),
    [1, {'nested': b'bytes'}], {'nested': [True, None, 2]},
])
def test_ComplexValuesKeepConversionAndLeaveRejectedGraphsUntouched(value):
    obj = item()
    obj._opaque = Object(value=value)
    actual = mapper()
    graph = actual._singleGraphForStandardItem(obj)
    beforeValues, beforeSchema = dict(graph[0]), dict(graph[1])
    assert actual._reusePlainItemGraph(graph, obj, None) is None
    assert graph[0] == beforeValues
    assert graph[1] == beforeSchema
    assert actual.serializeRuntimeItem(obj) == mapper(reference=True).serializeRuntimeItem(obj)


@pytest.mark.parametrize('parent', [None, type('RuntimeParent', (), {'isPostgresqlRuntimeOutput': lambda self: True})()])
def test_LegacySelfAndRuntimeStorageFieldsKeepTheirFiltering(parent):
    obj = item()
    obj.self = Object(value=[1, 2])
    obj.__item__legacy = Object(value=Decimal('1.2'))
    obj.__item__legacy._nested = Integer(10)
    obj._mapperPath = String('/tmp/compatibility.sqlite')
    actual = mapper().serializeRuntimeItem(obj, scipionSet=parent)
    expected = mapper(reference=True).serializeRuntimeItem(obj, scipionSet=parent)
    assert actual == expected
    assert 'self' not in actual['values']
    assert not any(path.startswith('__item__') for path in actual['values'])
    assert not any(path.startswith('__item__') for path in actual['_schema'])
    assert ('_mapperPath' in actual['values']) == (parent is None)
    assert obj.__item__legacy._nested.get() == 10


@pytest.mark.parametrize('hook', [
    '_singleGraphForStandardItem', '_getItemValues', '_getItemSchema',
    '_getCompleteItemSchema', '_toJsonValue', '_removeLegacyPointerListEntries',
    '_removePostgresqlRuntimeStorageProperties',
])
def test_InstanceHooksRetainOriginalCalls(hook):
    def run(reference):
        instance = mapper(reference)
        original = getattr(instance, hook)
        calls = []

        def observed(*args, **kwargs):
            calls.append(hook)
            return original(*args, **kwargs)

        setattr(instance, hook, observed)
        result = instance.serializeRuntimeItem(item())
        return result['values'], result['_schema'], calls

    assert run(False) == run(True)


def test_ClassNormalizerPatchKeepsCustomConversion(monkeypatch):
    original = ScipionSetPostgresqlMapper._toJsonValue

    def custom(self, value):
        if type(value) is int:
            return value + 100
        return original(self, value)

    monkeypatch.setattr(ScipionSetPostgresqlMapper, '_toJsonValue', custom)
    obj = item()
    actual = mapper().serializeRuntimeItem(obj)
    assert actual['values']['_number'] == 142
    assert actual == mapper(reference=True).serializeRuntimeItem(obj)


def test_RuntimeGetterCanReplaceNormalizerAndStorageHookMidCall():
    def run(reference):
        instance = mapper(reference)
        original = instance._toJsonValue

        class RuntimeParent:
            def isPostgresqlRuntimeOutput(self):
                def normalize(value):
                    return value + 1 if type(value) is int else original(value)

                def remove(values):
                    values.pop('_mapperPath', None)
                    values['_lateBytes'] = b'late'

                instance._toJsonValue = normalize
                instance._removePostgresqlRuntimeStorageProperties = remove
                return True

        obj = item()
        obj._mapperPath = String('transient')
        result = instance.serializeRuntimeItem(obj, scipionSet=RuntimeParent())
        assert result['values']['_number'] == 43
        assert result['values']['_lateBytes'] == 'late'
        return result['values'], result['_schema']

    assert run(False) == run(True)


@pytest.mark.parametrize('hook', ['_getItemSchema', '_getCompleteItemSchema', '_removeLegacyPointerListEntries'])
def test_DerivedGetterCanReplaceSchemaHooksBeforeSchemaCompletion(hook):
    def run(reference):
        instance = mapper(reference)
        original = getattr(instance, hook)
        calls = []

        class DerivedItem(Object):
            def getTsId(self):
                def changed(*args, **kwargs):
                    calls.append(hook)
                    return original(*args, **kwargs)

                setattr(instance, hook, changed)
                return 'TS-1'

        obj = DerivedItem()
        obj.setObjId(13)
        obj._number = Integer(42)
        obj._score = Float(0.125)
        obj._code = String('CODE-13')
        obj.__item__legacy = Integer(99)
        result = instance.serializeRuntimeItem(obj)
        assert result['values']['_tsId'] == 'TS-1'
        assert result['_schema']['_tsId'][0] == 'String'
        assert calls
        return result['values'], result['_schema'], calls

    assert run(False) == run(True)


def test_PointerGraphsRetainIndependentSerialization():
    obj = item()
    obj._link = Pointer()
    target = Object()
    target.setObjId(55)
    obj._link.set(target)
    assert mapper().serializeRuntimeItem(obj) == mapper(reference=True).serializeRuntimeItem(obj)


def test_PrecomputedPublicHelperInputsRemainUnmodified():
    instance = mapper()
    obj = item()
    values = {'_number': 42, '__item__legacy': 5}
    schema = {'_number': ('Integer', 42), '__item__legacy': ('Integer', 5)}
    assert instance._getItemValues(obj, precomputedRawValues=values) == {'_number': 42}
    assert instance._getItemSchema(obj, pointerSchema={}, precomputedRawSchema=schema) == {
        '_number': ('Integer', 42),
    }
    assert values == {'_number': 42, '__item__legacy': 5}
    assert schema == {'_number': ('Integer', 42), '__item__legacy': ('Integer', 5)}
