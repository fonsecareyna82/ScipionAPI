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
from fastapi import HTTPException


class FakeMapper:
    pass


class FakeProjectService:
    def __init__(self, currentProject):
        self.currentProject = currentProject
        self.projectRow = {"id": 1}
        self.runtimeProtocolIdByDbId = {}
        self.getProjectByIdCalls = []
        self.getProjectDbRowCalls = []
        self.loadProjectForThumbnailsCalls = []
        self.runtimeCalls = []

    def getProjectDbRow(
        self,
        mapper,
        projectId,
        currentUser,
    ):
        self.getProjectDbRowCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
        })

        return self.projectRow

    def loadProjectForThumbnails(
        self,
        dbProj,
        mapper,
    ):
        self.loadProjectForThumbnailsCalls.append({
            "dbProj": dbProj,
            "mapper": mapper,
        })

        return self.currentProject

    def getProjectById(self, mapper, projectId, currentUser, refresh=False, checkPid=False):
        self.getProjectByIdCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
            "refresh": refresh,
            "checkPid": checkPid,
        })
        return self.projectRow

    def _getScipionProtocolForRuntime(self, mapper, projectId, protocolId):
        self.runtimeCalls.append({
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
        })

        runtimeProtocolId = self.runtimeProtocolIdByDbId.get(
            int(protocolId),
            int(protocolId),
        )
        return self.currentProject.protocols[int(runtimeProtocolId)]


class FakeCurrentProject:
    def __init__(self):
        self.protocols = {}


class FakeProtocol:
    def __init__(self, objId=10):
        self.objId = objId

    def getObjId(self):
        return self.objId


class FakeMicrograph:
    def __init__(
        self,
        objId,
        location=None,
        fileName=None,
        micName=None,
        label=None,
        dims=None,
    ):
        self.objId = objId
        self.location = location
        self.fileName = fileName
        self.micName = micName
        self.label = label
        self.dims = dims or (4096, 4096)

    def clone(self):
        return FakeMicrograph(
            objId=self.objId,
            location=self.location,
            fileName=self.fileName,
            micName=self.micName,
            label=self.label,
            dims=self.dims,
        )

    def getObjId(self):
        return self.objId

    def getLocation(self):
        return self.location

    def getFileName(self):
        return self.fileName

    def getMicName(self):
        return self.micName

    def getObjLabel(self):
        return self.label

    def getDim(self):
        return self.dims


class FakeMicrographsSet:
    def __init__(self, micrographs):
        self.micrographs = list(micrographs)

    def iterItems(self, iterate=False):
        return iter(self.micrographs)

    def __getitem__(self, micId):
        for micrograph in self.micrographs:
            if int(micrograph.getObjId()) == int(micId):
                return micrograph

        raise KeyError(micId)


class FakeCoordinate:
    def __init__(
        self,
        objId,
        micId,
        x,
        y,
        score=None,
        classId=None,
    ):
        self.objId = objId
        self.micId = micId
        self.x = x
        self.y = y
        self.score = score
        self.classId = classId

    def getObjId(self):
        return self.objId

    def getMicId(self):
        return self.micId

    def getX(self):
        return self.x

    def getY(self):
        return self.y

    def getScore(self):
        return self.score

    def getClassId(self):
        return self.classId

    def clone(self):
        return FakeCoordinate(
            objId=self.objId,
            micId=self.micId,
            x=self.x,
            y=self.y,
            score=self.score,
            classId=self.classId,
        )


class FakeCoordinatesSet:
    def __init__(
        self,
        micrographs,
        coordinates,
        boxSize=64,
    ):
        self.micrographsSet = FakeMicrographsSet(micrographs)
        self.coordinates = list(coordinates)
        self.boxSize = boxSize

    def getMicrographs(self):
        return self.micrographsSet

    def iterItems(self, iterate=False):
        return iter(self.coordinates)

    def iterCoordinates(self, micId):
        return (
            coordinate
            for coordinate in self.coordinates
            if str(coordinate.getMicId()) == str(micId)
        )

    def getBoxSize(self):
        return self.boxSize

    def getSize(self):
        return len(self.coordinates)

    def getFirstItem(self):
        return self.coordinates[0] if self.coordinates else None


@pytest.fixture
def coords2dServiceModule(authTestEnv):
    return importlib.import_module("app.backend.api.services.coords2d_service")


