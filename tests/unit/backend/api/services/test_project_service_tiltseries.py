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


def test_ResolveOutputForTiltSeriesBuildsReadOnlyPostgresqlProxy(
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
        "outputName": "TiltSeries",
        "className": "SetOfTiltSeries",
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

    monkeypatch.setattr(
        service,
        "_getScipionProtocolForRuntime",
        getScipionProtocolForRuntime,
    )
    monkeypatch.setattr(
        service,
        "_resolvePostgresqlReaderProtocolId",
        lambda **kwargs: 321,
    )
    monkeypatch.setattr(
        service,
        "_getPostgresqlRuntimeOutputInfo",
        getPostgresqlRuntimeOutputInfo,
    )
    monkeypatch.setattr(
        projectServiceModule,
        "RuntimeOutputProxyService",
        FakeRuntimeOutputProxyService,
    )

    protocol, output = service._resolveOutputForTiltSeries(
        protocolId=5,
        outputName="TiltSeries",
        projectId=344,
        mapper=mapper,
    )

    assert protocol is parentProtocol
    assert output is proxyOutput
    assert protocolCalls == [
        {
            "mapper": mapper,
            "projectId": 344,
            "protocolId": 5,
        }
    ]
    assert outputInfoCalls == [
        {
            "mapper": mapper,
            "projectId": 344,
            "parentProtocolDbId": 321,
            "outputName": "TiltSeries",
        }
    ]
    assert proxyCalls == [
        {
            "parentProtocol": parentProtocol,
            "outputName": "TiltSeries",
            "outputInfo": outputInfo,
            "mapper": runtimeMapper,
        }
    ]
    assert not hasattr(parentProtocol, "TiltSeries")


def test_GetGeneratedSetOutputIdentityUsesPostgresqlOutputs(
    service,
    projectServiceModule,
    monkeypatch,
):
    class FakeMapper:
        pass

    class FakeProtocolIdentityResolver:
        def __init__(self, mapper, projectId):
            self.mapper = mapper
            self.projectId = projectId

        def resolvePostgresqlProtocolDbId(self, protocolId):
            assert protocolId == 5
            return 321

    class FakeOutputPersistenceService:
        def loadPersistedProtocolOutputNames(
                self,
                mapper,
                projectId,
                protocolDbId,
        ):
            assert projectId == 344
            assert protocolDbId == 321

            return {
                "TiltSeries",
                "TiltSeries_2",
                "outputCoordinates",
            }

    monkeypatch.setattr(
        projectServiceModule,
        "ProtocolIdentityResolver",
        FakeProtocolIdentityResolver,
    )
    monkeypatch.setattr(
        projectServiceModule,
        "RuntimeProtocolOutputPersistenceService",
        FakeOutputPersistenceService,
    )

    result = service._getGeneratedSetOutputIdentity(
        mapper=FakeMapper(),
        projectId=344,
        protocolId=5,
        protocol=object(),
        outputPrefix="TiltSeries_",
    )

    assert result == {
        "outputName": "TiltSeries_3",
        "outputSuffix": "3",
        "protocolDbId": 321,
    }


def test_CreateWritableGeneratedPostgresqlSetReservesOutputWithoutSqlite(
    projectServiceModule,
    service,
    monkeypatch,
):
    db = object()
    protocol = object()
    resolverCalls = []
    reserveCalls = []
    buildCalls = []
    setMapperInstances = []
    runtimeFactoryInstances = []

    class FakeNativeSet:
        @classmethod
        def create(cls, *args, **kwargs):
            raise AssertionError(
                "Generated PostgreSQL Sets must not call native create()"
            )

        def __init__(self):
            self.copiedFrom = None
            self.objId = None
            self.name = None
            self.label = None

        def copyInfo(self, sourceSet):
            self.copiedFrom = sourceSet

        def setObjId(self, value):
            self.objId = value

        def setName(self, value):
            self.name = value

        def setObjLabel(self, value):
            self.label = value

    class FakeSourceSet:
        def getClass(self):
            return FakeNativeSet

        def createCopy(self, *args, **kwargs):
            raise AssertionError(
                "Generated PostgreSQL Sets must not call createCopy()"
            )

    class FakeMapper:
        def __init__(self):
            self.db = db
            self.allocateCalls = []

        def allocateProjectObjectId(self, projectId):
            self.allocateCalls.append(projectId)
            return 1000026

    class FakeProtocolIdentityResolver:
        def __init__(self, mapper, projectId):
            resolverCalls.append({
                "mapper": mapper,
                "projectId": projectId,
            })

        def resolvePostgresqlProtocolDbId(self, protocolId):
            assert protocolId == 5
            return 321

    class FakeScipionSetPostgresqlMapper:
        def __init__(self, receivedDb):
            assert receivedDb is db
            setMapperInstances.append(self)

        def reserveRuntimeSet(
            self,
            projectId,
            protocolDbId,
            outputName,
            scipionSet,
            reservationToken,
        ):
            reserveCalls.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "outputName": outputName,
                "scipionSet": scipionSet,
                "reservationToken": reservationToken,
            })
            return {
                "setId": 77,
                "rootTableId": 78,
                "objectId": 79,
                "runtimeObjectId": 1000026,
                "className": "FakeNativeSet",
                "setClassName": "FakeNativeSet",
                "itemClassName": "FakeItem",
            }

        def discardReservedRuntimeSet(self, **kwargs):
            raise AssertionError(
                "A successful reservation must not be discarded"
            )

    class FakeWritableRuntimeSet:
        def __init__(self):
            self.postgresqlWriteEnabled = False

        def enablePostgresqlWrite(self):
            self.postgresqlWriteEnabled = True

    runtimeOutput = FakeWritableRuntimeSet()

    class FakePostgresqlRuntimeSetFactory:
        def __init__(self):
            runtimeFactoryInstances.append(self)

        def build(
            self,
            db,
            parent,
            outputName,
            outputInfo,
        ):
            buildCalls.append({
                "db": db,
                "parent": parent,
                "outputName": outputName,
                "outputInfo": outputInfo,
            })
            return runtimeOutput

    setMapperModule = importlib.import_module(
        "app.backend.mapper.scipion_set_mapper"
    )
    runtimeSetFactoryModule = importlib.import_module(
        "app.backend.runtime.postgresql_runtime_set_factory"
    )

    monkeypatch.setattr(
        projectServiceModule,
        "ProtocolIdentityResolver",
        FakeProtocolIdentityResolver,
    )
    monkeypatch.setattr(
        setMapperModule,
        "ScipionSetPostgresqlMapper",
        FakeScipionSetPostgresqlMapper,
    )
    monkeypatch.setattr(
        runtimeSetFactoryModule,
        "PostgresqlRuntimeSetFactory",
        FakePostgresqlRuntimeSetFactory,
    )

    mapper = FakeMapper()
    sourceSet = FakeSourceSet()

    context = service._createWritableGeneratedPostgresqlSet(
        mapper=mapper,
        projectId=344,
        protocolId=5,
        protocol=protocol,
        outputName="TiltSeries_0",
        sourceSet=sourceSet,
    )

    assert resolverCalls == [
        {
            "mapper": mapper,
            "projectId": 344,
        }
    ]
    assert mapper.allocateCalls == [344]
    assert len(reserveCalls) == 1

    reserveCall = reserveCalls[0]
    reservationToken = reserveCall["reservationToken"]
    seedSet = reserveCall["scipionSet"]

    assert isinstance(reservationToken, str)
    assert reservationToken
    assert {
        key: value
        for key, value in reserveCall.items()
        if key not in {
            "scipionSet",
            "reservationToken",
        }
    } == {
        "projectId": 344,
        "protocolDbId": 321,
        "outputName": "TiltSeries_0",
    }
    assert type(seedSet) is FakeNativeSet
    assert seedSet.copiedFrom is sourceSet
    assert seedSet.objId == 1000026
    assert seedSet.name == "TiltSeries_0"
    assert seedSet.label == "TiltSeries_0"

    assert buildCalls == [
        {
            "db": db,
            "parent": protocol,
            "outputName": "TiltSeries_0",
            "outputInfo": {
                "setId": 77,
                "rootTableId": 78,
                "objectId": 79,
                "runtimeObjectId": 1000026,
                "className": "FakeNativeSet",
                "setClassName": "FakeNativeSet",
                "itemClassName": "FakeItem",
                "exists": True,
                "itemsCount": 0,
            },
        }
    ]
    assert runtimeOutput.postgresqlWriteEnabled is True
    assert context["outputSet"] is runtimeOutput
    assert context["setMapper"] is setMapperInstances[0]
    assert context["runtimeSetFactory"] is runtimeFactoryInstances[0]
    assert context["protocolDbId"] == 321
    assert context["runtimeObjectId"] == 1000026


