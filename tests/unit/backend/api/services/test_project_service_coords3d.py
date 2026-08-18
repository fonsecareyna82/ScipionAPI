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
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException


class FakeTomogram:
    # fakeTomogram
    def __init__(self, tsId, label, fileName, samplingRate, dims):
        self._tsId = tsId
        self._label = label
        self._fileName = fileName
        self._samplingRate = samplingRate
        self._dims = dims

    def getTsId(self):
        return self._tsId

    def getObjId(self):
        return self._tsId

    def getObjLabel(self):
        return self._label

    def getFileName(self):
        return self._fileName

    def getSamplingRate(self):
        return self._samplingRate

    def getDim(self):
        return self._dims


class FakeCoord:
    # fakeCoord
    def __init__(
        self,
        x,
        y,
        z,
        objId=None,
        classId=None,
        label=None,
        score=None,
        weight=None,
        matrix=None,
    ):
        self._x = x
        self._y = y
        self._z = z
        self._objId = objId
        self._classId = classId
        self._objLabel = label
        self._score = score
        self._weight = weight
        self._matrix = matrix if matrix is not None else np.eye(4, dtype=float)

    def getX(self, corner):
        return self._x

    def getY(self, corner):
        return self._y

    def getZ(self, corner):
        return self._z

    def getObjId(self):
        return self._objId

    def getClassId(self):
        return self._classId

    def getObjLabel(self):
        return self._objLabel

    def getScore(self):
        return self._score

    def getWeight(self):
        return self._weight

    def getMatrix(self):
        return self._matrix

    def clone(self):
        cloned = FakeCreatedCoordinate3D()
        cloned.setObjId(self._objId)
        cloned.setPosition(self._x, self._y, self._z, "bottom-left")
        cloned.setGroupId(self._classId if self._classId is not None else 0)
        cloned.setScore(self._score if self._score is not None else 0)
        cloned.setMatrix(np.array(self._matrix, copy=True))
        return cloned


class FakeCoordinatesSet:
    # fakeCoordinatesSet
    def __init__(self, tomograms=None, coordsByTomogram=None, boxSize=24):
        self._tomograms = tomograms or []
        self._coordsByTomogram = coordsByTomogram or {}
        self._boxSize = boxSize

    def iterTomograms(self):
        return iter(self._tomograms)

    def getBoxSize(self):
        return self._boxSize

    def iterCoordinates(self, tomogram):
        return iter(self._coordsByTomogram.get(tomogram.getTsId(), []))

    def _getTomogram(self, key):
        for tomo in self._tomograms:
            if str(tomo.getTsId()) == str(key):
                return tomo
        return None

    def createCopy(self, protocolPath, prefix=None, copyInfo=True):
        return FakeCreatedCoordinatesSet(prefix=prefix)

    def getTomograms(self):
        return self._tomograms


class FakeCreatedCoordinatesSet:
    # fakeCreatedCoordinatesSet
    def __init__(self, prefix=None):
        self.prefix = prefix
        self.appended = []
        self.tomograms = None
        self.written = False
        self._samplingRate = 3.0
        self.infoSource = None
        self.boxSize = None

    def copyInfo(self, source):
        self.infoSource = source

    def setBoxSize(self, value):
        self.boxSize = value

    def setTomograms(self, tomograms):
        self.tomograms = tomograms

    def append(self, coord):
        self.appended.append(coord)

    def write(self):
        self.written = True

    def getSamplingRate(self):
        return self._samplingRate


class FakeCreatedCoordinate3D:
    # fakeCreatedCoordinate3D
    def __init__(self):
        self.objId = None
        self.volume = None
        self.position = None
        self.groupId = None
        self.tomoId = None
        self.boxSize = None
        self.score = None
        self.matrix = None

    def setObjId(self, value):
        self.objId = value

    def setVolume(self, value):
        self.volume = value

    def setPosition(self, x, y, z, corner):
        self.position = {
            "x": x,
            "y": y,
            "z": z,
            "corner": corner,
        }

    def setGroupId(self, value):
        self.groupId = value

    def setTomoId(self, value):
        self.tomoId = value

    def setBoxSize(self, value):
        self.boxSize = value

    def setScore(self, value):
        self.score = value

    def setMatrix(self, value):
        self.matrix = value