@pytest.fixture
def currentProject():
    return FakeCurrentProject()


@pytest.fixture
def projectService(currentProject):
    return FakeProjectService(currentProject)


@pytest.fixture
def service(coords2dServiceModule, projectService):
    instance = object.__new__(coords2dServiceModule.Coords2dService)
    instance.projectService = projectService
    return instance


@pytest.fixture
def mapper():
    return FakeMapper()


@pytest.fixture
def currentUser():
    return {"id": 1}


def buildCoordinatesOutput():
    micrographA = FakeMicrograph(
        objId=1,
        location=(0, "/data/micrograph-a.mrc"),
        micName="Micrograph A",
        dims=(4096, 3072),
    )
    micrographB = FakeMicrograph(
        objId=2,
        location="1@/data/micrograph-b.mrc",
        label="Micrograph B label",
        dims=(2048, 2048),
    )

    coordinateA = FakeCoordinate(
        objId=101,
        micId=1,
        x=10.5,
        y=20.5,
        score=0.95,
        classId="good",
    )
    coordinateB = FakeCoordinate(
        objId=102,
        micId=1,
        x=30.0,
        y=40.0,
        score=0.75,
        classId="bad",
    )
    coordinateC = FakeCoordinate(
        objId=201,
        micId=2,
        x=15.0,
        y=25.0,
        score=0.60,
        classId="ok",
    )

    return FakeCoordinatesSet(
        micrographs=[micrographA, micrographB],
        coordinates=[coordinateA, coordinateB, coordinateC],
        boxSize=96,
    )


def test_LoadCoordinatesOutputResolvesPostgresqlProtocolId(
    service,
    currentProject,
    projectService,
    mapper,
    currentUser,
):
    protocol = FakeProtocol(objId=10)
    coordinatesSet = buildCoordinatesOutput()
    protocol.outputCoordinates = coordinatesSet

    currentProject.protocols[10] = protocol
    projectService.runtimeProtocolIdByDbId[500] = 10

    loadedProtocol, loadedCoordinatesSet = service._loadCoordinatesOutput(
        mapper=mapper,
        projectId=1,
        currentUser=currentUser,
        protocolId=500,
        outputName="outputCoordinates",
    )

    assert loadedProtocol is protocol
    assert loadedCoordinatesSet is coordinatesSet

    assert projectService.getProjectByIdCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "currentUser": currentUser,
            "refresh": False,
            "checkPid": False,
        }
    ]

    assert projectService.runtimeCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 500,
        }
    ]


def test_LoadCoordinatesOutputRaisesWhenProjectDoesNotExist(
    service,
    projectService,
    mapper,
    currentUser,
):
    projectService.projectRow = None

    with pytest.raises(HTTPException) as exc:
        service._loadCoordinatesOutput(
            mapper=mapper,
            projectId=1,
            currentUser=currentUser,
            protocolId=500,
            outputName="outputCoordinates",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Project not found"
    assert projectService.runtimeCalls == []


def test_LoadCoordinatesOutputRaisesWhenOutputIsMissing(
    service,
    currentProject,
    projectService,
    mapper,
    currentUser,
):
    protocol = FakeProtocol(objId=10)

    currentProject.protocols[10] = protocol
    projectService.runtimeProtocolIdByDbId[500] = 10

    with pytest.raises(HTTPException) as exc:
        service._loadCoordinatesOutput(
            mapper=mapper,
            projectId=1,
            currentUser=currentUser,
            protocolId=500,
            outputName="missingOutput",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Output 'missingOutput' not found in protocol '500'"

    assert projectService.runtimeCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 500,
        }
    ]


def test_LoadCoordinatesOutputRaisesWhenOutputIsNotCoordinatesSet(
    service,
    currentProject,
    projectService,
    mapper,
    currentUser,
):
    protocol = FakeProtocol(objId=10)
    protocol.outputVolume = object()

    currentProject.protocols[10] = protocol
    projectService.runtimeProtocolIdByDbId[500] = 10

    with pytest.raises(HTTPException) as exc:
        service._loadCoordinatesOutput(
            mapper=mapper,
            projectId=1,
            currentUser=currentUser,
            protocolId=500,
            outputName="outputVolume",
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "Output 'outputVolume' is not a SetOfCoordinates output"

    assert projectService.runtimeCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 500,
        }
    ]


