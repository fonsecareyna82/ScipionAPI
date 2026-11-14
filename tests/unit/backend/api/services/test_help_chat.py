"""The help chat answers with real help texts: the kind of question decides which, and the search ranks first what
has more of the question's words."""
from app.backend.api.services import help_chat
from app.backend.api.services.help_chat import HelpChat, isSpanish, queryGroups, summaryOf

PROTOCOLS = [
    {"className": "ProtMotionCorr", "label": "movie alignment",
     "doc": "Aligns the frames of each movie and corrects the beam-induced drift.\n\nMore text.",
     "params": [{"name": "doseFilter", "label": "Apply dose filter", "help": "Weights each frame by its dose.",
                 "section": "Input", "group": ""},
                {"name": "gpuList", "label": "Choose GPU IDs", "help": "The GPUs to use.", "section": "Hardware",
                 "group": ""}]},
    {"className": "ProtCTFFind", "label": "ctffind", "doc": "Estimates the CTF of the micrographs.", "params": []},
    {"className": "XmippProtCTFMicrographs", "label": "ctf estimation",
     "doc": "Estimates the contrast transfer function (CTF) of the micrographs.", "params": []},
    {"className": "ProtImportVolumes", "label": "import volumes", "doc": "Imports maps. Projects mention projects.",
     "params": []},
]

GUIDE = [
    {"page": "Projects", "title": "Share a project", "text": "Open the project menu and choose Share.",
     "url": "https://docs/user-guide/projects/#share-a-project"},
    {"page": "Outputs", "title": "Open an output", "text": "Click an output to open its viewer.",
     "url": "https://docs/user-guide/outputs/#open-an-output"},
]

ROWS = [
    {"protocolId": "2", "className": "ProtImportVolumes", "status": "finished", "label": "import volumes"},
    {"protocolId": "3", "className": "ProtMotionCorr", "status": "failed", "label": "motioncor"},
    {"protocolId": "4", "className": "ProtCTFFind", "status": "running", "label": "ctffind"},
]


OUTPUTS = {
    "4": [{"outputName": "outputCoordinates", "setClassName": "SetOfCoordinates", "itemClassName": "Coordinate",
           "size": 12345},
          {"outputName": "outputParticles", "setClassName": "SetOfParticles", "itemClassName": "Particle",
           "size": 9876}],
    "2": [{"outputName": "outputVolume", "setClassName": "Volume", "itemClassName": None, "size": None}],
}


def chat(rows=ROWS, failure=None, suggestions=None):
    return HelpChat(lambda: PROTOCOLS, (lambda: rows) if rows is not None else None,
                    lambda protocolId: failure or {"cause": {"title": "Out of GPU memory", "hint": "Use another GPU"}},
                    suggestions or (lambda className: []), guide=lambda: GUIDE,
                    protocolOutputs=lambda protocolId: OUTPUTS.get(protocolId, []))


def kinds(answer):
    return [card["kind"] for card in answer["cards"]]


def test_language_of_the_question():
    assert isSpanish("¿cómo estimo el CTF?")
    assert isSpanish("que va despues del picking")
    assert not isSpanish("how do I estimate the CTF?")


def test_spanish_words_also_search_their_english_ones():
    groups = queryGroups("corregir el movimiento")
    assert any("mot" in group or "motion" in group for group in groups)
    assert len(groups) == 2


def test_summary_is_the_first_paragraph():
    assert summaryOf("First part.\n\nSecond part.") == "First part."


def test_why_a_selected_protocol_failed():
    answer = chat().answer("¿Por qué ha fallado?", "3")
    assert answer["text"].startswith("Por esto ha fallado motioncor")
    assert kinds(answer) == ["failure"]
    assert answer["cards"][0]["explained"]["cause"]["title"] == "Out of GPU memory"


def test_a_protocol_by_its_number_and_one_that_did_not_fail():
    answer = chat().answer("why did #4 fail?")
    assert answer["text"] == "ctffind did not fail: it is running."
    assert chat().answer("why did #99 fail?")["text"] == "There is no protocol 99 in this project."


def test_which_failed_without_a_protocol():
    answer = chat().answer("what failed?")
    assert kinds(answer) == ["protocols"]
    assert [item["protocolId"] for item in answer["cards"][0]["items"]] == ["3"]


def test_failure_needs_a_project():
    assert chat(rows=None).answer("why did it fail?")["text"] == "Open a project to ask about its protocols."


