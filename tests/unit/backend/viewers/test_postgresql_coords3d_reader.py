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

def _readerWithLinkedTomogram(module, monkeypatch, projectPath, fileName):
    """A reader whose coordinates link one tomogram (TS_01) stored with ``fileName``, in a project at
    ``projectPath``."""
    from app.backend.viewers.postgresql_path_resolver import PostgresqlProjectPathResolver

    reader = module.PostgresqlCoords3dReader(db=object(), projectId=16, protocolId=21, outputName="coordinates")
    tomogram = {"id": 1, "tomoId": "TS_01", "label": "TS_01", "name": "TS_01", "fileName": fileName}
    monkeypatch.setattr(reader, "_getStoredSet", lambda: {"properties": {}})
    monkeypatch.setattr(reader, "_getLinkedTomogramsFromProperties", lambda storedSet: [tomogram])
    monkeypatch.setattr(reader, "_normalizeLinkedTomogramItem", lambda item: item)
    monkeypatch.setattr(reader, "_getTomogramMatchKeys", lambda item: {"TS_01"})
    monkeypatch.setattr(PostgresqlProjectPathResolver, "getProjectPath", lambda self: projectPath)
    return reader


def test_PostgresqlCoords3dReaderFindsATomogramOfTheProjectWhateverTheWorkingDirectory(
        authTestEnv, tmp_path, monkeypatch):
    module = importlib.import_module("app.backend.viewers.postgresql_coords3d_reader")
    projectPath = tmp_path / "project"
    stored = projectPath / "Runs" / "000018_Recon" / "extra" / "TS_01.mrc"
    stored.parent.mkdir(parents=True)
    stored.write_bytes(b"")
    # The API process may be anywhere: another request loaded another project, or none was loaded yet
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    reader = _readerWithLinkedTomogram(module, monkeypatch, projectPath, "Runs/000018_Recon/extra/TS_01.mrc")

    tomogram = reader.getTomogramFile("TS_01")

    assert tomogram is not None and tomogram["fileName"] == str(stored)


def test_PostgresqlCoords3dReaderSaysWhenTheFileOfATomogramIsMissing(authTestEnv, tmp_path, monkeypatch):
    module = importlib.import_module("app.backend.viewers.postgresql_coords3d_reader")
    reader = _readerWithLinkedTomogram(module, monkeypatch, tmp_path, "Runs/000018_Recon/extra/TS_01.mrc")

    assert reader.getTomogramFile("TS_01") is None
    assert reader.lastSkipReason.startswith("tomogram_file_missing tomogramId=TS_01")


def test_PostgresqlCoords3dReaderDoesNotSearchTheProjectForAnOutputThatIsNotCoordinates(authTestEnv, monkeypatch):
    """Every volume request asks this reader first: a SetOfTomograms, whose items carry a tsId, must not make it
    go through every tomogram-like item of the project (thousands of particles) on each slice."""
    module = importlib.import_module("app.backend.viewers.postgresql_coords3d_reader")
    reader = module.PostgresqlCoords3dReader(db=object(), projectId=14, protocolId=5, outputName="Tomograms")
    storedSet = {"setClassName": "SetOfTomograms", "itemClassName": "Tomogram", "properties": {},
                 "items": [{"values": {"_tsId": "TS_01"}}]}
    monkeypatch.setattr(reader, "_getStoredSet", lambda: storedSet)

    def searchProject():
        raise AssertionError("the project must not be searched for tomograms of a SetOfTomograms")

    monkeypatch.setattr(reader, "_getProjectTomogramRows", searchProject)

    assert reader.listTomograms() is None
    assert reader.lastSkipReason == "not_coordinates_output setClassName=SetOfTomograms"


def test_PostgresqlCoords3dReaderShowsATomogramOfTheSetWithNothingPickedWithNoPoints(authTestEnv, monkeypatch):
    """The picking of one tomogram may fail or find nothing: the viewer opens it empty, not with an error."""
    module = importlib.import_module("app.backend.viewers.postgresql_coords3d_reader")
    reader = module.PostgresqlCoords3dReader(db=object(), projectId=16, protocolId=21, outputName="coordinates")
    linked = [{"id": "TS_01", "tomoId": "TS_01", "name": ".1", "objectId": "1", "dims": [100, 100, 50]},
              {"id": "TS_02", "tomoId": "TS_02", "name": ".2", "objectId": "2", "dims": [100, 100, 50]}]
    storedSet = {"setClassName": "SetOfCoordinates3D", "itemClassName": "Coordinate3D",
                 "properties": {"linkedTomograms": linked},
                 "items": [{"id": 1, "values": {"_x": -168.0, "_y": -494.0, "_z": 45.0, "_volId": 2, "_tomoId": "TS_02",
                                                "bottomLeftX": 344.0, "bottomLeftY": 18.0, "bottomLeftZ": 220.0,
                                                "coordinateConvention": "BOTTOM_LEFT_CORNER"}}]}
    monkeypatch.setattr(reader, "_getStoredSet", lambda: storedSet)
    monkeypatch.setattr(reader, "_getProjectTomogramRows", lambda: [])

    assert reader.getPoints("TS_01") == []
    assert len(reader.getPoints("TS_02")) == 1
    assert reader.getPoints("TS_99") is None
    assert reader.lastSkipReason.startswith("coordinates_not_found_for_tomogram tomogramId=TS_99")