class FakeProtocol:
    # fakeProtocol
    def __init__(self, outputName, output):
        setattr(self, outputName, output)
        self.definedOutputs = {}
        self.stored = False

    def getNextOutputName(self, baseName):
        return baseName + "_edited"

    def _getPath(self):
        return "/tmp/fake-protocol-path"

    def _defineOutputs(self, **kwargs):
        self.definedOutputs.update(kwargs)

    def _store(self):
        self.stored = True


class FakeCurrentProject:
    def __init__(self, protocol):
        self._protocol = protocol
        self.mapper = object()

    def getProtocol(self, protocolId):
        return self._protocol


@pytest.fixture
def projectServiceModule(authTestEnv):
    # projectServiceModule
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule):
    # service
    instance = object.__new__(projectServiceModule.ProjectService)
    instance.currentProject = None
    instance.tomoList = {}
    return instance


def test_ListCoordinates3dTomogramsServiceBuildsTomogramList(service, tmp_path):
    tomoPath1 = tmp_path / "tomo1.mrc"
    tomoPath2 = tmp_path / "tomo2.mrc"
    tomoPath1.write_text("placeholder", encoding="utf-8")
    tomoPath2.write_text("placeholder", encoding="utf-8")

    tomo1 = FakeTomogram(
        tsId="TS_001",
        label="Tomogram 1",
        fileName=str(tomoPath1),
        samplingRate=2.5,
        dims=[128, 128, 64],
    )
    tomo2 = FakeTomogram(
        tsId="TS_002",
        label="Tomogram 2",
        fileName=str(tomoPath2),
        samplingRate=3.0,
        dims=[64, 64, 32],
    )

    output = FakeCoordinatesSet(tomograms=[tomo1, tomo2])
    protocol = FakeProtocol("outputCoords3d", output)
    service.currentProject = FakeCurrentProject(protocol)

    result = service.listCoordinates3dTomogramsService(
        projectId=1,
        protocolId=10,
        outputName="outputCoords3d",
    )

    assert result == [
        {
            "id": "TS_001",
            "name": "Tomogram 1",
            "label": "TS_001",
            "dims": [128, 128, 64],
            "voxelSize": [2.5, 2.5, 2.5],
        },
        {
            "id": "TS_002",
            "name": "Tomogram 2",
            "label": "TS_002",
            "dims": [64, 64, 32],
            "voxelSize": [3.0, 3.0, 3.0],
        },
    ]
    assert service.tomoList["TS_001"] is tomo1
    assert service.tomoList["TS_002"] is tomo2


def test_GetPostgresqlCoords3dReaderIfAvailableUsesResolvedProtocolDbId(
    service,
    monkeypatch,
):
    createdReaders = []

    class FakeDb:
        # fakeDb
        pass

    class FakeMapper:
        # fakeMapper
        def __init__(self):
            self.db = FakeDb()

    class FakePostgresqlCoords3dReader:
        # fakePostgresqlCoords3dReader
        def __init__(self, db, projectId, protocolId, outputName):
            self.db = db
            self.projectId = projectId
            self.protocolId = protocolId
            self.outputName = outputName
            createdReaders.append(self)

        def hasOutput(self):
            return True

    readerModule = importlib.import_module(
        "app.backend.viewers.postgresql_coords3d_reader"
    )

    monkeypatch.setattr(
        readerModule,
        "PostgresqlCoords3dReader",
        FakePostgresqlCoords3dReader,
    )
    monkeypatch.setattr(
        service,
        "_resolvePostgresqlProtocolDbId",
        lambda mapper, projectId, protocolId: 987,
    )

    mapper = FakeMapper()

    reader = service._getPostgresqlCoords3dReaderIfAvailable(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        outputName="outputCoords3d",
    )

    assert reader is createdReaders[0]
    assert createdReaders[0].db is mapper.db
    assert createdReaders[0].projectId == 1
    assert createdReaders[0].protocolId == 987
    assert createdReaders[0].outputName == "outputCoords3d"


