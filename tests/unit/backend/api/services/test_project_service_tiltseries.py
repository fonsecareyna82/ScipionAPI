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
import math
from pathlib import Path

import pytest


class FakeAcquisition:
    # fakeAcquisition
    def __init__(self, tiltAxisAngle=None, accumDose=None):
        self._tiltAxisAngle = tiltAxisAngle
        self._accumDose = accumDose

    def getTiltAxisAngle(self):
        return self._tiltAxisAngle

    def getAccumDose(self):
        return self._accumDose


class FakeTransform:
    # fakeTransform
    def __init__(self, rotDegrees=15.0, shiftX=3.5, shiftY=-2.0):
        self._rotDegrees = rotDegrees
        self._shiftX = shiftX
        self._shiftY = shiftY

    def getEulerAngles(self):
        return (0.0, 0.0, math.radians(-self._rotDegrees))

    def getMatrixAsList(self):
        return [1, 0, self._shiftX, 0, 1, self._shiftY, 0, 0, 1]


class FakeTiltImage:
    # fakeTiltImage
    def __init__(
        self,
        objId,
        index,
        order,
        tiltAngle,
        fileName,
        enabled=True,
        accumDose=None,
        transform=None,
    ):
        self._objId = objId
        self._index = index
        self._order = order
        self._tiltAngle = tiltAngle
        self._fileName = fileName
        self._enabled = enabled
        self._acquisition = FakeAcquisition(accumDose=accumDose)
        self._transform = transform

    def getObjId(self):
        return self._objId

    def getIndex(self):
        return self._index

    def getAcquisitionOrder(self):
        return self._order

    def getTiltAngle(self):
        return self._tiltAngle

    def isEnabled(self):
        return self._enabled

    def getAcquisition(self):
        return self._acquisition

    def getFileName(self):
        return self._fileName

    def hasTransform(self):
        return self._transform is not None

    def getTransform(self):
        return self._transform


class FakeTiltSeries:
    # fakeTiltSeries
    def __init__(self, tsId, size, dims, samplingRate, tiltAxisAngle, items=None):
        self._tsId = tsId
        self._size = size
        self._dims = dims
        self._samplingRate = samplingRate
        self._acquisition = FakeAcquisition(tiltAxisAngle=tiltAxisAngle)
        self._items = items or []

    def getTsId(self):
        return self._tsId

    def getSize(self):
        return self._size

    def getDim(self):
        return self._dims

    def getSamplingRate(self):
        return self._samplingRate

    def getAcquisition(self):
        return self._acquisition

    def iterItems(self, iterate=False):
        return list(self._items)

    def getItem(self, key, value):
        if key != "_index":
            return None
        for item in self._items:
            if item.getIndex() == value:
                return item
        return None


class FakeTiltSeriesSet:
    # fakeTiltSeriesSet
    def __init__(self, items=None, hasOddEven=False, dims=None):
        self._items = items or []
        self._hasOddEven = hasOddEven
        self._dims = dims or [64, 64, 32]

    def iterItems(self, iterate=False):
        return list(self._items)

    def getItem(self, key, value):
        if key != "_tsId":
            return None
        for item in self._items:
            if str(item.getTsId()) == str(value):
                return item
        return None

    def hasOddEven(self):
        return self._hasOddEven

    def getDim(self):
        return self._dims

    def getSize(self):
        return len(self._items)


class FakeProtocol:
    # fakeProtocol
    def __init__(self, outputName, output):
        setattr(self, outputName, output)

    def getPath(self):
        return "/tmp/fake-protocol-path"

    def _getExtraPath(self):
        return "/tmp/fake-extra"

    def getOutputsSize(self):
        return 0

    def getNextOutputName(self, prefix):
        return "TiltSeries_0"

    def _defineOutputs(self, **kwargs):
        self._definedOutputs = kwargs

    def _store(self):
        self._stored = True


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(self, protocol):
        self._protocol = protocol

    def getProtocol(self, protocolId):
        return self._protocol


