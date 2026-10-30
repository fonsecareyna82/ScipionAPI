"""A facility's samples, their grid boxes and grids, saved as one tree, against the migrated database."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.backend.api.services.facility_sample_service import FacilitySampleService


@pytest.fixture
def samples(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    service = FacilitySampleService(db)
    created = []
    try:
        yield service, created
    finally:
        for sampleId in created:
            db.execute("DELETE FROM facility_samples WHERE id = %s", (sampleId,))


def _nz(code):
    """NZ251.2 as the facility recorded it: two boxes of four grids."""
    def grid(position, number, gridType, specimen):
        return {"position": position, "gridNumber": number, "gridType": gridType, "concentration": "0.3",
                "specimen": specimen}
    return {"code": code, "description": "nsp9 complexes", "accessRoute": "Instruct PID 45466",
            "boxes": [
                {"label": "1", "vitrificationCode": code + ".2", "vitrifiedOn": "2026-09-28",
                 "grids": [grid(1, 1, "Graphene", "Dimer +5mM MnCl2"), grid(2, 2, "CuRh 1.2", "Dimer +5mM MnCl2"),
                           grid(3, 3, "Au 1.2", "Dimer +5mM MnCl2"), grid(4, 4, "Au 1.2", "Dimer +5mM MnCl2")]},
                {"label": "2 green", "vitrificationCode": code + ".2", "vitrifiedOn": "2026-09-28",
                 "grids": [grid(1, 5, "CuRh 1.2", "nsp9+T2C3+5mM MnCl2"), grid(2, 6, "CuRh 1.2", "nsp9+T2C3+5mM MnCl2")]},
            ]}


def test_ASampleIsSavedWithItsBoxesAndGrids(samples):
    service, created = samples
    sample = service.saveSample(_nz("NZ%s" % uuid4().hex[:8]))
    created.append(sample["id"])

    assert [box["label"] for box in sample["boxes"]] == ["1", "2 green"]
    assert [grid["gridNumber"] for grid in sample["boxes"][0]["grids"]] == [1, 2, 3, 4]
    assert sample["boxes"][0]["vitrifiedOn"] == "2026-09-28"
    assert {grid["status"] for box in sample["boxes"] for grid in box["grids"]} == {"stored"}


def test_EditingKeepsTheIdsOfGridsAndCanSwapTwoPositions(samples):
    service, created = samples
    sample = service.saveSample(_nz("NZ%s" % uuid4().hex[:8]))
    created.append(sample["id"])
    box = sample["boxes"][0]
    first, second = box["grids"][0], box["grids"][1]

    payload = dict(sample, boxes=[dict(box, grids=[dict(first, position=2), dict(second, position=1, status="loaded")]),
                                  sample["boxes"][1]])
    edited = service.saveSample(payload, sampleId=sample["id"])

    grids = {grid["id"]: grid for grid in edited["boxes"][0]["grids"]}
    assert set(grids) == {first["id"], second["id"]}
    assert grids[first["id"]]["position"] == 2 and grids[second["id"]]["position"] == 1
    assert grids[second["id"]]["status"] == "loaded"


def test_WhatTheTreeLeavesOutIsDeleted(samples, postgresqlIntegrationDb):
    service, created = samples
    sample = service.saveSample(_nz("NZ%s" % uuid4().hex[:8]))
    created.append(sample["id"])
    removedBox = sample["boxes"][1]

    edited = service.saveSample(dict(sample, boxes=[sample["boxes"][0]]), sampleId=sample["id"])

    assert [box["id"] for box in edited["boxes"]] == [sample["boxes"][0]["id"]]
    row = postgresqlIntegrationDb.fetchOne('SELECT COUNT(*) AS n FROM facility_grids WHERE "boxId" = %s',
                                           (removedBox["id"],))
    assert row["n"] == 0


def test_TheBoxesAndGridsOfAnotherSampleCannotBeTaken(samples):
    service, created = samples
    one = service.saveSample(_nz("NZ%s" % uuid4().hex[:8]))
    other = service.saveSample(_nz("NZ%s" % uuid4().hex[:8]))
    created.extend([one["id"], other["id"]])
    foreignGrid = other["boxes"][0]["grids"][0]

    with pytest.raises(HTTPException) as error:
        service.saveSample(dict(one, boxes=[dict(one["boxes"][0], grids=[foreignGrid])]), sampleId=one["id"])
    assert error.value.status_code == 400 and "not one of this sample's" in error.value.detail

    with pytest.raises(HTTPException):
        service.saveSample(dict(one, boxes=[other["boxes"][0]]), sampleId=one["id"])


def test_CodesAreUniqueAndADeletedSampleTakesItsTree(samples, postgresqlIntegrationDb):
    service, created = samples
    code = "NZ%s" % uuid4().hex[:8]
    sample = service.saveSample(_nz(code))

    with pytest.raises(HTTPException) as error:
        service.saveSample({"code": code.lower()})
    assert error.value.status_code == 409

    service.deleteSample(sample["id"])
    row = postgresqlIntegrationDb.fetchOne(
        'SELECT COUNT(*) AS n FROM facility_grid_boxes WHERE "sampleId" = %s', (sample["id"],))
    assert row["n"] == 0


def test_SamplesAreFoundByCodeOrDescription(samples):
    service, created = samples
    marker = uuid4().hex[:8]
    sample = service.saveSample(dict(_nz("NZ%s" % marker), description="Ribosome 50%% %s" % marker))
    created.append(sample["id"])

    assert [found["id"] for found in service.listSamples(marker)] == [sample["id"]]
    assert service.listSamples("zz%s_none" % marker) == []
