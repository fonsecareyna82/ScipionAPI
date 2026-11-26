import pytest

from app.backend.api.services import assistant_templates as T
from app.backend.api.services.assistant_actions import ProposalError

# A small template like the facility's "Workflow 3D": import, CTF, picking, box size, extraction, then 2D, initial
# model, 3D and a re-extraction that needs the micrographs, the CTF and the box size again
TEMPLATE = [
    {"object.id": "1", "object.className": "ProtImportMovies", "object.label": "import"},
    {"object.id": "2", "object.className": "XmippProtCTFConsensus", "inputCTF": "1.outputMovies"},
    {"object.id": "3", "object.className": "ProtBoxSizeParameters", "inputMicrographs": "2.outputMicrographs"},
    {"object.id": "4", "object.className": "XmippProtExtractParticles", "ctfRelations": "2.outputCTF",
     "boxSize": "3.boxSizeExtraction", "_prerequisites": "3"},
    {"object.id": "5", "object.className": "ProtCryo2D", "object.label": "2D", "inputParticles": "4.outputParticles",
     "numberOfClasses": 50},
    {"object.id": "6", "object.className": "ProtCryoSparcInitialModel", "inputParticles": "4.outputParticles"},
    {"object.id": "7", "object.className": "ProtCryoSparc3DClassification", "inputParticles": "4.outputParticles",
     "refVolumes": ["6.outputVolumes.2", "6.outputVolumes.1"]},
    {"object.id": "8", "object.className": "XmippProtExtractParticles", "ctfRelations": "2.outputCTF",
     "boxSize": "3.boxSizeExtraction", "inputCoordinates": "7.outputClasses", "inputMicrographs": "2.outputMicrographs"},
]


def test_StepsAndSummary():
    steps = T.steps(TEMPLATE)
    assert steps[4] == {"id": "5", "className": "ProtCryo2D", "label": "2D", "inputs": ["4.outputParticles"],
                        "keyStep": "2D classes"}
    assert steps[6]["inputs"] == ["4.outputParticles", "6.outputVolumes.1", "6.outputVolumes.2"]
    summary = T.summary({"id": "WH:3D", "name": "Workflow 3D", "content": TEMPLATE,
                         "params": {"moviesPath": {"alias": "moviesPath", "title": "Movies", "value": "/data"}}})
    assert summary["startsWith"] == ["ProtImportMovies"]
    assert summary["fields"] == [{"alias": "moviesPath", "title": "Movies", "value": "/data"}]


def test_TemplatesFilteredByWords():
    template = {"name": "Workflow 3D cryosparc", "content": TEMPLATE}
    assert T.matches(template, "3D initialmodel")
    assert T.matches(template, "")
    assert not T.matches(template, "tomography")


def test_AnchorPrefersTheSameKindOfProtocol():
    assert T.anchorCandidates(TEMPLATE, "outputParticles", "XmippProtExtractParticles") == ["4.outputParticles"]
    assert T.anchorCandidates(TEMPLATE, "outputParticles", "RelionExtract") == ["4.outputParticles"]
    assert T.anchorCandidates(TEMPLATE, "outputTomograms") == []


def test_CutKeepsWhatDependsOnTheAnchorAndListsWhatItNeeds():
    kept, external = T.cut(TEMPLATE, "4.outputParticles")
    assert [protocol["object.id"] for protocol in kept] == ["5", "6", "7", "8"]
    assert external == ["4.outputParticles", "2.outputCTF", "3.boxSizeExtraction", "2.outputMicrographs"]
    with pytest.raises(ProposalError):
        T.cut(TEMPLATE, "99.outputParticles")
    with pytest.raises(ProposalError):
        T.cut(TEMPLATE, "8.outputParticles")


def test_RenumberedLinksToTheProjectAndKeepsItsOwnLinks():
    kept, _ = T.cut(TEMPLATE, "4.outputParticles")
    links = {"4.outputParticles": "22.outputParticles", "2.outputCTF": "6.outputCTF",
             "3.boxSizeExtraction": "11.boxSizeExtraction", "2.outputMicrographs": "6.outputMicrographs"}
    allIds = {protocol["object.id"] for protocol in TEMPLATE}
    content, ids = T.renumbered(kept, links, 1000, allIds)
    assert ids == {"5": "1000", "6": "1001", "7": "1002", "8": "1003"}
    assert content[0]["inputParticles"] == "22.outputParticles"
    assert content[0]["numberOfClasses"] == 50
    assert content[2]["refVolumes"] == ["1001.outputVolumes.2", "1001.outputVolumes.1"]
    assert content[3]["inputCoordinates"] == "1002.outputClasses"
    assert content[3]["boxSize"] == "11.boxSizeExtraction"
    # The template itself is not changed
    assert TEMPLATE[4]["inputParticles"] == "4.outputParticles"