class FakeOutputsPreview:
    # fakeOutputsPreview
    instances = []

    def __init__(self, currentProject, protocol, output, requestHeaders=None):
        self.currentProject = currentProject
        self.protocol = protocol
        self.output = output
        self.requestHeaders = requestHeaders
        self.lastRenderCall = None
        FakeOutputsPreview.instances.append(self)

    def renderImageFromFilePath(
        self,
        filePath,
        size,
        fmt,
        index,
        applyTransform,
        inline,
        rot,
        shifts,
    ):
        self.lastRenderCall = {
            "filePath": filePath,
            "size": size,
            "fmt": fmt,
            "index": index,
            "applyTransform": applyTransform,
            "inline": inline,
            "rot": rot,
            "shifts": shifts,
        }
        return {"rendered": True, "filePath": filePath}


class FakeCreatedTiltSeriesOutputSet:
    # fakeCreatedTiltSeriesOutputSet
    def __init__(self):
        self._items = []
        self._dim = None
        self._copiedInfoFrom = None
        self._written = False

    def copyInfo(self, inputSet):
        self._copiedInfoFrom = inputSet

    def setDim(self, dims):
        self._dim = dims

    def append(self, item):
        self._items.append(item)

    def getSize(self):
        return len(self._items)

    def write(self):
        self._written = True


@pytest.fixture
def projectServiceModule(authTestEnv):
    # projectServiceModule
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule):
    # service
    instance = object.__new__(projectServiceModule.ProjectService)
    instance.tomoList = {}
    instance.currentProject = None
    return instance


def test_ListOutputTiltSeriesServiceBuildsSummaries(service):
    ts1 = FakeTiltSeries(
        tsId="TS_001",
        size=5,
        dims=[128, 128, 40],
        samplingRate=1.5,
        tiltAxisAngle=90.0,
    )
    ts2 = FakeTiltSeries(
        tsId="TS_002",
        size=3,
        dims=[64, 64, 20],
        samplingRate=2.0,
        tiltAxisAngle=85.0,
    )
    output = FakeTiltSeriesSet([ts1, ts2])
    protocol = FakeProtocol("outputTiltSeries", output)
    service.currentProject = FakeCurrentProject(protocol)

    result = service.listOutputTiltSeriesService(
        projectId=1,
        protocolId=10,
        outputName="outputTiltSeries",
    )

    assert result == [
        {
            "tiltSeriesId": "TS_001",
            "label": "TiltSeries TS_001",
            "nViews": 5,
            "dims": [128, 128, 40],
            "pixelSize": 1.5,
            "tiltAxisAngle": 90.0,
        },
        {
            "tiltSeriesId": "TS_002",
            "label": "TiltSeries TS_002",
            "nViews": 3,
            "dims": [64, 64, 20],
            "pixelSize": 2.0,
            "tiltAxisAngle": 85.0,
        },
    ]


def test_GetTiltSeriesFramesServiceBuildsFramesFromSelectedSeries(service, tmp_path):
    imagePath1 = tmp_path / "tilt-1.mrc"
    imagePath2 = tmp_path / "tilt-2.mrc"
    imagePath1.write_text("placeholder", encoding="utf-8")
    imagePath2.write_text("placeholder", encoding="utf-8")

    item1 = FakeTiltImage(
        objId=101,
        index=1,
        order=1,
        tiltAngle=-60.0,
        fileName=str(imagePath1),
        enabled=True,
        accumDose=2.5,
        transform=None,
    )
    item2 = FakeTiltImage(
        objId=102,
        index=2,
        order=2,
        tiltAngle=-58.0,
        fileName=str(imagePath2),
        enabled=False,
        accumDose=3.0,
        transform=FakeTransform(rotDegrees=12.0, shiftX=4.0, shiftY=-1.0),
    )

    ts = FakeTiltSeries(
        tsId="TS_001",
        size=2,
        dims=[128, 128, 40],
        samplingRate=1.5,
        tiltAxisAngle=90.0,
        items=[item1, item2],
    )
    output = FakeTiltSeriesSet([ts])
    protocol = FakeProtocol("outputTiltSeries", output)
    service.currentProject = FakeCurrentProject(protocol)

    result = service.getTiltSeriesFramesService(
        projectId=1,
        protocolId=10,
        outputName="outputTiltSeries",
        tiltSeriesId="TS_001",
    )

    assert result["tiltSeriesId"] == "TS_001"
    assert result["label"] == "TS_001"
    assert len(result["frames"]) == 2

    frame1 = result["frames"][0]
    assert frame1 == {
        "viewId": 101,
        "index": 1,
        "order": 1,
        "tiltAngle": -60.0,
        "excluded": False,
        "dose": 2.5,
        "path": "1@" + str(imagePath1),
    }

    frame2 = result["frames"][1]
    assert frame2["viewId"] == 102
    assert frame2["index"] == 2
    assert frame2["order"] == 2
    assert frame2["tiltAngle"] == -58.0
    assert frame2["excluded"] is True
    assert frame2["dose"] == 3.0
    assert frame2["path"] == "2@" + str(imagePath2)
    assert frame2["rot"] == pytest.approx(12.0)
    assert frame2["shiftX"] == pytest.approx(4.0)
    assert frame2["shiftY"] == pytest.approx(-1.0)


