"""Regression coverage for optional fields appearing in later Set items."""
from pyworkflow.object import Integer, Object, String

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


def item_with_optional_object(include_optional):
    item = Object()
    item._optional = None
    item._name = String("particle")
    if include_optional:
        item._optional = Object()
        item._optional._value = Integer(185)
    return item


def columns_for(mapper, item):
    values = mapper._getItemValues(item)
    schema = mapper._getCompleteItemSchema(item, itemValues=values)
    return mapper._getSetColumns(schema)


def test_LateOptionalObjectPreservesExistingAliasesAndPositions():
    mapper = ScipionSetPostgresqlMapper(db=object())
    stored = columns_for(mapper, item_with_optional_object(False))
    discovered = columns_for(mapper, item_with_optional_object(True))
    stored_by_label = {column["labelProperty"]: dict(column) for column in stored}

    merged = mapper._mergeRuntimeColumns(discovered, stored)
    names = [column["columnName"] for column in merged]
    assert len(names) == len(set(names))
    assert any(column["labelProperty"] not in stored_by_label for column in merged)
    for column in merged:
        previous = stored_by_label.get(column["labelProperty"])
        if previous:
            assert column["columnName"] == previous["columnName"]
            assert column["position"] == previous["position"]
            assert column["indexed"] == previous["indexed"]
        else:
            assert column["position"] > max(c["position"] for c in stored)
    assert stored_by_label == {column["labelProperty"]: column for column in stored}


def test_SparseExistingAliasesDoNotCollideWithNewFields():
    stored = [dict(labelProperty="_name", columnName="c01", position=0, indexed=True)]
    discovered = [
        dict(labelProperty="_optional._value", columnName="c00", position=0, indexed=False),
        dict(labelProperty="_name", columnName="c01", position=1, indexed=False),
    ]
    merged = ScipionSetPostgresqlMapper._mergeRuntimeColumns(discovered, stored)
    assert merged[0]["columnName"] == "c02"
    assert merged[0]["position"] == 1
    assert merged[1] == stored[0]
