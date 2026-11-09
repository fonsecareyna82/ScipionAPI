"""How long a finished session's data are kept, its notices, and what the watcher does to grids and the ATLAS,
against the migrated database."""
import datetime
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.backend.api.services.facility_retention import FacilityRetention
from app.backend.api.services.facility_sample_service import FacilitySampleService
from app.backend.api.services.facility_service import FacilityService
from app.backend.api.services.facility_session_service import FacilitySessionService
from app.backend.api.services.facility_settings_service import FacilitySettingsService
from app.backend.mapper.postgresql import PostgresqlFlatMapper

EPU = Path(__file__).resolve().parents[2] / "resources" / "epu"
IMAGE = "FoilHole_15867355_Data_12771432_12771434_20200417_031214"


def _user(db, firstName):
    return PostgresqlFlatMapper(db).insertUser(
        email="retention-%s@example.com" % uuid4().hex, hashedPassword="test", firstName=firstName, lastName="Test",
        institution=None, role="user", isActive=True, isVerified=True, verificationCode="")


@pytest.fixture
def facility(postgresqlIntegrationDb, postgresqlMigratedEnv, tmp_path):
    """A microscope offloading to a folder, a sample with two grids, a user in a group with a PI, and the
    facility's settings (put back after the test)."""
    from app.backend.mapper.facility_settings_mapper import FacilitySettingsPostgresqlMapper

    db = postgresqlIntegrationDb
    kept = [dict(row) for row in db.fetchAll("SELECT key, value FROM facility_settings") or []]
    microscope = FacilityService(db).saveMicroscope({
        "name": "Glacios %s" % uuid4().hex[:8], "sessionsEnabled": True, "offloadPath": str(tmp_path),
        "atlasFolderPattern": "{session}_ATLAS",
        "detectors": [{"name": "Falcon 3", "metadataName": "BM-Falcon",
                       "pixelSizes": [{"magnification": 92000, "pixelSize": 1.55}]}]})
    sample = FacilitySampleService(db).saveSample({
        "code": "NZ%s" % uuid4().hex[:8],
        "boxes": [{"label": "1", "grids": [{"position": position, "gridNumber": position} for position in (1, 2)]}]})
    userId, piId = _user(db, "Gaoxin"), _user(db, "Ashleigh")
    group = db.fetchOne("INSERT INTO user_groups (name) VALUES (%s) RETURNING id", ("Lab %s" % uuid4().hex[:6],))
    db.execute('INSERT INTO user_group_members ("groupId", "userId", "groupRole") VALUES (%s, %s, %s), (%s, %s, %s)',
               (group["id"], userId, "member", group["id"], piId, "pi"))
    FacilitySettingsService(db).saveSettings({"rawRetentionDays": 90, "processedRetentionDays": 30,
                                              "retentionNoticeDays": [30, 7, 1], "timezone": "Europe/Madrid"})
    try:
        yield {"db": db, "microscope": microscope, "sample": sample, "userId": userId, "piId": piId,
               "groupId": group["id"], "offload": tmp_path}
    finally:
        db.execute('DELETE FROM facility_sessions WHERE "microscopeId" = %s', (microscope["id"],))
        db.execute("DELETE FROM facility_samples WHERE id = %s", (sample["id"],))
        db.execute("DELETE FROM facility_microscopes WHERE id = %s", (microscope["id"],))
        db.execute("DELETE FROM user_groups WHERE id = %s", (group["id"],))
        db.execute("DELETE FROM users WHERE id = ANY(%s)", ([userId, piId],))
        db.execute("DELETE FROM facility_settings")
        for row in kept:
            FacilitySettingsPostgresqlMapper(db).saveSettings({row["key"]: row["value"]}, None)


