"""A protocol's picking session: access, micrographs, saving particles."""
import pytest
from fastapi import HTTPException

from app.backend.api.services import xmipp_picking_files as files
from app.backend.api.services import xmipp_picking_session_service as module


class Db:
    def __init__(self, inputRef):
        self.inputRef = inputRef

    def fetchOne(self, query, params):
        return self.inputRef


class Mapper:
    def __init__(self, className="XmippProtParticlePicking", inputRef=None):
        self.className = className
        self.db = Db(inputRef if inputRef is not None else {
            "parentProtocolDbId": 142, "parentProtocolId": "9", "parentOutputName": "outputMicrographs"})

    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        return {"id": 9277, "protocolClassName": self.className}


class ProjectService:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def getProjectDbRow(self, mapper, projectId, currentUser):
        return {"id": projectId} if self.allowed else None


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(module.ProjectRuntimeRepository, "getProjectNameById",
                        lambda self, mapper, projectId: str(tmp_path))

    class SetMapper:
        def __init__(self, db):
            pass

        def getStoredSet(self, projectId, protocolDbId, outputName):
            assert (protocolDbId, outputName) == (142, "outputMicrographs")
            return {"items": [
                {"scipionItemId": 4, "values": {"_filename": "Runs/000009_X/extra/a_DW.mrc", "_micName": "a.tif"}},
                {"scipionItemId": 5, "values": {"_filename": "Runs/000009_X/extra/b_DW.mrc", "_micName": "b.tif"}},
            ]}

    monkeypatch.setattr(module, "ScipionSetPostgresqlMapper", SetMapper)
    extra = tmp_path / "Runs" / "000116_XmippProtParticlePicking" / "extra"
    extra.mkdir(parents=True)
    return module.XmippPickingSessionService(ProjectService()), extra


def test_the_session_lists_the_input_micrographs_and_their_desktop_picks(session):
    service, extra = session
    files.writePos(str(extra / "a_DW.pos"), files.MicrographPicks(
        state="Supervised", manual=[(1, 2)], automatic=[(3, 4, 0.9, 1), (5, 6, 0.8, -1)]))
    files.writeConfig(str(extra / "config.xmd"), files.PickerConfig(micrograph="a_DW", particleSize=99, mode="Supervised"))
    described = service.describeSession(Mapper(), 7, 116, {"id": 1})
    assert described["boxSize"] == 99 and described["mode"] == "Supervised"
    first, second = described["micrographs"]
    assert (first["id"], first["label"], first["particles"], first["state"]) == ("4", "a.tif", 2, "Supervised")
    assert (second["particles"], second["state"]) == (0, "Available")
    assert described["totalPicks"] == 2


def test_saving_replaces_manual_particles_and_keeps_automatic_ones(session):
    service, extra = session
    files.writePos(str(extra / "a_DW.pos"), files.MicrographPicks(
        state="Supervised", automatic=[(3, 4, 0.9, 1)]))
    result = service.saveParticles(Mapper(), 7, 116, {"id": 1}, "4",
                                   [{"x": 10.4, "y": 20.6}, {"id": "a0", "x": 3, "y": 4}])
    picks = files.readPos(str(extra / "a_DW.pos"))
    assert result == {"saved": 2, "state": "Supervised"}
    assert picks.manual == [(10, 21)] and picks.automatic == [(3, 4, 0.9, 1)]
    config = files.readConfig(str(extra / "config.xmd"))
    assert (config.manualParticlesNum, config.autoParticlesNum, config.micrograph) == (1, 1, "a_DW")


def test_a_first_manual_pick_starts_the_micrograph_and_removing_all_frees_it(session):
    service, extra = session
    assert service.saveParticles(Mapper(), 7, 116, {"id": 1}, "5", [{"x": 1, "y": 1}])["state"] == "Manual"
    assert service.saveParticles(Mapper(), 7, 116, {"id": 1}, "5", [])["state"] == "Available"
    assert not (extra / "b_DW.pos").exists()


def test_particle_size_is_saved_in_the_desktop_config(session):
    service, extra = session
    assert service.saveSettings(Mapper(), 7, 116, {"id": 1}, particleSize=186)["boxSize"] == 186
    assert files.readConfig(str(extra / "config.xmd")).particleSize == 186
    with pytest.raises(HTTPException):
        service.saveSettings(Mapper(), 7, 116, {"id": 1}, particleSize=0)


