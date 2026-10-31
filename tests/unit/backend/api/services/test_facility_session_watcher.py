"""Reading a session's first movie and watching its DATA folders, on files laid out as the microscope writes them."""
import os
import shutil
from pathlib import Path

import pytest

from app.backend.api.services.facility_acquisition_reader import metadataFileOf, readAcquisition
from app.backend.api.services.facility_session_service import watchState
from app.backend.api.services.facility_session_watcher import isMovie, scanFolder

EPU = Path(__file__).resolve().parents[4] / "resources" / "epu"
# EPU 2.6 on a Glacios with a Falcon 3 (EMPIAR-11502)
IMAGE = "FoilHole_15867355_Data_12771432_12771434_20200417_031214"
FALCON = {"id": 11, "name": "Falcon 3", "metadataName": "BM-Falcon",
          "pixelSizes": [{"magnification": 92000, "pixelSize": 1.55}]}
CETA = {"id": 12, "name": "Ceta-D", "metadataName": "BM-Ceta", "pixelSizes": []}


def _epuData(root: Path, square: str = "GridSquare_12759259") -> Path:
    """A GridSquare's Data folder with the EMPIAR movie's metadata and an (empty) movie."""
    data = root / "Images-Disc1" / square / "Data"
    data.mkdir(parents=True)
    for name in os.listdir(EPU):
        if name.endswith(".xml"):
            shutil.copy(EPU / name, data / name)
    (data / (IMAGE + "_Fractions.mrc")).write_bytes(b"\0" * 64)
    return data


def test_TheFirstMoviesMetadataSaysWhatWasAcquiredWithTheDetectorsCalibration():
    acquisition = readAcquisition(EPU / (IMAGE + ".xml"), [CETA, FALCON])

    assert acquisition["format"] == "EPU XML (Falcon)" and acquisition["cameraName"] == "BM-Falcon"
    assert (acquisition["detectorId"], acquisition["detectorName"]) == (11, "Falcon 3")
    assert acquisition["voltageKv"] == 200 and acquisition["magnification"] == 92000
    assert acquisition["nominalPixelSize"] == pytest.approx(1.5678, abs=1e-4)
    assert acquisition["pixelSize"] == 1.55 and acquisition["pixelCalibrated"]
    # EPU 2.6 gives the frames only in the movie's _Fractions.xml
    assert acquisition["frames"] == 13 and acquisition["statuses"]["frames"] == "DIRECT"
    # Without DoseOnSample the dose on the sample is not guessed: only the dose at the camera is known
    assert acquisition["totalDose"] is None and acquisition["cameraDose"] > 30
    assert any("DoseOnSample" in warning for warning in acquisition["warnings"])
    assert acquisition["instrument"] == "GLACIOS-9951664"


def test_TheDetectorTheStaffGaveIsTheOneCalibrated():
    other = dict(FALCON, id=13, name="Falcon 4i", metadataName="", pixelSizes=[{"magnification": 92000, "pixelSize": 1.6}])

    acquisition = readAcquisition(EPU / (IMAGE + ".xml"), [FALCON, other], detectorId=13)

    assert acquisition["detectorName"] == "Falcon 4i" and acquisition["pixelSize"] == 1.6


def test_ACalibrationFarFromEPUsPixelIsNotOne():
    # The Talos' 1.14 A at 92000x on a movie of a Glacios (EPU: 1.568 A)
    talos = dict(FALCON, pixelSizes=[{"magnification": 92000, "pixelSize": 1.14}])

    acquisition = readAcquisition(EPU / (IMAGE + ".xml"), [talos])

    assert not acquisition["pixelCalibrated"] and acquisition["pixelSize"] == pytest.approx(1.5678, abs=1e-4)
    assert any("was not used" in warning and "Falcon 3" in warning for warning in acquisition["warnings"])
    assert acquisition["cameraDose"] == pytest.approx(30.84, abs=0.01)


def test_WithoutACalibrationTheNominalPixelStays():
    acquisition = readAcquisition(EPU / (IMAGE + ".xml"), [])

    assert acquisition["detectorId"] is None and not acquisition["pixelCalibrated"]
    assert acquisition["pixelSize"] == pytest.approx(1.5678, abs=1e-4)