def _session(facility, **change):
    grids = facility["sample"]["boxes"][0]["grids"]
    payload = dict({"microscopeId": facility["microscope"]["id"], "userId": facility["userId"],
                    "groupId": facility["groupId"], "scheduledOn": "2026-08-01",
                    "datasets": [{"number": 1, "gridId": grids[0]["id"]}, {"number": 2, "gridId": grids[1]["id"]}]},
                   **change)
    return FacilitySessionService(facility["db"]).saveSession(payload)


def _finishedOn(facility, session, day):
    facility["db"].execute("UPDATE facility_sessions SET status = 'finished', \"startedAt\" = %s, "
                           '"finishedAt" = %s WHERE id = %s', (day, day, session["id"]))


def test_AFinishedSessionIsKeptTheFacilitysDaysUnlessGivenItsOwnDate(facility):
    session = _session(facility)
    retention = FacilityRetention(facility["db"])
    assert all(row["id"] != session["id"] for row in retention.listRetention()["sessions"])

    _finishedOn(facility, session, datetime.datetime(2026, 8, 1, 12, tzinfo=datetime.timezone.utc))
    listed = next(row for row in retention.listRetention()["sessions"] if row["id"] == session["id"])

    assert listed["raw"]["until"] == "2026-10-30" and not listed["raw"]["own"]
    # No project was made: there are no processed data to keep
    assert listed["processed"]["state"] == "none" and listed["projects"] == []
    assert listed["userEmail"] and listed["groupName"]

    later = retention.setKeepUntil(session["id"], {"rawKeepUntil": "2027-01-31"})
    assert later["raw"]["until"] == "2027-01-31" and later["raw"]["own"]
    assert retention.setKeepUntil(session["id"], {"rawKeepUntil": None})["raw"]["until"] == "2026-10-30"
    with pytest.raises(HTTPException) as error:
        retention.setKeepUntil(session["id"], {"rawKeepUntil": "2026-07-01"})
    assert error.value.status_code == 400

    # Its user sees the same dates
    mine = FacilitySessionService(facility["db"]).sessionsOf({"id": facility["userId"]})
    seen = next(item for item in mine["sessions"] if item["id"] == session["id"])
    assert seen["retention"]["raw"]["until"] == "2026-10-30" and seen["rawKeptUntil"] == "2026-10-30"


def test_RecordingTheRawDataDeletedArchivesASessionWithoutProjects(facility):
    session = _session(facility)
    _finishedOn(facility, session, datetime.datetime(2026, 8, 1, 12, tzinfo=datetime.timezone.utc))
    retention = FacilityRetention(facility["db"])

    marked = retention.markRawDeleted(session["id"], facility["piId"])

    assert marked["raw"]["state"] == "deleted" and marked["raw"]["deletedBy"] == "Ashleigh Test"
    assert marked["status"] == "archived"
    with pytest.raises(HTTPException) as error:
        retention.markRawDeleted(session["id"], facility["piId"])
    assert error.value.status_code == 409
    assert retention.unmarkRawDeleted(session["id"])["raw"]["state"] == "expired"
    with pytest.raises(HTTPException) as error:
        retention.deleteProjects(session["id"], {"id": facility["piId"]})
    assert error.value.status_code == 409


def test_ASessionNotFinishedHasNoDatesToKeep(facility):
    session = _session(facility)

    with pytest.raises(HTTPException) as error:
        FacilityRetention(facility["db"]).markRawDeleted(session["id"], None)
    assert error.value.status_code == 404


