from app.backend.api.services import tutorial_progress as tutorial


def row(protocolId, className, status="finished", output=None, size=None):
    return {"protocolId": protocolId, "className": className, "status": status, "label": className.lower(),
            "outputClass": output, "size": size}


def states(data):
    return {stage["key"]: stage["state"] for stage in data["stages"]}


SPA = [
    row("2", "ProtImportMovies", output="SetOfMovies", size="30"),
    row("3", "ProtMotionCorr", output="SetOfMovies", size="30"),
    row("3", "ProtMotionCorr", output="SetOfMicrographs", size="30"),
    row("5", "CistemProtCTFFind", output="SetOfCTF", size="28"),
    row("10", "SphireProtCRYOLOPicking", output="SetOfCoordinates", size="3885"),
    row("11", "ProtBoxSizeParameters", output="Integer"),
    row("22", "XmippProtExtractParticles", output="SetOfParticles", size="3445"),
    row("37", "XmippProtClassifyPcaStreaming", output="SetOfClasses2D", size="42"),
    row("106", "ProtCryoSparcInitialModel", output="SetOfClasses3D", size="4"),
    row("106", "ProtCryoSparcInitialModel", output="SetOfVolumes", size="4"),
    row("111", "ProtCryoSparc3DClassification", output="SetOfClasses3D", size="2"),
    row("124", "ProtImportVolumes", output="Volume"),
]


def test_SinglParticleRoadUpToTheRefinement():
    data = tutorial.progress(SPA)
    assert data["kind"] == "spa"
    assert states(data) == {"movies": "done", "micrographs": "done", "ctf": "done", "coordinates": "done",
                            "particles": "done", "classes2d": "done", "initial": "done", "classes3d": "done",
                            "refined": "pending"}
    assert data["current"] == data["next"] == "refined"
    assert data["fromProtocolId"] == "111"
    # Counts come from what was made; the initial model's classes are not the 3D classification
    stages = {stage["key"]: stage for stage in data["stages"]}
    assert stages["coordinates"]["items"] == 3885
    assert [item["id"] for item in stages["classes3d"]["protocols"]] == ["111"]


def test_RunningFailedAndPreparedStagesFromProtocolsThatMadeNothingYet():
    data = tutorial.progress([
        row("2", "ProtImportMovies", output="SetOfMovies", size="30"),
        row("3", "ProtMotionCorr", output="SetOfMicrographs", size="10"),
        row("4", "CistemProtCTFFind", status="failed"),
        row("5", "SphireProtCRYOLOPicking", status="saved"),
    ])
    assert states(data)["ctf"] == "failed" and states(data)["coordinates"] == "prepared"
    assert data["current"] == "ctf"
    running = tutorial.progress(SPA[:3] + [row("5", "CistemProtCTFFind", status="running", output="SetOfCTF",
                                               size="4")])
    assert states(running)["ctf"] == "running" and running["current"] == "ctf"
    waiting = tutorial.progress(SPA[:4] + [row("6", "XmippProtParticlePicking", status="interactive")])
    assert states(waiting)["coordinates"] == "waiting"


def test_StagesLeftBehindWereSkipped():
    data = tutorial.progress([row("2", "ProtImportMicrographs", output="SetOfMicrographs", size="50"),
                              row("3", "CistemProtCTFFind", output="SetOfCTF", size="50")])
    assert states(data)["movies"] == "skipped"
    assert data["next"] == "coordinates" and data["fromProtocolId"] == "3"


def test_TomographyRoad():
    data = tutorial.progress([
        row("2", "ProtImportTsMovies", output="SetOfTiltSeriesM", size="2"),
        row("3", "ProtWarpTSMotionCorr", output="SetOfTiltSeries", size="2"),
        row("3", "ProtWarpTSMotionCorr", output="SetOfCTFTomoSeries", size="2"),
        row("5", "ProtAreTomoAlignRecon", output="SetOfTiltSeries", size="2"),
        row("5", "ProtAreTomoAlignRecon", output="SetOfTomograms", size="2"),
        row("21", "EmanProtTemplateMatching", output="SetOfCoordinates3D", size="1008"),
        row("22", "ProtRelion5ReconstructParticle", status="saved"),
    ])
    assert data["kind"] == "tomo"
    assert states(data) == {"movies": "done", "motion": "done", "ctf": "done", "alignment": "done",
                            "tomograms": "done", "coordinates": "done", "subtomograms": "pending",
                            "average": "prepared"}
    assert data["next"] == "subtomograms" and data["fromProtocolId"] == "21"


def test_AnEmptyProjectAsksWhichKindOfData():
    data = tutorial.progress([])
    assert data["kind"] is None and data["empty"]
    assert "Ask the user which kind of data" in tutorial.describe(data)
    # Saying the road is enough
    assert tutorial.progress([], "tomo")["next"] == "movies"


def test_TheCardAndTheDescription():
    data = tutorial.progress(SPA)
    card = tutorial.card(7, data)
    assert card["kind"] == "tutorial" and card["projectId"] == 7 and card["road"] == "spa"
    assert set(card["stages"][0]) == {"key", "title", "state", "items", "protocols"}
    text = tutorial.describe(data)
    assert "- refined [3D refinement]: pending" in text
    assert "Go on from protocol: 111." in text


class _Model:
    def __init__(self):
        self.sent = []

    def chat(self, messages, tools=None):
        self.sent.append(messages)
        return {"message": {"content": "ok"}, "usage": {"inputTokens": 1, "outputTokens": 1}}


def _agent(canPropose):
    from app.backend.api.services.assistant_agent import AssistantAgent, AssistantTools

    read = [lambda: [], lambda p: [], lambda p, q: None, lambda p, q, c: "", lambda p, q: {}, lambda q: []]
    propose = dict(proposeRelaunch=lambda *a: {}, proposeStop=lambda *a: {}, proposeNextStep=lambda *a: {}) \
        if canPropose else {}
    model = _Model()
    return AssistantAgent(model, AssistantTools(*read, **propose)), model


def test_TheAgentTeachesWithTheProgressAsData():
    agent, model = _agent(True)
    agent.answer("guide me", "The user is in project p (id 7).", tutor=tutorial.describe(tutorial.progress(SPA)))
    system = model.sent[0][0]["content"]
    assert "You are now the TUTOR" in system and "propose_next_step" in system
    # The progress (with the user's own names) comes after the rules, with the context
    assert system.index("Everything the tools return") < system.index("Where the project is on its road")
    agent, model = _agent(False)
    agent.answer("guide me", "", tutor="")
    system = model.sent[0][0]["content"]
    assert "which protocol to add" in system and "ask them to open their project" in system
    agent, model = _agent(False)
    agent.answer("hi", "")
    assert "TUTOR" not in model.sent[0][0]["content"]
