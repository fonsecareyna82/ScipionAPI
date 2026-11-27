import pytest

from app.backend.api.services import assistant_custom
from app.backend.api.services.assistant_actions import ProposalError

ROWS = {"45": {"protocolId": "45", "label": "refine", "status": "finished"},
        "46": {"protocolId": "46", "label": "mask", "status": "finished"},
        "47": {"protocolId": "47", "label": "running one", "status": "running"},
        "48": {"protocolId": "48", "label": "two maps", "status": "finished"}}
OUTPUTS = {"45": [{"outputName": "outputVolume", "setClassName": "Volume"},
                  {"outputName": "outputParticles", "setClassName": "SetOfParticles"}],
           "46": [{"outputName": "outputMask", "setClassName": "VolumeMask"}],
           "47": [{"outputName": "outputVolume", "setClassName": "Volume"}],
           "48": [{"outputName": "half1", "setClassName": "Volume"}, {"outputName": "half2", "setClassName": "Volume"}]}
SCRIPT = "print('ok')\n"


def _plan(inputs, script=SCRIPT, operation="Does it", canRun=True, title="Op"):
    return assistant_custom.plan(inputs, script, operation, title, canRun, ROWS.get, lambda pid: OUTPUTS.get(pid, []))


def test_InputsAreFoundByKindAndBecomePointers():
    data = _plan([{"role": "volume", "protocolId": "#45"}, {"role": "particles", "protocolId": "45"},
                  {"role": "mask", "protocolId": "46"}])
    assert [(item["param"], item["output"]) for item in data["inputs"]] == [
        ("inputVolume", "outputVolume"), ("inputParticles", "outputParticles"), ("inputMask", "outputMask")]
    protocol = assistant_custom.workflowProtocol(data, 100060)
    assert protocol["object.className"] == "ProtCustomOperation" and protocol["object.id"] == "100060"
    assert protocol["inputVolume"] == "45.outputVolume" and protocol["inputMask"] == "46.outputMask"
    card = assistant_custom.card(7, data, "because")
    assert card["action"] == "custom" and card["lines"] == 1 and card["title"] == "Op"


def test_AMaskCountsAsAVolume():
    assert _plan([{"role": "volume", "protocolId": "46"}])["inputs"][0]["output"] == "outputMask"


@pytest.mark.parametrize("inputs, message", [
    ([], "at least one input"),
    ([{"role": "map", "protocolId": "45"}], "volume, a mask or particles"),
    ([{"role": "volume", "protocolId": "99"}], "no protocol 99"),
    ([{"role": "volume", "protocolId": "47"}], "has not finished"),
    ([{"role": "volume", "protocolId": "48"}], "protocol 48. It has: half1, half2"),
    ([{"role": "volume", "protocolId": "48", "output": "half3"}], "no volume output called half3"),
    ([{"role": "mask", "protocolId": "45"}], "has no mask output"),
    ([{"role": "volume", "protocolId": "45"}, {"role": "volume", "protocolId": "46"}], "One input of each kind"),
])
def test_WrongInputsAreSaid(inputs, message):
    with pytest.raises(ProposalError, match=message):
        _plan(inputs)


def test_TheScriptAndThePermissionAreChecked():
    volume = [{"role": "volume", "protocolId": "45"}]
    with pytest.raises(ProposalError, match="protocols.customCode"):
        _plan(volume, canRun=False)
    with pytest.raises(ProposalError, match="empty"):
        _plan(volume, script="  \n")
    with pytest.raises(ProposalError, match="syntax error in line 2"):
        _plan(volume, script="x = 1\nif x print(x)\n")
    with pytest.raises(ProposalError, match="plain words"):
        _plan(volume, operation=" ")
    with pytest.raises(ProposalError, match="too long"):
        _plan(volume, script="x = 1\n" * 5000)
