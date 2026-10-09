"""Regression tests for the fast Scipion Object graph path."""
from pyworkflow.object import Object, Integer, String, Pointer, PointerList
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


def mapper():
    return ScipionSetPostgresqlMapper(db=object())


def ordinary_item(obj_id):
    item = Object()
    item.setObjId(obj_id)
    item._count = Integer(obj_id)
    item._nested = Object()
    item._nested._name = String('name-%d' % obj_id)
    return item


def legacy_result(m, item):
    values = m._getItemValues(item)
    schema = m._getCompleteItemSchema(item, itemValues=values)
    return values, schema


def test_StandardObjectAvoidsBothExtraMapperTraversals(monkeypatch):
    m = mapper()
    item = ordinary_item(9)
    calls = []
    original_dict = m._getObjDict
    original_ptr = m._iterPointerAttributes

    def watch_dict(*args, **kwargs):
        calls.append('objdict')
        return original_dict(*args, **kwargs)

    def watch_ptr(*args, **kwargs):
        calls.append('pointer_walk')
        return original_ptr(*args, **kwargs)

    monkeypatch.setattr(m, '_getObjDict', watch_dict)
    monkeypatch.setattr(m, '_iterPointerAttributes', watch_ptr)
    stored = m.serializeRuntimeItem(item)
    assert stored['values']['_nested._name'] == 'name-9'
    assert stored['_schema']['_nested._name'][0] == 'String'
    assert calls == []


def test_NativeParticleAlsoAvoidsSeparateTraversals(monkeypatch):
    from pwem.objects import Particle
    m = mapper()
    item = Particle()
    item.setObjId(14)
    item.setLocation(3, 'data.mrcs')
    events = []
    orig_dict = m._getObjDict
    orig_ptr = m._iterPointerAttributes
    def watch_dict(*a, **kw):
        events.append('dict')
        return orig_dict(*a, **kw)
    def watch_ptr(*a, **kw):
        events.append('pointer')
        return orig_ptr(*a, **kw)
    monkeypatch.setattr(m, '_getObjDict', watch_dict)
    monkeypatch.setattr(m, '_iterPointerAttributes', watch_ptr)
    stored = m.serializeRuntimeItem(item)
    assert stored['values']['_filename'] == 'data.mrcs'
    assert events == []


def test_FastGraphMatchesIndependentLegacySerializationWithDynamicData():
    m = mapper()
    item = ordinary_item(7)
    item._nested._dynamic = Integer(44)
    item._hidden = String('discard')
    item._hidden._objDoStore = False
    values, schema = legacy_result(m, item)
    stored = m.serializeRuntimeItem(item)
    assert stored['values'] == values
    assert stored['_schema'] == schema
    assert '_hidden' not in stored['values']
    assert '_hidden' not in stored['_schema']


def test_FastGraphMatchesIndependentLegacySerializationWithPointer():
    m = mapper()
    item = ordinary_item(6)
    item._nested._link = Pointer()
    target = Object()
    target.setObjId(30)
    item._nested._link.set(target)
    values, schema = legacy_result(m, item)
    stored = m.serializeRuntimeItem(item)
    assert stored['values'] == values
    assert stored['_schema'] == schema
    assert schema['_nested._link'][0] == 'Pointer'


def test_NonStoredPointersDoNotLeakFromFastGraph():
    m = mapper()
    item = ordinary_item(6)
    item._nested._skippedPtr = Pointer()
    item._nested._skippedPtr._objDoStore = False
    values, schema = legacy_result(m, item)
    stored = m.serializeRuntimeItem(item)
    assert stored['values'] == values
    assert stored['_schema'] == schema


def test_CustomNestedGettersStillUseLegacyPath(monkeypatch):
    class CustomNode(Object):
        def getAttributesToStore(self):
            return super().getAttributesToStore()
    m = mapper()
    item = ordinary_item(6)
    node = CustomNode()
    node._inner = Integer(2)
    item._special = node
    seen = []
    original = m._getObjDict
    def watch(*a, **kw):
        seen.append(kw.get('includeClass', a[1] if len(a) > 1 else None))
        return original(*a, **kw)
    monkeypatch.setattr(m, '_getObjDict', watch)
    values, schema = legacy_result(m, item)
    seen.clear()
    stored = m.serializeRuntimeItem(item)
    assert stored['values'] == values
    assert stored['_schema'] == schema
    assert seen == [True]


def test_RuntimeOnlyObjectReferenceKeepsLegacySemantics():
    m = mapper()
    item = ordinary_item(6)
    item._objParent = Object()
    item._objParent._number = Integer(9)
    values, schema = legacy_result(m, item)
    stored = m.serializeRuntimeItem(item)
    assert stored['values'] == values
    assert stored['_schema'] == schema


def test_AliasedSubtreePreservesLegacyPointerPaths():
    m = mapper()
    item = ordinary_item(6)
    shared = Object()
    shared._link = Pointer()
    item._firstAlias = shared
    item._secondAlias = shared
    values, schema = legacy_result(m, item)
    stored = m.serializeRuntimeItem(item)
    assert stored['values'] == values
    assert stored['_schema'] == schema



def test_PointerListKeepsOriginalSerialization():
    m = mapper()
    item = ordinary_item(6)
    item._links = PointerList()
    target = Object()
    target.setObjId(18)
    item._links.append(target)
    values, schema = legacy_result(m, item)
    stored = m.serializeRuntimeItem(item)
    assert stored['values'] == values
    assert stored['_schema'] == schema


def test_MultipleItemsHaveIndependentSchemas():
    m = mapper()
    first = ordinary_item(1)
    second = ordinary_item(2)
    first._specialFirst = Integer(3)
    second._specialSecond = String('other')
    a = m.serializeRuntimeItem(first)
    b = m.serializeRuntimeItem(second)
    assert '_specialFirst' in a['_schema'] and '_specialSecond' not in a['_schema']
    assert '_specialSecond' in b['_schema'] and '_specialFirst' not in b['_schema']
