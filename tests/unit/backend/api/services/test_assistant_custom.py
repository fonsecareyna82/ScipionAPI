import pytest

from app.backend.api.services import assistant_custom
from app.backend.api.services.assistant_actions import ProposalError

ROWS = {"45": {"protocolId": "45", "label": "refine", "status": "finished"},
        "46": {"protocolId": "46", "label": "ctffind", "status": "finished"},
        "47": {"protocolId": "47", "label": "running one", "status": "running"},
        "48": {"protocolId": "48", "label": "nothing", "status": "finished"}}
OUTPUTS = {"45": [{"outputName": "outputVolume", "setClassName": "Volume", "size": None},
                  {"outputName": "outputParticles", "setClassName": "SetOfParticles", "size": 1200}],
           "46": [{"outputName": "outputCTF", "setClassName": "SetOfCTF", "size": 300}],
           "47": [{"outputName": "outputVolume", "setClassName": "Volume"}]}
SCRIPT = "print('ok')\n"


def _plan(inputs, script=SCRIPT, operation="Does it", canRun=True, title="Op"):
    return assistant_custom.plan(inputs, script, operation, title, canRun, ROWS.get, lambda pid: OUTPUTS.get(pid, []))


def test_AnyOutputsInTheOrderGivenBecomeOneListOfPointers():
    data = _plan([{"protocolId": "#46"}, {"protocolId": "45", "output": "outputVolume"},
                  {"protocolId": "45", "output": "outputParticles"}])
    assert [(item["output"], item["type"], item["size"]) for item in data["inputs"]] == [
        ("outputCTF", "SetOfCTF", 300), ("outputVolume", "Volume", None), ("outputParticles", "SetOfParticles", 1200)]
    protocol = assistant_custom.workflowProtocol(data, 100060)
    assert protocol["object.className"] == "ProtCustomOperation" and protocol["object.id"] == "100060"
    assert protocol["inputs"] == ["46.outputCTF", "45.outputVolume", "45.outputParticles"]
    card = assistant_custom.card(7, data, "because")
    assert card["action"] == "custom" and card["lines"] == 1 and card["label"] == "Op"


@pytest.mark.parametrize("inputs, message", [
    ([], "at least one input"),
    ([{"protocolId": "99"}], "no protocol 99"),
    ([{"protocolId": "47"}], "has not finished"),
    ([{"protocolId": "45"}], "protocol 45. It has: outputVolume, outputParticles"),
    ([{"protocolId": "45", "output": "outputMask"}], "no output called outputMask"),
    ([{"protocolId": "48"}], "has no outputs"),
    ([{"protocolId": "46"}, {"protocolId": "46", "output": "outputCTF"}], "same output is given twice"),
    ([{"protocolId": "46"}] * 11, "At most 10"),
])
def test_WrongInputsAreSaid(inputs, message):
    with pytest.raises(ProposalError, match=message):
        _plan(inputs)


def test_TheScriptAndThePermissionAreChecked():
    ctf = [{"protocolId": "46"}]
    with pytest.raises(ProposalError, match="protocols.customCode"):
        _plan(ctf, canRun=False)
    with pytest.raises(ProposalError, match="empty"):
        _plan(ctf, script="  \n")
    with pytest.raises(ProposalError, match="syntax error in line 2"):
        _plan(ctf, script="x = 1\nif x print(x)\n")
    with pytest.raises(ProposalError, match="plain words"):
        _plan(ctf, operation=" ")
    with pytest.raises(ProposalError, match="too long"):
        _plan(ctf, script="x = 1\n" * 5000)
