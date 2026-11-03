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


@pytest.fixture
def cnbNames(postgresqlIntegrationDb):
    """The facility names its sessions as the CNB (EMhub); its settings are put back after the test."""
    from app.backend.api.services.facility_settings_service import FacilitySettingsService

    db = postgresqlIntegrationDb
    kept = [dict(row) for row in db.fetchAll("SELECT key, value FROM facility_settings") or []]
    FacilitySettingsService(db).saveSettings({"sessionNamePattern": "{date:%Y_%m_%d}_{user}_{id:06d}"})
    try:
        yield
    finally:
        db.execute("DELETE FROM facility_settings")
        for row in kept:
            FacilitySettingsService(db).mapper.saveSettings({row["key"]: row["value"]}, None)


def test_ASessionIsNamedByTheNeutralPatternUnlessTheFacilitySetsItsOwn(facility, postgresqlIntegrationDb):
    sessions, microscope, sample = facility
    saved = postgresqlIntegrationDb.fetchOne("SELECT COUNT(*) AS n FROM facility_settings")["n"]
    if saved:
        pytest.skip("this database has its own facility settings")

    session = sessions.saveSession(_multigrid(microscope, sample))

    # {date:%Y%m%d}_{microscope}_{id:04d}: the microscope's code, else its name as a word
    assert session["name"] == "20261031_%s_%04d" % (microscope["name"].replace(" ", "-"), session["id"])


def test_ASessionIsNamedAsTheFacilityDoesAndKnowsItsFolders(facility, cnbNames):
    sessions, microscope, sample = facility

    session = sessions.saveSession(_multigrid(microscope, sample))

    assert re.match(r"^2026_10_31_\d{6}$", session["name"])
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
    ({"datasets": [{"number": 13}]}, "autoloader has positions 1 to 12"),
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


def test_EachMicroscopeNamesItsFoldersAndADatasetKeepsItsOwn(facility, owner):
    sessions, microscope, sample = facility
    flat, userId = owner
    db = sessions.mapper.db
    FacilityService(db).saveMicroscope(dict(microscope, code="KRIOS", dataFolderPattern="{session}_Grid{n}",
                                            atlasFolderPattern="", gridSlots=4), microscopeId=microscope["id"])
    group = db.fetchOne("INSERT INTO user_groups (name) VALUES (%s) RETURNING id", ("Shannon lab %s" % uuid4().hex[:6],))
    db.execute('INSERT INTO user_group_members ("groupId", "userId", "groupRole") VALUES (%s, %s, %s)',
               (group["id"], userId, "pi"))
    from app.backend.api.services.facility_settings_service import FacilitySettingsService

    kept = [dict(row) for row in db.fetchAll("SELECT key, value FROM facility_settings") or []]
    FacilitySettingsService(db).saveSettings({"sessionNamePattern": "{date:%Y%m%d}_{microscope}_{pi}_{group}_{id}"})
    try:
        session = sessions.saveSession(_multigrid(microscope, sample, groupId=group["id"]))
        assert session["name"] == "20261031_KRIOS_Gaoxin-Lu_Shannon-lab-%s_%d" % (
            db.fetchOne("SELECT name FROM user_groups WHERE id = %s", (group["id"],))["name"].split(" ")[-1],
            session["id"])
        # No atlas folder on this microscope, and its grids are named its way
        assert [dataset["folder"] for dataset in session["datasets"]] == [
            session["name"] + "_Grid1", session["name"] + "_Grid2"]
        with pytest.raises(HTTPException) as error:
            sessions.saveSession(_multigrid(microscope, sample, datasets=[{"number": 5}]))
        assert "positions 1 to 4" in error.value.detail

        # A later change of the pattern renames no folder the microscope may be writing
        FacilityService(db).saveMicroscope(dict(microscope, code="KRIOS", dataFolderPattern="{session}_D{n:02d}",
                                                atlasFolderPattern="", gridSlots=4), microscopeId=microscope["id"])
        edited = sessions.saveSession(dict(_multigrid(microscope, sample), name=session["name"],
                                           datasets=[dict(dataset) for dataset in session["datasets"]] + [{"number": 3}]),
                                      sessionId=session["id"])
        assert [dataset["folder"] for dataset in edited["datasets"]] == [
            session["name"] + "_Grid1", session["name"] + "_Grid2", session["name"] + "_D03"]
    finally:
        db.execute("DELETE FROM facility_settings")
        for row in kept:
            FacilitySettingsService(db).mapper.saveSettings({row["key"]: row["value"]}, None)
        db.execute('DELETE FROM facility_sessions WHERE "microscopeId" = %s', (microscope["id"],))
        db.execute("DELETE FROM user_groups WHERE id = %s", (group["id"],))


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


