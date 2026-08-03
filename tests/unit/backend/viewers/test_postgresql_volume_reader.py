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

def test_PostgresqlVolumeReaderExtractsDimsFromCommaSeparatedString(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")

    reader = module.PostgresqlVolumeReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputVolumes",
    )

    assert reader._extractDims({"_dim": "128,128,64"}) == [128, 128, 64]
    assert reader._extractDims({"dimensions": "128 128 64"}) == [128, 128, 64]
    assert reader._extractDims({"volumeDims": "128x128x64"}) == [128, 128, 64]


def test_PostgresqlVolumeReaderExtractsDimsFromJsonString(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")

    reader = module.PostgresqlVolumeReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputVolumes",
    )

    assert reader._extractDims({"dims": "[32, 48, 64]"}) == [32, 48, 64]
    assert reader._extractDims({"dims": '{"x": 32, "y": 48, "z": 64}'}) == [32, 48, 64]


def test_PostgresqlVolumeReaderExtractsSamplingRateFromFlatStrings(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")

    reader = module.PostgresqlVolumeReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputVolumes",
    )

    assert reader._extractSamplingRate({"samplingRate": "1.25"}) == 1.25
    assert reader._extractSamplingRate({"voxelSize": "1.5,1.5,1.5"}) == 1.5
    assert reader._extractSamplingRate({"pixelSize": "2.0 2.0 2.0"}) == 2.0


def test_PostgresqlVolumeReaderRejectsInvalidDims(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")

    reader = module.PostgresqlVolumeReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputVolumes",
    )

    assert reader._extractDims({"dims": "128,foo,64"}) is None
    assert reader._extractDims({"dims": "128,64"}) is None
    assert reader._extractDims({"dims": "128,0,64"}) is None


def test_PostgresqlVolumeReaderResolvesProjectRelativeVolumePath(
    authTestEnv,
    tmp_path,
):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")

    projectPath = tmp_path / "project"
    volumePath = projectPath / "Runs" / "000134_ProtVolume" / "extra" / "volume.mrc"
    volumePath.parent.mkdir(parents=True)
    volumePath.write_bytes(b"fake")

    class FakeDb:
        def fetchOne(self, query, params):
            if "FROM projects" in query:
                return {"name": str(projectPath)}
            return None

    reader = module.PostgresqlVolumeReader(
        db=FakeDb(),
        projectId=249,
        protocolId=134,
        outputName="outputVolume",
    )

    assert reader._resolveExistingPath(
        "Runs/000134_ProtVolume/extra/volume.mrc"
    ) == str(volumePath.resolve())