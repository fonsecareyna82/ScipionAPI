import copy

import pytest

from app.backend.api.services import assistant_chains
from app.backend.api.services.assistant_actions import ProposalError
from app.backend.api.services.assistant_chains import TemplateChains

from tests.unit.backend.api.services.test_assistant_templates import TEMPLATE


class FakeDb:
    def __init__(self, protocols):
        self.protocols = protocols
        self.saved = {}
        self.nextChain = 1

    def protocol(self, projectId, protocolId):
        return self.protocols.get(str(protocolId))

    def ancestors(self, projectId, protocolId):
        return [{"protocolId": "11", "depth": 1}, {"protocolId": "6", "depth": 3}] if str(protocolId) == "22" else []

    def topProtocolId(self, projectId):
        return 148

    def addChain(self, projectId, userId, templateId, title, protocolIds, parents, stops, launched):
        chainId = self.nextChain
        self.nextChain += 1
        self.saved[chainId] = {"id": chainId, "projectId": projectId, "templateId": templateId, "title": title,
                               "protocolIds": protocolIds, "parents": parents, "stops": stops, "passed": [],
                               "launched": launched}
        return chainId

    def chain(self, projectId, chainId):
        found = self.saved.get(int(chainId))
        return copy.deepcopy(found) if found else None

    def chains(self, projectId):
        return [copy.deepcopy(chain) for chain in self.saved.values()]

    def saveChainProgress(self, projectId, chainId, passed, launched):
        self.saved[int(chainId)].update(passed=list(passed), launched=list(launched))


class FakeHelp:
    def __init__(self, db, outputs):
        self.db, self.outputs = db, outputs

    def protocolOutputs(self, projectId, protocolId):
        return [{"outputName": name} for name in sorted(self.outputs.get(str(protocolId), ()))]

    def projectProtocols(self, projectId):
        return [dict(row, protocolId=pid) for pid, row in self.db.protocols.items()]


class FakeService:
    def __init__(self, db):
        self.db = db
        self.imported = None
        self.launched = []

    def listProjectWorkflows(self):
        return [{"id": "WH:3D", "name": "Workflow 3D", "content": TEMPLATE, "params": {}},
                {"id": "WH:broken", "name": "Broken", "content": [], "canLoad": False,
                 "missingPluginNames": ["scipion-em-cryosparc2"]}]

    def materializeWorkflowTemplate(self, templateId, values):
        self.materialized = (templateId, values)
        return copy.deepcopy(TEMPLATE)

    def loadPostgresqlRuntimeProjectForMutation(self, mapper, projectId, currentUser):
        return {"id": projectId}

    def importWorkflowProtocolsService(self, mapper, projectId, currentUser, payload):
        self.imported = payload
        created = []
        for index, protocol in enumerate(payload.workflow):
            newId = str(200 + index)
            created.append({"sourceId": protocol["object.id"], "newId": newId})
            self.db.protocols[newId] = {"protocolId": newId, "className": protocol["object.className"],
                                        "status": "saved", "label": protocol.get("object.label", "")}
        return {"status": 0, "errors": [], "created": created}

    def launchProtocol(self, **kwargs):
        assert kwargs["executeMode"] == "schedule"
        self.launched.append(kwargs["protocolId"])
        return {}


PROTOCOLS = {
    "6": {"protocolId": "6", "className": "XmippProtCTFConsensus", "status": "finished", "label": "ctf consensus"},
    "11": {"protocolId": "11", "className": "ProtBoxSizeParameters", "status": "finished", "label": "box size"},
    "22": {"protocolId": "22", "className": "XmippProtExtractParticles", "status": "finished", "label": "extract"},
}
OUTPUTS = {"6": {"outputCTF", "outputMicrographs"}, "11": {"boxSizeExtraction"}, "22": {"outputParticles"}}


@pytest.fixture
def chains(monkeypatch):
    db = FakeDb(copy.deepcopy(PROTOCOLS))
    monkeypatch.setattr(assistant_chains, "AssistantPostgresqlMapper", lambda raw: db)
    monkeypatch.setattr(assistant_chains, "HelpChatPostgresqlMapper", lambda raw: FakeHelp(db, OUTPUTS))
    service = FakeService(db)
    mapper = type("Mapper", (), {"db": None})()
    return TemplateChains(service, mapper, {"id": 3}), service, db


def test_TemplatesAreListedAndFiltered(chains):
    runner, _, _ = chains
    assert [item["id"] for item in runner.find("3D")] == ["WH:3D"]
    with pytest.raises(ProposalError) as error:
        runner.template("WH:broken")
    assert "scipion-em-cryosparc2" in str(error.value)


