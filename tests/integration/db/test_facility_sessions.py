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


def test_ANameIsMadeOfTheDayThePersonAndTheId():
    from app.backend.api.services.facility_session_service import sessionName

    assert sessionName(datetime.date(2026, 10, 31), "Gaoxin Lü", 123) == "2026_10_31_Gaoxin-Lu_000123"
    assert sessionName(datetime.date(2026, 10, 31), "  ", 7) == "2026_10_31_Facility_000007"
