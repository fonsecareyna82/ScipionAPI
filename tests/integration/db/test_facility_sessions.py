"""A facility's sessions and their datasets, against the migrated database."""
import datetime
import io
import re
from uuid import uuid4

import pytest
from fastapi import HTTPException
from PIL import Image

from app.backend.api.services.facility_sample_service import FacilitySampleService
from app.backend.api.services.facility_service import FacilityService
from app.backend.api.services.facility_session_processing import FacilitySessionProcessor
from app.backend.api.services.facility_session_service import FacilitySessionService


@pytest.fixture
def facility(postgresqlIntegrationDb, postgresqlMigratedEnv):
    """A microscope that runs sessions and a sample with four grids; what the test makes is removed after it."""
    db = postgresqlIntegrationDb
    microscope = FacilityService(db).saveMicroscope({
        "name": "Talos %s" % uuid4().hex, "sessionsEnabled": True,
        "detectors": [{"name": "Falcon 4i", "metadataName": "BM-Falcon"}, {"name": "Ceta-D"}]})
    sample = FacilitySampleService(db).saveSample({
        "code": "NZ%s" % uuid4().hex[:8],
        "boxes": [{"label": "2 green", "grids": [{"position": position, "gridNumber": position + 4,
                                                  "specimen": "nsp9+T2C3"} for position in range(1, 5)]}]})
    sessions = FacilitySessionService(db)
    try:
        yield sessions, microscope, sample
    finally:
        db.execute('DELETE FROM facility_sessions WHERE "microscopeId" = %s', (microscope["id"],))
        db.execute("DELETE FROM facility_samples WHERE id = %s", (sample["id"],))
        db.execute("DELETE FROM facility_microscopes WHERE id = %s", (microscope["id"],))


def _grids(sample):
    return sample["boxes"][0]["grids"]


def _multigrid(microscope, sample, **change):
    grids = _grids(sample)
    return dict({"microscopeId": microscope["id"], "bookingRef": "B-1203", "scheduledOn": "2026-10-31",
                 "datasets": [{"number": 1, "gridId": grids[1]["id"]}, {"number": 2, "gridId": grids[3]["id"]}]},
                **change)


def test_ASessionIsNamedAsTheFacilityDoesAndKnowsItsFolders(facility):
    sessions, microscope, sample = facility

    session = sessions.saveSession(_multigrid(microscope, sample))

    assert re.match(r"^2026_10_31_Facility_\d{6}$", session["name"])
    assert session["name"].endswith("%06d" % session["id"]) and session["status"] == "planned"
    assert [dataset["folder"] for dataset in session["datasets"]] == [
        session["name"] + "_ATLAS", session["name"] + "_DATA_01", session["name"] + "_DATA_02"]
    grid = session["datasets"][1]["grid"]
    assert (grid["sampleCode"], grid["boxLabel"], grid["position"], grid["gridNumber"]) == (
        sample["code"], "2 green", 2, 6)


def test_EditingKeepsTheDatasetsIdsAndTheAtlas(facility):
    sessions, microscope, sample = facility
    session = sessions.saveSession(_multigrid(microscope, sample))
    atlas, first, _ = session["datasets"]
    falcon = microscope["detectors"][0]

    edited = sessions.saveSession(dict(session, microscopeId=microscope["id"], datasets=[
        dict(first, detectorId=falcon["id"], notes="Thick ice in the centre")]), sessionId=session["id"])

    assert [dataset["id"] for dataset in edited["datasets"]] == [atlas["id"], first["id"]]
    assert edited["datasets"][1]["detectorName"] == "Falcon 4i"


def test_TheNameStaysOnceTheAcquisitionStarts(facility):
    sessions, microscope, sample = facility
    session = sessions.saveSession(_multigrid(microscope, sample, name="NZ251_screening"))

    started = sessions.saveSession(dict(_multigrid(microscope, sample), status="acquiring"), sessionId=session["id"])
    assert started["name"] == "NZ251_screening" and started["startedAt"] is not None

    with pytest.raises(HTTPException) as error:
        sessions.saveSession(dict(_multigrid(microscope, sample), name="other", status="acquiring"),
                             sessionId=session["id"])
    assert "name stays" in error.value.detail
    with pytest.raises(HTTPException) as error:
        sessions.deleteSession(session["id"])
    assert error.value.status_code == 409


