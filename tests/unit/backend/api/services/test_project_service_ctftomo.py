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

import pytest


class FakeAcquisition:
    # fakeAcquisition
    def __init__(self, accumDose=None):
        self._accumDose = accumDose

    def getAccumDose(self):
        return self._accumDose


class FakeTiltView:
    # fakeTiltView
    def __init__(self, acqOrder, tiltAngle, accumDose):
        self._acqOrder = acqOrder
        self._tiltAngle = tiltAngle
        self._acquisition = FakeAcquisition(accumDose=accumDose)

    def getTiltAngle(self):
        return self._tiltAngle

    def getAcquisition(self):
        return self._acquisition


class FakeAssociatedTiltSeries:
    # fakeAssociatedTiltSeries
    def __init__(self, items=None, dims=None, samplingRate=1.5):
        self._items = items or {}
        self._dims = dims or [128, 128, 40]
        self._samplingRate = samplingRate

    def getItem(self, key, value):
        if key != "_acqOrder":
            return None
        return self._items.get(value)

    def getDim(self):
        return self._dims

    def getSamplingRate(self):
        return self._samplingRate

    def getSize(self):
        return len(self._items)


class FakeCtfMeasurement:
    # fakeCtfMeasurement
    def __init__(
        self,
        objId,
        index,
        defocusU,
        defocusV,
        defocusAngle,
        resolution,
        phaseShift,
        acquisitionOrder,
        psdFile,
        enabled=True,
    ):
        self._objId = objId
        self._index = index
        self._defocusU = defocusU
        self._defocusV = defocusV
        self._defocusAngle = defocusAngle
        self._resolution = resolution
        self._phaseShift = phaseShift
        self._acquisitionOrder = acquisitionOrder
        self._psdFile = psdFile
        self._enabled = enabled

    def getObjId(self):
        return self._objId

    def getIndex(self):
        return self._index

    def getDefocusU(self):
        return self._defocusU

    def getDefocusV(self):
        return self._defocusV

    def getDefocusAngle(self):
        return self._defocusAngle

    def getResolution(self):
        return self._resolution

    def getPhaseShift(self):
        return self._phaseShift

    def getAcquisitionOrder(self):
        return self._acquisitionOrder

    def getPsdFile(self):
        return self._psdFile

    def isEnabled(self):
        return self._enabled

    def setEnabled(self, value):
        self._enabled = value

    def clone(self):
        return FakeCtfMeasurement(
            objId=self._objId,
            index=self._index,
            defocusU=self._defocusU,
            defocusV=self._defocusV,
            defocusAngle=self._defocusAngle,
            resolution=self._resolution,
            phaseShift=self._phaseShift,
            acquisitionOrder=self._acquisitionOrder,
            psdFile=self._psdFile,
            enabled=self._enabled,
        )


class FakeCtftomoSeries:
    # fakeCtftomoSeries
    def __init__(self, tsId, label, tiltSeries, items=None):
        self._tsId = tsId
        self._label = label
        self._tiltSeries = tiltSeries
        self._items = items or []
        self._enabled = True
        self._written = False

    def getTsId(self):
        return self._tsId

    def getObjLabel(self):
        return self._label

    def getTiltSeries(self):
        return self._tiltSeries

    def iterItems(self, iterate=False):
        return list(self._items)

    def clone(self):
        return FakeCtftomoSeries(
            tsId=self._tsId,
            label=self._label,
            tiltSeries=self._tiltSeries,
            items=[],
        )

    def setEnabled(self, value):
        self._enabled = value

    def append(self, item):
        self._items.append(item)

    def write(self):
        self._written = True


class FakeCtftomoOutputSet:
    # fakeCtftomoOutputSet
    def __init__(self, seriesList=None, associatedTiltSeriesSet=None):
        self._seriesList = seriesList or []
        self._associatedTiltSeriesSet = associatedTiltSeriesSet
        self._updated = []
        self._written = False
        self._linkedTiltSeries = None

    def iterItems(self, iterate=False):
        return list(self._seriesList)

    def getItem(self, key, value):
        if key != "_tsId":
            return None
        for item in self._seriesList:
            if str(item.getTsId()) == str(value):
                return item
        return None

    def getSetOfTiltSeries(self):
        return self._associatedTiltSeriesSet

    def createCopy(self, protocolPath, prefix=None, copyInfo=True):
        return FakeCtftomoOutputSet(seriesList=[], associatedTiltSeriesSet=self._associatedTiltSeriesSet)

    def append(self, item):
        self._seriesList.append(item)

    def update(self, item):
        self._updated.append(item)

    def write(self):
        self._written = True

    def isEmpty(self):
        return len(self._seriesList) == 0

    def setSetOfTiltSeries(self, tiltSeriesSet):
        self._linkedTiltSeries = tiltSeriesSet