def test_TheProjectIsTheStaffsAndItsUserSeesItReadOnly(facility, owner, tmp_path, monkeypatch):
    from app.backend.api.services.facility_session_watcher import watchSessions

    sessions, microscope, sample = facility
    flat, staffId = owner
    db = sessions.mapper.db
    userId = flat.insertUser(email="facility-user-%s@example.com" % uuid4().hex, hashedPassword="test",
                             firstName="Ana", lastName="User", institution=None, role="user", isActive=True,
                             isVerified=True, verificationCode="")
    try:
        FacilityService(db).saveMicroscope(dict(microscope, offloadPath=str(tmp_path)), microscopeId=microscope["id"])
        session = sessions.saveSession(_multigrid(microscope, sample, status="acquiring", userId=userId,
                                                  templateId="scipion:demo"), userId=staffId)
        calls = []
        _processWith(monkeypatch, flat, DEMO_WORKFLOW, calls)
        _epuMovie(tmp_path, session["name"])

        watchSessions(db)

        projectId = sessions.getSession(session["id"])["datasets"][1]["projectId"]
        assert db.fetchOne('SELECT "ownerId" FROM projects WHERE id = %s', (projectId,))["ownerId"] == staffId
        share = db.fetchOne('SELECT permission FROM project_shares WHERE "projectId" = %s AND "userId" = %s',
                            (projectId, userId))
        assert share["permission"] == "view"
    finally:
        db.execute('DELETE FROM facility_sessions WHERE "microscopeId" = %s', (microscope["id"],))
        db.execute("DELETE FROM users WHERE id = %s", (userId,))


def test_ASessionWithOneProjectPutsEachDataInItsOwnBranch(facility, owner, tmp_path, monkeypatch):
    from app.backend.api.services.facility_session_watcher import watchSessions

    sessions, microscope, sample = facility
    flat, userId = owner
    db = sessions.mapper.db
    FacilityService(db).saveMicroscope(dict(microscope, offloadPath=str(tmp_path)), microscopeId=microscope["id"])
    session = sessions.saveSession(_multigrid(microscope, sample, status="acquiring", templateId="scipion:demo",
                                              oneProject=True), userId=userId)
    calls = []
    _processWith(monkeypatch, flat, DEMO_WORKFLOW, calls)
    _epuMovie(tmp_path, session["name"], 1)
    _epuMovie(tmp_path, session["name"], 2)

    watchSessions(db)

    first, second = sessions.getSession(session["id"])["datasets"][1:]
    assert [call[1] for call in calls if call[0] == "create"] == [session["name"]]
    assert first["projectId"] == second["projectId"] is not None
    assert (first["processing"]["state"], second["processing"]["state"]) == ("launched", "launched")
    imports = [call[1] for call in calls if call[0] == "import"]
    assert [workflow[0]["object.label"].split(" · ")[0] for workflow in imports] == ["DATA_01", "DATA_02"]
    assert imports[1][0]["filesPath"].endswith("_DATA_02")
    assert len([call for call in calls if call[0] == "launch"]) == 2


