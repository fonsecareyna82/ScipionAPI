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
from fastapi import HTTPException


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


def test_GetCtftomoSeriesViewsServiceRequiresPostgresqlWhenMapperIsPresent(
    service,
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "_getPostgresqlCtftomoReaderIfAvailable",
        lambda **kwargs: None,
    )

    def failRuntimeFallback(**kwargs):
        raise AssertionError("Legacy CTFTomo views fallback should not be used")

    monkeypatch.setattr(service, "_resolveOutputForCtftomoSeries", failRuntimeFallback)

    with pytest.raises(Exception) as exc:
        service.getCtftomoSeriesViewsService(
            projectId=1,
            protocolId=10,
            outputName="outputCtftomo",
            tiltSeriesId="TS_001",
            mapper=object(),
        )

    assert exc.value.status_code == 404
    assert "CTFTomo views output is not available in PostgreSQL metadata" in exc.value.detail
    assert "reader_not_available" in exc.value.detail


def test_ListOutputCtftomoSeriesServiceRequiresPostgresqlWhenMapperIsPresent(
    service,
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "_getPostgresqlCtftomoReaderIfAvailable",
        lambda **kwargs: None,
    )

    def failRuntimeFallback(**kwargs):
        raise AssertionError("Legacy CTFTomo fallback should not be used")

    monkeypatch.setattr(service, "_resolveOutputForCtftomoSeries", failRuntimeFallback)

    with pytest.raises(Exception) as exc:
        service.listOutputCtftomoSeriesService(
            projectId=1,
            protocolId=10,
            outputName="outputCtftomo",
            mapper=object(),
        )

    assert exc.value.status_code == 404
    assert "CTFTomo output is not available in PostgreSQL metadata" in exc.value.detail
    assert "reader_not_available" in exc.value.detail


def test_RenderCtfTomoPsdImageServiceRequiresPostgresqlPathWhenMapperIsPresent(
    service,
    monkeypatch,
):
    def failRuntimeFallback(**kwargs):
        raise AssertionError("Legacy CTFTomo PSD fallback should not be used")

    monkeypatch.setattr(service, "_resolveOutputForCtftomoSeries", failRuntimeFallback)

    with pytest.raises(Exception) as exc:
        service.renderCtfTomoPsdImageService(
            projectId=1,
            protocolId=10,
            outputName="outputCtftomo",
            psdPath="relative/psd.mrc",
            size=512,
            fmt="png",
            inline=True,
            index=0,
            mapper=object(),
        )

    assert exc.value.status_code == 404
    assert "CTFTomo PSD output is not available in PostgreSQL metadata" in exc.value.detail
    assert "psd_file_not_available" in exc.value.detail