def test_WhatASessionUsedStays(facility):
    sessions, microscope, sample = facility
    sessions.saveSession(_multigrid(microscope, sample))
    samples = FacilitySampleService(sessions.mapper.db)

    unusedOnly = dict(sample, boxes=[dict(sample["boxes"][0], grids=[_grids(sample)[1], _grids(sample)[3]])])
    assert len(samples.saveSample(unusedOnly, sampleId=sample["id"])["boxes"][0]["grids"]) == 2
    with pytest.raises(HTTPException) as error:
        samples.saveSample(dict(sample, boxes=[]), sampleId=sample["id"])
    assert error.value.status_code == 409 and "Grids used in sessions" in error.value.detail
    with pytest.raises(HTTPException) as error:
        samples.deleteSample(sample["id"])
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        FacilityService(sessions.mapper.db).deleteMicroscope(microscope["id"])
    assert error.value.status_code == 409


@pytest.mark.parametrize("change, message", [
    ({"datasets": [{"number": 13}]}, "DATA_01 to DATA_12"),
    ({"datasets": [{"number": 1}, {"number": 1}]}, "given twice"),
    ({"datasets": [{"number": 1, "gridId": 2147483000}]}, "Unknown grid"),
    ({"datasets": [{"number": 1, "detectorId": 2147483000}]}, "not one of this session's microscope"),
    ({"name": "NZ251 day one"}, "folder names"),
    ({"technique": "confocal"}, "Unknown technique"),
])
def test_ASessionIsCheckedBeforeItIsKept(facility, change, message):
    sessions, microscope, sample = facility

    with pytest.raises(HTTPException) as error:
        sessions.saveSession(_multigrid(microscope, sample, **change))
    assert message in error.value.detail


def test_AMicroscopeWithoutSessionsTakesNone(facility):
    sessions, microscope, sample = facility
    FacilityService(sessions.mapper.db).saveMicroscope(dict(microscope, sessionsEnabled=False),
                                                       microscopeId=microscope["id"])

    with pytest.raises(HTTPException) as error:
        sessions.saveSession(_multigrid(microscope, sample))
    assert "does not run sessions" in error.value.detail


def test_TheDatasetsOfAnotherSessionCannotBeTaken(facility):
    sessions, microscope, sample = facility
    one = sessions.saveSession(_multigrid(microscope, sample))
    other = sessions.saveSession(_multigrid(microscope, sample))

    with pytest.raises(HTTPException) as error:
        sessions.saveSession(dict(_multigrid(microscope, sample), datasets=[other["datasets"][1]]),
                             sessionId=one["id"])
    assert "not one of this session's" in error.value.detail


def test_ADatasetKeepsImagesThatGoWithTheSession(facility, postgresqlIntegrationDb):
    sessions, microscope, sample = facility
    session = sessions.saveSession(_multigrid(microscope, sample))
    raw = io.BytesIO()
    Image.new("RGB", (300, 200), (20, 20, 20)).save(raw, format="JPEG")

    added = sessions.addImage("dataset", session["datasets"][0]["id"], raw.getvalue(), caption="Atlas")
    assert [image["caption"] for image in added["session"]["datasets"][0]["images"]] == ["Atlas"]
    assert FacilitySampleService(postgresqlIntegrationDb).getImage(added["image"]["id"])["sessionId"] == session["id"]
    assert sessions.deleteImage(added["image"]["id"])["datasets"][0]["images"] == []

    sessions.addImage("session", session["id"], raw.getvalue())
    sessions.deleteSession(session["id"])
    row = postgresqlIntegrationDb.fetchOne('SELECT COUNT(*) AS n FROM facility_images WHERE "sessionId" = %s',
                                           (session["id"],))
    assert row["n"] == 0


