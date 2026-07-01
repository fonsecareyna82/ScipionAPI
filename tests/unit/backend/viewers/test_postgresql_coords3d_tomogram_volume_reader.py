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
import importlib


class FakeCoordsReader:
    def __init__(self, tomograms=None, lastSkipReason=None):
        self.tomograms = tomograms
        self.lastSkipReason = lastSkipReason
        self.listTomogramsCalls = 0

    def listTomograms(self):
        self.listTomogramsCalls += 1
        return self.tomograms


def _makeReader(authTestEnv):
    module = importlib.import_module(
        "app.backend.viewers.postgresql_coords3d_tomogram_volume_reader"
    )

    return module.PostgresqlCoords3dTomogramVolumeReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputCoordinates",
    )


def test_PostgresqlCoords3dTomogramVolumeReaderPropagatesCoordsReaderSkipReason(authTestEnv):
    reader = _makeReader(authTestEnv)
    reader.coordsReader = FakeCoordsReader(
        tomograms=None,
        lastSkipReason="linked_tomograms_not_found",
    )

    result = reader.listVolumes()

    assert result is None
    assert reader.lastSkipReason == "linked_tomograms_not_found"


def test_PostgresqlCoords3dTomogramVolumeReaderBuildsVolumesFromLinkedTomograms(authTestEnv, tmp_path):
    tomoPath = tmp_path / "tomo_001.mrc"

    reader = _makeReader(authTestEnv)
    reader.coordsReader = FakeCoordsReader(
        tomograms=[
            {
                "id": "TS_001",
                "tomoId": "TS_001",
                "label": "Tomogram TS_001",
                "fileName": "2@%s" % str(tomoPath),
                "dims": [64, 128, 256],
                "voxelSize": [1.5, 1.5, 1.5],
                "nCoords": 25,
            },
        ],
    )

    result = reader.listVolumes()

    assert result == [
        {
            "id": "TS_001",
            "index": 0,
            "name": "Tomogram TS_001",
            "label": "Tomogram TS_001",
            "relPath": "Tomogram TS_001",
            "tomoId": "TS_001",
            "fileName": str(tomoPath),
            "path": str(tomoPath),
            "source": "coordinates3d",
            "locationIndex": 2,
            "nCoords": 25,
            "dims": [64, 128, 256],
            "voxelSize": [1.5, 1.5, 1.5],
            "pixelSize": 1.5,
            "samplingRate": 1.5,
        },
    ]


def test_PostgresqlCoords3dTomogramVolumeReaderFindsVolumeByTomoId(authTestEnv, tmp_path):
    tomoPath = tmp_path / "tomo_001.mrc"

    reader = _makeReader(authTestEnv)
    reader.coordsReader = FakeCoordsReader(
        tomograms=[
            {
                "id": "TS_001",
                "tomoId": "TS_001",
                "label": "Tomogram TS_001",
                "fileName": str(tomoPath),
                "dims": [64, 128, 256],
            },
        ],
    )

    info = reader.getVolumeInfo("TS_001")

    assert info is not None
    assert info["id"] == "TS_001"
    assert info["tomoId"] == "TS_001"
    assert info["fileName"] == str(tomoPath)


def test_PostgresqlCoords3dTomogramVolumeReaderReportsMissingVolumeFile(authTestEnv, tmp_path):
    missingPath = tmp_path / "missing_tomo.mrc"

    reader = _makeReader(authTestEnv)
    reader.coordsReader = FakeCoordsReader(
        tomograms=[
            {
                "id": "TS_001",
                "tomoId": "TS_001",
                "label": "Tomogram TS_001",
                "fileName": str(missingPath),
                "dims": [64, 128, 256],
            },
        ],
    )

    result = reader.getVolumeFile("TS_001")

    assert result is None
    assert reader.lastSkipReason == "volume_file_missing fileName=%s" % str(missingPath)


def test_PostgresqlCoords3dTomogramVolumeReaderReportsMissingVolumeId(authTestEnv, tmp_path):
    tomoPath = tmp_path / "tomo_001.mrc"

    reader = _makeReader(authTestEnv)
    reader.coordsReader = FakeCoordsReader(
        tomograms=[
            {
                "id": "TS_001",
                "tomoId": "TS_001",
                "label": "Tomogram TS_001",
                "fileName": str(tomoPath),
                "dims": [64, 128, 256],
            },
        ],
    )

    result = reader.getVolumeInfo("TS_999")

    assert result is None
    assert reader.lastSkipReason == "volume_not_found volumeId=TS_999"