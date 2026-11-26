from app.backend.api.services.session_summary import monitorFigures


def test_MonitorInAFewFigures():
    monitor = {
        "flow": {"items": 30, "unit": "movies", "acquisition": "finished", "lastItemAt": None, "stalled": []},
        "stages": [{"stage": "movies", "label": "motioncorr", "status": "finished", "items": 30, "behind": None}],
        "thresholds": {"maxResolution": 4.8, "minParticles": None},
        "series": {"points": [
            {"resolution": 3.2, "defocusU": 10000, "defocusV": 12000, "astigmatism": 40, "totalDrift": 3,
             "alerts": ["minDefocus"]},
            {"resolution": 3.6, "defocusU": 14000, "defocusV": 14000, "astigmatism": 80, "totalDrift": 4, "alerts": []},
            {"failed": True, "alerts": ["failed"]}]},
        "dose": {"points": [{"meanDose": 0.8}, {"meanDose": 0.9, "discarded": True}]},
        "picking": {"counts": {"1": 300, "2": 340}, "boxSize": 184},
        "classesOutputs": [{"setId": 1}],
    }
    figures = monitorFigures(monitor)
    assert figures["acquisition"]["items"] == 30 and figures["acquisition"]["stalled"] is False
    assert figures["thresholds"] == {"maxResolution": 4.8}
    assert figures["ctf"]["micrographs"] == 3 and figures["ctf"]["failedFits"] == 1
    assert figures["ctf"]["resolutionA"]["median"] == 3.4
    assert figures["ctf"]["defocusA"]["min"] == 11000
    assert figures["ctf"]["beyondThresholds"] == {"minDefocus": 1, "failed": 1}
    assert figures["dose"] == {"movies": 2, "meanDose": figures["dose"]["meanDose"], "discarded": 1}
    assert figures["particles"]["total"] == 640 and figures["particles"]["boxSize"] == 184
    assert figures["classes2D"] == 1


def test_NoFiguresForWhatIsNotThere():
    figures = monitorFigures({})
    assert figures["ctf"] is None and figures["dose"] is None and figures["particles"] is None
