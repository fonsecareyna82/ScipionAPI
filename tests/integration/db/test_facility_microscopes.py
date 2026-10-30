"""A facility's microscopes and their calibrated pixel sizes, against the migrated database."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.backend.api.services.facility_service import FacilityService, calibratedPixelSize


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
    return {"name": name, "model": "Talos Arctica", "detectors": "Falcon 4i, Ceta-D", "acquisitionSoftware": "EPU",
            "voltageKv": 200, "csMm": 2.7, "gainPath": "/data/gains/*Talos*gain*.mrc",
            "offloadPath": "/mnt/micros/talos_offload", "sessionsEnabled": True,
            "pixelSizes": [{"magnification": 120000, "pixelSize": 0.84}, {"magnification": 190000, "pixelSize": 0.52},
                           {"magnification": 92000, "pixelSize": 1.14}]}


def test_AMicroscopeKeepsItsCalibratedPixelSizes(facility):
    service, created = facility
    microscope = service.saveMicroscope(_talos("Talos %s" % uuid4().hex))
    created.append(microscope["id"])

    assert microscope["csMm"] == 2.7 and microscope["gainFlip"] == "none" and microscope["gainRotation"] == 0
    assert [row["magnification"] for row in microscope["pixelSizes"]] == [190000, 120000, 92000]
    # The calibrated pixel replaces the nominal one read from EPU, which carries other decimals
    assert calibratedPixelSize(microscope["pixelSizes"], magnification=120000) == 0.84
    assert calibratedPixelSize(microscope["pixelSizes"], nominalPixelSize=0.8387) == 0.84


def test_EditingAMicroscopeReplacesItsTable(facility):
    service, created = facility
    microscope = service.saveMicroscope(_talos("Talos %s" % uuid4().hex))
    created.append(microscope["id"])

    payload = dict(_talos(microscope["name"]), status="maintenance",
                   pixelSizes=[{"magnification": 73000, "pixelSize": 1.35}])
    edited = service.saveMicroscope(payload, microscopeId=microscope["id"])

    assert edited["status"] == "maintenance"
    assert edited["pixelSizes"] == [{"magnification": 73000, "pixelSize": 1.35}]
    assert edited["updatedAt"] >= microscope["updatedAt"]


def test_NamesAreUniqueWhateverTheirCase(facility):
    service, created = facility
    name = "Krios %s" % uuid4().hex
    created.append(service.saveMicroscope({"name": name})["id"])

    with pytest.raises(HTTPException) as error:
        service.saveMicroscope({"name": name.upper()})
    assert error.value.status_code == 409


def test_DeletingAMicroscopeDeletesItsTable(facility, postgresqlIntegrationDb):
    service, created = facility
    microscope = service.saveMicroscope(_talos("Talos %s" % uuid4().hex))

    service.deleteMicroscope(microscope["id"])

    assert service.mapper.getMicroscope(microscope["id"]) is None
    row = postgresqlIntegrationDb.fetchOne(
        'SELECT COUNT(*) AS n FROM facility_microscope_pixel_sizes WHERE "microscopeId" = %s', (microscope["id"],))
    assert row["n"] == 0
