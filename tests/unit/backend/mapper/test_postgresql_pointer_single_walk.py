"""Regression: one pointer walk during incremental Scipion item serialization.

Keep direct schema/value callers, dynamic item attributes and pointer lists intact.
"""
from types import SimpleNamespace

import pytest

import app.backend.mapper.scipion_set_mapper as mapper_module
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class FakePointer:
    def __init__(self, value):
        self.value = value


class FakePointerList(list):
    pass


class FakeItem:
    def __init__(self, obj_id, pointer_name='_ptr', with_pointers=True):
        self.obj_id = obj_id
        self.pointer_name = pointer_name
        self.with_pointers = with_pointers

    def getObjId(self):
        return self.obj_id

    def getObjDict(self, includeClass=False):
        if includeClass:
            return {'self': ('Particle', None), '_score': ('Float', None)}
        return {'_score': float(self.obj_id)}


@pytest.fixture
def serializer(monkeypatch):
    mapper = object.__new__(ScipionSetPostgresqlMapper)
    walked = []

    def walk(item):
        walked.append(item.obj_id)
        if item.with_pointers:
            yield item.pointer_name, FakePointer(item.obj_id)
            yield '_pointerList', FakePointerList([FakePointer('a'), FakePointer('b')])

    monkeypatch.setattr(mapper_module, 'Pointer', FakePointer)
    monkeypatch.setattr(mapper_module, 'PointerList', FakePointerList)
    monkeypatch.setattr(mapper, '_iterPointerAttributes', walk)
    monkeypatch.setattr(mapper, '_getClassName', lambda obj: type(obj).__name__)
    monkeypatch.setattr(mapper, '_serializePointerReference', lambda pointer: {'value': pointer.value})
    monkeypatch.setattr(mapper, '_isPostgresqlRuntimeSet', lambda obj: False)
    monkeypatch.setattr(mapper, '_toJsonValue', lambda value: value)
    monkeypatch.setattr(mapper, '_addRelationIdentityValues', lambda **kwargs: None)
    monkeypatch.setattr(mapper, '_getClassItemSize', lambda item: None)
    monkeypatch.setattr(mapper, '_addCoordinate3dBottomLeftCoordinates', lambda **kwargs: None)
    monkeypatch.setattr(mapper, '_getItemEnabled', lambda item: True)
    monkeypatch.setattr(mapper, '_getObjectLabel', lambda item: '')
    monkeypatch.setattr(mapper, '_getObjectComment', lambda item: '')
    monkeypatch.setattr(mapper, '_getObjectCreation', lambda item: None)
    return mapper, walked


def test_SerializeRuntimeItemTraversesPointersOnce(serializer):
    mapper, walked = serializer
    result = mapper.serializeRuntimeItem(FakeItem(7))
    assert result['scipionItemId'] == 7
    assert walked == [7]


def test_EmptyPointerSetAlsoAvoidsSecondTraversal(serializer):
    mapper, walked = serializer
    result = mapper.serializeRuntimeItem(FakeItem(8, with_pointers=False))
    assert result['values']['_score'] == 8.0
    assert walked == [8]


def test_PointerSchemaValuesAndOrderedListArePreserved(serializer):
    mapper, _ = serializer
    result = mapper.serializeRuntimeItem(FakeItem(11))
    assert result['values']['_ptr'] == {'value': 11}
    assert result['values']['_pointerList'] == [{'value': 'a'}, {'value': 'b'}]
    assert result['_schema']['_ptr'] == ('FakePointer', None)
    assert result['_schema']['_pointerList'] == ('FakePointerList', None)
    assert result['_schema']['_score'] == ('Float', None)


def test_PointerSchemaCannotLeakAcrossDifferentItems(serializer):
    mapper, walked = serializer
    a = mapper.serializeRuntimeItem(FakeItem(1, pointer_name='_alpha'))
    b = mapper.serializeRuntimeItem(FakeItem(2, pointer_name='_beta'))
    assert '_alpha' in a['_schema'] and '_beta' not in a['_schema']
    assert '_beta' in b['_schema'] and '_alpha' not in b['_schema']
    assert a['values']['_alpha'] == {'value': 1}
    assert b['values']['_beta'] == {'value': 2}
    assert walked == [1, 2]


def test_DirectSchemaCallerStillTraversesAndIncludesPointers(serializer):
    mapper, walked = serializer
    schema = mapper._getItemSchema(FakeItem(3))
    assert schema['_ptr'] == ('FakePointer', None)
    assert walked == [3]


def test_DirectCompleteSchemaCallerStillIncludesPointers(serializer):
    mapper, walked = serializer
    schema = mapper._getCompleteItemSchema(FakeItem(4))
    assert schema['_ptr'] == ('FakePointer', None)
    assert schema['_score'] == ('Float', None)
    assert walked == [4, 4]  # direct caller retains original independent discovery


def test_DirectPointerValuesCallerStillSupportsLists(serializer):
    mapper, walked = serializer
    values = mapper._getItemPointerValues(FakeItem(5))
    assert values['_ptr'] == {'value': 5}
    assert values['_pointerList'] == [{'value': 'a'}, {'value': 'b'}]
    assert walked == [5]
