import pytest

from app.backend.api.services import assistant_new_project as new
from app.backend.api.services.assistant_actions import ProposalError


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.delenv("SCIPIONWEB_DATA_ROOTS", raising=False)
    data = tmp_path / "Images-Disc1" / "GridSquare_1" / "Data"
    data.mkdir(parents=True)
    for index in range(4):
        (data / ("FoilHole_%d_Fractions.tiff" % index)).write_text("x")
    (data / "FoilHole_0.jpg").write_text("x")
    return tmp_path


def test_TheMoviesAreFoundInTheGridSquares(folder):
    data = new.plan("My project", str(folder), "movies", "", {"samplingRate": "0.83", "voltage": 300}, False, "",
                    False)
    assert data["files"]["pattern"] == "Images-Disc*/GridSquare_*/Data/*_Fractions.tiff"
    assert data["files"]["count"] == 4 and data["missing"] == []
    protocol = new.importProtocol(data)
    assert protocol["object.className"] == "ProtImportMovies" and protocol["samplingRate"] == 0.83
    assert protocol["filesPath"] == str(folder) and protocol["dataStreaming"] is False


def test_MissingValuesAreListedNotGuessed(folder):
    card = new.card(new.plan("p", str(folder), "movies", "", {}, True, "", False))
    assert card["missing"] == ["Pixel size (Å)", "Voltage (kV)"] and card["streaming"] is True


def test_ThePatternGivenMustFindFiles(folder):
    with pytest.raises(ProposalError):
        new.plan("p", str(folder), "movies", "*.eer", {}, False, "", False)
    with pytest.raises(ProposalError):
        new.plan("p", str(folder), "movies", "../*.tiff", {}, False, "", False)


def test_OnlyTheDataFoldersWithoutBrowsingTheServer(folder, monkeypatch, tmp_path_factory):
    other = tmp_path_factory.mktemp("allowed")
    monkeypatch.setenv("SCIPIONWEB_DATA_ROOTS", str(other))
    with pytest.raises(ProposalError) as error:
        new.plan("p", str(folder), "movies", "", {}, False, "", False)
    assert "out of the folders" in str(error.value)
    assert new.plan("p", str(folder), "movies", "", {}, False, "", True)["files"]["count"] == 4


def test_ValuesOutOfRangeAndOtherDataAreRefused(folder):
    with pytest.raises(ProposalError):
        new.plan("p", str(folder), "movies", "", {"voltage": 3000}, False, "", False)
    with pytest.raises(ProposalError):
        new.plan("p", str(folder), "tiltseries", "", {}, False, "", False)
    with pytest.raises(ProposalError):
        new.plan("p", "relative/path", "movies", "", {}, False, "", False)