class FakeProtocol:
    # fakeProtocol
    def __init__(self, outputName, output, protocolPath):
        setattr(self, outputName, output)
        self._protocolPath = protocolPath
        self._stored = False
        self._definedOutputs = {}
        self._nextOutputName = "CTFTomoSeries_0"

    def getPath(self):
        return str(self._protocolPath)

    def _getPath(self):
        return str(self._protocolPath)

    def getNextOutputName(self, prefix):
        return self._nextOutputName

    def _defineOutputs(self, **kwargs):
        self._definedOutputs.update(kwargs)

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

    def __init__(self, currentProject, protocol, output=None, requestHeaders=None):
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
        inline,
        quality,
        applyTransform,
        rot,
        shifts,
    ):
        self.lastRenderCall = {
            "filePath": filePath,
            "size": size,
            "fmt": fmt,
            "index": index,
            "inline": inline,
            "quality": quality,
            "applyTransform": applyTransform,
            "rot": rot,
            "shifts": shifts,
        }
        return {
            "rendered": True,
            "filePath": filePath,
        }


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


def test_ListOutputCtftomoSeriesServiceBuildsSummaries(service, tmp_path):
    associatedTs = FakeAssociatedTiltSeries(
        items={
            1: FakeTiltView(acqOrder=1, tiltAngle=-60.0, accumDose=2.5),
            2: FakeTiltView(acqOrder=2, tiltAngle=-58.0, accumDose=3.0),
        },
        dims=[128, 128, 40],
        samplingRate=1.25,
    )
    series1 = FakeCtftomoSeries(
        tsId="TS_001",
        label="Series 1",
        tiltSeries=associatedTs,
        items=[],
    )
    series2 = FakeCtftomoSeries(
        tsId="TS_002",
        label="Series 2",
        tiltSeries=associatedTs,
        items=[],
    )
    output = FakeCtftomoOutputSet(seriesList=[series1, series2], associatedTiltSeriesSet=None)
    protocol = FakeProtocol("outputCtftomo", output, tmp_path)
    service.currentProject = FakeCurrentProject(protocol)

    result = service.listOutputCtftomoSeriesService(
        projectId=1,
        protocolId=10,
        outputName="outputCtftomo",
    )

    assert result == [
        {
            "tiltSeriesId": "TS_001",
            "label": "Series 1",
            "nViews": 2,
            "dims": [128, 128, 40],
            "pixelSize": 1.25,
            "index": 0,
        },
        {
            "tiltSeriesId": "TS_002",
            "label": "Series 2",
            "nViews": 2,
            "dims": [128, 128, 40],
            "pixelSize": 1.25,
            "index": 1,
        },
    ]


def test_GetCtftomoSeriesViewsServiceBuildsFrames(service, tmp_path):
    associatedTs = FakeAssociatedTiltSeries(
        items={
            1: FakeTiltView(acqOrder=1, tiltAngle=-60.0, accumDose=2.5),
            2: FakeTiltView(acqOrder=2, tiltAngle=-58.0, accumDose=3.0),
        },
        dims=[128, 128, 40],
        samplingRate=1.25,
    )
    ctf1 = FakeCtfMeasurement(
        objId=100,
        index=1,
        defocusU=12000.0,
        defocusV=11000.0,
        defocusAngle=45.0,
        resolution=3.2,
        phaseShift=0.15,
        acquisitionOrder=1,
        psdFile="psd1.mrc",
        enabled=True,
    )
    ctf2 = FakeCtfMeasurement(
        objId=101,
        index=2,
        defocusU=13000.0,
        defocusV=12500.0,
        defocusAngle=50.0,
        resolution=3.5,
        phaseShift=0.12,
        acquisitionOrder=2,
        psdFile="psd2.mrc",
        enabled=False,
    )
    series = FakeCtftomoSeries(
        tsId="TS_001",
        label="Series 1",
        tiltSeries=associatedTs,
        items=[ctf1, ctf2],
    )
    output = FakeCtftomoOutputSet(seriesList=[series], associatedTiltSeriesSet=FakeCtftomoOutputSet(seriesList=[]))
    output._associatedTiltSeriesSet = type(
        "TiltSeriesSet",
        (),
        {
            "getItem": lambda self, key, value: associatedTs,
        },
    )()

    protocol = FakeProtocol("outputCtftomo", output, tmp_path)
    service.currentProject = FakeCurrentProject(protocol)

    result = service.getCtftomoSeriesViewsService(
        projectId=1,
        protocolId=10,
        outputName="outputCtftomo",
        tiltSeriesId="TS_001",
    )

    assert result["tiltSeriesId"] == "TS_001"
    assert result["label"] == "Series 1"
    assert result["nViews"] == 2
    assert result["dims"] == [128, 128, 40]
    assert result["pixelSize"] == 1.25
    assert len(result["frames"]) == 2

    frame1 = result["frames"][0]
    assert frame1 == {
        "index": 100,
        "viewIndex": 100,
        "tiltAngle": -60.0,
        "dose": 2.5,
        "defocusU": 12000.0,
        "defocusV": 11000.0,
        "astigmatism": 1000.0,
        "defocusAngle": 45.0,
        "resolution": 3.2,
        "phaseShift": 0.15,
        "order": 1,
        "psdFile": "psd1.mrc",
        "excluded": False,
    }

    frame2 = result["frames"][1]
    assert frame2["index"] == 101
    assert frame2["viewIndex"] == 101
    assert frame2["tiltAngle"] == -58.0
    assert frame2["dose"] == 3.0
    assert frame2["astigmatism"] == 500.0
    assert frame2["excluded"] is True


