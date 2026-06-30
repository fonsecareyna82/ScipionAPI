# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
from fastapi import HTTPException
import pytest

from app.backend.api.services.coords2d_service import Coords2dService


class FakeReader:
    def __init__(self, micrographs=None, coordinates=None):
        self.micrographs = micrographs
        self.coordinates = coordinates
        self.lastSkipReason = None

    def listMicrographs(self):
        return self.micrographs

    def listCoordinatesForMicrograph(self, micId):
        return self.coordinates


def test_Coords2dServiceListMicrographsUsesPostgresqlReader(monkeypatch):
    service = Coords2dService()
    expected = {
        "micrographs": [{"id": "10", "particles": 2}],
        "totalMicrographs": 1,
        "totalPicks": 2,
        "boxSize": 128,
    }

    monkeypatch.setattr(
        service,
        "_getPostgresqlCoords2dReaderIfAvailable",
        lambda **kwargs: FakeReader(micrographs=expected),
    )

    payload = service.listMicrographs(
        mapper=object(),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
    )

    assert payload == expected


def test_Coords2dServiceListCoordinatesUsesPostgresqlReader(monkeypatch):
    service = Coords2dService()
    expected = {
        "coordinates": [
            {"id": 1, "micId": "10", "x": 11.5, "y": 22.5}
        ]
    }

    monkeypatch.setattr(
        service,
        "_getPostgresqlCoords2dReaderIfAvailable",
        lambda **kwargs: FakeReader(coordinates=expected),
    )

    payload = service.listCoordinatesForMicrograph(
        mapper=object(),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
        micId="10",
    )

    assert payload == expected


def test_Coords2dServiceRaisesWhenPostgresqlReaderMissing(monkeypatch):
    service = Coords2dService()

    monkeypatch.setattr(
        service,
        "_getPostgresqlCoords2dReaderIfAvailable",
        lambda **kwargs: None,
    )

    with pytest.raises(HTTPException) as exc:
        service.listMicrographs(
            mapper=object(),
            projectId=1,
            currentUser={"id": 1},
            protocolId=2,
            outputName="coordinates",
        )

    assert exc.value.status_code == 404
    assert "Coordinates2D output is not available in PostgreSQL metadata" in str(exc.value.detail)