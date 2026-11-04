"""The navigation reports of tomography DATA, made by an outside tomo5-mapper (here a stand-in)."""
import sys

import pytest
from fastapi import HTTPException

from app.backend.api.services import facility_navigation as navigation

# What tomo5-mapper does, as far as ScipionWeb sees it: a folder with Session.dm makes <name>_report.html in -o;
# none is exit code 1
STAND_IN = """
import os, sys
source, output = sys.argv[1], sys.argv[3]
if not os.path.exists(os.path.join(source, "Session.dm")):
    print("no Tomography 5 session found", file=sys.stderr)
    sys.exit(1)
assert sys.argv[4:] == ["--tilt-source", "thumbnails", "--skip-screening", "--quiet"], sys.argv
with open(os.path.join(output, "Lamella_3_report.html"), "w") as report:
    report.write("<html>atlas</html>")
"""


@pytest.fixture
def tomo(tmp_path, monkeypatch):
    program = tmp_path / "tomo5_mapper_stand_in.py"
    program.write_text(STAND_IN)
    monkeypatch.setenv(navigation.COMMAND_VARIABLE, "%s %s" % (sys.executable, program))
    monkeypatch.setenv(navigation.REPORTS_VARIABLE, str(tmp_path / "reports"))
    offload = tmp_path / "offload"
    (offload / "S_DATA_01").mkdir(parents=True)
    (offload / "S_DATA_01" / "Session.dm").write_text("<Session/>")
    (offload / "S_DATA_02").mkdir()
    session = {"id": 4, "technique": "tomo", "offloadPath": str(offload),
               "datasets": [{"id": 1, "kind": "atlas", "folder": "S_ATLAS"},
                            {"id": 2, "kind": "data", "folder": "S_DATA_01", "movieCount": 41},
                            {"id": 3, "kind": "data", "folder": "S_DATA_02", "movieCount": 2},
                            {"id": 5, "kind": "data", "folder": "S_DATA_03", "movieCount": 0}]}
    return session


def test_ATomographyDataGetsItsReportIntoTheFacilitysFolder(tomo, tmp_path):
    data = tomo["datasets"][1]
    assert navigation.navigationOf(tomo, data) == {"state": "none", "startedAt": None, "finishedAt": None,
                                                   "message": None, "available": True, "sizeBytes": None}

    made = navigation.startReport(tomo, data, wait=True)

    assert made["state"] == "done" and made["sizeBytes"] == len("<html>atlas</html>")
    report = navigation.reportPath(tomo, data)
    assert report.read_text() == "<html>atlas</html>"
    assert str(report).startswith(str(tmp_path / "reports" / "4" / "S_DATA_01"))
    # The microscope's folder is left as it was
    assert sorted(path.name for path in (tmp_path / "offload" / "S_DATA_01").iterdir()) == ["Session.dm"]


def test_AFolderWithoutATomo5SessionSaysSo(tomo):
    data = tomo["datasets"][2]
    failed = navigation.startReport(tomo, data, wait=True)
    assert failed["state"] == "failed" and failed["message"].startswith("No Tomography 5 session in ")
    with pytest.raises(HTTPException) as error:
        navigation.reportPath(tomo, data)
    assert error.value.status_code == 404


def test_OnlyTheDataOfATomographySessionThatIsThereGetOne(tomo, monkeypatch):
    for session, dataset in ((dict(tomo, technique="spa"), tomo["datasets"][1]), (tomo, tomo["datasets"][0]),
                             (tomo, tomo["datasets"][3])):
        with pytest.raises(HTTPException) as error:
            navigation.startReport(session, dataset, wait=True)
        assert error.value.status_code == 409

    monkeypatch.delenv(navigation.COMMAND_VARIABLE)
    assert navigation.navigationOf(tomo, tomo["datasets"][1])["available"] is False
    with pytest.raises(HTTPException) as error:
        navigation.startReport(tomo, tomo["datasets"][1])
    assert "SCIPIONWEB_TOMO5_MAPPER" in error.value.detail
    assert navigation.reportsWhenFinished(tomo) == []


def test_AFinishedTomographySessionMakesTheReportsOfItsDataWithMovies(tomo, monkeypatch):
    started = []
    monkeypatch.setattr(navigation, "startReport", lambda session, dataset: started.append(dataset["folder"]))

    assert navigation.reportsWhenFinished(tomo) == ["S_DATA_01", "S_DATA_02"]
    assert navigation.reportsWhenFinished(dict(tomo, technique="spa")) == []
