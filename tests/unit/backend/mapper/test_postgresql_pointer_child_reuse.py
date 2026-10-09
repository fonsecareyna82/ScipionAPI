# SCIPIONAPI-POINTER-CHILD-REUSE-RED-76
"""Nested pointer scans must be reused only for standard, deterministic getters."""

from collections import Counter
from types import MethodType

from pyworkflow.object import Object, Pointer, PointerList

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class CountingMapper(ScipionSetPostgresqlMapper):
    def __init__(self):
        super().__init__(db=object())
        self.reads = Counter()

    def _getAttributesToStore(self, obj):
        self.reads[id(obj)] += 1
        return super()._getAttributesToStore(obj)


def pointer_paths(mapper, item):
    return dict(mapper._iterPointerAttributes(item))


def test_StandardNestedObjectIsScannedOnlyOnce():
    mapper = CountingMapper()
    root, nested = Object(), Object()
    pointer = Pointer()
    nested._pointer = pointer
    root._nested = nested

    assert pointer_paths(mapper, root) == {'_nested._pointer': pointer}
    assert mapper.reads[id(root)] == 1
    assert mapper.reads[id(nested)] == 1


def test_DeepNestedBranchIsScannedOnlyOncePerObject():
    mapper = CountingMapper()
    root, outer, inner = Object(), Object(), Object()
    pointer = Pointer()
    inner._pointer = pointer
    outer._inner = inner
    root._outer = outer

    assert pointer_paths(mapper, root) == {'_outer._inner._pointer': pointer}
    assert [mapper.reads[id(x)] for x in (root, outer, inner)] == [1, 1, 1]


def test_DynamicPointerAndPointerListRemainVisible():
    mapper = CountingMapper()
    root, nested = Object(), Object()
    pointer, pointers = Pointer(), PointerList()
    nested._dynamic = pointer
    nested._many = pointers
    root._nested = nested

    assert pointer_paths(mapper, root) == {
        '_nested._dynamic': pointer, '_nested._many': pointers,
    }


def test_NonStoredPointerRemainsExcluded():
    mapper = CountingMapper()
    root = Object()
    keep, skip = Pointer(), Pointer()
    skip._objDoStore = False
    root._keep, root._skip = keep, skip

    assert pointer_paths(mapper, root) == {'_keep': keep}


def test_CustomGetterIsReadAgainAsBefore():
    """A plugin getter may legitimately expose a different graph on next call."""
    first, second = Pointer(), Pointer()

    class Custom(Object):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def getAttributesToStore(self):
            self.calls += 1
            if self.calls == 1:
                yield '_first', first
            else:
                yield '_second', second

    mapper = CountingMapper()
    root, child = Object(), Custom()
    root._child = child

    assert pointer_paths(mapper, root) == {'_child._second': second}
    assert child.calls == 2


def test_CustomGetAttributesStaysOnLegacyRoute():
    p = Pointer()

    class Custom(Object):
        def getAttributes(self):
            yield '_computed', p

    mapper = CountingMapper()
    root, child = Object(), Custom()
    root._child = child
    assert pointer_paths(mapper, root) == {'_child._computed': p}
    assert mapper.reads[id(child)] == 2


def test_InstanceLevelGetAttributesOverrideStaysOnLegacyRoute():
    p = Pointer()
    mapper = CountingMapper()
    root, child = Object(), Object()
    child.getAttributes = MethodType(lambda self: iter([('_virtual', p)]), child)
    root._child = child

    assert pointer_paths(mapper, root) == {'_child._virtual': p}
    assert mapper.reads[id(child)] == 2


def test_DynamicAttributesRemainIndependentBetweenItems():
    mapper = CountingMapper()
    a, b = Object(), Object()
    pa, pb = Pointer(), Pointer()
    a._first = pa
    b._second = pb

    assert pointer_paths(mapper, a) == {'_first': pa}
    assert pointer_paths(mapper, b) == {'_second': pb}


def test_CyclicScipionGraphTerminatesWithoutDuplicates():
    mapper = CountingMapper()
    root, child = Object(), Object()
    pointer = Pointer()
    root._child = child
    child._back = root
    child._pointer = pointer

    assert pointer_paths(mapper, root) == {'_child._pointer': pointer}


def test_CustomGetattributeRetainsLegacyLookup():
    pointer = Pointer()
    original = Pointer()

    class Custom(Object):
        def __getattribute__(self, name):
            if name == '_node':
                return pointer
            return super().__getattribute__(name)

    mapper = CountingMapper()
    root, child = Object(), Custom()
    child._node = original
    root._child = child

    assert pointer_paths(mapper, root) == {'_child._node': pointer}
    assert mapper.reads[id(child)] == 2