@pytest.mark.parametrize(
    "serviceCall, expectedDetail",
    [
        (
            lambda service, mapper: service.listCoordinates3dTomogramsService(
                projectId=1,
                protocolId=10,
                outputName="outputCoords3d",
                mapper=mapper,
            ),
            "Coordinates3D output is not available in PostgreSQL metadata",
        ),
        (
            lambda service, mapper: service.getCoordinates3dPointsService(
                projectId=1,
                protocolId=10,
                outputName="outputCoords3d",
                tomogramId="TS_001",
                mapper=mapper,
            ),
            "Coordinates3D points output is not available in PostgreSQL metadata",
        ),
        (
            lambda service, mapper: service.renderCoords3dTomogramSliceService(
                projectId=1,
                protocolId=10,
                outputName="outputCoords3d",
                tomogramId="TS_001",
                sliceIndex=0,
                axis="z",
                colormap=None,
                normalize="minmax",
                scale=1.0,
                inline=True,
                fmt="png",
                thumb=None,
                fast=True,
                quality=75,
                mapper=mapper,
            ),
            "Coordinates3D tomogram slice output is not available in PostgreSQL metadata",
        ),
    ],
)
def test_Coordinates3dServicesRequirePostgresqlWhenMapperIsPresent(
    service,
    monkeypatch,
    serviceCall,
    expectedDetail,
):
    monkeypatch.setattr(
        service,
        "_getPostgresqlCoords3dReaderIfAvailable",
        lambda **kwargs: None,
    )

    def failRuntimeFallback(**kwargs):
        raise AssertionError("Legacy Coordinates3D fallback should not be used")

    monkeypatch.setattr(service, "_resolveOutputForCoordinates3d", failRuntimeFallback)

    with pytest.raises(HTTPException) as exc:
        serviceCall(service, object())

    assert exc.value.status_code == 404
    assert expectedDetail in exc.value.detail


def test_GetCoordinates3dPointsServiceBuildsPointPayload(service, tmp_path):
    tomoPath = tmp_path / "tomo1.mrc"
    tomoPath.write_text("placeholder", encoding="utf-8")

    tomo = FakeTomogram(
        tsId="TS_001",
        label="Tomogram 1",
        fileName=str(tomoPath),
        samplingRate=2.5,
        dims=[128, 128, 64],
    )

    coords = [
        FakeCoord(
            x=10.0,
            y=20.0,
            z=30.0,
            objId=101,
            classId=7,
            label="point-101",
            score=0.87,
            weight=1.5,
            matrix=np.array([[1, 0], [0, 1]], dtype=float),
        ),
    ]

    output = FakeCoordinatesSet(
        tomograms=[tomo],
        coordsByTomogram={"TS_001": coords},
        boxSize=48,
    )
    protocol = FakeProtocol("outputCoords3d", output)
    service.currentProject = FakeCurrentProject(protocol)
    service.tomoList = {"TS_001": tomo}

    result = service.getCoordinates3dPointsService(
        projectId=1,
        protocolId=10,
        outputName="outputCoords3d",
        tomogramId="TS_001",
    )

    assert result == [
        {
            "x": 10.0,
            "y": 20.0,
            "z": 30.0,
            "id": 101,
            "classId": 7,
            "label": "point-101",
            "score": 0.87,
            "weight": 1.5,
            "radius": 48.0,
            "matrix": [[1.0, 0.0], [0.0, 1.0]],
            "tomoId": "TS_001",
        }
    ]


