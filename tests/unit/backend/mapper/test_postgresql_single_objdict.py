"""#78: one object-graph read per native item, without weakening dynamic schema."""
import pytest
from pyworkflow.object import Object, Integer, String, Pointer
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


def build_item(item_id=7):
    item = Object()
    item.setObjId(item_id)
    item._count = Integer(item_id)
    sub = Object()
    sub._text = String('value-%s' % item_id)
    item._sub = sub
    return item


def spy_obj_dict(monkeypatch, mapper):
    seen = []
    original = mapper._getObjDict
    def tracked(obj, includeClass):
        seen.append((id(obj), includeClass))
        return original(obj, includeClass)
    monkeypatch.setattr(mapper, '_getObjDict', tracked)
    return seen


def test_NativeObjectUsesUnifiedGraphOnceWithoutObjDict(monkeypatch):
    # SCIPIONAPI-SINGLE-OBJDICT-TEST-CONTRACT-83
    # #81 intentionally supersedes #79's one-ObjDict fast path.
    mapper = ScipionSetPostgresqlMapper(db=object())
    item = build_item()
    seen = spy_obj_dict(monkeypatch, mapper)
    graph_calls = []
    original_graph = mapper._singleGraphForStandardItem

    def watch_graph(candidate):
        graph_calls.append(id(candidate))
        return original_graph(candidate)

    monkeypatch.setattr(mapper, '_singleGraphForStandardItem', watch_graph)
    result = mapper.serializeRuntimeItem(item)
    assert result['values']['_count'] == 7
    assert result['_schema']['_count'][0] == 'Integer'
    assert graph_calls == [id(item)]
    assert [flag for obj_id, flag in seen if obj_id == id(item)] == []


def test_SecondItemUsesFreshAttributesAndSchema(monkeypatch):
    mapper = ScipionSetPostgresqlMapper(db=object())
    first, second = build_item(1), build_item(2)
    first._onlyFirst = String('first')
    second._onlySecond = Integer(22)
    seen = spy_obj_dict(monkeypatch, mapper)
    graph_calls = []
    original_graph = mapper._singleGraphForStandardItem

    def watch_graph(candidate):
        graph_calls.append(id(candidate))
        return original_graph(candidate)

    monkeypatch.setattr(mapper, '_singleGraphForStandardItem', watch_graph)
    a = mapper.serializeRuntimeItem(first)
    b = mapper.serializeRuntimeItem(second)
    assert '_onlyFirst' in a['values'] and '_onlySecond' not in a['values']
    assert '_onlySecond' in b['_schema'] and '_onlyFirst' not in b['_schema']
    assert graph_calls == [id(first), id(second)]
    assert [flag for obj_id, flag in seen if obj_id in (id(first), id(second))] == []


def test_RawValuesAndRawSchemaMatchIndependentCalls():
    mapper = ScipionSetPostgresqlMapper(db=object())
    item = build_item()
    item._notStored = String('hidden')
    item._notStored._objDoStore = False
    expectedValues = mapper._getItemValues(item)
    expectedSchema = mapper._getCompleteItemSchema(item, itemValues=expectedValues)
    result = mapper.serializeRuntimeItem(item)
    assert result['values'] == expectedValues
    assert result['_schema'] == expectedSchema
    assert '_notStored' not in result['values']
    assert '_notStored' not in result['_schema']


def test_CustomGetObjDictKeepsTwoIndependentCalls(monkeypatch):
    class Custom(Object):
        def getObjDict(self, includeClass=False, **kwargs):
            return super().getObjDict(includeClass=includeClass, **kwargs)
    mapper = ScipionSetPostgresqlMapper(db=object())
    item = Custom()
    item.setObjId(13)
    item._value = Integer(99)
    seen = spy_obj_dict(monkeypatch, mapper)
    result = mapper.serializeRuntimeItem(item)
    assert result['values']['_value'] == 99
    assert [flag for obj_id, flag in seen if obj_id == id(item)] == [False, True]


