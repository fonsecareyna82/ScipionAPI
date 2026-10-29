"""The shape learnt from the first item of a Set never changes what any item stores."""
import json

import numpy as np
from pwem import objects as emobj
from pyworkflow.object import CsvList, Float, Integer, Pointer, String

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class NoPlans(dict):
    """Every class without a learnt shape: each item takes the general walk."""

    def get(self, key, default=None):
        return [None, 0, 0]


def particle(particleId):
    item = emobj.Particle()
    item.setObjId(particleId)
    item.setLocation(particleId, "particles.mrcs")
    item.setSamplingRate(1.25)
    coordinate = emobj.Coordinate()
    coordinate.setPosition(particleId % 400, particleId % 300)
    item.setCoordinate(coordinate)
    ctf = emobj.CTFModel()
    ctf.setStandardDefocus(12000.0 + particleId, 11800.0, 45.0)
    item.setCTF(ctf)
    matrix = np.eye(4)
    matrix[0, 3] = particleId
    item.setTransform(emobj.Transform(matrix=matrix))
    return item


def serialized(items, plans):
    mapper = ScipionSetPostgresqlMapper(db=None)
    if not plans:
        mapper._itemGraphPlans = NoPlans()
    # JSON keeps the key order and compares NaN as the same text
    return mapper, [json.dumps([row["values"], sorted(row["_schema"].items())], default=str)
                    for row in (mapper.serializeRuntimeItem(item) for item in items)]


def assertSameAsGeneralWalk(items):
    mapper, planned = serialized(items, plans=True)
    _, general = serialized(items, plans=False)
    assert planned == general
    return mapper._itemGraphPlans


def test_ItemsOfOneShapeUseTheLearntShapeAndStoreTheSame():
    items = [particle(index) for index in range(1, 51)]
    items[7].getCTF().setResolution(float("nan"))
    items[9].setClassId(None)

    plans = assertSameAsGeneralWalk(items)

    plan, hits, misses = plans[emobj.Particle]
    assert plan is not None and hits == 49 and misses == 0


def test_ItemsOfAnotherShapeTakeTheGeneralWalk():
    items = [particle(index) for index in range(1, 13)]
    items[1]._extra = String("only here")                    # one more attribute
    items[2].getCTF()._objDoStore = False                    # a stored object that is no longer stored
    items[3]._ctfModel = None                                 # an object replaced by a plain value
    items[4]._coordinate._objIsPointer = True                 # a child that became a pointer
    items[5]._micName = items[5]._filename                    # a sub-object shared by two attributes
    items[6]._samplingRate = Integer(2)                       # another class for an attribute
    items[7]._acquisition = Pointer()                         # a pointer where an object was
    del items[8]._coordinate                                  # one attribute less
    items[9].getTransform().__dict__.pop("_objDoStore")       # an object without its storage flag

    plans = assertSameAsGeneralWalk(items)

    _, hits, misses = plans[emobj.Particle]
    assert misses == 9 and hits == 2


def test_ListsAndFailingGettersKeepTheGeneralBehaviour():
    class Failing(Float):
        def getObjValue(self):
            if self._objValue == 3.0:
                raise ValueError("cannot read")
            return Float.getObjValue(self)

    items = []
    for index in range(1, 6):
        item = particle(index)
        item._ids = CsvList()
        item._ids.set([index, index + 1])
        item._failing = Failing(float(index))
        items.append(item)

    assertSameAsGeneralWalk(items)


def test_EachClassLearnsItsOwnShape():
    class Picked(emobj.Particle):
        pass

    items = []
    for index in range(1, 7):
        item = particle(index) if index % 2 else Picked()
        if index % 2 == 0:
            item.setObjId(index)
            item.setLocation(index, "picked.mrcs")
        items.append(item)

    plans = assertSameAsGeneralWalk(items)

    assert plans[emobj.Particle][1] == 2 and plans[Picked][1] == 2


def test_AClassWhoseItemsKeepChangingStopsUsingItsShape():
    items = []
    for index in range(1, 81):
        item = particle(index)
        if index > 1:
            setattr(item, "_extra%d" % index, String("x"))
        items.append(item)

    plans = assertSameAsGeneralWalk(items)

    assert plans[emobj.Particle][0] is None