def test_CardOfACutTemplate(chains):
    runner, _, _ = chains
    card = runner.card(7, runner.plan(7, "WH:3D", "22", None), "From your particles")
    assert card["action"] == "template" and card["anchor"] == "4.outputParticles"
    assert card["source"] == {"protocolId": "22", "label": "extract", "output": "outputParticles"}
    assert {link["templateRef"]: link["projectRef"] for link in card["links"]} == {
        "4.outputParticles": "22.outputParticles", "2.outputCTF": "6.outputCTF",
        "3.boxSizeExtraction": "11.boxSizeExtraction", "2.outputMicrographs": "6.outputMicrographs"}
    assert card["links"][1]["projectLabel"] == "ctf consensus"
    assert card["missing"] == []
    assert [(step["id"], step["stop"]) for step in card["steps"]] == [("5", True), ("6", True), ("7", True),
                                                                       ("8", False)]


def test_SourceOutputMustBeSaidWhenThereAreSeveral(chains):
    runner, _, _ = chains
    with pytest.raises(ProposalError) as error:
        runner.plan(7, "WH:3D", "6", None)
    assert "outputCTF, outputMicrographs" in str(error.value)


def test_ApplyAddsTheCutLinkedAndLaunchesUpToTheStops(chains):
    runner, service, db = chains
    result = runner.apply(7, "WH:3D", "22", "outputParticles", None, {}, ["5", "6", "7"], {})
    workflow = service.imported.workflow
    assert service.imported.sourceProjectId == "7"
    assert [protocol["object.id"] for protocol in workflow] == ["100148", "100149", "100150", "100151"]
    assert workflow[0]["inputParticles"] == "22.outputParticles"
    assert workflow[3]["ctfRelations"] == "6.outputCTF"
    assert result["created"] == ["200", "201", "202", "203"]
    # 2D and the initial model run; the 3D waits for the initial model's stop
    assert service.launched == ["200", "201"] and result["launched"] == ["200", "201"]
    chain = db.saved[result["chainId"]]
    assert chain["stops"] == ["200", "201", "202"] and chain["parents"]["202"] == ["201"]

    with pytest.raises(ProposalError) as error:
        runner.continueCard(7, result["chainId"], "201")
    assert "goes on once it has finished" in str(error.value)
    db.protocols["201"]["status"] = "finished"
    card = runner.continueCard(7, result["chainId"], "201")
    assert [item["protocolId"] for item in card["next"]] == ["202"] and card["next"][0]["stop"] is True

    runner.launchNext(7, result["chainId"], "201")
    assert service.launched[-1] == "202"
    db.protocols["202"]["status"] = "finished"
    runner.launchNext(7, result["chainId"], "202")
    assert service.launched[-1] == "203"
    overview = runner.chainsOf(7)[0]
    assert overview["notLaunched"] == 0 and [stop["passed"] for stop in overview["stops"]] == [False, True, True]


def test_ApplyRefusesLinksThatAreNotReady(chains):
    runner, service, db = chains
    db.protocols["6"]["status"] = "running"
    # Not proposed by itself...
    with pytest.raises(ProposalError) as error:
        runner.apply(7, "WH:3D", "22", "outputParticles", None, {}, [], {})
    assert "Say what in the project stands for 2.outputCTF" in str(error.value)
    # ...nor taken when chosen
    chosen = {"2.outputCTF": "6.outputCTF", "2.outputMicrographs": "6.outputMicrographs"}
    with pytest.raises(ProposalError) as error:
        runner.apply(7, "WH:3D", "22", "outputParticles", None, chosen, [], {})
    assert "has not finished" in str(error.value)
    assert service.imported is None


def test_ApplyRefusesWhatIsNotFound(chains):
    runner, service, db = chains
    del db.protocols["11"]
    with pytest.raises(ProposalError) as error:
        runner.apply(7, "WH:3D", "22", "outputParticles", None, {}, [], {})
    assert "3.boxSizeExtraction" in str(error.value)


def test_WholeTemplateWithItsFields(chains):
    runner, service, _ = chains
    card = runner.card(7, runner.plan(7, "WH:3D"), "")
    assert card["source"] is None and card["links"] == [] and len(card["steps"]) == len(TEMPLATE)
    result = runner.apply(7, "WH:3D", None, None, None, {}, ["5"], {"moviesPath": "/data/x"})
    assert service.materialized == ("WH:3D", {"moviesPath": "/data/x"})
    assert len(service.imported.workflow) == len(TEMPLATE)
    # Everything but what follows the stop (the 2D) runs
    assert len(result["launched"]) == len(TEMPLATE)
