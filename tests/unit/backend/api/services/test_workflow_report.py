import json

import pytest

from app.backend.api.services import workflow_report
from app.backend.api.services.workflow_report import _choice, methodsData, protocolIdsOf, writeMethods

REPORT = {
    "project": "SPA", "projectId": 7, "description": "", "upTo": "37", "generatedAt": "2026-11-27T10:00:00+00:00",
    "programs": {"scipion-em-xmipp": "29.0.1"}, "workflowFile": "[]",
    "protocols": [
        {"protocolId": "22", "label": "extract", "className": "XmippProtExtractParticles",
         "protocol": "extract particles", "status": "finished", "plugin": "xmipp3", "package": "scipion-em-xmipp",
         "version": "29.0.1", "inputs": [{"input": "inputCoordinates", "protocolId": "17", "output": "outputCoordinates"}],
         "params": [{"section": "Input", "name": "boxSize", "label": "Box size", "value": "184"}],
         "outputs": [{"name": "outputParticles", "type": "SetOfParticles", "size": 3445}],
         "run": {"started": "2026-11-12T12:00:00", "ended": "2026-11-12T12:05:00", "host": "node1", "queue": None,
                 "gpus": None, "threads": 4, "mpi": 1}},
        {"protocolId": "37", "label": "2D", "className": "XmippProtClassifyPcaStreaming", "protocol": "alignPCA-2D",
         "status": "failed", "plugin": "xmipp3", "package": "scipion-em-xmipp", "version": "29.0.1", "inputs": [],
         "params": [], "outputs": [], "run": None},
    ],
}


def test_ChoicesAreShownByTheirText():
    param = {"choices": ["Create", "Update"]}
    assert _choice(param, "1") == "Update"
    assert _choice(param, 0) == "Create"
    assert _choice(param, "7") == "7"
    assert _choice({}, "1") == "1"
    assert _choice(param, True) is True


def test_TheModelGetsOnlyFinishedProtocolsAndNoPeople():
    data = methodsData(REPORT)
    assert [item["id"] for item in data["protocols"]] == ["22"]
    assert data["protocols"][0]["parameters"] == {"Box size": "184"}
    assert data["protocols"][0]["outputs"][0]["items"] == 3445
    assert "host" not in json.dumps(data) and "node1" not in json.dumps(data)


def test_MethodsAreWrittenFromTheFigures():
    class Model:
        def chat(self, messages, tools=None):
            self.messages = messages
            return {"message": {"content": "Particles were extracted with Xmipp 29.0.1."},
                    "usage": {"inputTokens": 900, "outputTokens": 60}}

    model = Model()
    written = writeMethods(model, REPORT)
    assert written["text"] == "Particles were extracted with Xmipp 29.0.1."
    assert "never invent" in model.messages[0]["content"]


class FakeHelp:
    def __init__(self, db):
        pass

    def projectProtocols(self, projectId):
        return [{"protocolId": pid} for pid in ("37", "2", "22", "105", "5")]


class FakeAssistant:
    def __init__(self, db):
        pass

    def ancestors(self, projectId, protocolId):
        return [{"protocolId": "22", "depth": 1}, {"protocolId": "5", "depth": 2}]


def test_ProtocolsOfTheReportInOrder(monkeypatch):
    monkeypatch.setattr(workflow_report, "HelpChatPostgresqlMapper", FakeHelp)
    monkeypatch.setattr(workflow_report, "AssistantPostgresqlMapper", FakeAssistant)
    mapper = type("Mapper", (), {"db": None})()
    assert protocolIdsOf(mapper, 7, None) == ["2", "5", "22", "37", "105"]
    assert protocolIdsOf(mapper, 7, "37") == ["5", "22", "37"]
    with pytest.raises(ValueError):
        protocolIdsOf(mapper, 7, "999")


def test_ThePdfIsWritten():
    pytest.importorskip("reportlab")
    from app.backend.api.services.workflow_report_pdf import render

    pdf = render(REPORT, "Particles were extracted with <Xmipp> 29.0.1 & sorted.", "4.0.0")
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000


def test_WithoutTheLibraryItSaysSo(monkeypatch):
    import builtins

    from app.backend.api.services import workflow_report_pdf

    real = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("reportlab"):
            raise ImportError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(workflow_report_pdf.ReportUnavailable) as error:
        workflow_report_pdf.render(REPORT)
    assert "reportlab" in str(error.value)
