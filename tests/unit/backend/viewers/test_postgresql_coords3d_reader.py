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
import inspect


def test_PostgresqlCoords3dReaderReadsBottomLeftCoordinateValues(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_coords3d_reader")

    reader = module.PostgresqlCoords3dReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputCoordinates",
    )

    values = {
        "_bottomLeftX": "10.5",
        "_bottomLeftY": "20.25",
        "_bottomLeftZ": "30.75",
    }

    assert reader._getCoordinateValue(values, "x") == 10.5
    assert reader._getCoordinateValue(values, "y") == 20.25
    assert reader._getCoordinateValue(values, "z") == 30.75


def test_PostgresqlCoords3dReaderBuildsPointWithCurrentOverlayContract(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_coords3d_reader")

    reader = module.PostgresqlCoords3dReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputCoordinates",
    )

    point = reader._buildCoordinatePoint(
        item={
            "scipionItemId": 7,
            "label": "particle-7",
        },
        values={
            "_bottomLeftX": "10",
            "_bottomLeftY": "20",
            "_bottomLeftZ": "30",
            "score": "0.75",
            "groupId": "2",
            "matrix": "[[1,0,0],[0,1,0],[0,0,1]]",
        },
        tomogramId="TS_001",
        boxSize=64,
    )

    assert point == {
        "x": 10.0,
        "y": 20.0,
        "z": 30.0,
        "tomoId": "TS_001",
        "id": 7,
        "classId": "2",
        "score": 0.75,
        "label": "particle-7",
        "matrix": [
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
        ],
        "radius": 64.0,
    }


def test_PostgresqlCoords3dReaderDoesNotInferCoordinatesFromGenericPosition(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_coords3d_reader")

    reader = module.PostgresqlCoords3dReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputCoordinates",
    )

    values = {
        "position": "10,20,30",
    }

    assert reader._getCoordinateValue(values, "x") is None
    assert reader._getCoordinateValue(values, "y") is None
    assert reader._getCoordinateValue(values, "z") is None


def test_PostgresqlCoords3dReaderKeepsFlatMatrixStringIgnored(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_coords3d_reader")

    reader = module.PostgresqlCoords3dReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputCoordinates",
    )

    matrix = reader._extractPointMatrix({
        "matrix": "1,0,0,0,1,0,0,0,1",
    })

    assert matrix is None


def test_PostgresqlCoords3dReaderDelegatesProjectTomogramReads(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_coords3d_reader")
    mapperCalls = []

    class ForbiddenDb:
        def fetchAll(self, *args, **kwargs):
            raise AssertionError("PostgresqlCoords3dReader must not query project tomograms directly")

    class SetMapperStub:
        def listProjectTomogramCandidateItemRows(self, projectId):
            mapperCalls.append({
                "projectId": projectId,
            })

            return [
                {
                    "setId": 11,
                    "projectId": 7,
                    "protocolDbId": 500,
                    "outputName": "outputTomograms",
                    "setClassName": "SetOfTomograms",
                    "itemClassName": "Tomogram",
                    "scipionItemId": 1,
                },
            ]

    reader = module.PostgresqlCoords3dReader(
        db=ForbiddenDb(),
        projectId=7,
        protocolId=600,
        outputName="outputCoordinates",
    )

    reader.setMapper = SetMapperStub()

    result = reader._getProjectTomogramRows()

    assert result == [
        {
            "setId": 11,
            "projectId": 7,
            "protocolDbId": 500,
            "outputName": "outputTomograms",
            "setClassName": "SetOfTomograms",
            "itemClassName": "Tomogram",
            "scipionItemId": 1,
        },
    ]

    assert mapperCalls == [
        {
            "projectId": 7,
        },
    ]

    source = inspect.getsource(module.PostgresqlCoords3dReader._getProjectTomogramRows)

    assert "listProjectTomogramCandidateItemRows(" in source
    assert ".fetchOne(" not in source
    assert ".fetchAll(" not in source
    assert ".execute(" not in source