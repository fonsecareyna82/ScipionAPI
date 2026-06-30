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

import pytest


def test_PostgresqlTiltSeriesReaderExtractsDimsFromFlatStrings(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_tiltseries_reader")

    reader = module.PostgresqlTiltSeriesReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputTiltSeries",
    )

    assert reader._extractDims({"dims": "4096,4096"}) == [4096, 4096]
    assert reader._extractDims({"dimensions": "4096 4096"}) == [4096, 4096]
    assert reader._extractDims({"imageDims": "4096x4096"}) == [4096, 4096]
    assert reader._extractDims({"dims": "4096,4096,61"}) == [4096, 4096, 61]


def test_PostgresqlTiltSeriesReaderRejectsInvalidDims(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_tiltseries_reader")

    reader = module.PostgresqlTiltSeriesReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputTiltSeries",
    )

    assert reader._extractDims({"dims": "4096,foo"}) is None
    assert reader._extractDims({"dims": "4096"}) is None
    assert reader._extractDims({"dims": "4096,0"}) is None


def test_PostgresqlTiltSeriesReaderParsesFlatTransformMatrix(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_tiltseries_reader")

    reader = module.PostgresqlTiltSeriesReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputTiltSeries",
    )

    transform = reader._getFrameTransform({
        "matrix": "1,0,2,0,1,3",
    })

    assert transform["shiftX"] == 2.0
    assert transform["shiftY"] == 3.0
    assert transform["rot"] == pytest.approx(0.0)


def test_PostgresqlTiltSeriesReaderParsesJsonTransformMatrix(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_tiltseries_reader")

    reader = module.PostgresqlTiltSeriesReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputTiltSeries",
    )

    transform = reader._getFrameTransform({
        "matrix": "[[0,-1,5],[1,0,7]]",
    })

    assert transform["shiftX"] == 5.0
    assert transform["shiftY"] == 7.0
    assert transform["rot"] == pytest.approx(-90.0)