def test_GetPostgresqlTiltSeriesReaderIfAvailableUsesResolvedProtocolDbId(
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

    class FakePostgresqlTiltSeriesReader:
        # fakePostgresqlTiltSeriesReader
        def __init__(self, db, projectId, protocolId, outputName):
            self.db = db
            self.projectId = projectId
            self.protocolId = protocolId
            self.outputName = outputName
            createdReaders.append(self)

        def hasOutput(self):
            return True

    readerModule = importlib.import_module(
        "app.backend.viewers.postgresql_tiltseries_reader"
    )

    monkeypatch.setattr(
        readerModule,
        "PostgresqlTiltSeriesReader",
        FakePostgresqlTiltSeriesReader,
    )
    monkeypatch.setattr(
        service,
        "_resolvePostgresqlProtocolDbId",
        lambda mapper, projectId, protocolId: 321,
    )

    mapper = FakeMapper()

    reader = service._getPostgresqlTiltSeriesReaderIfAvailable(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        outputName="outputTiltSeries",
    )

    assert reader is createdReaders[0]
    assert createdReaders[0].db is mapper.db
    assert createdReaders[0].projectId == 1
    assert createdReaders[0].protocolId == 321
    assert createdReaders[0].outputName == "outputTiltSeries"

def test_ListOutputTiltSeriesServiceRequiresPostgresqlWhenMapperIsPresent(
    service,
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "_getPostgresqlTiltSeriesReaderIfAvailable",
        lambda **kwargs: None,
    )

    def failRuntimeFallback(**kwargs):
        raise AssertionError("Legacy TiltSeries fallback should not be used")

    monkeypatch.setattr(service, "_resolveOutputForTiltSeries", failRuntimeFallback)

    with pytest.raises(Exception) as exc:
        service.listOutputTiltSeriesService(
            projectId=1,
            protocolId=10,
            outputName="outputTiltSeries",
            mapper=object(),
        )

    assert exc.value.status_code == 404
    assert "TiltSeries output is not available in PostgreSQL metadata" in exc.value.detail
    assert "reader_not_available" in exc.value.detail


def test_GetTiltSeriesFramesServiceRequiresPostgresqlWhenMapperIsPresent(
    service,
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "_getPostgresqlTiltSeriesReaderIfAvailable",
        lambda **kwargs: None,
    )

    def failRuntimeFallback(**kwargs):
        raise AssertionError("Legacy TiltSeries fallback should not be used")

    monkeypatch.setattr(service, "_resolveOutputForTiltSeries", failRuntimeFallback)

    with pytest.raises(Exception) as exc:
        service.getTiltSeriesFramesService(
            projectId=1,
            protocolId=10,
            outputName="outputTiltSeries",
            tiltSeriesId="TS_001",
            mapper=object(),
        )

    assert exc.value.status_code == 404
    assert "TiltSeries frames output is not available in PostgreSQL metadata" in exc.value.detail
    assert "reader_not_available" in exc.value.detail


def test_RenderTiltSeriesImageServiceRequiresPostgresqlWhenMapperIsPresent(
    service,
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "_getPostgresqlTiltSeriesReaderIfAvailable",
        lambda **kwargs: None,
    )

    def failRuntimeFallback(**kwargs):
        raise AssertionError("Legacy TiltSeries image fallback should not be used")

    monkeypatch.setattr(service, "_resolveOutputForTiltSeries", failRuntimeFallback)

    with pytest.raises(Exception) as exc:
        service.renderTiltSeriesImageService(
            projectId=1,
            protocolId=10,
            outputName="outputTiltSeries",
            tiltSeriesId="TS_001",
            index=0,
            size=512,
            fmt="png",
            applyTransform=True,
            inline=True,
            mapper=object(),
        )

    assert exc.value.status_code == 404
    assert "TiltSeries image output is not available in PostgreSQL metadata" in exc.value.detail
    assert "reader_not_available" in exc.value.detail


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


def test_RenderTiltSeriesImageServiceResolvesProjectRelativePostgresqlFramePath(
    projectServiceModule,
    service,
    monkeypatch,
    tmp_path,
):
    FakeOutputsPreview.instances = []

    projectPath = tmp_path / "project"
    framePath = (
        projectPath
        / "Runs"
        / "000084_ProtWarpTSMotionCorr"
        / "extra"
        / "warp_frameseries"
        / "average"
        / "TS_1.mrcs"
    )
    framePath.parent.mkdir(parents=True)
    framePath.write_bytes(b"fake")

    class FakeDb:
        def fetchOne(self, query, params):
            if "FROM projects" in query:
                return {"name": str(projectPath)}
            return None

    class FakeMapper:
        def __init__(self):
            self.db = FakeDb()

    class FakePostgresqlTiltSeriesReader:
        lastSkipReason = None

        def getTiltImageFrame(self, tiltSeriesId, index):
            return {
                "index": int(index),
                "path": (
                    f"{index}@"
                    "Runs/000084_ProtWarpTSMotionCorr/extra/"
                    "warp_frameseries/average/TS_1.mrcs"
                ),
                "rot": 12.0,
                "shiftX": 1.5,
                "shiftY": -2.5,
            }

    mapper = FakeMapper()

    monkeypatch.setattr(projectServiceModule, "OutputsPreview", FakeOutputsPreview)
    monkeypatch.setattr(
        service,
        "_getPostgresqlTiltSeriesReaderIfAvailable",
        lambda **kwargs: FakePostgresqlTiltSeriesReader(),
    )

    result = service.renderTiltSeriesImageService(
        projectId=246,
        protocolId=180,
        outputName="TiltSeries",
        tiltSeriesId="TS_1",
        index=1,
        size=512,
        fmt="png",
        applyTransform=True,
        inline=True,
        mapper=mapper,
    )

    assert result == {
        "rendered": True,
        "filePath": str(framePath.resolve()),
    }

    assert FakeOutputsPreview.instances[0].lastRenderCall["filePath"] == str(framePath.resolve())
    assert FakeOutputsPreview.instances[0].lastRenderCall["index"] == 1
    assert FakeOutputsPreview.instances[0].lastRenderCall["rot"] == 12.0
    assert FakeOutputsPreview.instances[0].lastRenderCall["shifts"] == (1.5, -2.5)


def test_CreateNewSetOfTiltSeriesServiceReturnsEmptyWhenNoSeriesCreated(
    service,
    monkeypatch,
):
    createdOutputSet = FakeCreatedTiltSeriesOutputSet()
    inputSet = FakeTiltSeriesSet(
        items=[],
        hasOddEven=False,
        dims=[128, 128, 40],
    )
    protocol = FakeProtocol(
        "outputTiltSeries",
        inputSet,
    )
    service.currentProject = FakeCurrentProject(protocol)

    mapper = object()
    generatedContext = {
        "outputSet": createdOutputSet,
        "protocolDbId": 321,
    }
    createCalls = []
    discardCalls = []

    monkeypatch.setattr(
        service,
        "_resolveOutputForTiltSeries",
        lambda **kwargs: (protocol, inputSet),
    )
    monkeypatch.setattr(
        service,
        "_getGeneratedSetOutputIdentity",
        lambda **kwargs: {
            "outputName": "TiltSeries_0",
            "outputSuffix": "0",
            "protocolDbId": 321,
        },
    )

    def createWritableGeneratedPostgresqlSet(**kwargs):
        createCalls.append(kwargs)
        return generatedContext

    def discardGeneratedPostgresqlSet(**kwargs):
        discardCalls.append(kwargs)
        return True

    def failFinalize(**kwargs):
        raise AssertionError(
            "An empty generated Set must not be finalized"
        )

    monkeypatch.setattr(
        service,
        "_createWritableGeneratedPostgresqlSet",
        createWritableGeneratedPostgresqlSet,
    )
    monkeypatch.setattr(
        service,
        "_discardGeneratedPostgresqlSet",
        discardGeneratedPostgresqlSet,
    )
    monkeypatch.setattr(
        service,
        "_finalizeGeneratedPostgresqlSet",
        failFinalize,
    )

    result = service.createNewSetOfTiltSeriesService(
        projectId=1,
        protocolId=10,
        outputName="outputTiltSeries",
        exclusions={},
        restack=False,
        mapper=mapper,
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
    assert createdOutputSet._dim == [128, 128, 40]
    assert createCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 10,
            "protocol": protocol,
            "outputName": "TiltSeries_0",
            "sourceSet": inputSet,
        }
    ]
    assert discardCalls == [
        {
            "context": generatedContext,
            "projectId": 1,
        }
    ]