def test_TheUserAndThePiAreToldOnceBeforeTheDataGo(facility, monkeypatch):
    from app.backend.api.services.mail_service import MailService

    monkeypatch.setattr(MailService, "sending", lambda self: True)
    db = facility["db"]
    session = _session(facility)
    _finishedOn(facility, session, datetime.datetime(2026, 8, 1, 12, tzinfo=datetime.timezone.utc))
    retention = FacilityRetention(db)
    first = db.fetchOne("SELECT COALESCE(MAX(id), 0) AS id FROM notifications")["id"]

    def told():
        return db.fetchAll('SELECT "userId", kind, title, body, link, "emailState" FROM notifications '
                           'WHERE id > %s AND "userId" = ANY(%s) ORDER BY id',
                           (first, [facility["userId"], facility["piId"]]))

    try:
        # 5 days before the raw data's date: one notice for its 30 and 7 day notices, to the user and the PI
        done = retention.sendNotices(on=datetime.date(2026, 10, 25))

        mine = [item for item in done if item["sessionId"] == session["id"]]
        assert len(mine) == 1 and set(mine[0]["userIds"]) == {facility["userId"], facility["piId"]}
        rows = told()
        assert {row["userId"] for row in rows} == {facility["userId"], facility["piId"]} and len(rows) == 2
        assert all(row["kind"] == "facility.retention" and session["name"] in row["title"] and "in 5 days" in row["body"]
                   and row["link"] == "/facility/mine" for row in rows)
        # Mandatory: mailed whatever the user chose (instant by default)
        assert {row["emailState"] for row in rows} == {"pending"}
        assert not [item for item in retention.sendNotices(on=datetime.date(2026, 10, 26))
                    if item["sessionId"] == session["id"]]
        assert [item["sessionId"] for item in retention.sendNotices(on=datetime.date(2026, 10, 29))].count(
            session["id"]) == 1
        assert retention.getRetention(session["id"])["raw"]["noticesSent"] == [30, 7, 1]
        assert len(told()) == 4
    finally:
        db.execute("DELETE FROM notifications WHERE id > %s", (first,))


def test_GridsAreLoadedWhenTheSessionAcquiresAndUsedOnceAMovieCame(facility):
    db = facility["db"]
    grids = facility["sample"]["boxes"][0]["grids"]
    session = _session(facility)

    def statuses():
        rows = db.fetchAll("SELECT id, status FROM facility_grids WHERE id = ANY(%s)", ([grid["id"] for grid in grids],))
        return {row["id"]: row["status"] for row in rows}

    assert set(statuses().values()) == {"stored"}
    FacilitySessionService(db).saveSession(dict(_payload(session), status="acquiring"), sessionId=session["id"])
    assert set(statuses().values()) == {"loaded"}

    db.execute('UPDATE facility_session_datasets SET "movieCount" = 3 WHERE id = %s', (session["datasets"][1]["id"],))
    FacilitySessionService(db).mapper.markGrids()
    assert statuses() == {grids[0]["id"]: "used", grids[1]["id"]: "loaded"}

    # A session that finished before the watcher looked: its grid with movies is used, the other not loaded again
    db.execute("UPDATE facility_grids SET status = 'stored' WHERE id = ANY(%s)", ([grid["id"] for grid in grids],))
    db.execute("UPDATE facility_sessions SET status = 'finished' WHERE id = %s", (session["id"],))
    FacilitySessionService(db).mapper.markGrids()
    assert statuses() == {grids[0]["id"]: "used", grids[1]["id"]: "stored"}
    db.execute("UPDATE facility_sessions SET status = 'acquiring' WHERE id = %s", (session["id"],))

    # A grid set as discarded by hand stays so
    db.execute("UPDATE facility_grids SET status = 'discarded' WHERE id = %s", (grids[1]["id"],))
    FacilitySessionService(db).mapper.markGrids()
    assert statuses()[grids[1]["id"]] == "discarded"


def _payload(session):
    return {"name": session["name"], "microscopeId": session["microscopeId"], "userId": session["userId"],
            "groupId": session["groupId"], "scheduledOn": str(session["scheduledOn"]),
            "datasets": [{"id": dataset["id"], "kind": dataset["kind"], "number": dataset["number"],
                          "gridId": dataset["gridId"]} for dataset in session["datasets"]]}