def test_ATomographyDataComposesItsTiltSeriesFromItsMdocs(facility, owner, tmp_path, monkeypatch):
    from app.backend.api.services.facility_session_watcher import watchSessions

    sessions, microscope, sample = facility
    flat, userId = owner
    db = sessions.mapper.db
    FacilityService(db).saveMicroscope(dict(microscope, offloadPath=str(tmp_path)), microscopeId=microscope["id"])
    session = sessions.saveSession(_multigrid(microscope, sample, status="acquiring", technique="tomo",
                                              templateId="tomo:streaming"), userId=userId)
    frames = tmp_path / ("%s_DATA_01" % session["name"]) / "TS_01" / "frames"
    frames.mkdir(parents=True)
    (frames / "TS_01.mdoc").write_text("PixelSpacing = 1.6\nVoltage = 300\nMagnification = 64000\nNumSubFrames = 8\n"
                                       "ExposureTime = 0.5\nExposureDose = 3.2\n")
    for tilt in ("001_0.0", "002_3.0"):
        (frames / ("TS_01_%s.mrc" % tilt)).write_bytes(b"\0" * 8)
    calls = []
    workflow = [{"object.className": "ProtImportMovies", "object.id": "2", "filesPattern": "*.mrc"},
                {"object.className": "ProtMotionCorr", "object.id": "3", "inputMovies": "2.outputMovies"},
                {"object.className": "ProtComposeTS", "object.id": "4", "inputMicrographs": "3.outputMicrographs",
                 "filesPath": "/somewhere", "mdocPattern": "*.mdoc"}]
    _processWith(monkeypatch, flat, workflow, calls)

    watchSessions(db)

    first = sessions.getSession(session["id"])["datasets"][1]
    assert first["movieCount"] == 2 and first["acquisition"]["format"] == "SerialEM MDOC"
    assert first["acquisition"]["metadataPath"] == "TS_01/frames/TS_01.mdoc"
    assert first["processing"]["state"] == "launched" and first["processing"]["composesTiltSeries"]
    imported = [call[1] for call in calls if call[0] == "import"][0]
    folder = str(tmp_path / ("%s_DATA_01" % session["name"]))
    assert (imported[0]["filesPath"], imported[0]["filesPattern"]) == (folder, "*/frames/*.mrc")
    assert (imported[0]["samplingRate"], imported[0]["dosePerFrame"]) == (1.6, 0.4)
    assert (imported[2]["filesPath"], imported[2]["mdocPattern"]) == (folder, "*/frames/*.mdoc")


def test_TheWatchersTurnLeavesNoTransactionOpen(facility):
    """Idle in transaction, the watcher's connection held the facility tables and a migration waited for hours."""
    import psycopg2.extensions

    from app.backend.api.services.facility_session_watcher import watchOnce

    sessions, microscope, sample = facility
    db = sessions.mapper.db

    watchOnce(db)

    assert db.conn.get_transaction_status() == psycopg2.extensions.TRANSACTION_STATUS_IDLE


@pytest.fixture
def keptSettings(postgresqlIntegrationDb):
    """The facility's settings are put back after the test."""
    from app.backend.mapper.facility_settings_mapper import FacilitySettingsPostgresqlMapper

    db = postgresqlIntegrationDb
    kept = [dict(row) for row in db.fetchAll("SELECT key, value FROM facility_settings") or []]
    try:
        yield
    finally:
        db.execute("DELETE FROM facility_settings")
        for row in kept:
            FacilitySettingsPostgresqlMapper(db).saveSettings({row["key"]: row["value"]}, None)


def test_AnAlertIsOpenedOnceForADataThatStopsAndResolvedWhenMoviesComeBack(facility):
    from app.backend.api.services.facility_alerts import FacilityAlerts

    sessions, microscope, sample = facility
    db = sessions.mapper.db
    session = sessions.saveSession(_multigrid(microscope, sample, status="acquiring"))
    first = session["datasets"][1]
    db.execute('UPDATE facility_session_datasets SET "movieCount" = 40, "lastMovieAt" = NOW() - INTERVAL %s '
               "WHERE id = %s", ("45 minutes", first["id"]))
    alerts = FacilityAlerts(db)

    opened = alerts.refresh(stallMinutes=20)
    assert len(opened) == 1 and alerts.refresh(stallMinutes=20) == []
    alert = next(alert for alert in alerts.listAlerts() if alert["id"] == opened[0])
    assert alert["kind"] == "stalled" and alert["folder"] == first["folder"]
    assert "no new movie for 45 minutes (40 movies so far)" in alert["message"]

    db.execute('UPDATE facility_session_datasets SET "lastMovieAt" = NOW() WHERE id = %s', (first["id"],))
    alerts.refresh(stallMinutes=20)
    assert opened[0] not in [alert["id"] for alert in alerts.listAlerts()]
    assert next(alert for alert in alerts.listAlerts(openOnly=False) if alert["id"] == opened[0])["resolvedAt"]