@pytest.mark.parametrize("mapper, service_allowed, status", [
    (Mapper(), False, 404),
    (Mapper(className="SphireProtCRYOLOPicking"), True, 409),
    (Mapper(inputRef={}), True, 409),
])
def test_only_reachable_xmipp_picking_protocols_with_input_micrographs_open(
        session, mapper, service_allowed, status):
    service, _ = session
    service.projectService.allowed = service_allowed
    with pytest.raises(HTTPException) as error:
        service.describeSession(mapper, 7, 116, {"id": 1})
    assert error.value.status_code == status


def test_unknown_micrographs_and_bad_coordinates_are_rejected(session):
    service, _ = session
    with pytest.raises(HTTPException) as error:
        service.listParticles(Mapper(), 7, 116, {"id": 1}, "999")
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        service.saveParticles(Mapper(), 7, 116, {"id": 1}, "4", [{"x": "left"}])
    assert error.value.status_code == 422


def test_automatic_particles_are_listed_with_their_score_unless_rejected(session):
    service, extra = session
    files.writePos(str(extra / "a_DW.pos"), files.MicrographPicks(
        state="Supervised", threshold=0.3, manual=[(1, 2)],
        automatic=[(3, 4, 0.9, 1), (5, 6, 0.8, -1), (7, 8, 0.2, 1)]))
    listed = service.listParticles(Mapper(), 7, 116, {"id": 1}, "4")
    assert [(p["id"], p.get("kind"), p.get("score")) for p in listed["coordinates"]] == [
        ("m0", None, None), ("a0", "automatic", 0.9), ("a2", "automatic", 0.2)]
    assert listed["threshold"] == 0.3 and listed["automaticTotal"] == 3


def test_removed_automatic_particles_are_rejected_and_moved_ones_become_manual(session):
    service, extra = session
    files.writePos(str(extra / "a_DW.pos"), files.MicrographPicks(
        state="Supervised", automatic=[(3, 4, 0.9, 1), (5, 6, 0.8, 1), (7, 8, 0.7, 1)]))
    service.saveParticles(Mapper(), 7, 116, {"id": 1}, "4",
                          [{"id": "a0", "x": 3, "y": 4}, {"id": "a2", "x": 70, "y": 80}], threshold=0.5)
    picks = files.readPos(str(extra / "a_DW.pos"))
    assert picks.manual == [(70, 80)]
    assert picks.automatic == [(3, 4, 0.9, 1), (5, 6, 0.8, -1), (7, 8, 0.7, -1)]
    assert picks.threshold == 0.5


class FakeClassifier:
    def __init__(self):
        self.calls = []
        self.lastAutopicked = None
        self.trainedOn = None

    def train(self, rows, rectangle):
        self.calls.append(("train", [row[1].rsplit("/", 1)[-1] for row in rows], rectangle))

    def autopick(self, micrograph, percent):
        self.calls.append(("autopick", micrograph.rsplit("/", 1)[-1], percent))
        self.lastAutopicked = micrograph
        return [(1, 1, 0.9), (500, 500, 0.8)]

    def correct(self, added, rows):
        self.calls.append(("correct", list(added), list(rows)))


@pytest.fixture
def supervised(session, monkeypatch):
    service, extra = session
    classifier = FakeClassifier()
    monkeypatch.setattr(service, "_classifier", lambda *args: classifier)
    monkeypatch.setattr(service, "_trainingRectangle", lambda session, mic, manual, size: (0, 0, 100, 100))
    classifier.templates = []
    monkeypatch.setattr(service, "writeTemplates",
                        lambda session, mapper, config, allPicks=None: classifier.templates.append(config.mode))
    return service, extra, classifier


def test_training_needs_enough_manual_particles(supervised):
    service, extra, classifier = supervised
    service.saveParticles(Mapper(), 7, 116, {"id": 1}, "4", [{"x": 10, "y": 10}] * 3)
    with pytest.raises(HTTPException) as error:
        service.trainAndAutopick(Mapper(), 7, 116, {"id": 1}, "4")
    assert error.value.status_code == 409 and "at least 15" in error.value.detail
    assert classifier.calls == []


