"""Stored Sets answer the id IN (...) filters streaming consumers load their batches with."""
from tests.integration.db.test_stored_set_copies import copyContext, _particles  # noqa: F401 (fixture)


def test_StoredSetIteratesOnlyTheItemsOfAnIdList(copyContext, tmp_path):
    particles = _particles(copyContext, range(1, 7), str(tmp_path / "stack.mrcs"))

    ids = [item.getObjId() for item in particles.iterItems(where="id IN (5,2,4)")]

    assert ids == [2, 4, 5]


def test_AnIdListCombinesWithOtherConditions(copyContext, tmp_path):
    particles = _particles(copyContext, range(1, 7), str(tmp_path / "stack.mrcs"))

    ids = [item.getObjId() for item in particles.iterItems(where="id > 3 AND id IN (1,4,6)")]

    assert ids == [4, 6]