def test_AFailedProcessingOrProtocolIsAnAlertThatSomeoneTakes(facility, owner):
    from app.backend.api.services.facility_alerts import FacilityAlerts

    sessions, microscope, sample = facility
    flat, userId = owner
    db = sessions.mapper.db
    session = sessions.saveSession(_multigrid(microscope, sample, status="acquiring"))
    first, second = session["datasets"][1:]
    projectId = flat.insertProject(ownerId=userId, name="/tmp/alerts-%s" % uuid4().hex, description="alerts")
    sessions.mapper.saveProcessing(first["id"], {"state": "error", "message": "The template has no Import Movies"})
    sessions.mapper.saveProcessing(second["id"], {"state": "launched"}, projectId=projectId)
    db.execute('INSERT INTO protocols ("protocolId", "projectId", "protocolClassName", params, status) '
               "VALUES (%s, %s, %s, %s, %s)", (7, projectId, "ProtMotionCorr", "{}", "failed"))
    alerts = FacilityAlerts(db)

    alerts.refresh()

    kinds = {alert["kind"]: alert for alert in alerts.listAlerts() if alert["sessionId"] == session["id"]}
    assert set(kinds) == {"processingFailed", "protocolFailed"}
    assert "The template has no Import Movies" in kinds["processingFailed"]["message"]
    assert "protocol 7 (ProtMotionCorr) failed" in kinds["protocolFailed"]["message"]
    taken = alerts.acknowledge(kinds["protocolFailed"]["id"], userId)
    assert taken["acknowledgedBy"] == userId and taken["acknowledgedByName"] == "Gaoxin Lu"

    db.execute('UPDATE protocols SET status = %s WHERE "projectId" = %s', ("finished", projectId))
    alerts.refresh()
    assert {alert["kind"] for alert in alerts.listAlerts() if alert["sessionId"] == session["id"]} == {"processingFailed"}


def test_TheNewAlertsAreMailedOnceAndThePasswordIsNeverAnswered(facility, keptSettings, postgresqlIntegrationDb,
                                                              monkeypatch):
    import smtplib

    from app.backend.api.services.facility_alerts import FacilityAlerts
    from app.backend.api.services.facility_mail import FacilityMail

    sent = []

    class FakeSmtp:
        def __init__(self, host, port, timeout=None):
            sent.append({"server": (host, port)})

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self, context=None):
            sent[-1]["tls"] = True

        def login(self, user, password):
            sent[-1]["login"] = (user, password)

        def send_message(self, message):
            sent[-1]["message"] = message

    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    sessions, microscope, sample = facility
    db = sessions.mapper.db
    mail = FacilityMail(db)
    settings = mail.saveSettings({"host": "smtp.cnb.csic.es", "port": 587, "security": "starttls", "user": "facility",
                                  "password": "s3cret", "sender": "facility@cnb.csic.es",
                                  "recipients": "ops1@cnb.csic.es; ops2@cnb.csic.es"})
    assert settings["passwordSet"] and "password" not in settings and "passwordEncrypted" not in settings
    stored = db.fetchOne("SELECT value FROM facility_settings WHERE key = 'mail'")["value"]
    assert "s3cret" not in str(stored)
    # Left out, the password stays
    assert mail.saveSettings({"host": "smtp.cnb.csic.es", "sender": "facility@cnb.csic.es"})["passwordSet"]

    session = sessions.saveSession(_multigrid(microscope, sample, status="acquiring"))
    sessions.mapper.saveProcessing(session["datasets"][1]["id"], {"state": "error", "message": "boom"})
    alerts = FacilityAlerts(db)
    alerts.refresh()

    assert alerts.mailNew() == ["ops1@cnb.csic.es", "ops2@cnb.csic.es"]
    assert sent[0]["tls"] and sent[0]["login"] == ("facility", "s3cret")
    assert "boom" in sent[0]["message"].get_content() and sent[0]["message"]["To"] == "ops1@cnb.csic.es, ops2@cnb.csic.es"
    assert alerts.mailNew() is None and len(sent) == 1