def test_ASerialEMMovieIsReadFromItsMdoc(tmp_path):
    movie = tmp_path / "TS_01_001_-3.0.tif"
    movie.write_bytes(b"")
    (tmp_path / "TS_01_001_-3.0.tif.mdoc").write_text(
        "PixelSpacing = 0.84\nVoltage = 300\nMagnification = 105000\nNumSubFrames = 10\nExposureTime = 1.2\n"
        "ExposureDose = 3.0\n")

    acquisition = readAcquisition(metadataFileOf(movie), [])

    assert acquisition["format"] == "SerialEM MDOC"
    assert (acquisition["pixelSize"], acquisition["voltageKv"], acquisition["frames"]) == (0.84, 300, 10)
    assert acquisition["totalDose"] == 3.0 and acquisition["dosePerFrame"] == pytest.approx(0.3)


@pytest.mark.parametrize("name, movie", [
    ("FoilHole_1_Data_2_3_20200417_031214_Fractions.mrc", True),
    ("FoilHole_1_Data_2_3_20200417_031214_Fractions.tiff", True),
    ("FoilHole_1_Data_2_3_20200417_031214_EER.eer", True),
    ("TS_01_001_-3.0.tif", True),
    # The integrated image, its metadata and thumbnail, and gain references
    ("FoilHole_1_Data_2_3_20200417_031214.mrc", False),
    ("FoilHole_1_Data_2_3_20200417_031214_Fractions.xml", False),
    ("FoilHole_1_Data_2_3_20200417_031214.jpg", False),
    ("CountRef_TS_01.tif", False),
    ("gain_20200417.tiff", False),
])
def test_MoviesAreTheFractionsAndTheMovieFormats(name, movie):
    assert isMovie(name) is movie


def test_ADataFolderIsCountedAndOnlyItsChangedFoldersAreReadAgain(tmp_path):
    root = tmp_path / "S_DATA_01"
    data = _epuData(root)
    (data / "FoilHole_2_Data_2_3_20200417_031400_Fractions.mrc").write_bytes(b"\0" * 36)

    first = scanFolder(root, {}, now=1000.0)
    assert (first["exists"], first["count"], first["bytes"]) == (True, 2, 100)
    assert first["first"].endswith(IMAGE + "_Fractions.mrc") or first["first"].endswith("_031400_Fractions.mrc")

    # A folder whose modification time did not change is not read again
    state = first["state"]
    state["folders"]["Images-Disc1/GridSquare_12759259/Data"]["count"] = 7
    again = scanFolder(root, state, now=1010.0)
    assert again["count"] == 7
    # ... unless the last full look is too old
    assert scanFolder(root, state, now=1000.0 + 601)["count"] == 2


def test_MoviesInTheFolderItselfCountTooAndAMissingFolderIsSaid(tmp_path):
    root = tmp_path / "S_DATA_02"
    root.mkdir()
    (root / "TS_01_001_-3.0.tif").write_bytes(b"\0" * 10)

    assert scanFolder(root, {}, now=1.0)["count"] == 1
    missing = scanFolder(tmp_path / "S_DATA_03", {}, now=1.0)
    assert (missing["exists"], missing["count"], missing["state"]) == (False, 0, {"exists": False})


@pytest.mark.parametrize("session, dataset, state", [
    ({"status": "acquiring", "offloadPath": "/mnt"}, {"movieCount": 5, "minutesSinceLastMovie": 2}, "receiving"),
    ({"status": "acquiring", "offloadPath": "/mnt"}, {"movieCount": 5, "minutesSinceLastMovie": 45}, "stalled"),
    ({"status": "finished", "offloadPath": "/mnt"}, {"movieCount": 5, "minutesSinceLastMovie": 600}, "acquired"),
    ({"status": "planned", "offloadPath": "/mnt"}, {"movieCount": 0}, "idle"),
    ({"status": "acquiring", "offloadPath": ""}, {"movieCount": 0}, "noOffload"),
    ({"status": "acquiring", "offloadPath": "/mnt"}, {"movieCount": 0, "scannedAt": None}, "pending"),
    ({"status": "acquiring", "offloadPath": "/mnt"}, {"movieCount": 0, "scannedAt": "t", "folderFound": False}, "noFolder"),
    ({"status": "acquiring", "offloadPath": "/mnt"}, {"movieCount": 0, "scannedAt": "t", "folderFound": True}, "waiting"),
])
def test_EachDataSaysWhereItsAcquisitionIs(session, dataset, state):
    assert watchState(session, dict(dataset, kind="data")) == state
    assert watchState(session, dict(dataset, kind="atlas")) is None
