import pytest

from app.backend.api.services.compare_protocols import compare
from app.backend.api.services.subset_by_values import MAX_ROWS, SubsetError, meets, plan


def described(pid, params, outputs, run=None, inputs=()):
    return {"protocolId": pid, "label": "picking %s" % pid, "protocol": "cryolo picking", "className": "P",
            "status": "finished", "params": [{"name": name, "label": name.title(), "section": "Input", "value": value}
                                              for name, value in params.items()],
            "outputs": [{"name": name, "type": "SetOfCoordinates", "size": size} for name, size in outputs.items()],
            "run": run, "inputs": list(inputs)}


def test_ComparisonShowsOnlyWhatDiffers():
    found = compare([
        described("10", {"runName": "a", "threshold": "0.3", "box": "184"}, {"outputCoordinates": 3487},
                  {"started": "2026-11-12T12:00:00", "ended": "2026-11-12T12:30:00"},
                  [{"protocolId": "9", "output": "outputMicrographs"}]),
        described("16", {"runName": "b", "threshold": "0.4", "box": "184"}, {"outputCoordinates": 3885}),
    ])
    assert [item["name"] for item in found["parameters"]] == ["threshold"]
    assert found["parameters"][0]["values"] == {"10": "0.3", "16": "0.4"}
    assert found["same"] == 1
    assert found["outputs"] == [{"output": "outputCoordinates (SetOfCoordinates)", "sizes": {"10": 3487, "16": 3885}}]
    assert found["protocols"][0]["minutes"] == 30.0 and found["protocols"][1]["minutes"] is None
    assert found["inputs"] == {"10": ["#9 outputMicrographs"], "16": []}


def test_AParameterOnlyOneHasDiffers():
    found = compare([described("1", {"a": "1"}, {}), described("2", {}, {})])
    assert found["parameters"][0]["values"] == {"1": "1", "2": ""}


SCHEMA = {"columns": [{"name": "id"}, {"name": "enabled"}, {"name": "_resolution"}, {"name": "_label"}],
          "actions": ["CTFModel", "Micrographs"]}
ROWS = [{"id": i, "values": [i, True, res, label]}
        for i, res, label in [(1, 3.1, "good"), (2, 3.6, "good"), (3, 2.9, "bad"), (4, "None", "good")]]


def pages(rows, total=None):
    def read(page, size):
        return {"totalRows": len(rows) if total is None else total, "rows": rows[(page - 1) * size: page * size]}
    return read


def test_KeepsTheRowsMeetingEveryCondition():
    chosen = plan(SCHEMA, pages(ROWS), [{"column": "_resolution", "op": "<", "value": "3.4"},
                                        {"column": "_label", "op": "=", "value": "good"}], None)
    assert chosen["kept"] == [1] and chosen["removed"] == [2, 3, 4] and chosen["total"] == 4
    assert chosen["action"] == "CTFModel" and chosen["actions"] == ["CTFModel", "Micrographs"]
    assert chosen["examples"][0] == {"_resolution": 3.6, "_label": "good", "id": 2}


def test_ValuesCompareAsNumbersOrText():
    assert meets("3.5", {"op": "<", "value": "4"})
    assert not meets("None", {"op": "<", "value": "4"})
    assert meets(True, {"op": "=", "value": "yes"})
    assert meets("Good", {"op": "!=", "value": "bad"})
    assert not meets("abc", {"op": ">", "value": "aaa"})


@pytest.mark.parametrize("conditions, action, said", [
    ([], None, "at least one condition"),
    ([{"column": "_nothing", "op": "<", "value": "1"}], None, "no column _nothing"),
    ([{"column": "_resolution", "op": "~", "value": "1"}], None, "Unknown operator"),
    ([{"column": "_resolution", "op": "<", "value": "3"}], "Volumes", "one of: CTFModel, Micrographs"),
    ([{"column": "_resolution", "op": "<", "value": "1"}], None, "nothing would be kept"),
])
def test_WhatCannotBeDoneIsSaid(conditions, action, said):
    with pytest.raises(SubsetError) as error:
        plan(SCHEMA, pages(ROWS), conditions, action)
    assert said in str(error.value)


def test_ReadsEveryPageButRefusesHugeTables():
    many = [{"id": i, "values": [i, True, 3.0, "good"]} for i in range(1, 12001)]
    assert len(plan(SCHEMA, pages(many), [{"column": "_resolution", "op": "<", "value": "4"}], None)["kept"]) == 12000
    with pytest.raises(SubsetError):
        plan(SCHEMA, pages(ROWS, total=MAX_ROWS + 1), [{"column": "_resolution", "op": "<", "value": "4"}], None)