def test_what_comes_next_uses_the_suggestions_and_marks_what_is_not_installed():
    def suggestions(className):
        assert className == "ProtMotionCorr"
        return [{"className": "ProtCTFFind", "count": 9}, {"className": "ProtMissing", "count": 3}]

    answer = chat(suggestions=suggestions).answer("What comes next?", "3")
    items = answer["cards"][0]["items"]
    assert [item["installed"] for item in items] == [True, False]
    assert items[0]["label"] == "ctffind"


def test_what_comes_next_asks_which_protocol():
    assert chat().answer("qué va después?")["text"].startswith("¿Qué protocolo?")


def test_status_of_the_project_failed_first():
    answer = chat().answer("How is the project going?")
    assert [item["status"] for item in answer["cards"][0]["items"]] == ["failed", "running", "finished"]


def test_search_finds_protocols_by_their_words():
    answer = chat().answer("how do I estimate the CTF?")
    labels = [card["label"] for card in answer["cards"]]
    assert set(labels) == {"ctffind", "ctf estimation"}


def test_search_in_spanish():
    answer = chat().answer("¿cómo corrijo el movimiento de las movies?")
    assert answer["text"] == "Esto es lo que he encontrado en la ayuda:"
    assert answer["cards"][0]["label"] == "movie alignment"


def test_the_selected_protocols_parameters_answer_first():
    answer = chat().answer("dose filter", "3")
    assert answer["text"] == "In the parameters of motioncor:"
    assert answer["cards"][0] == {"kind": "param", "className": "ProtMotionCorr", "protocolLabel": "movie alignment",
                                  "name": "doseFilter", "label": "Apply dose filter",
                                  "help": "Weights each frame by its dose.", "section": "Input"}


def test_the_guide_beats_protocols_that_only_mention_the_words():
    answer = chat().answer("how do I share a project")
    assert kinds(answer) == ["guide"]
    assert answer["cards"][0]["url"].endswith("#share-a-project")


def test_nothing_found():
    answer = chat().answer("frobnicate the zorblax")
    assert answer["cards"] == []
    assert answer["text"].startswith("I found nothing")


def test_empty_question():
    assert chat().answer("   ")["cards"] == []


def test_suggestions_service_errors_give_nothing(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr("urllib.request.urlopen", broken)
    assert help_chat.fetchSuggestions("ProtMotionCorr") == []


def test_chat_sentences_are_answered_not_searched():
    assert chat().answer("Ah ok")["text"] == "Ok. If you have another question, write it here."
    assert chat().answer("muchas gracias!")["text"] == "De nada. Pregúntame lo que necesites cuando quieras."
    assert chat().answer("thanks a lot")["text"].startswith("You're welcome")
    assert chat().answer("hola")["text"].startswith("¡Hola!")
    assert chat().answer("hasta luego")["text"].startswith("¡Hasta luego!")
    assert chat().answer("ok, ¿y el CTF?")["cards"]


def test_what_happened_to_a_protocol():
    failed = chat().answer("qué pasó con el protocolo #3?")
    assert kinds(failed) == ["failure"]
    running = chat().answer("¿qué pasó con el #4?")
    assert running["text"] == "ctffind (#4): se está ejecutando. Esto es lo que hace:"
    assert running["cards"][0]["label"] == "ctffind"
    assert chat().answer("what happened?", "2")["text"].startswith("import volumes (#2): it finished well.")
    assert chat().answer("¿por qué ha fallado el #4?")["text"] == "ctffind no ha fallado: se está ejecutando."
    assert kinds(chat().answer("¿qué ha pasado con el 3?")) == ["failure"]
    assert chat().answer("el #4 cómo va?")["text"].startswith("ctffind (#4)")
    assert chat().answer("¿cómo va el proyecto?")["cards"][0]["kind"] == "protocols"


def test_how_many_items_a_protocol_made():
    answer = chat().answer("How many particles has #4")
    assert answer["text"] == "ctffind (#4) has 9,876 particles in outputParticles."
    assert [item["size"] for item in answer["cards"][0]["items"]] == [12345, 9876]
    assert chat().answer("¿cuántas coordenadas tiene el #4?")["text"] == \
        "ctffind (#4) tiene 12.345 coordenadas en outputCoordinates."
    assert chat().answer("how many micrographs has #4?")["text"].startswith("ctffind (#4) made no micrographs")
    assert chat().answer("¿qué salidas tiene?", "2")["cards"][0]["items"][0]["type"] == "Volume"
    assert chat().answer("how many particles has #3")["text"].startswith("motioncor (#3) has no outputs yet: it failed")
    assert chat().answer("¿cuántas partículas hay?")["text"].startswith("¿De qué protocolo?")
