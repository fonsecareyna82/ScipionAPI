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


def test_OnlyTheLibrariesThereAndPythonsOwnModulesMayBeImported():
    ctf = [{"protocolId": "46"}]
    allowed = ("import csv, json, os.path\nfrom collections import Counter\nimport numpy as np\n"
               "from scipy import ndimage\nimport mrcfile\nimport matplotlib.pyplot as plt\n")
    assert _plan(ctf, script=allowed)["script"] == allowed
    with pytest.raises(ProposalError, match="imports pandas, which it cannot use"):
        _plan(ctf, script="import numpy\nimport pandas as pd\n")
    with pytest.raises(ProposalError, match="imports nosuchmodule, torch"):
        _plan(ctf, script="from torch import nn\nimport nosuchmodule\n")


def test_ANewLineWrittenAsABackslashAndAnNIsSentBack():
    ctf = [{"protocolId": "46"}]
    good = "open('output/keep_1.txt', 'w').write('\\n'.join(['16', '17']) + '\\n')\n"
    assert _plan(ctf, script=good)["script"] == good
    twice = "ids = [16, 17]\nopen('output/keep_1.txt', 'w').write('\\\\n'.join(map(str, ids)))\n"
    with pytest.raises(ProposalError, match="Line 2 of the script writes a backslash and an n"):
        _plan(ctf, script=twice)
    inFString = "x = 3\nprint(f'mean {x}\\\\n')\n"
    with pytest.raises(ProposalError, match="Line 2"):
        _plan(ctf, script=inFString)


CTF_COLUMNS = ["id", "enabled", "_defocusU", "_defocusV", "_astigmatism", "_resolution", "_micObj._filename"]


def test_TheColumnsOfEachSetAreGivenAndTheScriptMayOnlyNameThose():
    columnsOf = lambda pid, output: CTF_COLUMNS if output == "outputCTF" else None  # noqa: E731
    good = ("keep = [row['id'] for row in rows(0) if row['_defocusU'] < 15000 and row['_astigmatism'] < 44]\n"
            "open('output/keep_1.txt', 'w').write('\\n'.join(map(str, keep)))\n")
    data = assistant_custom.plan([{"protocolId": "46"}], good, "Keeps some", "Op", True, ROWS.get,
                                 lambda pid: OUTPUTS.get(pid, []), columnsOf)
    assert data["inputs"][0]["columns"] == ["id", "_defocusU", "_defocusV", "_astigmatism", "_resolution",
                                            "_micObj._filename"]
    wrong = "keep = [row['id'] for row in rows(0) if row['_defocus_u'] < 15000]\n"
    with pytest.raises(ProposalError, match="reads _defocus_u, which no input has. Input 0 \\(SetOfCTF\\) has: id, "
                                            "_defocusU"):
        assistant_custom.plan([{"protocolId": "46"}], wrong, "x", "Op", True, ROWS.get,
                              lambda pid: OUTPUTS.get(pid, []), columnsOf)
    # With an input whose values are not known (a volume), nothing is checked
    mixed = assistant_custom.plan([{"protocolId": "46"}, {"protocolId": "45", "output": "outputVolume"}], wrong,
                                  "x", "Op", True, ROWS.get, lambda pid: OUTPUTS.get(pid, []), columnsOf)
    assert mixed["inputs"][1].get("columns") is None


def test_3DCoordinatesGetTheirCornerColumns():
    assert assistant_custom._columns(["id", "_x", "_y", "_z", "_tomoId"])[-3:] == ["x_px", "y_px", "z_px"]