def test_TheListFindsSessionsByStatusAndText(facility):
    sessions, microscope, sample = facility
    marker = uuid4().hex[:8]
    planned = sessions.saveSession(_multigrid(microscope, sample, bookingRef="B-%s" % marker))
    finished = sessions.saveSession(_multigrid(microscope, sample, bookingRef="B-%s" % marker, status="finished"))

    assert [found["id"] for found in sessions.listSessions(["planned", "acquiring"], marker)] == [planned["id"]]
    assert {found["id"] for found in sessions.listSessions([], marker)} == {planned["id"], finished["id"]}
    assert finished["finishedAt"] is not None and finished["startedAt"] is not None
    reopened = sessions.saveSession(dict(_multigrid(microscope, sample), status="acquiring"), sessionId=finished["id"])
    assert reopened["finishedAt"] is None and reopened["startedAt"] == finished["startedAt"]


def test_ANameIsMadeOfTheDayThePersonAndTheId():
    from app.backend.api.services.facility_session_service import sessionName

    assert sessionName(datetime.date(2026, 10, 31), "Gaoxin Lü", 123) == "2026_10_31_Gaoxin-Lu_000123"
    assert sessionName(datetime.date(2026, 10, 31), "  ", 7) == "2026_10_31_Facility_000007"


def test_TheWatcherFollowsTheDataOfASessionThatAcquires(facility, tmp_path):
    import os
    import shutil
    from pathlib import Path

    from app.backend.api.services.facility_session_watcher import watchSessions

    sessions, microscope, sample = facility
    db = sessions.mapper.db
    falcon = microscope["detectors"][0]
    calibrated = dict(falcon, metadataName="BM-Falcon", pixelSizes=[{"magnification": 92000, "pixelSize": 1.55}])
    FacilityService(db).saveMicroscope(dict(microscope, offloadPath=str(tmp_path),
                                            detectors=[calibrated, microscope["detectors"][1]]),
                                       microscopeId=microscope["id"])
    session = sessions.saveSession(_multigrid(microscope, sample, status="acquiring"))
    waiting = sessions.getSession(session["id"])["datasets"][1]
    assert waiting["watch"] == "pending"

    watchSessions(db)
    assert sessions.getSession(session["id"])["datasets"][1]["watch"] == "noFolder"

    # EPU makes DATA_01 and writes a movie with its metadata (EMPIAR-11502's)
    epu = Path(__file__).resolve().parents[2] / "resources" / "epu"
    data = tmp_path / ("%s_DATA_01" % session["name"]) / "Images-Disc1" / "GridSquare_1" / "Data"
    data.mkdir(parents=True)
    for name in ("FoilHole_15867355_Data_12771432_12771434_20200417_031214.xml",
                 "FoilHole_15867355_Data_12771432_12771434_20200417_031214_Fractions.xml"):
        shutil.copy(epu / name, data / name)
    (data / "FoilHole_15867355_Data_12771432_12771434_20200417_031214_Fractions.mrc").write_bytes(b"\0" * 100)
    (tmp_path / ("%s_DATA_02" % session["name"])).mkdir()

    assert watchSessions(db) == 2
    first, second = sessions.getSession(session["id"])["datasets"][1:]
    assert (first["watch"], first["movieCount"], first["movieBytes"]) == ("receiving", 1, 100)
    assert first["acquisition"]["detectorName"] == "Falcon 4i" and first["detectorName"] == "Falcon 4i"
    assert first["acquisition"]["pixelSize"] == 1.55 and first["acquisition"]["frames"] == 13
    assert first["firstMovieAt"] is not None and second["watch"] == "waiting"

    # More movies arrive: they are counted, and the first movie's reading is kept
    (data / "FoilHole_2_Data_2_3_20200417_031400_Fractions.mrc").write_bytes(b"\0" * 50)
    # (a file system with coarse times might not move the folder's modification time within the test)
    os.utime(data, (data.stat().st_atime, data.stat().st_mtime + 5))
    watchSessions(db)
    first = sessions.getSession(session["id"])["datasets"][1]
    assert (first["movieCount"], first["movieBytes"]) == (2, 150)
    assert first["acquisition"]["firstMovie"].endswith("031214_Fractions.mrc")

    # A session that does not acquire is not watched
    sessions.saveSession(dict(_multigrid(microscope, sample), status="finished"), sessionId=session["id"])
    assert watchSessions(db) == 0


