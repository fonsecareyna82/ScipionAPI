"""Stored Sets of classes say whether their classes have representatives, as native Sets do."""
import pytest
from pwem import objects as emobj

from tests.integration.db.test_stored_set_copies import _particles, copyContext  # noqa: F401 (fixture)


def _fillByClassify(classes, stack):
    def assign(item, row):
        item.setClassId(item.getObjId() % 2 + 1)

    def representative(classItem):
        classItem.getRepresentative().setLocation(classItem.getObjId(), stack)

    classes.classifyItems(updateItemCallback=assign, updateClassCallback=representative)


def _fillWithoutRepresentatives(classes, stack):
    for classId in (1, 2):
        classes.append(emobj.Class2D(objId=classId))


@pytest.mark.parametrize("fill, expected", [(_fillByClassify, True), (_fillWithoutRepresentatives, False)])
def test_StoredClassesSayWhetherTheyHaveRepresentativesAsNativeOnes(copyContext, tmp_path, fill, expected):
    stack = str(tmp_path / "averages.mrcs")
    particles = _particles(copyContext, range(1, 7), str(tmp_path / "particles.mrcs"))

    native = emobj.SetOfClasses2D(filename=str(tmp_path / "classes.sqlite"))
    native.setImages(particles)
    fill(native, stack)
    native.write()
    classes, info = copyContext["reserve"](emobj.SetOfClasses2D())
    classes.setImages(particles)
    fill(classes, stack)
    stored = copyContext["finalize"](classes, info)

    assert native.hasRepresentatives() is expected
    assert stored.hasRepresentatives() is expected, "writeStack and the averages consumers rely on this mark"
