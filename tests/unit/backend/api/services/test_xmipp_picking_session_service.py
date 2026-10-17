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
    result = service.saveParticles(Mapper(), 7, 116, {"id": 1}, "4", [{"x": 10.4, "y": 20.6}])
    picks = files.readPos(str(extra / "a_DW.pos"))
    assert result == {"saved": 1, "state": "Supervised"}
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