def test_RenumberedRefusesWhatIsNotLinked():
    kept, _ = T.cut(TEMPLATE, "4.outputParticles")
    with pytest.raises(ProposalError) as error:
        T.renumbered(kept, {"4.outputParticles": "22.outputParticles"}, 1000, {p["object.id"] for p in TEMPLATE})
    assert "2.outputCTF" in str(error.value)


def test_AVolumeOfALinkedSetFollowsTheSet():
    kept = [TEMPLATE[6]]
    content, _ = T.renumbered(kept, {"4.outputParticles": "22.outputParticles", "6.outputVolumes": "30.outputVolumes"},
                              500, {p["object.id"] for p in TEMPLATE})
    assert content[0]["refVolumes"] == ["30.outputVolumes.2", "30.outputVolumes.1"]


def test_WaitForProtocolsAreDropped():
    content, _ = T.renumbered([TEMPLATE[3]], {"2.outputCTF": "6.outputCTF", "3.boxSizeExtraction": "11.b"}, 10,
                              {p["object.id"] for p in TEMPLATE})
    assert "_prerequisites" not in content[0]


def test_StopsAndStretches():
    kept, _ = T.cut(TEMPLATE, "4.outputParticles")
    assert T.defaultStops(kept) == ["5", "6", "7"]
    parents = T.parentsOf(kept)
    assert parents == {"5": [], "6": [], "7": ["6"], "8": ["7"]}
    order = ["5", "6", "7", "8"]
    stops = ["5", "6", "7"]
    assert T.launchable(order, parents, stops, [], []) == ["5", "6"]
    assert T.launchable(order, parents, stops, ["5"], ["5", "6"]) == []
    assert T.launchable(order, parents, stops, ["5", "6"], ["5", "6"]) == ["7"]
    assert T.launchable(order, parents, stops, ["5", "6", "7"], ["5", "6", "7"]) == ["8"]


# Linking -------------------------------------------------------------------------------------------------------

PROJECT = [
    {"protocolId": "5", "className": "CistemProtCTFFind", "status": "finished"},
    {"protocolId": "6", "className": "XmippProtCTFConsensus", "status": "finished"},
    {"protocolId": "9", "className": "XmippProtCTFConsensus", "status": "finished"},
    {"protocolId": "11", "className": "ProtBoxSizeParameters", "status": "finished"},
    {"protocolId": "13", "className": "ProtBoxSizeParameters", "status": "failed"},
    {"protocolId": "22", "className": "XmippProtExtractParticles", "status": "finished"},
]
OUTPUTS = {"5": {"outputCTF"}, "6": {"outputCTF", "outputMicrographs"}, "9": {"outputCTF", "outputMicrographs"},
           "11": {"boxSizeExtraction"}, "13": {"boxSizeExtraction"}, "22": {"outputParticles"}}
CLASSES = {step["id"]: step["className"] for step in T.steps(TEMPLATE)}
EXTERNAL = ["4.outputParticles", "2.outputCTF", "3.boxSizeExtraction", "2.outputMicrographs"]


def links(ancestors, overrides=None, project=PROJECT):
    found = T.suggestLinks(EXTERNAL, CLASSES, "4.outputParticles", {"protocolId": "22", "output": "outputParticles"},
                           ancestors, project, lambda pid: OUTPUTS.get(pid, set()), overrides)
    return {link["templateRef"]: (link["projectRef"], link["how"]) for link in found}


def test_LinksPreferTheSourcesOwnAncestors():
    found = links([{"protocolId": "11", "depth": 1}, {"protocolId": "6", "depth": 3}])
    assert found["4.outputParticles"] == ("22.outputParticles", "the source")
    assert found["2.outputCTF"] == ("6.outputCTF", "an earlier step of the source")
    assert found["3.boxSizeExtraction"] == ("11.boxSizeExtraction", "an earlier step of the source")


def test_LinksFallBackToTheNewestFinishedOfTheSameKind():
    found = links([])
    assert found["2.outputCTF"] == ("9.outputCTF", "the same kind of protocol in the project")
    # A failed protocol is never used
    assert found["3.boxSizeExtraction"] == ("11.boxSizeExtraction", "the same kind of protocol in the project")


def test_LinksFallBackToTheSameOutputAmongTheAncestors():
    project = [row for row in PROJECT if row["className"] != "XmippProtCTFConsensus"]
    found = links([{"protocolId": "5", "depth": 1}], project=project)
    assert found["2.outputCTF"] == ("5.outputCTF", "the same output in an earlier step")
    assert found["2.outputMicrographs"] == (None, "")


def test_ChosenLinksWin():
    found = links([], overrides={"2.outputCTF": "5.outputCTF"})
    assert found["2.outputCTF"] == ("5.outputCTF", "chosen")
