"""A machine's scratch: where it is written, how its worker sees it, and unsetting it."""
import pytest
from fastapi import HTTPException

from app.backend.api.services import scratch_settings as scratch
from scipionapi_cli.envfile import readEnvFile


@pytest.fixture
def home(tmp_path):
    (tmp_path / ".env").write_text("# shared\nDATABASE_NAME=scipion\n", encoding="utf-8")
    (tmp_path / "nodes").mkdir()
    (tmp_path / "nodes" / "gpu01.env").write_text("SCIPIONAPI_NODE_ROLE=protocols\n", encoding="utf-8")
    return tmp_path


def test_AComputeNodesScratchGoesToItsProfileAndTheMainOnesToTheSharedEnv(home):
    node = scratch.setScratch("gpu01.cnb.csic.es", "/ssd/scipion", home)
    main = scratch.setScratch("galileo-services", "/scratch", home)

    assert node["node"] and node["restartNeeded"]
    assert readEnvFile(home / "nodes" / "gpu01.env")["SCIPION_SCRATCH"] == "/ssd/scipion"
    assert not main["node"] and readEnvFile(home / ".env")["SCIPION_SCRATCH"] == "/scratch"
    assert readEnvFile(home / ".env")["DATABASE_NAME"] == "scipion"


def test_UnsettingItRemovesTheLineNeverLeavesItEmpty(home):
    scratch.setScratch("standalone", "/scratch", home)

    scratch.setScratch("standalone", "", home)

    text = (home / ".env").read_text()
    assert "SCIPION_SCRATCH" not in text and "# shared" in text and "DATABASE_NAME=scipion" in text


@pytest.mark.parametrize("path", ["scratch", "/", "/home", "/tmp"])
def test_AScratchIsAnAbsoluteFolderOfItsOwn(home, path):
    with pytest.raises(HTTPException) as error:
        scratch.setScratch("standalone", path, home)
    assert error.value.status_code == 400


def test_AWorkerTellsHowItsScratchIs(tmp_path):
    assert scratch.scratchStatus("") == {"path": None}
    missing = scratch.scratchStatus(str(tmp_path / "nope"))
    assert missing["exists"] is False and "does not exist" in missing["error"]
    fine = scratch.scratchStatus(str(tmp_path))
    assert fine["exists"] and fine["writable"] and fine["freeBytes"] > 0 and fine["error"] is None
