"""Schema plans preserve native hooks and per-row object construction."""

import pytest
from pyworkflow.object import Integer, Object, String

from app.backend.mapper.postgresql_scipion_item_hydrator import (
    PostgresqlScipionItemHydrator,
)


class PlanNested(Object):
    def __init__(self):
        super().__init__()
        self._a = Integer()
        self._b = String()


class PlanItem(Object):
    def __init__(self):
        super().__init__()
        self._name = String()
        self._nested = None


def hydrator(itemClass=PlanItem, hydratorClass=PostgresqlScipionItemHydrator):
    return hydratorClass(
        itemClassName=itemClass.__name__,
        columns=[
            {"labelProperty": path, "className": cls}
            for path, cls in {
                "self": itemClass.__name__,
                "_name": "String",
                "_nested": "PlanNested",
                "_nested._a": "Integer",
                "_nested._b": "String",
            }.items()
        ],
        classes={itemClass.__name__: itemClass, "PlanNested": PlanNested},
    )


@pytest.mark.parametrize("values", [
    {},
    {"self": None, "_name": "absent"},
    {"_nested._b": "last", "_nested._a": "42", "_nested": None},
    {"_nested._a": 0},
    {"_nested._a": None, "_nested._b": None},
    {"_nested._a": 7, "unknown.path": 9},
    {"_nested._a": 7, 3: "unknown"},
])
def test_PlannedRowsMatchGenericHydrationAndPreserveAbsence(values):
    planned, generic = hydrator(), hydrator()
    original = generic._setAttributeValue
    generic._setAttributeValue = lambda **kwargs: original(**kwargs)
    row = {"scipionItemId": 13, "values": values}
    actual, expected = planned.build(row), generic.build(row)
    assert actual.getObjDict() == expected.getObjDict()
    assert actual._postgresqlRuntimeValues == expected._postgresqlRuntimeValues
    assert (actual._nested is None) == (expected._nested is None)
    absent = planned.build({"scipionItemId": 14, "values": {"_name": "next"}})
    assert absent._nested is None
    assert actual.getObjDict() == expected.getObjDict()


def test_ParentDescriptorsAndNativeSettersAreResolvedForEveryPath():
    def run(generic):
        events = []

        class DescriptorItem(PlanItem):
            def __init__(self):
                super().__init__()
                self._backing = PlanNested()
                first = self._backing
                setter = first._a.set

                def replaceParent(value):
                    events.append(("set", value))
                    setter(value)
                    self._backing = PlanNested()

                first._a.set = replaceParent
                self.first = first

            @property
            def _nested(self):
                events.append("get-parent")
                return self._backing

            @_nested.setter
            def _nested(self, value):
                self._backing = value

        reader = hydrator(DescriptorItem)
        if generic:
            original = reader._setAttributeValue
            reader._setAttributeValue = lambda **kwargs: original(**kwargs)
        item = reader.build({"values": {
            "_nested": None, "_nested._a": 42, "_nested._b": "fresh",
        }})
        assert item.first._a.get() == 42
        assert item.first._b.get() is None
        assert item._backing._a.get() is None
        assert item._backing._b.get() == "fresh"
        return events

    assert run(False) == run(True)


@pytest.mark.parametrize("scope", ["instance", "subclass", "class"])
def test_CustomAttributeHydrationHooksKeepParentFirstCalls(monkeypatch, scope):
    calls = []
    original = PostgresqlScipionItemHydrator._setAttributeValue

    def hook(self, item, path, value):
        calls.append(path)
        return original(self, item=item, path=path, value=value)

    if scope == "subclass":
        class CustomHydrator(PostgresqlScipionItemHydrator):
            _setAttributeValue = hook
        reader = hydrator(hydratorClass=CustomHydrator)
    else:
        reader = hydrator()
        if scope == "class":
            monkeypatch.setattr(PostgresqlScipionItemHydrator, "_setAttributeValue", hook)
        else:
            monkeypatch.setattr(reader, "_setAttributeValue", hook.__get__(reader))
    item = reader.build({"values": {"_nested._a": 42, "_nested": None}})
    assert calls == ["_nested", "_nested._a"]
    assert item._nested._a.get() == 42


def test_CustomNestedPathHookStillControlsNativeSetter(monkeypatch):
    events = []

    class TracedNested(PlanNested):
        def __init__(self):
            super().__init__()
            events.clear()  # Observe hydration rather than Object construction.

        def set(self, value):
            events.append(value)
            super().set(value)

    reader = hydrator()
    reader.classes["PlanNested"] = TracedNested
    monkeypatch.setattr(reader, "_hasNestedPaths", lambda path: False)
    item = reader.build({"values": {"_nested": None, "_nested._a": 4}})
    assert events == [None]
    assert item._nested._a.get() == 4


def test_PlansResolveMissingAttributeClassesAtConsumptionTime():
    reader = hydrator()
    first = reader.build({"values": {"_nested._a": 1}})

    class NewNested(PlanNested):
        pass

    reader.classes["PlanNested"] = NewNested
    second = reader.build({"values": {"_nested._a": 2}})
    assert type(first._nested) is PlanNested
    assert type(second._nested) is NewNested
    assert first._nested._a.get() == 1
    assert second._nested._a.get() == 2


def test_NativeSetterErrorsPropagateWithoutApplyingLaterPaths():
    failure = ValueError("invalid plugin value")
    events = []

    class StrictItem(PlanItem):
        def __init__(self):
            super().__init__()

            def reject(value):
                events.append(value)
                raise failure

            self._name.set = reject

    reader = hydrator(StrictItem)
    with pytest.raises(ValueError) as caught:
        reader.build({"values": {"_name": "bad", "_nested._a": 7}})
    assert caught.value is failure
    assert events == ["bad"]
