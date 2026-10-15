"""RED 85: expose real per-class particle counts and sampling rate.

A Class2D/Class3D is a nested Set. Its number of particles is NOT the number
of classes in SetOfClasses*. Only persisted child logical tables can establish
per-class membership. These tests protect lazy, bounded, read-only metadata
listing and do not hydrate Scipion objects or fabricate pointer values.
"""
import pytest

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class ReadOnlyDb:
    def __init__(self, rows):
        self.rows = rows
        self.fetch_calls = []
        self.writes = 0

    def fetchAll(self, query, params=None):
        self.fetch_calls.append((query, params))
        return list(self.rows)

    def execute(self, *args, **kwargs):
        self.writes += 1
        raise AssertionError("The pointer-item browser must be read-only")

    def fetchOne(self, *args, **kwargs):
        raise AssertionError("The page must not query one class at a time")


def item(scipion_id, class_name, *, count=None, sampling=None, label=""):
    # Simulate a bounded SQL result with projected metadata columns.
    # Both metadata fields must be sourced by the eventual SQL, not invented.
    return {
        'scipionItemId': scipion_id,
        'itemClassName': class_name,
        'enabled': True,
        'label': label,
        'itemsCount': count,
        'samplingRate': sampling,
    }


def browse(rows, *, output_name='outputClasses', cursor=None, limit=50):
    db = ReadOnlyDb(rows)
    page = ScipionSetPostgresqlMapper(db).listPointerSelectableSetItemsPage(
        projectId=7, protocolDbId=205, outputName=output_name,
        cursor=cursor, limit=limit,
    )
    return page, db


def test_Class2DExposesPersistedPerClassParticleCountAndSampling_RED85():
    page, db = browse([item(3, 'Class2D', count=1520, sampling=2.05, label='Class A')])
    assert page == {
        'items': [{
            'scipionItemId': 3, 'name': 'Class A', 'enabled': True,
            'itemClassName': 'Class2D', 'itemsCount': 1520,
            'samplingRate': 2.05,
        }],
        'nextCursor': None,
    }
    assert db.writes == 0
    assert len(db.fetch_calls) == 1


def test_Class3DPreservesDifferentMemberCountsAndIdPaging_RED85():
    # The class ID is NOT an ordinal position. The count is per class.
    page, db = browse([
        item(22, 'Class3D', count=870, sampling=1.25),
        item(47, 'Class3D', count=2340, sampling=1.25),
        item(99, 'Class3D', count=77, sampling=1.25),
    ], cursor='10', limit=2)
    assert [x['scipionItemId'] for x in page['items']] == [22, 47]
    assert [x['itemsCount'] for x in page['items']] == [870, 2340]
    assert [x['samplingRate'] for x in page['items']] == [1.25, 1.25]
    assert page['nextCursor'] == '47'
    sql, params = db.fetch_calls[0]
    assert '"scipionItemId" > %s' in sql
    assert params == (7, 205, 'outputClasses', 10, 3)


def test_EmptyClassHasZeroParticlesButMissingSamplingIsOmitted_RED85():
    page, _ = browse([
        item(1, 'Class2D', count=0, sampling=None),
        item(2, 'Class2D', count=None, sampling=None),
    ])
    assert page['items'][0]['itemsCount'] == 0
    assert 'samplingRate' not in page['items'][0]
    # A missing child table is NOT evidence of an empty class.
    assert 'itemsCount' not in page['items'][1]
    assert 'samplingRate' not in page['items'][1]


def test_InvalidMetadataIsNeverPresentedAsAParticleCountOrSampling_RED85():
    page, _ = browse([
        item(1, 'Class3D', count=-1, sampling=-2),
        item(2, 'Class3D', count=True, sampling=float('nan')),
        item(3, 'Class3D', count='not-a-number', sampling='bad'),
    ])
    for member in page['items']:
        assert 'itemsCount' not in member
        assert 'samplingRate' not in member


def test_ClassMetadataSQLIsScopedBoundedAndCountsPersistedChildren_RED85():
    page, db = browse([item(1, 'Class2D', count=5, sampling=2.05)], limit=25)
    assert page['items'][0]['scipionItemId'] == 1
    assert len(db.fetch_calls) == 1
    sql, params = db.fetch_calls[0]
    normalized = ' '.join(sql.split()).lower()
    # Class membership is represented by nested logical-table rows.
    assert 'scipion_set_tables' in normalized
    assert 'scipion_set_table_items' in normalized
    assert 'parentitemid' in normalized
    assert 'count(' in normalized
    # Sampling comes from persisted metadata, not expensive runtime hydration.
    assert '_samplingrate' in normalized or "'samplingrate'" in normalized
    assert 'stored_set.properties' in normalized
    assert 'scipion_set_items' in normalized
    assert 'runtimeReserved'.lower() in normalized
    assert 'limit %s' in normalized
    assert ' offset ' not in f' {normalized} '
    assert 'select *' not in normalized
    assert 'item."values"' not in normalized
    assert params == (7, 205, 'outputClasses', 26)
    assert db.writes == 0


def test_LegacyNonClassMemberResponseKeepsMetadataOnlyContract_RED85_baseline():
    page, db = browse([item(12, 'Volume', label='Reference volume')], output_name='outputVolumes')
    assert page == {
        'items': [{
            'scipionItemId': 12,
            'name': 'Reference volume',
            'enabled': True,
            'itemClassName': 'Volume',
        }],
        'nextCursor': None,
    }
    assert db.writes == 0
    assert len(db.fetch_calls) == 1