def test_CustomAttributeTraversalKeepsOriginalSemantics(monkeypatch):
    class Custom(Object):
        def getAttributesToStore(self):
            return super().getAttributesToStore()
    mapper = ScipionSetPostgresqlMapper(db=object())
    item = Custom()
    item.setObjId(14)
    item._value = Integer(5)
    seen = spy_obj_dict(monkeypatch, mapper)
    mapper.serializeRuntimeItem(item)
    assert [flag for obj_id, flag in seen if obj_id == id(item)] == [False, True]


def test_NativeParticleActuallyUsesTheUnifiedGraph(monkeypatch):
    from pwem.objects import Particle
    mapper = ScipionSetPostgresqlMapper(db=object())
    particle = Particle()
    particle.setObjId(21)
    particle.setLocation(3, 'test-particles.mrcs')
    seen = spy_obj_dict(monkeypatch, mapper)
    graph_calls = []
    original_graph = mapper._singleGraphForStandardItem

    def watch_graph(candidate):
        graph_calls.append(id(candidate))
        return original_graph(candidate)

    monkeypatch.setattr(mapper, '_singleGraphForStandardItem', watch_graph)
    result = mapper.serializeRuntimeItem(particle)
    assert result['values']['_filename'] == 'test-particles.mrcs'
    assert result['_schema']['_filename'][0] == 'String'
    assert graph_calls == [id(particle)]
    assert [flag for obj_id, flag in seen if obj_id == id(particle)] == []


def test_NestedPointerUsesProvenObjDictFallback(monkeypatch):
    mapper = ScipionSetPostgresqlMapper(db=object())
    item = build_item(29)
    target = Object()
    target.setObjId(30)
    item._sub._link = Pointer()
    item._sub._link.set(target)

    # Compute the expected persisted representation independently.
    expected_values = mapper._getItemValues(item)
    expected_schema = mapper._getCompleteItemSchema(
        item, itemValues=expected_values
    )
    # SCIPIONAPI-POINTER-FALLBACK-TEST-84
    # Verify actual routing, rather than an incidental number of calls
    # to _getObjDict. Keep full value/schema equality checks.
    seen = spy_obj_dict(monkeypatch, mapper)
    graph_outcomes = []
    fallback_calls = []
    original_graph = mapper._singleGraphForStandardItem
    original_fallback = mapper._singleObjDictForStandardItem

    def watch_graph(candidate):
        outcome = original_graph(candidate)
        graph_outcomes.append((id(candidate), outcome))
        return outcome

    def watch_fallback(candidate):
        fallback_calls.append(id(candidate))
        return original_fallback(candidate)

    monkeypatch.setattr(mapper, '_singleGraphForStandardItem', watch_graph)
    monkeypatch.setattr(mapper, '_singleObjDictForStandardItem', watch_fallback)
    result = mapper.serializeRuntimeItem(item)

    assert result['values'] == expected_values
    assert result['_schema'] == expected_schema
    assert result['_schema']['_sub._link'][0] == 'Pointer'
    assert graph_outcomes == [(id(item), None)]
    assert fallback_calls == [id(item)]
    assert True in [flag for obj_id, flag in seen if obj_id == id(item)]


def test_DirectPublicHelpersRemainIndependent():
    mapper = ScipionSetPostgresqlMapper(db=object())
    item = build_item()
    assert mapper._getItemValues(item)['_sub._text'] == 'value-7'
    assert mapper._getItemSchema(item)['_sub._text'][0] == 'String'
    assert mapper._getCompleteItemSchema(item)['_count'][0] == 'Integer'


def test_PointerSchemaStillIncludesDynamicPointers():
    mapper = ScipionSetPostgresqlMapper(db=object())
    item = build_item()
    item._pointer = Pointer()
    result = mapper.serializeRuntimeItem(item)
    assert result['_schema']['_pointer'][0] == 'Pointer'
    assert '_pointer' in result['values']