def test_CreateNewSetOfTiltSeriesServiceFinalizesGeneratedPostgresqlSet(
    projectServiceModule,
    service,
    monkeypatch,
):
    class FakeCreatedTiltSeries:
        def __init__(self):
            self._items = []
            self._dim = None
            self._anglesCount = None
            self._copiedInfoFrom = None
            self._enabled = True

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
    protocol = FakeProtocol(
        "outputTiltSeries",
        inputSet,
    )
    service.currentProject = FakeCurrentProject(protocol)

    mapper = object()
    generatedContext = {
        "outputSet": createdOutputSet,
        "protocolDbId": 321,
    }
    finalSync = {
        "stored": True,
        "protocolDbId": 321,
        "outputName": "TiltSeries_0",
    }
    createCalls = []
    finalizeCalls = []

    monkeypatch.setattr(
        projectServiceModule,
        "TiltSeries",
        FakeCreatedTiltSeries,
    )
    monkeypatch.setattr(
        service,
        "_resolveOutputForTiltSeries",
        lambda **kwargs: (protocol, inputSet),
    )
    monkeypatch.setattr(
        service,
        "_getGeneratedSetOutputIdentity",
        lambda **kwargs: {
            "outputName": "TiltSeries_0",
            "outputSuffix": "0",
            "protocolDbId": 321,
        },
    )

    def createWritableGeneratedPostgresqlSet(**kwargs):
        createCalls.append(kwargs)
        return generatedContext

    def finalizeGeneratedPostgresqlSet(**kwargs):
        finalizeCalls.append(kwargs)
        return finalSync

    def failDiscard(**kwargs):
        raise AssertionError(
            "A successful generated Set must not be discarded"
        )

    monkeypatch.setattr(
        service,
        "_createWritableGeneratedPostgresqlSet",
        createWritableGeneratedPostgresqlSet,
    )
    monkeypatch.setattr(
        service,
        "_finalizeGeneratedPostgresqlSet",
        finalizeGeneratedPostgresqlSet,
    )
    monkeypatch.setattr(
        service,
        "_discardGeneratedPostgresqlSet",
        failDiscard,
    )

    result = service.createNewSetOfTiltSeriesService(
        projectId=1,
        protocolId=10,
        outputName="outputTiltSeries",
        exclusions={},
        restack=False,
        mapper=mapper,
    )

    assert result == {
        "status": 0,
        "outputName": "TiltSeries_0",
        "createdTiltSeries": 1,
        "hasOddEven": False,
        "restack": False,
        "postgresqlSync": finalSync,
        "postgresqlError": None,
    }
    assert createCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 10,
            "protocol": protocol,
            "outputName": "TiltSeries_0",
            "sourceSet": inputSet,
        }
    ]
    assert finalizeCalls == [
        {
            "context": generatedContext,
            "projectId": 1,
            "outputName": "TiltSeries_0",
        }
    ]
    assert protocol._definedOutputs == {
        "TiltSeries_0": createdOutputSet,
    }
    assert protocol._stored is True
    assert createdOutputSet._dim == [128, 128, 40]
    assert createdOutputSet.getSize() == 1

    createdTiltSeries = createdOutputSet._items[0]

    assert createdTiltSeries._copiedInfoFrom is tiltSeries
    assert createdTiltSeries._dim == [128, 128, 40]
    assert createdTiltSeries._anglesCount == 0


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