def test_train_uses_every_manual_micrograph_and_rejects_picks_in_the_trained_area(supervised):
    service, extra, classifier = supervised
    service.saveParticles(Mapper(), 7, 116, {"id": 1}, "5", [{"x": 300, "y": 300}] * 5)
    service.saveParticles(Mapper(), 7, 116, {"id": 1}, "4", [{"x": 10, "y": 10}] * 12)
    listed = service.trainAndAutopick(Mapper(), 7, 116, {"id": 1}, "4")
    assert classifier.calls[0] == ("train", ["b_DW.pos", "a_DW.pos"], (0, 0, 100, 100))
    picks = files.readPos(str(extra / "a_DW.pos"))
    assert picks.state == "Supervised"
    assert picks.automatic == [(1, 1, -1.0, -1), (500, 500, 0.8, 1)]
    assert [p["id"] for p in listed["coordinates"] if p.get("kind")] == ["a1"]
    assert files.readConfig(str(extra / "config.xmd")).mode == "Supervised"
    # Xmipp's automatic picking needs templates.stk next to the model.
    assert classifier.templates == ["Supervised"]


def _writeMicrograph(path, data):
    from pwem import emlib
    image = emlib.Image()
    image.setData(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.write(str(path))


def test_templates_average_the_manual_particles_inside_their_micrographs(session):
    import numpy as np
    from pwem.emlib.image import ImageHandler
    service, extra = session
    micrographs = extra.parent.parent / "000009_X" / "extra"
    particle = np.zeros((200, 200), dtype=np.float32)
    particle[95:105, 95:105] = 1.0
    _writeMicrograph(micrographs / "a_DW.mrc", particle)
    _writeMicrograph(micrographs / "b_DW.mrc", np.zeros((200, 200), dtype=np.float32))
    service.saveSettings(Mapper(), 7, 116, {"id": 1}, particleSize=20)
    # The second particle is too close to the border to be boxed.
    service.saveParticles(Mapper(), 7, 116, {"id": 1}, "4", [{"x": 100, "y": 100}, {"x": 5, "y": 5}])
    path = service.writeTemplates(service.openSession(Mapper(), 7, 116, {"id": 1}),
                                  Mapper(), files.readConfig(str(extra / "config.xmd")))
    assert path == str(extra / "templates.stk")
    assert ImageHandler().getDimensions(path)[:2] == (20, 20)
    template = ImageHandler().read("1@" + path).getData()
    assert template[10, 10] > template[0, 0]


def test_closing_a_trained_session_without_templates_writes_them(session, monkeypatch):
    service, extra = session
    written = []
    monkeypatch.setattr(service, "writeTemplates", lambda session, mapper, config, allPicks=None: written.append(1))
    service.closeWebSession(Mapper(), 7, 116, {"id": 1})
    assert written == []
    (extra / "model_svm.txt").write_text("model")
    service.closeWebSession(Mapper(), 7, 116, {"id": 1})
    assert written == [1]


def test_next_learns_from_corrections_and_autopicks_a_free_next_micrograph(supervised):
    service, extra, classifier = supervised
    service.saveParticles(Mapper(), 7, 116, {"id": 1}, "4", [{"x": 10, "y": 10}] * 15)
    service.trainAndAutopick(Mapper(), 7, 116, {"id": 1}, "4")
    # The user rejects the automatic particle and adds one outside the trained area.
    service.saveParticles(Mapper(), 7, 116, {"id": 1}, "4",
                          [{"x": 10, "y": 10}] * 15 + [{"x": 700, "y": 700}])
    result = service.correctAndAutopick(Mapper(), 7, 116, {"id": 1}, "4", "5")
    correct = [call for call in classifier.calls if call[0] == "correct"][0]
    assert correct[1] == [(700, 700)]
    assert correct[2] == [(1, 1, -1.0, -1), (500, 500, 0.8, -1)]
    assert files.readPos(str(extra / "a_DW.pos")).state == "Corrected"
    nextPicks = files.readPos(str(extra / "b_DW.pos"))
    assert nextPicks.state == "Supervised" and len(nextPicks.automatic) == 2
    assert result["state"] == "Corrected" and len(result["next"]["coordinates"]) == 2


def test_next_does_not_correct_with_candidates_of_another_micrograph(supervised):
    service, extra, classifier = supervised
    service.saveParticles(Mapper(), 7, 116, {"id": 1}, "4", [{"x": 10, "y": 10}] * 15)
    service.trainAndAutopick(Mapper(), 7, 116, {"id": 1}, "4")
    classifier.lastAutopicked = "/elsewhere/other.mrc"
    service.correctAndAutopick(Mapper(), 7, 116, {"id": 1}, "4", None)
    assert not [call for call in classifier.calls if call[0] == "correct"]


def test_next_requires_a_trained_picker(supervised):
    service, extra, classifier = supervised
    with pytest.raises(HTTPException) as error:
        service.correctAndAutopick(Mapper(), 7, 116, {"id": 1}, "4", "5")
    assert error.value.status_code == 409
