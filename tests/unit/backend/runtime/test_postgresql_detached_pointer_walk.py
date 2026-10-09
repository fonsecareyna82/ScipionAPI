# SCIPIONAPI-DETACHED-POINTER-WALK-RED-74
"""Fast traversal must retain the exact Scipion getAttributes contract."""

from types import MethodType

from pyworkflow.object import Integer, Object, Pointer, PointerList, String

from app.backend.runtime.postgresql_runtime_set_factory import (
    PostgresqlRuntimeSetMixin,
)


def collect(obj):
    return PostgresqlRuntimeSetMixin._getDetachedScipionChildren(obj)


def test_DefaultScipionGetterIsBypassedWithoutDroppingChildren(monkeypatch):
    root = Object()
    integer = Integer(7)
    nested = Object()
    root._integer = integer
    root._nested = nested
    root._ordinary = 'not a Scipion Object'

    def forbidden(self):
        raise AssertionError('Default getAttributes should not be needed')

    monkeypatch.setattr(Object, 'getAttributes', forbidden)
    assert collect(root) == [integer, nested]


def test_DefaultFastpathIncludesDynamicallyAddedPointersAndPointerLists():
    root = Object()
    p = Pointer()
    many = PointerList()
    root._latePointer = p
    root._lateList = many
    assert collect(root) == [p, many]


def test_DefaultFastpathPreservesNativeAttributeOrder():
    root = Object()
    first = Integer(1)
    second = String('second')
    third = Integer(3)
    root._first = first
    root._notAnObject = 123
    root._second = second
    root._third = third
    assert collect(root) == [first, second, third]


def test_OverriddenGetterMayExposeVirtualAttributes():
    external = Pointer()

    class Custom(Object):
        def getAttributes(self):
            yield 'virtual', external

    assert collect(Custom()) == [external]


def test_InstanceLevelGetterOverrideRemainsAuthoritative():
    root = Object()
    value = Pointer()

    def instanceGetter(self):
        yield 'computed', value

    root.getAttributes = MethodType(instanceGetter, root)
    assert collect(root) == [value]


def test_CustomGetattributeDoesNotSilentlyUseRawValues():
    raw = Integer(1)
    calculated = Pointer()

    class Dynamic(Object):
        def __getattribute__(self, name):
            if name == '_node':
                return calculated
            return super().__getattribute__(name)

    root = Dynamic()
    root._node = raw
    assert collect(root) == [calculated]


def test_FailedCustomGeneratorHasSameAllOrNothingFallback():
    value = Pointer()

    class Broken(Object):
        def getAttributes(self):
            yield 'some', value
            raise RuntimeError('traversal failed')

    assert collect(Broken()) == []


def test_NonScipionObjectWithGetterStillUsesFallback():
    child = Integer(3)

    class LegacyObject:
        def getAttributes(self):
            return [('legacy', child)]

    assert collect(LegacyObject()) == [child]


def test_NoAttributesOrNoGetterYieldsEmptySnapshot():
    assert collect(Object()) == []
    assert collect(object()) == []
