"""Refilled items must be indistinguishable from freshly built ones."""
import random

import numpy as np
from pwem import objects as emobj
from pyworkflow.object import Float, Integer, List, Object, Pointer, String

from app.backend.mapper.postgresql_scipion_item_hydrator import PostgresqlScipionItemHydrator
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper

CLASSES = {name: cls for name, cls in vars(emobj).items() if isinstance(cls, type)}


def particle(itemId, ctf=True, transform=True, coordinate=True, late=False):
    item = emobj.Particle()
    item.setObjId(itemId)
    item.setLocation(itemId, "particles.mrcs")
    item.setSamplingRate(1.25)
    item.setClassId(itemId % 3)
    if ctf:
        model = emobj.CTFModel()
        model.setStandardDefocus(12000.0 + itemId, 11800.0 + itemId, itemId % 90)
        item.setCTF(model)
    if transform:
        matrix = np.eye(4)
        matrix[0, 3] = itemId
        item.setTransform(emobj.Transform(matrix=matrix))
    if coordinate:
        position = emobj.Coordinate()
        position.setPosition(itemId, 2 * itemId)
        item.setCoordinate(position)
    if late:
        item._lateScore = Float(itemId / 4.0)
    return item


def rowsFor(items, mapper):
    rows, schema = [], {}
    for index, item in enumerate(items):
        serialized = mapper.serializeRuntimeItem(item)
        schema.update(serialized["_schema"])
        rows.append({
            "scipionItemId": serialized["scipionItemId"],
            "enabled": index % 5 != 0,
            "label": "particle-%s" % serialized["scipionItemId"] if index % 2 else "",
            "comment": "kept" if index % 3 else None,
            "creation": "2026-10-13 10:00:%02d" % (index % 60) if index % 4 else None,
            "values": serialized["values"],
        })
    return rows, mapper._getSetColumns(schema)


def snapshot(item):
    return (
        item.getObjId(), item.getObjLabel(), item.getObjComment(), item.isEnabled(),
        item.getObjCreation(), item.getObjDict(includeClass=True),
        item.hasCTF(), item.hasTransform(), item.hasCoordinate(),
        item._postgresqlRuntimeValues,
        sorted(name for name, value in vars(item).items() if isinstance(value, Object)),
    )


def iterateLikeMapper(hydrator, rows):
    previous, refills = None, 0
    for row in rows:
        item = hydrator.refill(previous, row) if previous is not None else None
        if item is None:
            item = hydrator.build(row)
        else:
            refills += 1
        yield item, refills
        previous = item


def test_RefilledParticlesMatchFreshBuildsAcrossMixedRows():
    mapper = ScipionSetPostgresqlMapper(db=None)
    items = []
    for itemId in range(1, 301):
        shape = itemId % 7
        items.append(particle(itemId, ctf=shape != 1, transform=shape != 2,
                              coordinate=shape != 3, late=shape in (4, 5)))
    # Long same-shape runs as in real Sets, with shape changes in between.
    items.sort(key=lambda item: (item.getObjId() // 50, item.getObjId() % 7))
    rows, columns = rowsFor(items, mapper)
    random.Random(7).shuffle(rows[200:])
    hydrator = PostgresqlScipionItemHydrator("Particle", columns, classes=CLASSES)
    reference = PostgresqlScipionItemHydrator("Particle", columns, classes=CLASSES)

    refills = 0
    for (item, refills), row in zip(iterateLikeMapper(hydrator, rows), rows):
        assert snapshot(item) == snapshot(reference.build(row))
    # Rows vary in optional metadata too, so only part of them can refill.
    assert refills > 100


def test_RowShapeChangeBuildsAFreshItem():
    mapper = ScipionSetPostgresqlMapper(db=None)
    rows, columns = rowsFor([particle(1), particle(2, ctf=False), particle(3)], mapper)
    hydrator = PostgresqlScipionItemHydrator("Particle", columns, classes=CLASSES)
    first = hydrator.build(rows[0])

    assert hydrator.refill(first, rows[1]) is None
    second = hydrator.build(rows[1])
    assert not second.hasCTF()
    assert hydrator.refill(second, rows[2]) is None
    # Same paths and metadata shape: the item is refilled in place.
    third = hydrator.build(rows[2])
    assert hydrator.refill(third, dict(rows[2], scipionItemId=9)) is third
    assert third.getObjId() == 9


class PointerItem(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._value = Integer()
        self._source = Pointer()


class ListItem(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._names = List()


class PropertyItem(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._backing = String()

    @property
    def _label(self):
        return self._backing


def columnsFor(*pairs):
    return [{"labelProperty": label, "className": className} for label, className in pairs]


def test_PointersListsAndClassAttributesAreNeverRefilled():
    classes = {"PointerItem": PointerItem, "ListItem": ListItem, "PropertyItem": PropertyItem,
               "Integer": Integer, "Pointer": Pointer, "List": List, "String": String}
    cases = [
        ("PointerItem", columnsFor(("_value", "Integer"), ("_source", "Pointer")),
         {"_value": 1, "_source": None}),
        ("ListItem", columnsFor(("_names", "List"), ("_names.__item__000001", "String")),
         {"_names": None, "_names.__item__000001": "a"}),
        ("PropertyItem", columnsFor(("_label", "String")), {"_label": "x"}),
    ]
    for className, columns, values in cases:
        hydrator = PostgresqlScipionItemHydrator(className, columns, classes=classes)
        row = {"scipionItemId": 1, "values": values}
        item = hydrator.build(row)
        assert hydrator.refill(item, dict(row, scipionItemId=2)) is None, className


def test_CustomHydratorHooksDisableRefill():
    mapper = ScipionSetPostgresqlMapper(db=None)
    rows, columns = rowsFor([particle(1), particle(2)], mapper)

    class CustomHydrator(PostgresqlScipionItemHydrator):
        pass

    for hydrator in (CustomHydrator("Particle", columns, classes=CLASSES),
                     PostgresqlScipionItemHydrator("Particle", columns, classes=CLASSES)):
        if type(hydrator) is PostgresqlScipionItemHydrator:
            original = hydrator._setAttributeValue
            hydrator._setAttributeValue = lambda **kwargs: original(**kwargs)
        assert hydrator.refill(hydrator.build(rows[0]), rows[1]) is None


def test_NestedSetItemsAreNeverRefilled():
    columns = columnsFor(("_samplingRate", "Float"))
    hydrator = PostgresqlScipionItemHydrator("Class2D", columns, classes=CLASSES)
    row = {"scipionItemId": 1, "values": {"_samplingRate": 1.0}}
    assert hydrator.refill(hydrator.build(row), dict(row, scipionItemId=2)) is None
