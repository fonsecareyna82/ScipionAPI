"""The acquisitions of a project and the branch of each one."""
from app.backend.api.services import stream_branches as branches


def output(setId, protocolId, outputName="out", streaming=True, items=10):
    return {"setId": setId, "stage": "movies", "protocolId": protocolId, "outputName": outputName, "label": "run %s" % protocolId,
            "items": items, "streaming": streaming}


# Import A (1) -> align (2) -> CTF (3); import B (11) -> align (12) -> CTF (13); a union (20) of both CTFs ->
# picking (21); a reference imported on its own (30)
INPUTS = {"2": [("1", "out")], "3": [("2", "out")], "12": [("11", "out")], "13": [("12", "out")],
          "20": [("3", "out"), ("13", "out")], "21": [("20", "out")]}
OUTPUTS = [output(setId, protocolId) for setId, protocolId in
           ((10, "1"), (20, "2"), (30, "3"), (110, "11"), (120, "12"), (130, "13"), (200, "20"), (210, "21"),
            (300, "30"))]
A, B = OUTPUTS[0], OUTPUTS[3]


def test_a_branch_is_the_import_and_what_was_made_from_it_with_what_comes_after_a_union():
    assert branches.branchProtocols(INPUTS, "1") == {"1", "2", "3", "20", "21"}
    assert branches.branchProtocols(INPUTS, "11") == {"11", "12", "13", "20", "21"}


def test_outputs_made_from_no_acquisition_belong_to_every_branch():
    ofA = branches.branchOutputs(OUTPUTS, INPUTS, A, [A, B])

    assert [item["setId"] for item in ofA] == [10, 20, 30, 200, 210, 300]
    assert branches.branchOutputs(OUTPUTS, INPUTS, None, [A, B]) == OUTPUTS


def test_an_import_reads_none_of_the_outputs_followed():
    assert branches.readsNone(OUTPUTS, INPUTS, A)
    assert not branches.readsNone(OUTPUTS, INPUTS, OUTPUTS[1])


def test_the_one_asked_for_is_followed_else_the_open_one_that_received_something_last():
    closedNewer = dict(B, streaming=False)
    last = {10: "2026-10-28T10:00:00+00:00", 110: "2026-10-28T11:00:00+00:00"}

    assert branches.followedAcquisition([A, B], last, 10) is A
    assert branches.followedAcquisition([A, B], last, None) is B
    assert branches.followedAcquisition([A, closedNewer], last, None) is A
    assert branches.followedAcquisition([], last, None) is None


def test_the_bell_looks_at_every_open_acquisition_or_at_the_one_followed():
    last = {10: "2026-10-28T10:00:00+00:00", 110: "2026-10-28T11:00:00+00:00"}
    many = [output(setId, str(setId)) for setId in range(1, 9)]

    assert branches.alertAcquisitions([A, B], last) == [B, A]
    assert len(branches.alertAcquisitions(many, {})) == branches.MAX_ALERT_BRANCHES
    closed = [dict(A, streaming=False), dict(B, streaming=False)]
    assert branches.alertAcquisitions(closed, last) == [closed[1]]


def test_each_acquisition_says_what_it_imports():
    described = branches.describeAcquisitions([B, A], {10: "t"})

    assert [(item["setId"], item["stage"], item["lastItemAt"]) for item in described] == [
        (10, "movies", "t"), (110, "movies", None)]
