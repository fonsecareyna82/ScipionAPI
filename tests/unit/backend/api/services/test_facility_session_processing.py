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


def test_ATomographyDataIsReadFromItsTiltSeriesFolders():
    from app.backend.api.services.facility_session_processing import fillComposeTiltSeries, labelBranch, mdocPattern

    assert moviesPattern("TS_01/frames/TS_01_001_0.0_EER.eer") == "*/frames/*_EER.eer"
    assert moviesPattern("TS_01_001_0.0.mrc") == "*.mrc"
    assert mdocPattern("TS_01/frames/TS_01.mdoc") == "*/frames/*.mdoc"
    assert mdocPattern("TS_01.mdoc") == "*.mdoc"
    assert mdocPattern("FoilHole_1.xml") is None

    workflow = [{"object.className": "ProtImportMovies", "object.label": "import movies"},
                {"object.className": "ProtComposeTS", "object.label": "compose", "filesPath": "~x~", "mdocPattern": "*.mdoc"}]
    assert fillComposeTiltSeries(workflow, "/offload/S_DATA_01", "*/frames/*.mdoc") == 1
    assert (workflow[1]["filesPath"], workflow[1]["mdocPattern"]) == ("/offload/S_DATA_01", "*/frames/*.mdoc")
    labelBranch(workflow, "DATA_02")
    assert [protocol["object.label"] for protocol in workflow] == ["DATA_02 · import movies", "DATA_02 · compose"]


def test_ATemplateWithEMhubsAliasesTakesTheMoviesValues(tmp_path, monkeypatch):
    """The CNB's templates, filled by EMhub with `scipion template ... sampling=... spherical=...`."""
    from pyworkflow.template import LocalTemplate

    from app.backend.api.services.facility_session_processing import TEMPLATE_ALIASES
    from app.backend.api.services.project_service import ProjectService

    path = tmp_path / "spa-basic.json.template"
    # As a template is written: text fields quoted, numbers not
    path.write_text('[{"object.className": "ProtImportMovies", "object.id": "2", '
                    '"filesPath": "~Movies folder|/data/|2|moviesPath~", "filesPattern": "~Pattern|*.tiff|0|filesPattern~", '
                    '"samplingRate": ~Pixel|1.0|4|sampling~, "voltage": ~Voltage|300|4|voltage~, '
                    '"sphericalAberration": ~Cs|2.7|4|spherical~, "dosePerFrame": ~Dose|1.0|4|dosePerFrame~}]')
    service = ProjectService.__new__(ProjectService)
    monkeypatch.setattr(service, "listProjectWorkflows", lambda raw=False: [LocalTemplate("cnb", str(path))])
    values = {"filesPath": str(tmp_path), "filesPattern": "Images-Disc*/GridSquare_*/Data/*_Fractions.tiff",
              "samplingRate": 0.84, "voltage": 200.0, "sphericalAberration": 2.7, "dosePerFrame": 1.07}

    workflow = service.materializeWorkflowTemplate(
        "cnb:spa-basic", {alias: values.get(param) for alias, param in TEMPLATE_ALIASES.items()})

    imported = workflow[0]
    assert imported["filesPath"] == str(tmp_path)
    assert imported["filesPattern"] == "Images-Disc*/GridSquare_*/Data/*_Fractions.tiff"
    assert (imported["samplingRate"], imported["voltage"], imported["dosePerFrame"]) == (0.84, 200.0, 1.07)


def test_TheSessionsCtfLimitsGoIntoTheCtfConsensus():
    from app.backend.api.services.facility_session_processing import fillCtfConsensus

    workflow = [{"object.className": "XmippProtCTFConsensus", "useDefocus": False, "minDefocus": 4000, "maxDefocus": 50000,
                 "useResolution": True, "resolution": 17},
                {"object.className": "CistemProtCTFFind", "lowRes": 30}]

    assert fillCtfConsensus(workflow, 5000, 40000, 8) == 1
    assert {key: workflow[0][key] for key in ("useDefocus", "minDefocus", "maxDefocus", "useResolution", "resolution")} == \
        {"useDefocus": True, "minDefocus": 5000.0, "maxDefocus": 40000.0, "useResolution": True, "resolution": 8.0}
    assert workflow[1] == {"object.className": "CistemProtCTFFind", "lowRes": 30}

    # A limit not given keeps the template's
    kept = [{"object.className": "XmippProtCTFConsensus", "useDefocus": False, "minDefocus": 4000, "resolution": 17}]
    fillCtfConsensus(kept, None, None, 6)
    assert kept[0]["useDefocus"] is False and kept[0]["minDefocus"] == 4000 and kept[0]["resolution"] == 6.0
    assert fillCtfConsensus([{"object.className": "ProtImportMovies"}], 5000, None, None) == 0


def test_TheMovieAlignmentTurnsTheGainAsTheDetectorSays():
    from app.backend.api.services.facility_session_processing import fillGainOrientation

    workflow = [{"object.className": "ProtImportMovies"},
                {"object.className": "ProtMotionCorr", "gainRot": 0, "gainFlip": 0},
                {"object.className": "XmippProtFlexAlign"},
                {"object.className": "ProtRelionMotioncor"}]
    assert fillGainOrientation(workflow, "vertical", 270) == {"filled": 3, "notTurned": []}
    # MotionCor2's convention: three steps of 90 degrees, 1 is upside down (2 left to right)
    assert [(p.get("gainRot"), p.get("gainFlip")) for p in workflow[1:]] == [(3, 1)] * 3
    assert "gainRot" not in workflow[0]

    fillGainOrientation(workflow, "horizontal", 0)
    assert (workflow[1]["gainRot"], workflow[1]["gainFlip"]) == (0, 2)


def test_WarpFlipsTheGainButCannotRotateIt():
    from app.backend.api.services.facility_session_processing import fillGainOrientation

    warp = [{"object.className": "ProtWarpMotionCorr", "object.label": "warp motion", "gainFlip": 0}]
    assert fillGainOrientation(warp, "horizontal", 0) == {"filled": 1, "notTurned": []}
    # Warp's own numbers: 1 flips X (left to right)
    assert warp[0]["gainFlip"] == 1
    warp[0]["gainFlip"] = 0
    assert fillGainOrientation(warp, "vertical", 90) == {"filled": 0, "notTurned": ["warp motion"]}
    assert warp[0]["gainFlip"] == 0
