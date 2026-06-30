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


def test_PostgresqlCtftomoReaderExtractsDimsFromFlatStrings(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_ctftomo_reader")

    reader = module.PostgresqlCtftomoReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputCTF",
    )

    assert reader._extractDims({"dims": "4096,4096"}) == [4096, 4096]
    assert reader._extractDims({"dimensions": "4096 4096"}) == [4096, 4096]
    assert reader._extractDims({"imageDims": "4096x4096"}) == [4096, 4096]
    assert reader._extractDims({"dims": "4096,4096,61"}) == [4096, 4096, 61]


def test_PostgresqlCtftomoReaderExtractsSamplingRateFromFlatStrings(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_ctftomo_reader")

    reader = module.PostgresqlCtftomoReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputCTF",
    )

    assert reader._extractSamplingRate({"pixelSize": "1.25"}) == 1.25
    assert reader._extractSamplingRate({"voxelSize": "1.5,1.5,1.5"}) == 1.5
    assert reader._extractSamplingRate({"apix": "2.0 2.0"}) == 2.0


def test_PostgresqlCtftomoReaderBuildsMeasurementFrameFromCommonAliases(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_ctftomo_reader")

    reader = module.PostgresqlCtftomoReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputCTF",
    )

    frame = reader._buildCtftomoMeasurementFrame(
        {
            "scipionItemId": 11,
            "enabled": True,
            "values": {
                "tiltAngle": "-45.0",
                "df1": "12000.5",
                "df2": "11800.25",
                "astigAngle": "35.0",
                "estRes": "4.2",
                "cc": "0.87",
                "phase_shift": "0.1",
                "acqOrder": "3",
                "psdFile": "ctf_003.mrc",
            },
        },
        position=2,
    )

    assert frame["viewId"] == 11
    assert frame["index"] == 2
    assert frame["viewIndex"] == 2
    assert frame["tiltAngle"] == -45.0
    assert frame["defocusU"] == 12000.5
    assert frame["defocusV"] == 11800.25
    assert frame["astigmatism"] == 200.25
    assert frame["defocusAngle"] == 35.0
    assert frame["resolution"] == 4.2
    assert frame["cc"] == 0.87
    assert frame["phaseShift"] == 0.1
    assert frame["order"] == 3
    assert frame["psdFile"] == "ctf_003.mrc"
    assert frame["excluded"] is False


def test_PostgresqlCtftomoReaderRejectsInvalidDims(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_ctftomo_reader")

    reader = module.PostgresqlCtftomoReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputCTF",
    )

    assert reader._extractDims({"dims": "4096,foo"}) is None
    assert reader._extractDims({"dims": "4096"}) is None
    assert reader._extractDims({"dims": "4096,0"}) is None


def test_PostgresqlCtftomoReaderStoresSkipReasonWhenSeriesIsMissing(authTestEnv, monkeypatch):
    module = importlib.import_module("app.backend.viewers.postgresql_ctftomo_reader")

    reader = module.PostgresqlCtftomoReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputCTF",
    )

    monkeypatch.setattr(
        reader,
        "_getStoredSet",
        lambda: {
            "items": [],
        },
    )

    result = reader.getCtftomoSeriesViews("TS_999")

    assert result is None
    assert reader.lastSkipReason == "ctftomo_series_item_not_found tiltSeriesId=TS_999"