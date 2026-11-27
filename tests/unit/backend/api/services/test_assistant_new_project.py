import pytest

from app.backend.api.services import assistant_new_project as new
from app.backend.api.services.assistant_actions import ProposalError

FORM = ["filesPath", "filesPattern", "samplingRate", "voltage", "sphericalAberration", "amplitudeContrast",
        "dataStreaming", "importFrom"]
PROTOCOLS = [
    {"className": "ProtImportMovies", "label": "import movies", "params": [{"name": n} for n in FORM + [
        "dosePerFrame", "gainFile", "samplingRateMode"]]},
    {"className": "ProtImportParticles", "label": "import particles", "params": [{"name": n} for n in FORM]},
    {"className": "ProtImportTsMovies", "label": "import tilt-series movies", "params": [{"name": n} for n in FORM]},
    {"className": "ProtImportTs", "label": "import tilt-series", "params": [{"name": n} for n in FORM]},
    {"className": "ProtImportPdb", "label": "import atomic structure", "params": []},
]


def plan(name="p", folder="", data="", pattern="", given=None, streaming=False, browse=False):
    return new.plan(name, folder, data, pattern, given or {}, streaming, "", browse, PROTOCOLS)


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.delenv("SCIPIONWEB_DATA_ROOTS", raising=False)
    data = tmp_path / "Images-Disc1" / "GridSquare_1" / "Data"
    data.mkdir(parents=True)
    for index in range(4):
        (data / ("FoilHole_%d_Fractions.tiff" % index)).write_text("x")
    (tmp_path / "particles.star").write_text("x")
    return tmp_path


def test_OnlyANameMakesAnEmptyProject():
    data = plan(name="Test-Krios 27")
    assert data == {"name": "Test-Krios 27", "importClass": None}
    assert new.card(data)["importClass"] is None


def test_AFolderWithoutSayingWhatDataIsRefused(folder):
    with pytest.raises(ProposalError):
        plan(folder=str(folder))


def test_TheImportIsPickedByTheDataSaid():
    assert plan(data="particles")["importClass"] == "ProtImportParticles"
    assert plan(data="tilt series movies")["importClass"] == "ProtImportTsMovies"
    assert plan(data="Tilt-Series")["importClass"] == "ProtImportTs"
    assert plan(data="importing the movies")["importClass"] == "ProtImportMovies"
    assert plan(data="a pdb")["importClass"] == "ProtImportPdb"
    with pytest.raises(ProposalError) as error:
        plan(data="spaceships")
    assert "import particles" not in str(error.value) and "particles" in str(error.value)


def test_AnImportWithoutFolderIsLeftForTheForm():
    data = plan(data="particles", given={"samplingRate": 1.1, "dosePerFrame": 2})
    protocol = new.importProtocol(data)
    assert protocol == {"object.className": "ProtImportParticles", "object.id": "1",
                        "object.label": "import particles", "dataStreaming": False, "samplingRate": 1.1}


def test_TheMoviesAreFoundInTheGridSquares(folder):
    data = plan(folder=str(folder), data="movies", given={"samplingRate": "0.83", "voltage": 300})
    assert data["files"]["pattern"] == "Images-Disc*/GridSquare_*/Data/*_Fractions.tiff"
    assert data["files"]["count"] == 4 and data["missing"] == []
    protocol = new.importProtocol(data)
    assert protocol["object.className"] == "ProtImportMovies" and protocol["samplingRate"] == 0.83
    assert protocol["filesPath"] == str(folder) and protocol["importFrom"] == 0
    assert protocol["samplingRateMode"] == 0


def test_ParticlesFromAStarFile(folder):
    data = plan(folder=str(folder), data="particles")
    assert data["files"]["pattern"] == "*.star"
    assert data["missing"] == ["Pixel size (Å)", "Voltage (kV)"]
    assert "importFrom" not in new.importProtocol(data)


def test_AnImportWithoutFolderInItsFormRefusesOne(folder):
    with pytest.raises(ProposalError):
        plan(folder=str(folder), data="atomic structure")


def test_ThePatternGivenMustFindFiles(folder):
    with pytest.raises(ProposalError):
        plan(folder=str(folder), data="movies", pattern="*.eer")
    with pytest.raises(ProposalError):
        plan(folder=str(folder), data="movies", pattern="../*.tiff")


def test_OnlyTheDataFoldersWithoutBrowsingTheServer(folder, monkeypatch, tmp_path_factory):
    other = tmp_path_factory.mktemp("allowed")
    monkeypatch.setenv("SCIPIONWEB_DATA_ROOTS", str(other))
    with pytest.raises(ProposalError) as error:
        plan(folder=str(folder), data="movies")
    assert "out of the folders" in str(error.value)
    assert plan(folder=str(folder), data="movies", browse=True)["files"]["count"] == 4


def test_ValuesOutOfRangeAreRefused(folder):
    with pytest.raises(ProposalError):
        plan(folder=str(folder), data="movies", given={"voltage": 3000})
    with pytest.raises(ProposalError):
        plan(folder="relative/path", data="movies")