def test_RenderCtfTomoPsdImageServiceDelegatesToOutputsPreview(projectServiceModule, service, monkeypatch, tmp_path):
    FakeOutputsPreview.instances = []

    psdFile = tmp_path / "psd_001.mrc"
    psdFile.write_text("placeholder", encoding="utf-8")

    output = FakeCtftomoOutputSet(seriesList=[], associatedTiltSeriesSet=None)
    protocol = FakeProtocol("outputCtftomo", output, tmp_path)
    service.currentProject = FakeCurrentProject(protocol)

    monkeypatch.setattr(projectServiceModule, "OutputsPreview", FakeOutputsPreview)

    result = service.renderCtfTomoPsdImageService(
        projectId=1,
        protocolId=10,
        outputName="outputCtftomo",
        psdPath="3@" + psdFile.name,
        size=512,
        fmt="png",
        inline=False,
        quality=80,
        applyTransform=True,
        rot=12.0,
        shifts=(4.0, -1.0),
    )

    assert result == {
        "rendered": True,
        "filePath": str(psdFile.resolve()),
    }
    assert len(FakeOutputsPreview.instances) == 1
    assert FakeOutputsPreview.instances[0].lastRenderCall == {
        "filePath": str(psdFile.resolve()),
        "size": 512,
        "fmt": "png",
        "index": 3,
        "inline": False,
        "quality": 80,
        "applyTransform": True,
        "rot": 12.0,
        "shifts": (4.0, -1.0),
    }


def test_CreateNewSetOfCtftomoSeriesServiceReturnsEmptyWhenEverythingExcluded(service, tmp_path):
    associatedTs = FakeAssociatedTiltSeries()
    series1 = FakeCtftomoSeries(
        tsId="TS_001",
        label="Series 1",
        tiltSeries=associatedTs,
        items=[],
    )
    inputSet = FakeCtftomoOutputSet(seriesList=[series1], associatedTiltSeriesSet=associatedTs)
    protocol = FakeProtocol("outputCtftomo", inputSet, tmp_path)
    service.currentProject = FakeCurrentProject(protocol)

    result = service.createNewSetOfCtftomoSeriesService(
        projectId=1,
        protocolId=10,
        outputName="outputCtftomo",
        exclusions={
            "TS_001": {
                "excluded": True,
                "tiltimages": [],
            }
        },
        restack=False,
    )

    assert result == {
        "status": "empty",
        "outputName": "CTFTomoSeries_0",
        "createdSeries": 0,
        "restack": False,
        "message": "No output was generated because it cannot be empty",
    }


def test_CreateNewSetOfCtftomoSeriesServiceCreatesFilteredSeries(service, tmp_path):
    associatedTs = FakeAssociatedTiltSeries()
    ctf1 = FakeCtfMeasurement(
        objId=100,
        index=1,
        defocusU=12000.0,
        defocusV=11000.0,
        defocusAngle=45.0,
        resolution=3.2,
        phaseShift=0.15,
        acquisitionOrder=1,
        psdFile="psd1.mrc",
        enabled=True,
    )
    ctf2 = FakeCtfMeasurement(
        objId=101,
        index=2,
        defocusU=13000.0,
        defocusV=12500.0,
        defocusAngle=50.0,
        resolution=3.5,
        phaseShift=0.12,
        acquisitionOrder=2,
        psdFile="psd2.mrc",
        enabled=True,
    )
    inputSeries = FakeCtftomoSeries(
        tsId="TS_001",
        label="Series 1",
        tiltSeries=associatedTs,
        items=[ctf1, ctf2],
    )
    inputSet = FakeCtftomoOutputSet(seriesList=[inputSeries], associatedTiltSeriesSet=associatedTs)
    protocol = FakeProtocol("outputCtftomo", inputSet, tmp_path)
    service.currentProject = FakeCurrentProject(protocol)

    result = service.createNewSetOfCtftomoSeriesService(
        projectId=1,
        protocolId=10,
        outputName="outputCtftomo",
        exclusions={
            "TS_001": {
                "excluded": False,
                "tiltimages": [2],
            }
        },
        restack=False,
    )

    assert result == {
        "status": 0,
        "outputName": "CTFTomoSeries_0",
        "createdSeries": 1,
        "restack": False,
    }
    assert "CTFTomoSeries_0" in protocol._definedOutputs
    createdSet = protocol._definedOutputs["CTFTomoSeries_0"]
    assert createdSet.isEmpty() is False
    createdSeries = createdSet._seriesList[0]
    assert len(createdSeries._items) == 2
    assert createdSeries._items[0]._enabled is True
    assert createdSeries._items[1]._enabled is False
    assert protocol._stored is True