def test_AUserSeesTheirSessionsAndThePiThoseOfTheGroupWithoutWhatIsTheStaffs(facility, owner, keptSettings):
    from app.backend.api.services.facility_settings_service import FacilitySettingsService

    sessions, microscope, sample = facility
    flat, userId = owner
    db = sessions.mapper.db

    def person(first):
        return flat.insertUser(email="%s-%s@example.com" % (first, uuid4().hex), hashedPassword="test", firstName=first,
                               lastName="X", institution=None, role="user", isActive=True, isVerified=True,
                               verificationCode="")
    pi, stranger = person("Pi"), person("Stranger")
    group = db.fetchOne("INSERT INTO user_groups (name) VALUES (%s) RETURNING id", ("Lab %s" % uuid4().hex[:6],))
    db.execute('INSERT INTO user_group_members ("groupId", "userId", "groupRole") VALUES (%s, %s, %s), (%s, %s, %s)',
               (group["id"], userId, "member", group["id"], pi, "pi"))
    try:
        FacilitySettingsService(db).saveSettings({"rawRetentionDays": 30, "processedRetentionDays": 7,
                                                  "downloadInstructions": "Take your data with the iRODS ticket."})
        session = sessions.saveSession(_multigrid(microscope, sample, status="finished", userId=userId,
                                                  groupId=group["id"], notes="Internal: the gun was unstable",
                                                  userNotes="Thin ice on grid 6; the other grids are fine."))
        sessions.mapper.saveProcessing(session["datasets"][1]["id"], {"state": "error", "message": "Traceback (internal)"})

        mine = sessions.sessionsOf({"id": userId})
        seen = next(found for found in mine["sessions"] if found["id"] == session["id"])
        assert not seen["asPi"] and seen["userNotes"].startswith("Thin ice") and "notes" not in seen
        assert seen["datasets"][1]["processing"] == {"state": "error"}
        assert "notes" not in seen["datasets"][1] and "Internal" not in str(seen)
        finished = datetime.datetime.fromisoformat(session["finishedAt"]) if isinstance(session["finishedAt"], str) \
            else session["finishedAt"]
        assert seen["rawKeptUntil"] == (finished + datetime.timedelta(days=30)).isoformat()
        assert mine["downloadInstructions"] == "Take your data with the iRODS ticket." and not mine["isPi"]

        asPi = sessions.sessionsOf({"id": pi})
        assert asPi["isPi"] and next(found for found in asPi["sessions"] if found["id"] == session["id"])["asPi"]
        assert session["id"] not in [found["id"] for found in sessions.sessionsOf({"id": stranger})["sessions"]]
    finally:
        db.execute('DELETE FROM facility_sessions WHERE "microscopeId" = %s', (microscope["id"],))
        db.execute("DELETE FROM user_groups WHERE id = %s", (group["id"],))
        db.execute("DELETE FROM users WHERE id = ANY(%s)", ([pi, stranger],))


