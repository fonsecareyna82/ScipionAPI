"""SCIPIONAPI_SINGLE_ITEM_STORAGE=1 stores a Set's items once: no copies in its root logical table, and every
reader sees what it saw with them."""
from tests.integration.db.test_root_rows_from_set_items import _micrographs, _whatReadersSee
from tests.integration.db.test_stored_set_copies import (  # noqa: F401 (fixture)
    POLICIES, _particles, _stored, _union, copyContext)

# What two Sets of the same items share: the signature of the values also holds their creation times
SHARED = ("count", "rows", "byId", "sorted", "position", "enabledFirst", "tableItems")


def _rootCopies(db, setId):
    row = db.fetchOne('SELECT COUNT(*) AS count FROM scipion_set_table_items ti JOIN scipion_set_tables t '
                      'ON t.id = ti."tableId" WHERE t."setId" = %s AND t."tableKind" = \'root\'', (int(setId),))
    return int(row["count"])


def test_ItemsAreStoredOnceAndReadTheSame(copyContext, monkeypatch):
    db = copyContext["db"]
    withCopies = _micrographs(copyContext)
    monkeypatch.setenv("SCIPIONAPI_SINGLE_ITEM_STORAGE", "1")
    once = _micrographs(copyContext)

    assert _rootCopies(db, withCopies["id"]) == 4
    assert _rootCopies(db, once["id"]) == 0
    before, after = _whatReadersSee(db, withCopies)[1], _whatReadersSee(db, once)[1]
    assert {key: before[key] for key in SHARED} == {key: after[key] for key in SHARED}
    assert after["outputChecks"]["rootTableItemsCount"] == 4
    assert after["outputChecks"]["rootTableItemsIdSignature"] == before["outputChecks"]["rootTableItemsIdSignature"]


def test_WholeSetCopiesStoreItemsOnce(copyContext, tmp_path, monkeypatch):
    monkeypatch.setenv("SCIPIONAPI_SINGLE_ITEM_STORAGE", "1")
    db = copyContext["db"]
    stack = str(tmp_path / "particles.mrcs")
    sources = [_particles(copyContext, range(1, 31), stack), _particles(copyContext, range(20, 41), stack)]
    fast, fastInfo, copied = _union(copyContext, sources, True, **POLICIES[0])
    slow, slowInfo, _ = _union(copyContext, sources, False, **POLICIES[0])

    assert copied
    stored = _stored(db, fastInfo, fast)
    assert stored == _stored(db, slowInfo, slow)
    assert len(stored[0]) == 51 and stored[1] == []
    assert _rootCopies(db, fastInfo["setId"]) == 0