def test_TheWatcherCountsTheAtlasAndADatasAcquisitionCanBeReadAgain(facility):
    from app.backend.api.services.facility_session_watcher import watchSessions

    db = facility["db"]
    session = _session(facility)
    session = FacilitySessionService(db).saveSession(dict(_payload(session), status="acquiring"),
                                                     sessionId=session["id"])
    atlas = next(dataset for dataset in session["datasets"] if dataset["kind"] == "atlas")
    data = next(dataset for dataset in session["datasets"] if dataset["kind"] == "data")
    atlasFolder = facility["offload"] / atlas["folder"] / "Sample1" / "Atlas"
    atlasFolder.mkdir(parents=True)
    (atlasFolder / "Atlas_1.mrc").write_bytes(b"\0" * 1000)
    movies = facility["offload"] / data["folder"] / "Images-Disc1" / "GridSquare_1" / "Data"
    movies.mkdir(parents=True)
    for name in os.listdir(EPU):
        if name.endswith(".xml"):
            shutil.copy(EPU / name, movies / name)
    (movies / (IMAGE + "_Fractions.mrc")).write_bytes(b"\0" * 64)

    watchSessions(db)

    session = FacilitySessionService(db).getSession(session["id"])
    atlas = next(dataset for dataset in session["datasets"] if dataset["kind"] == "atlas")
    data = next(dataset for dataset in session["datasets"] if dataset["id"] == data["id"])
    assert atlas["watch"] == "atlasFound" and atlas["atlas"]["files"] == 1 and atlas["atlas"]["bytes"] == 1000
    assert data["acquisition"]["detectorName"] == "Falcon 3"
    # Read again after the detector was renamed: the new name comes in
    db.execute("UPDATE facility_detectors SET name = 'Falcon 3EC' WHERE \"microscopeId\" = %s",
               (facility["microscope"]["id"],))
    again = FacilitySessionService(db).rereadAcquisition(data["id"])
    assert next(dataset for dataset in again["datasets"] if dataset["id"] == data["id"])[
        "acquisition"]["detectorName"] == "Falcon 3EC"
    with pytest.raises(HTTPException) as error:
        FacilitySessionService(db).rereadAcquisition(atlas["id"])
    assert error.value.status_code == 404


def test_TheSessionsProjectsAreDeletedOnlyWhereTheUserManagesThem(facility, tmp_path):
    from app.backend.utils.background_delete import waitForBackgroundDeletes

    db = facility["db"]
    flat = PostgresqlFlatMapper(db)
    session = _session(facility)
    data = [dataset for dataset in session["datasets"] if dataset["kind"] == "data"]
    mineId = flat.insertProject(ownerId=facility["piId"], name=str(tmp_path / ("A-%s" % uuid4().hex)))
    otherId = flat.insertProject(ownerId=facility["userId"], name=str(tmp_path / ("B-%s" % uuid4().hex)))
    for dataset, projectId in zip(data, (mineId, otherId)):
        db.execute('UPDATE facility_session_datasets SET "projectId" = %s WHERE id = %s', (projectId, dataset["id"]))
    _finishedOn(facility, session, datetime.datetime(2026, 8, 1, 12, tzinfo=datetime.timezone.utc))
    retention = FacilityRetention(db)
    retention.markRawDeleted(session["id"], facility["piId"])
    assert retention.getRetention(session["id"])["status"] == "finished"

    first = retention.deleteProjects(session["id"], flat.getUserById(facility["piId"]))

    assert [project["id"] for project in first["deleted"]] == [mineId]
    assert [project["id"] for project in first["failed"]] == [otherId]
    # Not all gone: not recorded, and the one left is still listed
    assert first["session"]["processed"]["state"] != "deleted"
    assert [project["id"] for project in first["session"]["projects"]] == [otherId]

    second = retention.deleteProjects(session["id"], flat.getUserById(facility["userId"]))

    assert [project["id"] for project in second["deleted"]] == [otherId] and second["failed"] == []
    assert second["session"]["processed"]["state"] == "deleted"
    assert second["session"]["status"] == "archived"
    waitForBackgroundDeletes(timeout=60)
    assert db.fetchOne("SELECT COUNT(*) AS n FROM projects WHERE id = ANY(%s)", ([mineId, otherId],))["n"] == 0