def test_TheFacilitysPoliciesAreCheckedAndDecideWhoOwnsADatasProject(facility, owner, keptSettings, tmp_path,
                                                                     monkeypatch):
    from app.backend.api.services.facility_session_watcher import watchSessions
    from app.backend.api.services.facility_settings_service import FacilitySettingsService

    sessions, microscope, sample = facility
    flat, staffId = owner
    db = sessions.mapper.db
    settings = FacilitySettingsService(db)
    for wrong in ({"projectOwner": "group"}, {"projectShareLevel": "manage"}, {"stallMinutes": 0},
                  {"calibrationTolerancePercent": 90}, {"watchSeconds": "soon"}):
        with pytest.raises(HTTPException):
            settings.saveSettings(wrong)
    assert settings.values()["projectOwner"] == "staff" and settings.values()["stallMinutes"] == 20

    settings.saveSettings({"projectOwner": "user", "projectShareLevel": "work", "stallMinutes": 45})
    userId = flat.insertUser(email="owner-%s@example.com" % uuid4().hex, hashedPassword="test", firstName="Ana",
                             lastName="User", institution=None, role="user", isActive=True, isVerified=True,
                             verificationCode="")
    role = db.fetchOne('SELECT r.id FROM access_roles r JOIN access_role_permissions p ON p."roleId" = r.id '
                       "WHERE p.permission = 'projects.create' AND NOT r.\"isSystem\" ORDER BY r.id LIMIT 1")
    db.execute('INSERT INTO user_access_roles ("userId", "roleId") VALUES (%s, %s)', (userId, role["id"]))
    try:
        FacilityService(db).saveMicroscope(dict(microscope, offloadPath=str(tmp_path)), microscopeId=microscope["id"])
        session = sessions.saveSession(_multigrid(microscope, sample, status="acquiring", userId=userId,
                                                  templateId="scipion:demo"), userId=staffId)
        calls = []
        _processWith(monkeypatch, flat, DEMO_WORKFLOW, calls)
        _epuMovie(tmp_path, session["name"])
        watchSessions(db)

        projectId = sessions.getSession(session["id"])["datasets"][1]["projectId"]
        assert db.fetchOne('SELECT "ownerId" FROM projects WHERE id = %s', (projectId,))["ownerId"] == userId
        shares = {row["userId"]: row["permission"] for row in db.fetchAll(
            'SELECT "userId", permission FROM project_shares WHERE "projectId" = %s AND "userId" IS NOT NULL',
            (projectId,))}
        assert shares == {staffId: "manage"}
        # 30 minutes without movies is not stalled for a facility that allows 45
        db.execute('UPDATE facility_session_datasets SET "lastMovieAt" = NOW() - INTERVAL %s WHERE "sessionId" = %s',
                   ("30 minutes", session["id"]))
        assert sessions.getSession(session["id"])["datasets"][1]["watch"] == "receiving"
    finally:
        db.execute('DELETE FROM facility_sessions WHERE "microscopeId" = %s', (microscope["id"],))
        db.execute('DELETE FROM projects WHERE "ownerId" = %s', (userId,))
        db.execute("DELETE FROM users WHERE id = %s", (userId,))


def test_ASessionsCtfLimitsAreCheckedAndGoIntoItsDataProjects(facility, owner, tmp_path, monkeypatch):
    from app.backend.api.services.facility_session_watcher import watchSessions

    sessions, microscope, sample = facility
    flat, userId = owner
    db = sessions.mapper.db
    for wrong, message in (({"ctfMinDefocus": 40000, "ctfMaxDefocus": 5000}, "minimum defocus is below"),
                           ({"ctfMaxResolution": "fine"}, "is a number")):
        with pytest.raises(HTTPException) as error:
            sessions.saveSession(_multigrid(microscope, sample, **wrong))
        assert message in error.value.detail
    FacilityService(db).saveMicroscope(dict(microscope, offloadPath=str(tmp_path)), microscopeId=microscope["id"])
    session = sessions.saveSession(_multigrid(microscope, sample, status="acquiring", templateId="scipion:demo",
                                              ctfMinDefocus=6000, ctfMaxDefocus=35000, ctfMaxResolution=7.5),
                                   userId=userId)
    assert (session["ctfMinDefocus"], session["ctfMaxDefocus"], session["ctfMaxResolution"]) == (6000, 35000, 7.5)
    calls = []
    workflow = DEMO_WORKFLOW + [{"object.className": "XmippProtCTFConsensus", "object.id": "5", "useDefocus": False,
                                 "minDefocus": 4000, "maxDefocus": 50000, "resolution": 17}]
    _processWith(monkeypatch, flat, workflow, calls)
    _epuMovie(tmp_path, session["name"])

    watchSessions(db)

    imported = [call[1] for call in calls if call[0] == "import"][0]
    consensus = next(protocol for protocol in imported if protocol["object.className"] == "XmippProtCTFConsensus")
    assert (consensus["useDefocus"], consensus["minDefocus"], consensus["maxDefocus"], consensus["resolution"]) == (
        True, 6000.0, 35000.0, 7.5)
    assert sessions.getSession(session["id"])["datasets"][1]["processing"]["ctfLimits"]["resolution"] == 7.5


