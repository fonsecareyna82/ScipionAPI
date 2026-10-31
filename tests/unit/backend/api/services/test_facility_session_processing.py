"""What a DATA's project reads: the Import Movies of the session's template filled with what the first movie says."""
import os

from app.backend.api.services.facility_session_processing import (
    fillImportMovies, gainReference, importValues, moviesPattern,
)

ACQUISITION = {"firstMovie": "Images-Disc1/GridSquare_12759259/Data/FoilHole_1_Data_2_3_20200417_031214_Fractions.mrc",
               "pixelSize": 1.14, "voltageKv": 200.0, "magnification": 92000, "dosePerFrame": 1.02}


def test_ThePatternIsThatOfTheMoviesEPUWrites():
    assert moviesPattern(ACQUISITION["firstMovie"]) == "Images-Disc*/GridSquare_*/Data/*_Fractions.mrc"
    assert moviesPattern("Images-Disc2/GridSquare_7/Data/FoilHole_1_Data_2_3_EER.eer") == \
        "Images-Disc*/GridSquare_*/Data/*_EER.eer"
    assert moviesPattern("TS_01_001_-3.0.tif") == "*.tif"


def test_TheGainIsEPUsElseTheNewestOfTheDetectorsPattern(tmp_path):
    older, newer = tmp_path / "Talos_gain_1.mrc", tmp_path / "Talos_gain_2.mrc"
    older.write_bytes(b"")
    newer.write_bytes(b"")
    os.utime(older, (1, 1))
    detector = {"gainPath": str(tmp_path / "*Talos*gain*.mrc")}

    assert gainReference({"gainFile": "/offload/S_DATA_01/x.gain"}, detector) == "/offload/S_DATA_01/x.gain"
    assert gainReference({}, detector) == str(newer)
    assert gainReference({}, {"gainPath": str(tmp_path / "missing*.mrc")}) is None
    assert gainReference({}, None) is None


def test_TheImportMoviesReadsTheDataInStreaming():
    workflow = [
        {"object.className": "ProtImportMovies", "object.id": "2", "filesPath": "~Movie's folder~",
         "samplingRate": 3.54, "voltage": 300, "dosePerFrame": 0.0, "dataStreaming": False, "timeout": 7200},
        {"object.className": "ProtMotionCorr", "object.id": "3", "inputMovies": "2.outputMovies"},
    ]
    values = importValues("/offload/S_DATA_01", ACQUISITION, 2.7, None)

    assert fillImportMovies(workflow, values) == 1
    imported = workflow[0]
    assert imported["filesPath"] == "/offload/S_DATA_01"
    assert imported["filesPattern"] == "Images-Disc*/GridSquare_*/Data/*_Fractions.mrc"
    assert (imported["samplingRate"], imported["voltage"], imported["sphericalAberration"]) == (1.14, 200.0, 2.7)
    assert (imported["magnification"], imported["dosePerFrame"]) == (92000, 1.02)
    assert imported["dataStreaming"] is True and imported["samplingRateMode"] == 0 and imported["timeout"] == 7200
    assert workflow[1] == {"object.className": "ProtMotionCorr", "object.id": "3", "inputMovies": "2.outputMovies"}


def test_WhatTheMovieDoesNotSayKeepsTheTemplatesValue():
    workflow = [{"object.className": "ProtImportMovies", "dosePerFrame": 0.8, "sphericalAberration": 2.0}]

    fillImportMovies(workflow, importValues("/offload/S_DATA_01", dict(ACQUISITION, dosePerFrame=None), None, None))

    assert (workflow[0]["dosePerFrame"], workflow[0]["sphericalAberration"]) == (0.8, 2.0)
    assert fillImportMovies([{"object.className": "ProtCTFFind"}], {"filesPath": "/x"}) == 0
