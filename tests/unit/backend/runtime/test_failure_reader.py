"""Why a protocol failed, read from its logs: the error shown, the command, the traceback and the known cause."""
import json
import re

from app.backend.runtime import failure_reader
from app.backend.runtime.failure_reader import HINTS_FILE, explainFailure, knownErrors, matchHint, readTail


def _logs(tmp_path, stdout, stderr=""):
    out, err = tmp_path / "run.stdout", tmp_path / "run.stderr"
    out.write_text(stdout)
    err.write_text(stderr)
    return str(out), str(err)


def test_AProgramThatEndedBadlyShowsWhatTheProgramWroteAndTheKnownCause(tmp_path):
    stdout = ("STARTED: refineStep, step 2\n"
              "** Running command: **\n"
              "\x1b[32m refine_mpi --i particles.star --gpu 0\x1b[0m\n"
              "FAILED: refineStep, step 2, time 2026-11-10\n"
              "\x1b[31mProtocol failed: Command ' refine_mpi --i particles.star' returned non-zero exit status 1.\x1b[0m\n"
              "------------------- PROTOCOL FAILED (DONE 1/2)\n")
    stderr = "Iteration 1 Error: 0.25\nRuntimeError: CUDA error: out of memory\n"
    explained = explainFailure(*_logs(tmp_path, stdout, stderr))

    assert explained["cause"]["id"] == "gpu-out-of-memory"
    assert explained["cause"]["title"] == "The GPU ran out of memory"
    assert explained["error"] == {"text": "RuntimeError: CUDA error: out of memory", "line": 2, "channel": "stderr"}
    assert explained["command"] == {"text": "refine_mpi --i particles.star --gpu 0", "line": 3, "channel": "stdout"}
    # A numeric "Error:" is no error
    assert all("0.25" not in line["text"] for line in explained["errors"])


def test_WhatTheProtocolSaidWinsAndItsMessageMayGoOnInTheNextLines(tmp_path):
    stderr = ("Protocol failed: \n\n > error when importing from a package: No module named 'somepackage'\n"
              "   File \"<frozen importlib._bootstrap>\", line 991, in _find_and_load\n")
    explained = explainFailure(*_logs(tmp_path, "------------------- PROTOCOL FAILED (DONE 1/1)\n", stderr))
    assert explained["error"]["text"] == "error when importing from a package: No module named 'somepackage'"
    assert explained["cause"]["id"] == "python-module-missing"


def test_AProtocolThatDidNotStartSaysWhyItIsNotValid(tmp_path):
    stdout = ("Protocol has validation errors:\n"
              "No files matching the pattern /data/tomos/* were found.\n"
              "------------------- PROTOCOL FAILED (DONE 0/0)\n")
    explained = explainFailure(*_logs(tmp_path, stdout))
    assert explained["error"]["text"] == "No files matching the pattern /data/tomos/* were found."
    assert explained["error"]["line"] == 2
    assert explained["cause"]["id"] == "not-valid"


def test_TheTracebacksExceptionIsShownWhenNothingElseSaysMore(tmp_path):
    stderr = ("Traceback (most recent call last):\n"
              "  File \"/x/protocol.py\", line 10, in run\n"
              "    self.extract()\n"
              "Exception: No particles were extracted!\n")
    explained = explainFailure(*_logs(tmp_path, "", stderr))
    assert explained["error"] == {"text": "Exception: No particles were extracted!", "line": 4, "channel": "stderr"}
    assert len(explained["traceback"]) == 4 and explained["cause"] is None


def test_AWarningFurtherUpNeverHidesTheCause(tmp_path):
    stdout = "WARNING: file /tmp/x does not exist, using default\n" * 3
    stderr = "Segmentation fault (core dumped)\n"
    assert explainFailure(*_logs(tmp_path, stdout, stderr))["cause"]["id"] == "crashed"


def test_NoLogsStillTellTheFailedStepsError(tmp_path):
    explained = explainFailure(None, None, ["Disk quota exceeded writing output"])
    assert explained["error"]["text"] == "Disk quota exceeded writing output"
    assert explained["cause"]["id"] == "disk-full" and not explained["hasLogs"]


def test_OnlyTheEndOfAHugeLogIsReadWithItsLineNumbers(tmp_path):
    path = tmp_path / "big.log"
    path.write_text("".join("line %d\n" % number for number in range(1, 20001)))
    tail = readTail(str(path), tailBytes=1000)
    assert tail[-1] == (20000, "line 20000")
    assert all(text == "line %d" % number for number, text in tail)
    assert readTail(str(tmp_path / "missing")) == []


def test_TheKnownErrorsAreValidAndNameNoProgram():
    data = json.loads(HINTS_FILE.read_text())
    ids = [rule["id"] for rule in data["rules"]]
    assert len(ids) == len(set(ids)) and len(knownErrors()) == len(ids)
    for rule in data["rules"]:
        re.compile(rule["pattern"])
        assert rule["title"] and rule["hint"] and rule["category"]
        # User-facing texts name no program (CUDA is the GPU's, not a program's, but keep it out too)
        assert not re.search(r"relion|xmipp|cryosparc|eman|motioncor|gctf|ctffind|cistem|cryolo|scipion|cuda",
                             rule["title"] + " " + rule["hint"], re.IGNORECASE), rule["id"]


def test_TheFirstRuleWins():
    rules = [dict(id="a", pattern="memory", title="A", hint="", category="x", regex=re.compile("memory")),
             dict(id="b", pattern="out", title="B", hint="", category="x", regex=re.compile("out"))]
    assert matchHint(["out of memory"], rules)["id"] == "a"
    assert matchHint(["nothing"], rules) is None


def test_AServicesRefusalSaysTheReasonItGave(tmp_path):
    stderr = ("Traceback (most recent call last):\n"
              "  File \"/x/api.py\", line 179, in _handle_response\n"
              "    raise APIError(\"Received error response\")\n"
              "errors.APIError: *** [API] (POST http://host:61002/jobs/J1:enqueue, code 422) Received error response\n"
              "Response data:\n"
              "{\n"
              "    \"detail\": \"Unable to queue to gpus without a specified target\"\n"
              "}\n")
    explained = explainFailure(*_logs(tmp_path, "", stderr))
    assert explained["cause"]["id"] == "service-refused"
    assert explained["error"]["text"].endswith("Received error response: Unable to queue to gpus without a specified "
                                               "target")
    assert explained["error"]["line"] == 4