def test_RenderTiltSeriesImageServiceDelegatesToOutputsPreview(projectServiceModule, service, monkeypatch, tmp_path):
    FakeOutputsPreview.instances = []

    imagePath = tmp_path / "tilt-1.mrc"
    imagePath.write_text("placeholder", encoding="utf-8")

    tiltImage = FakeTiltImage(
        objId=101,
        index=2,
        order=2,
        tiltAngle=-58.0,
        fileName=str(imagePath),
        enabled=True,
        accumDose=2.0,
        transform=FakeTransform(rotDegrees=20.0, shiftX=6.0, shiftY=-3.0),
    )
    ts = FakeTiltSeries(
        tsId="TS_001",
        size=1,
        dims=[128, 128, 40],
        samplingRate=1.5,
        tiltAxisAngle=90.0,
        items=[tiltImage],
    )
    output = FakeTiltSeriesSet([ts])
    protocol = FakeProtocol("outputTiltSeries", output)
    service.currentProject = FakeCurrentProject(protocol)

    monkeypatch.setattr(projectServiceModule, "OutputsPreview", FakeOutputsPreview)

    result = service.renderTiltSeriesImageService(
        projectId=1,
        protocolId=10,
        outputName="outputTiltSeries",
        tiltSeriesId="TS_001",
        index=2,
        size=512,
        fmt="png",
        applyTransform=True,
        inline=False,
    )

    assert result == {
        "rendered": True,
        "filePath": str(imagePath),
    }
    assert len(FakeOutputsPreview.instances) == 1
    assert FakeOutputsPreview.instances[0].lastRenderCall == {
        "filePath": str(imagePath),
        "size": 512,
        "fmt": "png",
        "index": 2,
        "applyTransform": True,
        "inline": False,
        "rot": 20.0,
        "shifts": (6.0, -3.0),
    }


def test_CreateNewSetOfTiltSeriesServiceReturnsEmptyWhenNoSeriesCreated(projectServiceModule, service, monkeypatch):
    createdOutputSet = FakeCreatedTiltSeriesOutputSet()

    class FakeSetOfTiltSeriesFactory:
        # fakeSetOfTiltSeriesFactory
        @staticmethod
        def create(projectPath, suffix):
            return createdOutputSet

    inputSet = FakeTiltSeriesSet(items=[], hasOddEven=False, dims=[128, 128, 40])
    protocol = FakeProtocol("outputTiltSeries", inputSet)
    service.currentProject = FakeCurrentProject(protocol)

    monkeypatch.setattr(projectServiceModule, "SetOfTiltSeries", FakeSetOfTiltSeriesFactory)

    result = service.createNewSetOfTiltSeriesService(
        projectId=1,
        protocolId=10,
        outputName="outputTiltSeries",
        exclusions={},
        restack=False,
    )

    assert result == {
        "status": "empty",
        "outputName": "TiltSeries_0",
        "createdTiltSeries": 0,
        "hasOddEven": False,
        "restack": False,
        "message": "No output was generated because it cannot be empty",
    }
    assert createdOutputSet.getSize() == 0
    assert createdOutputSet._copiedInfoFrom is inputSet
    assert createdOutputSet._dim == [128, 128, 40]


