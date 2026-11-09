"""Cleaning a machine's scratch: what protocols left there, never what is in use or not Scipion's."""
import os
import time

from app.backend.runtime import scratch_cleanup as cleanup

HOUR = 3600.0
NOW = 1_800_000_000.0


def _folder(root, name, ageHours, size=10):
    path = root / name
    (path / "deep").mkdir(parents=True)
    (path / "deep" / "particles.mrcs").write_bytes(b"\0" * size)
    for item in (path / "deep" / "particles.mrcs", path / "deep", path):
        os.utime(item, (NOW - ageHours * HOUR, NOW - ageHours * HOUR))
    return path


PROTOCOLS = [
    {"shortName": "Krios_Session", "protocolId": "12", "protocolClassName": "ProtClassify2D", "status": "running"},
    {"shortName": "Krios_Session", "protocolId": "13", "protocolClassName": "ProtRefine3D", "status": "failed"},
    {"shortName": "Krios_Session", "protocolId": "14", "protocolClassName": "ProtCtf", "status": "aborted"},
    {"shortName": "Empty", "protocolId": None, "protocolClassName": None, "status": ""},
]


def test_AFolderNameIsReadEvenWithUnderscoresInTheProject():
    assert cleanup.parseFolder("Krios_Session_000013_ProtRefine3D") == ("Krios_Session", 13, "ProtRefine3D")
    assert cleanup.parseFolder("cryosparc_cache") is None and cleanup.parseFolder("notes.txt") is None


def test_OnlyWhatNobodyWillUseGoes(tmp_path):
    names = {
        "Krios_Session_000012_ProtClassify2D": 48,   # running: stays, however old
        "Krios_Session_000013_ProtRefine3D": 30,     # failed a day ago: goes
        "Krios_Session_000014_ProtCtf": 5,           # aborted 5 h ago: stays (a recent failure is looked into)
        "Krios_Session_000099_ProtGone": 2,          # its protocol was deleted: goes
        "Deleted_Project_000001_ProtImport": 2,      # its project was deleted: goes
        "Empty_000001_ProtImport": 0.2,              # touched minutes ago: stays (it may be starting)
        "someone_elses_cache": 500,                  # not Scipion's: never touched
    }
    for name, age in names.items():
        _folder(tmp_path, name, age, size=100)

    report = cleanup.cleanScratch(None, str(tmp_path), now=NOW, protocolsOf=lambda shortNames: PROTOCOLS)

    gone = {item["name"]: item["reason"] for item in report["removed"]}
    assert gone == {"Krios_Session_000013_ProtRefine3D": "its protocol is not running",
                    "Krios_Session_000099_ProtGone": "its protocol is gone",
                    "Deleted_Project_000001_ProtImport": "its project is gone"}
    assert report["freedBytes"] == 300 and report["errors"] == [] and report["kept"] == 3
    assert {path.name for path in tmp_path.iterdir()} == {
        "Krios_Session_000012_ProtClassify2D", "Krios_Session_000014_ProtCtf", "Empty_000001_ProtImport",
        "someone_elses_cache", cleanup.LOCK_NAME}


def test_AFolderWrittenDeepInsideCountsAsInUse(tmp_path):
    path = _folder(tmp_path, "Krios_Session_000013_ProtRefine3D", 30)
    os.utime(path / "deep" / "particles.mrcs", (NOW - 60, NOW - 60))

    report = cleanup.cleanScratch(None, str(tmp_path), now=NOW, protocolsOf=lambda shortNames: PROTOCOLS)

    assert report["removed"] == [] and path.exists()


def test_AMissingScratchIsSaid(tmp_path):
    report = cleanup.cleanScratch(None, str(tmp_path / "nope"), now=NOW, protocolsOf=lambda names: [])

    assert report["errors"] == ["The scratch folder does not exist"]