def test_GetPostgresqlCtftomoReaderIfAvailableUsesResolvedProtocolDbId(
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

    class FakePostgresqlCtftomoReader:
        # fakePostgresqlCtftomoReader
        def __init__(self, db, projectId, protocolId, outputName):
            self.db = db
            self.projectId = projectId
            self.protocolId = protocolId
            self.outputName = outputName
            createdReaders.append(self)

        def hasOutput(self):
            return True

    readerModule = importlib.import_module(
        "app.backend.viewers.postgresql_ctftomo_reader"
    )

    monkeypatch.setattr(
        readerModule,
        "PostgresqlCtftomoReader",
        FakePostgresqlCtftomoReader,
    )
    monkeypatch.setattr(
        service,
        "_resolvePostgresqlProtocolDbId",
        lambda mapper, projectId, protocolId: 654,
    )

    mapper = FakeMapper()

    reader = service._getPostgresqlCtftomoReaderIfAvailable(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        outputName="outputCtftomo",
    )

    assert reader is createdReaders[0]
    assert createdReaders[0].db is mapper.db
    assert createdReaders[0].projectId == 1
    assert createdReaders[0].protocolId == 654
    assert createdReaders[0].outputName == "outputCtftomo"


def test_ResolveOutputForCtftomoSeriesBuildsReadOnlyPostgresqlProxy(
    service,
    projectServiceModule,
    monkeypatch,
):
    parentProtocol = object()
    proxyOutput = object()
    runtimeMapper = object()
    outputInfo = {
        "exists": True,
        "setId": 77,
        "runtimeObjectId": 9001,
        "outputName": "CTFTomoSeries",
        "className": "SetOfCTFTomoSeries",
    }

    class FakeRuntimeProject:
        pass

    service.currentProject = FakeRuntimeProject()
    service.currentProject.mapper = runtimeMapper

    protocolCalls = []
    outputInfoCalls = []
    proxyCalls = []

    def getScipionProtocolForRuntime(**kwargs):
        protocolCalls.append(kwargs)
        return parentProtocol

    def getPostgresqlRuntimeOutputInfo(**kwargs):
        outputInfoCalls.append(kwargs)
        return outputInfo

    class FakeRuntimeOutputProxyService:
        def attachPostgresqlRuntimeOutputProxy(
                self,
                parentProtocol,
                outputName,
                outputInfo,
                mapper=None,
        ):
            proxyCalls.append({
                "parentProtocol": parentProtocol,
                "outputName": outputName,
                "outputInfo": outputInfo,
                "mapper": mapper,
            })
            return proxyOutput

    mapper = object()

    monkeypatch.setattr(service, "_getScipionProtocolForRuntime", getScipionProtocolForRuntime)
    monkeypatch.setattr(service, "_resolvePostgresqlReaderProtocolId", lambda **kwargs: 654)
    monkeypatch.setattr(service, "_getPostgresqlRuntimeOutputInfo", getPostgresqlRuntimeOutputInfo)
    monkeypatch.setattr(projectServiceModule, "RuntimeOutputProxyService", FakeRuntimeOutputProxyService)

    protocol, output = service._resolveOutputForCtftomoSeries(
        protocolId=3,
        outputName="CTFTomoSeries",
        projectId=344,
        mapper=mapper,
    )

    assert protocol is parentProtocol
    assert output is proxyOutput
    assert protocolCalls == [
        {
            "mapper": mapper,
            "projectId": 344,
            "protocolId": 3,
        }
    ]
    assert outputInfoCalls == [
        {
            "mapper": mapper,
            "projectId": 344,
            "parentProtocolDbId": 654,
            "outputName": "CTFTomoSeries",
        }
    ]
    assert proxyCalls == [
        {
            "parentProtocol": parentProtocol,
            "outputName": "CTFTomoSeries",
            "outputInfo": outputInfo,
            "mapper": runtimeMapper,
        }
    ]
    assert not hasattr(parentProtocol, "CTFTomoSeries")


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


def test_CreateNewSetOfCtftomoSeriesServiceStoresSetWithResolvedProtocolDbId(
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

    scipionSetMapperModule = importlib.import_module(
        "app.backend.mapper.scipion_set_mapper"
    )
    monkeypatch.setattr(
        scipionSetMapperModule,
        "ScipionSetPostgresqlMapper",
        FakeScipionSetPostgresqlMapper,
    )
    outputPersistenceServiceModule = (
        importlib.import_module(
            "app.backend.runtime."
            "protocol_output_persistence_service"
        )
    )

    monkeypatch.setattr(
        outputPersistenceServiceModule
        .ProtocolIdentityResolver,
        "resolvePostgresqlProtocolDbId",
        lambda self, protocolId: 654,
    )

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
    inputSeries = FakeCtftomoSeries(
        tsId="TS_001",
        label="Series 1",
        tiltSeries=associatedTs,
        items=[ctf1],
    )
    inputSet = FakeCtftomoOutputSet(
        seriesList=[inputSeries],
        associatedTiltSeriesSet=associatedTs,
    )
    protocol = FakeProtocol("outputCtftomo", inputSet, "/tmp/fake-protocol")
    service.currentProject = FakeCurrentProject(protocol)

    mapper = FakeMapper()
    outputIdentityCalls = []

    def getGeneratedSetOutputIdentity(**kwargs):
        outputIdentityCalls.append(kwargs)
        return {
            "outputName": "CTFTomoSeries2",
            "outputSuffix": "1",
            "protocolDbId": 654,
        }

    monkeypatch.setattr(
        service,
        "_resolveOutputForCtftomoSeries",
        lambda **kwargs: (protocol, inputSet),
    )
    monkeypatch.setattr(
        service,
        "_getGeneratedSetOutputIdentity",
        getGeneratedSetOutputIdentity,
    )

    result = service.createNewSetOfCtftomoSeriesService(
        projectId=1,
        protocolId=10,
        outputName="outputCtftomo",
        exclusions={
            "TS_001": {
                "excluded": False,
                "tiltimages": [],
            }
        },
        restack=False,
        mapper=mapper,
    )

    assert result["status"] == 0
    assert result["outputName"] == "CTFTomoSeries2"
    assert result["postgresqlSync"] == {
        "stored": True,
        "protocolDbId": 654,
        "outputName": "CTFTomoSeries2",
    }
    assert result["postgresqlError"] is None
    assert outputIdentityCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 10,
            "protocol": protocol,
            "outputPrefix": "CTFTomoSeries",
        }
    ]
    assert storedCalls == [
        {
            "projectId": 1,
            "protocolDbId": 654,
            "outputName": "CTFTomoSeries_0",
            "scipionSet": protocol._definedOutputs["CTFTomoSeries2"],
        }
    ]


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

    assert result["status"] == 0
    assert result["outputName"] == "CTFTomoSeries_0"
    assert result["createdSeries"] == 1
    assert result["restack"] is False
    assert result["postgresqlSync"] is None
    assert result["postgresqlError"] is None
    assert "CTFTomoSeries_0" in protocol._definedOutputs
    createdSet = protocol._definedOutputs["CTFTomoSeries_0"]
    assert createdSet.isEmpty() is False
    createdSeries = createdSet._seriesList[0]
    assert len(createdSeries._items) == 2
    assert createdSeries._items[0]._enabled is True
    assert createdSeries._items[1]._enabled is False
    assert protocol._stored is True


@pytest.fixture
def projectServiceModule(authTestEnv):
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule):
    return object.__new__(projectServiceModule.ProjectService)


def test_GetCtftomoSeriesViewsServiceRaisesPostgresqlUnavailableWithReaderReason(
    service,
    monkeypatch,
):
    class FakePgReader:
        lastSkipReason = "ctftomo_series_item_not_found tiltSeriesId=TS_999"

        def getCtftomoSeriesViews(self, tiltSeriesId):
            assert tiltSeriesId == "TS_999"
            return None

    monkeypatch.setattr(
        service,
        "_getPostgresqlCtftomoReaderIfAvailable",
        lambda **kwargs: FakePgReader(),
    )

    def failRuntimeFallback(**kwargs):
        raise AssertionError("runtime fallback should not be used when mapper is present")

    monkeypatch.setattr(service, "_resolveOutputForCtftomoSeries", failRuntimeFallback)

    with pytest.raises(HTTPException) as exc:
        service.getCtftomoSeriesViewsService(
            projectId=1,
            protocolId=10,
            outputName="outputCTF",
            tiltSeriesId="TS_999",
            mapper=object(),
        )

    assert exc.value.status_code == 404
    assert "ctftomo_series_item_not_found" in str(exc.value.detail)
    assert "TS_999" in str(exc.value.detail)