class _Projects:
    """ProjectService as the processing sees it: real project rows, the rest recorded."""

    def __init__(self, flat, workflow, calls):
        self.flat, self.workflow, self.calls = flat, workflow, calls

    def materializeWorkflowTemplate(self, workflowId, aliasValues=None):
        self.calls.append(("template", workflowId, aliasValues.get("sr")))
        return [dict(protocol) for protocol in self.workflow]

    def createProject(self, mapper, projectData, currentUser):
        projectId = self.flat.insertProject(ownerId=currentUser["id"], name="/tmp/%s-%s" % (projectData.name, uuid4().hex),
                                            description=projectData.description)
        self.calls.append(("create", projectData.name, currentUser["id"]))
        return {"id": projectId}

    def loadPostgresqlRuntimeProjectForMutation(self, mapper, projectId, currentUser):
        return {"id": projectId}

    def importWorkflowProtocolsService(self, mapper, projectId, currentUser, payload):
        self.calls.append(("import", payload.workflow))
        return {"status": 0, "errors": [], "created": [{"sourceId": item["object.id"], "newId": str(100 + index)}
                                                        for index, item in enumerate(payload.workflow)]}

    def restartProtocolAll(self, mapper, projectId, protocolId, currentUserId=None):
        self.calls.append(("launch", projectId, protocolId))
        return {"status": 0, "errors": []}


@pytest.fixture
def owner(postgresqlIntegrationDb):
    """A user who may create projects."""
    from app.backend.mapper.postgresql import PostgresqlFlatMapper

    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    userId = flat.insertUser(email="facility-%s@example.com" % uuid4().hex, hashedPassword="test", firstName="Gaoxin",
                             lastName="Lu", institution=None, role="user", isActive=True, isVerified=True,
                             verificationCode="")
    role = db.fetchOne('SELECT r.id FROM access_roles r JOIN access_role_permissions p ON p."roleId" = r.id '
                       "WHERE p.permission = 'projects.create' AND NOT r.\"isSystem\" ORDER BY r.id LIMIT 1")
    db.execute('INSERT INTO user_access_roles ("userId", "roleId") VALUES (%s, %s)', (userId, role["id"]))
    try:
        yield flat, userId
    finally:
        db.execute('DELETE FROM projects WHERE "ownerId" = %s', (userId,))
        db.execute("DELETE FROM users WHERE id = %s", (userId,))


def _epuMovie(tmp_path, sessionName, number=1):
    import shutil
    from pathlib import Path

    epu = Path(__file__).resolve().parents[2] / "resources" / "epu"
    data = tmp_path / ("%s_DATA_%02d" % (sessionName, number)) / "Images-Disc1" / "GridSquare_1" / "Data"
    data.mkdir(parents=True)
    for name in ("FoilHole_15867355_Data_12771432_12771434_20200417_031214.xml",
                 "FoilHole_15867355_Data_12771432_12771434_20200417_031214_Fractions.xml"):
        shutil.copy(epu / name, data / name)
    (data / "FoilHole_15867355_Data_12771432_12771434_20200417_031214_Fractions.mrc").write_bytes(b"\0" * 10)


def _processWith(monkeypatch, flat, workflow, calls):
    from app.backend.api.services import facility_session_processing as processing

    monkeypatch.setattr(processing, "FacilitySessionProcessor",
                        lambda mapper: FacilitySessionProcessor(
                            mapper, projectServiceFactory=lambda: _Projects(flat, workflow, calls)))


DEMO_WORKFLOW = [{"object.className": "ProtImportMovies", "object.id": "2", "samplingRate": 3.54, "dosePerFrame": 0.0},
                 {"object.className": "ProtMotionCorr", "object.id": "3", "inputMovies": "2.outputMovies"}]