def test_CreateNewSetOfTiltSeriesServiceStoresSetWithResolvedProtocolDbId(
    projectServiceModule,
    service,
    monkeypatch,
):
    storedCalls = []

    class FakeDb:
        # fakeDb
        def fetchOne(self, *args, **kwargs):
            return None

    class FakeMapper:
        # fakeMapper
        def __init__(self):
            self.db = FakeDb()

    class FakeScipionSetPostgresqlMapper:
        # fakeScipionSetPostgresqlMapper
        def __init__(self, db):
            self.db = db

        def storeSet(self, projectId, protocolDbId, outputName, scipionSet):
            storedCalls.append(
                {
                    "projectId": projectId,
                    "protocolDbId": protocolDbId,
                    "outputName": outputName,
                    "scipionSet": scipionSet,
                }
            )
            return {
                "stored": True,
                "protocolDbId": protocolDbId,
                "outputName": outputName,
            }

    class FakeCreatedTiltSeries:
        # fakeCreatedTiltSeries
        def __init__(self):
            self._items = []
            self._dim = None
            self._anglesCount = None
            self._written = False

        def copyInfo(self, tiltSeries):
            self._copiedInfoFrom = tiltSeries

        def append(self, item):
            self._items.append(item)

        def setEnabled(self, value):
            self._enabled = value

        def getSize(self):
            return len(self._items)

        def setDim(self, dim):
            self._dim = dim

        def setAnglesCount(self, count):
            self._anglesCount = count

        def write(self):
            self._written = True

    class FakeSetOfTiltSeriesFactory:
        # fakeSetOfTiltSeriesFactory
        @staticmethod
        def create(projectPath, suffix):
            return createdOutputSet

    createdOutputSet = FakeCreatedTiltSeriesOutputSet()
    createdOutputSet.update = lambda item: None
    createdOutputSet.remove = lambda item: None

    tiltSeries = FakeTiltSeries(
        tsId="TS_001",
        size=0,
        dims=[128, 128, 40],
        samplingRate=1.5,
        tiltAxisAngle=90.0,
        items=[],
    )
    inputSet = FakeTiltSeriesSet(
        items=[tiltSeries],
        hasOddEven=False,
        dims=[128, 128, 40],
    )
    protocol = FakeProtocol("outputTiltSeries", inputSet)
    service.currentProject = FakeCurrentProject(protocol)

    scipionSetMapperModule = importlib.import_module(
        "app.backend.mapper.scipion_set_mapper"
    )

    monkeypatch.setattr(
        scipionSetMapperModule,
        "ScipionSetPostgresqlMapper",
        FakeScipionSetPostgresqlMapper,
    )
    monkeypatch.setattr(projectServiceModule, "SetOfTiltSeries", FakeSetOfTiltSeriesFactory)
    monkeypatch.setattr(projectServiceModule, "TiltSeries", FakeCreatedTiltSeries)
    monkeypatch.setattr(
        service,
        "_resolvePostgresqlProtocolDbId",
        lambda mapper, projectId, protocolId: 321,
    )

    mapper = FakeMapper()

    result = service.createNewSetOfTiltSeriesService(
        projectId=1,
        protocolId=10,
        outputName="outputTiltSeries",
        exclusions={},
        restack=False,
        mapper=mapper,
    )

    assert result["status"] == 0
    assert result["outputName"] == "TiltSeries_0"
    assert result["postgresqlSync"] == {
        "stored": True,
        "protocolDbId": 321,
        "outputName": "TiltSeries_0",
    }
    assert result["postgresqlError"] is None
    assert storedCalls == [
        {
            "projectId": 1,
            "protocolDbId": 321,
            "outputName": "TiltSeries_0",
            "scipionSet": createdOutputSet,
        }
    ]

def test_ResolveOutputForTiltSeriesReturns404WhenProtocolMissing(service):
    class BrokenCurrentProject:
        # brokenCurrentProject
        def getProtocol(self, protocolId):
            raise RuntimeError("missing protocol")

    service.currentProject = BrokenCurrentProject()

    with pytest.raises(Exception) as exc:
        service._resolveOutputForTiltSeries(10, "outputTiltSeries")

    assert exc.value.status_code == 404
    assert str(exc.value.detail).startswith("Protocol not found in Scipion runtime:")