def test_GetCoordinates3dPointsServiceReturns404WhenTomogramMissing(service):
    output = FakeCoordinatesSet(tomograms=[], coordsByTomogram={})
    protocol = FakeProtocol("outputCoords3d", output)
    service.currentProject = FakeCurrentProject(protocol)
    service.tomoList = {}

    with pytest.raises(HTTPException) as exc:
        service.getCoordinates3dPointsService(
            projectId=1,
            protocolId=10,
            outputName="outputCoords3d",
            tomogramId="missing",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Tomogram 'missing' not found in SetOfCoordinates3D"


def test_RenderCoords3dTomogramSliceServiceReturnsImageResponse(projectServiceModule, service, monkeypatch, tmp_path):
    tomoPath = tmp_path / "tomo1.mrc"
    tomoPath.write_text("placeholder", encoding="utf-8")

    tomo = FakeTomogram(
        tsId="TS_001",
        label="Tomogram 1",
        fileName=str(tomoPath),
        samplingRate=2.5,
        dims=[4, 4, 4],
    )

    output = FakeCoordinatesSet(tomograms=[tomo], coordsByTomogram={})
    protocol = FakeProtocol("outputCoords3d", output)
    service.currentProject = FakeCurrentProject(protocol)
    service.tomoList = {"TS_001": tomo}

    monkeypatch.setattr(
        projectServiceModule,
        "readVolumeArray3d",
        lambda volumePath: (
            np.arange(64, dtype=np.float32).reshape((4, 4, 4)),
            {},
        ),
    )

    response = service.renderCoords3dTomogramSliceService(
        projectId=1,
        protocolId=10,
        outputName="outputCoords3d",
        tomogramId="TS_001",
        sliceIndex=1,
        axis="z",
        colormap=None,
        normalize="minmax",
        scale=1.0,
        inline=True,
        fmt="png",
        thumb=None,
        fast=False,
        quality=75,
    )

    assert response.media_type == "image/png"
    assert response.headers["x-preview-depth"] == "4"
    assert response.headers["x-preview-tomogramid"] == "TS_001"
    assert response.headers["x-preview-format"] == "PNG"
    assert len(response.body) > 0


def test_RenderTomogramSliceFromPathAvoidsWritableImageRegistry(
    projectServiceModule,
    service,
    monkeypatch,
    tmp_path,
):
    volumePath = tmp_path / "tomo.mrc"
    volumePath.write_bytes(b"placeholder")

    registryCalls = []

    def registryOpen(*args, **kwargs):
        registryCalls.append((args, kwargs))
        raise RuntimeError("ImageReadersRegistry must not be used for volume slices")

    monkeypatch.setattr(
        projectServiceModule.ImageReadersRegistry,
        "open",
        registryOpen,
    )
    monkeypatch.setattr(
        projectServiceModule,
        "readVolumeSlice2d",
        lambda volumePath, sliceIndex, axis, maxSide: (
            np.arange(16, dtype=np.float32).reshape((4, 4)),
            {},
            {
                "dims": (8, 4, 4),
                "index": int(sliceIndex),
                "step": 1,
            },
        ),
    )

    response = service._renderTomogramSliceFromPath(
        volumePath=str(volumePath),
        tomogramId=0,
        sliceIndex=3,
        axis="z",
        colormap="gray",
        normalize="minmax",
        scale=1.0,
        inline=True,
        fmt="png",
        thumb=384,
        fast=True,
        quality=55,
    )

    assert registryCalls == []
    assert response.media_type == "image/png"
    assert response.headers["x-preview-depth"] == "8"
    assert response.headers["x-preview-tomogramid"] == "0"


def test_CreateCoords3dOutputFromPointsServiceCreatesNewPostgresqlOutput(
    projectServiceModule,
    service,
    monkeypatch,
    tmp_path,
):
    tomoPath = tmp_path / "tomo1.mrc"
    tomoPath.write_text("placeholder", encoding="utf-8")

    tomo = FakeTomogram(
        tsId="TS_001",
        label="Tomogram 1",
        fileName=str(tomoPath),
        samplingRate=2.5,
        dims=[128, 128, 64],
    )

    sourceSet = FakeCoordinatesSet(
        tomograms=[tomo],
        coordsByTomogram={},
        boxSize=48,
    )
    protocol = FakeProtocol("outputCoords3d", sourceSet)
    createdSet = FakeCreatedCoordinatesSet()
    mapper = object()
    discardCalls = []

    service.currentProject = FakeCurrentProject(protocol)

    monkeypatch.setattr(projectServiceModule, "Coordinate3D", FakeCreatedCoordinate3D)
    monkeypatch.setattr(
        service,
        "_resolveOutputForCoordinates3d",
        lambda **kwargs: (protocol, sourceSet),
    )
    monkeypatch.setattr(
        service,
        "_getGeneratedSetOutputIdentity",
        lambda **kwargs: {"outputName": "outputCoords3d_edited"},
    )
    monkeypatch.setattr(
        service,
        "_createWritableGeneratedPostgresqlSet",
        lambda **kwargs: {"outputSet": createdSet},
    )
    monkeypatch.setattr(
        service,
        "_finalizeGeneratedPostgresqlSet",
        lambda **kwargs: {"sets": 1, "items": 2},
    )
    monkeypatch.setattr(
        service,
        "_discardGeneratedPostgresqlSet",
        lambda **kwargs: discardCalls.append(kwargs),
    )

    payload = {
        "tomograms": [
            {
                "tomoId": "TS_001",
                "coords": [
                    {
                        "x": 1.0,
                        "y": 2.0,
                        "z": 3.0,
                        "classId": 5,
                        "score": 0.9,
                        "radius": 48,
                        "matrix": [[1, 0], [0, 1]],
                        "tomoId": "TS_001",
                    },
                    {
                        "x": 4.0,
                        "y": 5.0,
                        "z": 6.0,
                        "tomoId": "TS_001",
                    },
                ],
            }
        ]
    }

    result = service.createCoords3dOutputFromPointsService(
        projectId=1,
        protocolId=10,
        outputName="outputCoords3d",
        payload=payload,
        mapper=mapper,
    )

    assert result["success"] is True
    assert result["outputName"] == "outputCoords3d_edited"
    assert result["data"]["replacedPoints"] == 2
    assert result["data"]["copiedPoints"] == 0
    assert result["data"]["postgresqlStored"] is True
    assert result["data"]["postgresqlError"] is None
    assert result["data"]["postgresqlSync"] == {"sets": 1, "items": 2}

    assert createdSet.written is False
    assert createdSet.infoSource is sourceSet
    assert createdSet.tomograms is sourceSet.getTomograms()
    assert createdSet.boxSize == 48
    assert len(createdSet.appended) == 2

    firstCoord = createdSet.appended[0]
    assert firstCoord.position["x"] == 1.0
    assert firstCoord.position["y"] == 2.0
    assert firstCoord.position["z"] == 3.0
    assert firstCoord.groupId == 5
    assert firstCoord.tomoId == "TS_001"
    assert firstCoord.score == 0.9
    assert firstCoord.boxSize == 48
    assert firstCoord.matrix.tolist() == [[1, 0], [0, 1]]

    assert "outputCoords3d_edited" in protocol.definedOutputs
    assert protocol.definedOutputs["outputCoords3d_edited"] is createdSet
    assert protocol.stored is True
    assert discardCalls == []


def test_CreateCoords3dOutputFromPointsServiceCopiesUntouchedTomograms(
    projectServiceModule,
    service,
    monkeypatch,
    tmp_path,
):
    tomoPath1 = tmp_path / "tomo1.mrc"
    tomoPath2 = tmp_path / "tomo2.mrc"
    tomoPath1.write_text("placeholder", encoding="utf-8")
    tomoPath2.write_text("placeholder", encoding="utf-8")

    tomo1 = FakeTomogram("TS_001", "Tomogram 1", str(tomoPath1), 2.5, [128, 128, 64])
    tomo2 = FakeTomogram("TS_002", "Tomogram 2", str(tomoPath2), 2.5, [128, 128, 64])

    untouchedCoordinate = FakeCoord(
        x=20.0,
        y=30.0,
        z=40.0,
        objId=200,
        classId=7,
        score=0.8,
    )

    sourceSet = FakeCoordinatesSet(
        tomograms=[tomo1, tomo2],
        coordsByTomogram={
            "TS_001": [],
            "TS_002": [untouchedCoordinate],
        },
        boxSize=48,
    )
    protocol = FakeProtocol("outputCoords3d", sourceSet)
    createdSet = FakeCreatedCoordinatesSet()

    service.currentProject = FakeCurrentProject(protocol)

    monkeypatch.setattr(projectServiceModule, "Coordinate3D", FakeCreatedCoordinate3D)
    monkeypatch.setattr(service, "_resolveOutputForCoordinates3d", lambda **kwargs: (protocol, sourceSet))
    monkeypatch.setattr(service, "_getGeneratedSetOutputIdentity", lambda **kwargs: {"outputName": "outputCoords3d_edited"})
    monkeypatch.setattr(service, "_createWritableGeneratedPostgresqlSet", lambda **kwargs: {"outputSet": createdSet})
    monkeypatch.setattr(service, "_finalizeGeneratedPostgresqlSet", lambda **kwargs: {"sets": 1, "items": 1})
    monkeypatch.setattr(service, "_discardGeneratedPostgresqlSet", lambda **kwargs: None)

    result = service.createCoords3dOutputFromPointsService(
        projectId=1,
        protocolId=10,
        outputName="outputCoords3d",
        payload={
            "tomograms": [
                {
                    "tomoId": "TS_001",
                    "coords": [],
                }
            ]
        },
        mapper=object(),
    )

    assert result["data"]["replacedPoints"] == 0
    assert result["data"]["copiedPoints"] == 1
    assert len(createdSet.appended) == 1

    copiedCoordinate = createdSet.appended[0]
    assert copiedCoordinate.objId is None
    assert copiedCoordinate.volume is tomo2
    assert copiedCoordinate.tomoId == "TS_002"
    assert copiedCoordinate.position["x"] == 20.0
    assert copiedCoordinate.position["y"] == 30.0
    assert copiedCoordinate.position["z"] == 40.0
    assert copiedCoordinate.groupId == 7