def test_TheRoomScreenShowsEachMicroscopesStateToWhoHasItsLinkOnly(facility, owner, keptSettings):
    from app.backend.api.services.facility_room import FacilityRoom

    sessions, microscope, sample = facility
    flat, userId = owner
    db = sessions.mapper.db
    room = FacilityRoom(db)
    with pytest.raises(HTTPException) as error:
        room.checkToken("anything")
    assert error.value.status_code == 404
    token = room.newLink(userId)["token"]
    room.checkToken(token)
    other = room.newLink(userId)["token"]
    with pytest.raises(HTTPException):
        room.checkToken(token)
    room.checkToken(other)

    pi = flat.insertUser(email="pi-%s@example.com" % uuid4().hex, hashedPassword="test", firstName="Ashleigh",
                         lastName="Shannon", institution=None, role="user", isActive=True, isVerified=True,
                         verificationCode="")
    group = db.fetchOne("INSERT INTO user_groups (name) VALUES (%s) RETURNING id", ("Lab %s" % uuid4().hex[:6],))
    db.execute('INSERT INTO user_group_members ("groupId", "userId", "groupRole") VALUES (%s, %s, %s)',
               (group["id"], pi, "pi"))
    try:
        today = datetime.date.today()
        acquiring = sessions.saveSession(_multigrid(microscope, sample, status="acquiring", userId=userId,
                                                    groupId=group["id"], notes="Internal: gun unstable"), userId=userId)
        sessions.saveSession(_multigrid(microscope, sample, scheduledOn=str(today + datetime.timedelta(days=2)),
                                        userId=userId, groupId=group["id"]), userId=userId)
        db.execute('UPDATE facility_session_datasets SET "movieCount" = 12, "lastMovieAt" = NOW() WHERE id = %s',
                   (acquiring["datasets"][1]["id"],))

        view = room.view(today)

        mine = next(item for item in view["microscopes"] if item["id"] == microscope["id"])
        assert mine["state"] == "acquiring" and mine["session"]["name"] == acquiring["name"]
        assert (mine["session"]["technician"], mine["session"]["user"], mine["session"]["pi"]) == (
            "Gaoxin Lu", "Gaoxin Lu", "Ashleigh Shannon")
        assert mine["session"]["datasets"][0]["movieCount"] == 12
        assert mine["session"]["datasets"][0]["sample"] == sample["code"]
        upcoming = [item for item in view["upcoming"] if item["microscope"] == microscope["name"]]
        assert len(upcoming) == 1 and upcoming[0]["pi"] == "Ashleigh Shannon"
        # Names and states only
        assert "@" not in str(view) and "Internal" not in str(view) and str(microscope["offloadPath"] or "/x") not in str(view)

        FacilityService(db).saveMicroscope(dict(microscope, status="maintenance"), microscopeId=microscope["id"])
        assert next(item for item in room.view(today)["microscopes"] if item["id"] == microscope["id"])["state"] == "maintenance"
        room.turnOff(userId)
        with pytest.raises(HTTPException):
            room.checkToken(other)
    finally:
        db.execute('DELETE FROM facility_sessions WHERE "microscopeId" = %s', (microscope["id"],))
        db.execute("DELETE FROM user_groups WHERE id = %s", (group["id"],))
        db.execute("DELETE FROM users WHERE id = %s", (pi,))
