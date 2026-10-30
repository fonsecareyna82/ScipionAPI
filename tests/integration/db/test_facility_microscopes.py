"""A facility's microscopes, their detectors and the detectors' calibrated pixel sizes, against the migrated database."""
import io
from uuid import uuid4

from PIL import Image

import pytest
from fastapi import HTTPException

from app.backend.api.services.facility_service import FacilityService, calibratedPixelSize, detectorFor


@pytest.fixture
def facility(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    service = FacilityService(db)
    created = []
    try:
        yield service, created
    finally:
        for microscopeId in created:
            db.execute("DELETE FROM facility_microscopes WHERE id = %s", (microscopeId,))


def _talos(name):
    return {"name": name, "model": "Talos Arctica", "acquisitionSoftware": "EPU",
            "voltageKv": 200, "csMm": 2.7, "offloadPath": "/mnt/micros/talos_offload", "sessionsEnabled": True,
            "detectors": [
                {"name": "Falcon 4i", "metadataName": "BM-Falcon", "gainPath": "/data/gains/*Talos*gain*.mrc",
                 "pixelSizes": [{"magnification": 120000, "pixelSize": 0.84},
                                {"magnification": 190000, "pixelSize": 0.52},
                                {"magnification": 92000, "pixelSize": 1.14}]},
                {"name": "Ceta-D", "metadataName": "BM-Ceta", "gainFlip": "vertical",
                 "pixelSizes": [{"magnification": 120000, "pixelSize": 1.21}]},
            ]}


def test_EachDetectorKeepsItsGainAndCalibratedPixelSizes(facility):
    service, created = facility
    microscope = service.saveMicroscope(_talos("Talos %s" % uuid4().hex))
    created.append(microscope["id"])

    falcon, ceta = microscope["detectors"]
    assert microscope["csMm"] == 2.7 and falcon["gainFlip"] == "none" and ceta["gainFlip"] == "vertical"
    assert [row["magnification"] for row in falcon["pixelSizes"]] == [190000, 120000, 92000]
    # The same magnification is another pixel on each detector: the movie's metadata names which
    assert calibratedPixelSize(detectorFor(microscope["detectors"], "BM-Falcon")["pixelSizes"],
                               magnification=120000) == 0.84
    assert calibratedPixelSize(detectorFor(microscope["detectors"], "BM-Ceta")["pixelSizes"],
                               magnification=120000) == 1.21
    # The calibrated pixel replaces the nominal one read from EPU, which carries other decimals
    assert calibratedPixelSize(falcon["pixelSizes"], nominalPixelSize=0.8387) == 0.84


def test_EditingKeepsTheIdsOfTheDetectorsAndDeletesTheOnesLeftOut(facility, postgresqlIntegrationDb):
    service, created = facility
    microscope = service.saveMicroscope(_talos("Talos %s" % uuid4().hex))
    created.append(microscope["id"])
    falcon, ceta = microscope["detectors"]

    payload = dict(microscope, status="maintenance",
                   detectors=[dict(falcon, pixelSizes=[{"magnification": 73000, "pixelSize": 1.35}])])
    edited = service.saveMicroscope(payload, microscopeId=microscope["id"])

    assert edited["status"] == "maintenance"
    assert [detector["id"] for detector in edited["detectors"]] == [falcon["id"]]
    assert edited["detectors"][0]["pixelSizes"] == [{"magnification": 73000, "pixelSize": 1.35}]
    assert edited["updatedAt"] >= microscope["updatedAt"]
    row = postgresqlIntegrationDb.fetchOne(
        'SELECT COUNT(*) AS n FROM facility_detector_pixel_sizes WHERE "detectorId" = %s', (ceta["id"],))
    assert row["n"] == 0


def test_TheDetectorsOfAnotherMicroscopeCannotBeTaken(facility):
    service, created = facility
    one = service.saveMicroscope(_talos("Talos %s" % uuid4().hex))
    other = service.saveMicroscope(_talos("Talos %s" % uuid4().hex))
    created.extend([one["id"], other["id"]])

    with pytest.raises(HTTPException) as error:
        service.saveMicroscope(dict(one, detectors=[other["detectors"][0]]), microscopeId=one["id"])
    assert error.value.status_code == 400 and "not one of this microscope's" in error.value.detail


def test_TwoDetectorsCanSwapTheirNames(facility):
    service, created = facility
    microscope = service.saveMicroscope(_talos("Talos %s" % uuid4().hex))
    created.append(microscope["id"])
    falcon, ceta = microscope["detectors"]

    edited = service.saveMicroscope(dict(microscope, detectors=[dict(falcon, name="Ceta-D"),
                                                                dict(ceta, name="Falcon 4i")]),
                                    microscopeId=microscope["id"])

    assert [(row["id"], row["name"]) for row in edited["detectors"]] == [(falcon["id"], "Ceta-D"),
                                                                         (ceta["id"], "Falcon 4i")]


def test_NamesAreUniqueWhateverTheirCase(facility):
    service, created = facility
    name = "Krios %s" % uuid4().hex
    created.append(service.saveMicroscope({"name": name})["id"])

    with pytest.raises(HTTPException) as error:
        service.saveMicroscope({"name": name.upper()})
    assert error.value.status_code == 409


def test_DeletingAMicroscopeDeletesItsDetectors(facility, postgresqlIntegrationDb):
    service, created = facility
    microscope = service.saveMicroscope(_talos("Talos %s" % uuid4().hex))

    service.deleteMicroscope(microscope["id"])

    assert service.mapper.getMicroscope(microscope["id"]) is None
    row = postgresqlIntegrationDb.fetchOne(
        'SELECT COUNT(*) AS n FROM facility_detectors WHERE "microscopeId" = %s', (microscope["id"],))
    assert row["n"] == 0


def test_APhotoIsKeptWithItsMicroscopeAndGoesWithIt(facility, postgresqlIntegrationDb):
    service, created = facility
    microscope = service.saveMicroscope(_talos("Talos %s" % uuid4().hex))
    assert microscope["photoUpdatedAt"] is None
    raw = io.BytesIO()
    Image.new("RGB", (800, 600), (10, 20, 30)).save(raw, format="JPEG")

    withPhoto = service.savePhoto(microscope["id"], raw.getvalue())

    assert withPhoto["photoUpdatedAt"] is not None
    photo = service.getPhoto(microscope["id"])
    assert photo["contentType"] == "image/webp"
    assert Image.open(io.BytesIO(bytes(photo["data"]))).size == (800, 600)

    service.deleteMicroscope(microscope["id"])
    row = postgresqlIntegrationDb.fetchOne(
        'SELECT COUNT(*) AS n FROM facility_microscope_photos WHERE "microscopeId" = %s', (microscope["id"],))
    assert row["n"] == 0