def test_ADataGetsItsProjectWhenItsFirstMovieIsRead(facility, owner, tmp_path, monkeypatch):
    from app.backend.api.services.facility_session_watcher import watchSessions

    sessions, microscope, sample = facility
    flat, userId = owner
    db = sessions.mapper.db
    falcon = dict(microscope["detectors"][0], metadataName="BM-Falcon",
                  pixelSizes=[{"magnification": 92000, "pixelSize": 1.55}])
    FacilityService(db).saveMicroscope(dict(microscope, offloadPath=str(tmp_path), csMm=2.7,
                                            detectors=[falcon, microscope["detectors"][1]]), microscopeId=microscope["id"])
    session = sessions.saveSession(_multigrid(microscope, sample, status="acquiring", userId=userId,
                                              templateId="scipion:demo"), userId=userId)
    calls = []
    _processWith(monkeypatch, flat, DEMO_WORKFLOW, calls)

    watchSessions(db)
    assert calls == []
    _epuMovie(tmp_path, session["name"])
    watchSessions(db)

    first = sessions.getSession(session["id"])["datasets"][1]
    assert first["processing"]["state"] == "launched" and first["projectId"] is not None
    assert first["processing"]["projectName"] == session["name"] + "_DATA_01"
    assert calls[0] == ("template", "scipion:demo", 1.55) and calls[1] == ("create", session["name"] + "_DATA_01", userId)
    imported = calls[2][1][0]
    assert imported["filesPath"] == str(tmp_path / (session["name"] + "_DATA_01"))
    assert imported["filesPattern"] == "Images-Disc*/GridSquare_*/Data/*_Fractions.mrc"
    assert (imported["samplingRate"], imported["voltage"], imported["sphericalAberration"]) == (1.55, 200.0, 2.7)
    assert imported["dataStreaming"] is True
    assert calls[3] == ("launch", first["projectId"], "100")

    # Made once: the next turns leave it
    watchSessions(db)
    assert len([call for call in calls if call[0] == "create"]) == 1


def test_AFailureIsKeptAndTheStaffAskAgain(facility, owner, tmp_path, monkeypatch):
    from app.backend.api.services.facility_session_watcher import watchSessions

    sessions, microscope, sample = facility
    flat, userId = owner
    db = sessions.mapper.db
    FacilityService(db).saveMicroscope(dict(microscope, offloadPath=str(tmp_path)), microscopeId=microscope["id"])
    session = sessions.saveSession(_multigrid(microscope, sample, status="acquiring", userId=userId,
                                              templateId="scipion:ctf-only"), userId=userId)
    calls = []
    _processWith(monkeypatch, flat, [{"object.className": "ProtCTFFind", "object.id": "2"}], calls)
    _epuMovie(tmp_path, session["name"])

    watchSessions(db)
    first = sessions.getSession(session["id"])["datasets"][1]
    assert first["processing"]["state"] == "error" and "no Import Movies" in first["processing"]["message"]
    assert first["projectId"] is None
    watchSessions(db)
    assert len([call for call in calls if call[0] == "template"]) == 1

    _processWith(monkeypatch, flat, DEMO_WORKFLOW, calls)
    queued = sessions.queueProcessing(first["id"])
    assert queued["datasets"][1]["processing"]["state"] == "queued"
    watchSessions(db)
    assert sessions.getSession(session["id"])["datasets"][1]["processing"]["state"] == "launched"
    with pytest.raises(HTTPException) as error:
        sessions.queueProcessing(first["id"])
    assert error.value.status_code == 409


def test_ASessionThatDoesNotProcessByItselfWaitsForTheStaff(facility, owner, tmp_path, monkeypatch):
    from app.backend.api.services.facility_session_watcher import watchSessions

    sessions, microscope, sample = facility
    flat, userId = owner
    db = sessions.mapper.db
    FacilityService(db).saveMicroscope(dict(microscope, offloadPath=str(tmp_path)), microscopeId=microscope["id"])
    session = sessions.saveSession(_multigrid(microscope, sample, status="acquiring", userId=userId,
                                              templateId="scipion:demo", autoProcess=False), userId=userId)
    calls = []
    _processWith(monkeypatch, flat, DEMO_WORKFLOW, calls)
    _epuMovie(tmp_path, session["name"])

    watchSessions(db)
    assert calls == [] and sessions.getSession(session["id"])["datasets"][1]["processing"] is None
