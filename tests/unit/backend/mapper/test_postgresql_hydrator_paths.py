# SCIPIONAPI-HYDRATOR-PATHS-RED-70
"""Per-hydrator path metadata, with dynamic and nested fields preserved."""

from pyworkflow.object import Integer, Object, String
from app.backend.mapper.postgresql_scipion_item_hydrator import (
    PostgresqlScipionItemHydrator,
)


class PathNested(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._score = Integer()


class PathItem(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._name = String()
        self._nested = None


def makeHydrator(paths=None):
    if paths is None:
        paths = {
            '_name': 'String',
            '_nested': 'PathNested',
            '_nested._score': 'Integer',
            '_deep.child.value': 'Integer',
        }
    return PostgresqlScipionItemHydrator(
        itemClassName='PathItem',
        columns=[
            {'labelProperty': path, 'className': cls}
            for path, cls in paths.items()
        ],
        classes={'PathItem': PathItem, 'PathNested': PathNested},
    )


def test_NestedPrefixesPreparedFromCurrentColumns():
    hydrator = makeHydrator()
    assert hydrator._nestedPathPrefixes == {
        '_nested', '_deep', '_deep.child',
    }


def test_DeclaredAttributePathsArePreSplit():
    hydrator = makeHydrator()
    assert hydrator._pathPartsCache['_nested._score'] == (
        '_nested', '_score',
    )
    assert hydrator._pathPartsCache['_name'] == ('_name',)


def test_NestedPrefixLookupMatchesOriginalSemantics():
    hydrator = makeHydrator()
    assert hydrator._hasNestedPaths('_nested')
    assert hydrator._hasNestedPaths('_deep')
    assert hydrator._hasNestedPaths('_deep.child')
    assert not hydrator._hasNestedPaths('_name')
    assert not hydrator._hasNestedPaths('_deep.chil')
    assert not hydrator._hasNestedPaths('')


def test_SplitPathKeepsListAndReturnsIndependentInstances():
    hydrator = makeHydrator()
    first = hydrator._splitPath('_nested._score')
    first.append('mutated')
    assert hydrator._splitPath('_nested._score') == ['_nested', '_score']
    assert hydrator._splitPath('.a..b.') == ['a', 'b']


def test_UnknownDynamicPathsDoNotGrowStaticCache():
    hydrator = makeHydrator()
    before = len(hydrator._pathPartsCache)
    for index in range(100):
        assert hydrator._splitPath('dynamic.%s' % index) == [
            'dynamic', str(index),
        ]
    assert len(hydrator._pathPartsCache) == before


def test_NestedObjectAndDynamicConvenienceValuesStillHydrate():
    hydrator = makeHydrator()
    item = hydrator.build({
        'scipionItemId': 17,
        'values': {
            '_name': 'sample',
            '_nested': None,
            '_nested._score': 42,
            'runtimeOnly': 99,
        },
    })
    assert item._name.get() == 'sample'
    assert isinstance(item._nested, PathNested)
    assert item._nested._score.get() == 42
    assert item._postgresqlRuntimeValues['runtimeOnly'] == 99
    assert not hasattr(item, 'runtimeOnly')


def test_PerHydratorIndexesCannotLeakAcrossSchemas():
    first = makeHydrator({'_a.value': 'Integer'})
    second = makeHydrator({'_b.value': 'Integer'})
    assert first._hasNestedPaths('_a')
    assert not first._hasNestedPaths('_b')
    assert second._hasNestedPaths('_b')
    assert not second._hasNestedPaths('_a')
