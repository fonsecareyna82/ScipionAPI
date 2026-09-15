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


class FakeVolumeOutput:
    # fakeVolumeOutput
    def __init__(self, fileName):
        self._fileName = fileName

    def getFileName(self):
        return self._fileName


class FakeSetOfVolumes:
    # fakeSetOfVolumes
    def __init__(self, items):
        self.items = items
        self.lastGetItemCall = None

    def getItem(self, key, value):
        self.lastGetItemCall = {
            "key": key,
            "value": value,
        }
        return self.items.get(value)


class FakeProtocol:
    # fakeProtocol
    def __init__(self, **outputs):
        for key, value in outputs.items():
            setattr(self, key, value)


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(self, protocol=None, protocolError=None):
        self.protocol = protocol
        self.protocolError = protocolError

    def getProtocol(self, protocolId):
        if self.protocolError is not None:
            raise self.protocolError
        return self.protocol


class FakeOutputsPreview:
    # fakeOutputsPreview
    instances = []

    def __init__(self, currentProject, protocol, output):
        self.currentProject = currentProject
        self.protocol = protocol
        self.output = output
        self.listOutputVolumesResult = [
            {"id": 0, "name": "vol-0"},
            {"id": 1, "name": "vol-1"},
        ]
        self.getVolumeInfoResult = {
            "id": 3,
            "dims": [16, 16, 16],
            "samplingRate": 1.5,
        }
        self.getVolumeHistogramResult = {
            "bin_edges": [0.0, 1.0, 2.0],
            "values": [10, 20],
        }
        self.renderVolumeSliceResult = {
            "rendered": True,
        }
        self.lastGetVolumeInfoCall = None
        self.lastGetVolumeHistogramCall = None
        self.lastRenderVolumeSliceCall = None
        FakeOutputsPreview.instances.append(self)

    def listOutputVolumes(self):
        return self.listOutputVolumesResult

    def getVolumeInfo(self, volumeId):
        self.lastGetVolumeInfoCall = {
            "volumeId": volumeId,
        }
        return self.getVolumeInfoResult

    def getVolumeHistogram(self, volumePath, bins):
        self.lastGetVolumeHistogramCall = {
            "volumePath": volumePath,
            "bins": bins,
        }
        return self.getVolumeHistogramResult

    def renderVolumeSlice(
        self,
        volumeId,
        sliceIndex,
        axis,
        colormap,
        normalize,
        windowMin,
        windowMax,
        scale,
        inline,
        fmt,
        thumb,
        fast,
        quality,
    ):
        self.lastRenderVolumeSliceCall = {
            "volumeId": volumeId,
            "sliceIndex": sliceIndex,
            "axis": axis,
            "colormap": colormap,
            "normalize": normalize,
            "windowMin": windowMin,
            "windowMax": windowMax,
            "scale": scale,
            "inline": inline,
            "fmt": fmt,
            "thumb": thumb,
            "fast": fast,
            "quality": quality,
        }
        return self.renderVolumeSliceResult


@pytest.fixture
def projectServiceModule(authTestEnv):
    # projectServiceModule
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule):
    # service
    instance = object.__new__(projectServiceModule.ProjectService)
    instance.currentProject = FakeCurrentProject()
    instance.tomoList = {}
    return instance


def test_ResolveOutputForVolumesReturnsExactOutput(service):
    volume = FakeVolumeOutput("/tmp/volume.mrc")
    protocol = FakeProtocol(outputVolumes=volume)
    service.currentProject = FakeCurrentProject(protocol=protocol)

    resolvedProtocol, resolvedOutput = service._resolveOutputForVolumes(10, "outputVolumes")

    assert resolvedProtocol is protocol
    assert resolvedOutput is volume


def test_GetPostgresqlVolumeReaderIfAvailableUsesResolvedProtocolDbId(
    service,
    monkeypatch,
):
    createdCoordsVolumeReaders = []
    createdVolumeReaders = []

    class FakeDb:
        # fakeDb
        pass

    class FakeMapper:
        # fakeMapper
        def __init__(self):
            self.db = FakeDb()

    class FakePostgresqlCoords3dTomogramVolumeReader:
        # fakePostgresqlCoords3dTomogramVolumeReader
        def __init__(self, db, projectId, protocolId, outputName):
            self.db = db
            self.projectId = projectId
            self.protocolId = protocolId
            self.outputName = outputName
            createdCoordsVolumeReaders.append(self)

        def hasOutput(self):
            return False

    class FakePostgresqlVolumeReader:
        # fakePostgresqlVolumeReader
        def __init__(self, db, projectId, protocolId, outputName):
            self.db = db
            self.projectId = projectId
            self.protocolId = protocolId
            self.outputName = outputName
            createdVolumeReaders.append(self)

        def hasOutput(self):
            return True

    coordsVolumeModule = importlib.import_module(
        "app.backend.viewers.postgresql_coords3d_tomogram_volume_reader"
    )
    volumeModule = importlib.import_module(
        "app.backend.viewers.postgresql_volume_reader"
    )

    monkeypatch.setattr(
        coordsVolumeModule,
        "PostgresqlCoords3dTomogramVolumeReader",
        FakePostgresqlCoords3dTomogramVolumeReader,
    )
    monkeypatch.setattr(
        volumeModule,
        "PostgresqlVolumeReader",
        FakePostgresqlVolumeReader,
    )
    monkeypatch.setattr(
        service,
        "_resolvePostgresqlProtocolDbId",
        lambda mapper, projectId, protocolId: 741,
    )

    mapper = FakeMapper()

    reader = service._getPostgresqlVolumeReaderIfAvailable(
        mapper=mapper,
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
    )

    assert reader is createdVolumeReaders[0]

    assert createdCoordsVolumeReaders[0].db is mapper.db
    assert createdCoordsVolumeReaders[0].projectId == 1
    assert createdCoordsVolumeReaders[0].protocolId == 741
    assert createdCoordsVolumeReaders[0].outputName == "outputVolumes"

    assert createdVolumeReaders[0].db is mapper.db
    assert createdVolumeReaders[0].projectId == 1
    assert createdVolumeReaders[0].protocolId == 741
    assert createdVolumeReaders[0].outputName == "outputVolumes"


def test_ResolveOutputForVolumesSupportsAliasFallback(service):
    volume = FakeVolumeOutput("/tmp/volume.mrc")
    protocol = FakeProtocol(outputVolume=volume)
    service.currentProject = FakeCurrentProject(protocol=protocol)

    resolvedProtocol, resolvedOutput = service._resolveOutputForVolumes(10, "outputVolumes")

    assert resolvedProtocol is protocol
    assert resolvedOutput is volume

@pytest.mark.parametrize(
    "serviceCall, expectedDetail",
    [
        (
            lambda service, mapper: service.listOutputVolumesService(
                projectId=1,
                protocolId=10,
                outputName="outputVolumes",
                mapper=mapper,
            ),
            "Volume output is not available in PostgreSQL metadata",
        ),
        (
            lambda service, mapper: service.getVolumeInfoService(
                projectId=1,
                protocolId=10,
                outputName="outputVolumes",
                volumeId=0,
                mapper=mapper,
            ),
            "Volume output is not available in PostgreSQL metadata",
        ),
        (
            lambda service, mapper: service.getVolumeHistogramService(
                projectId=1,
                protocolId=10,
                outputName="outputVolumes",
                volumeId=0,
                bins=32,
                mapper=mapper,
            ),
            "Volume histogram output is not available in PostgreSQL metadata",
        ),
        (
            lambda service, mapper: service.renderVolumeSliceService(
                projectId=1,
                protocolId=10,
                outputName="outputVolumes",
                volumeId=0,
                sliceIndex=0,
                axis="z",
                colormap=None,
                normalize="minmax",
                scale=1.0,
                inline=True,
                mapper=mapper,
            ),
            "Volume slice output is not available in PostgreSQL metadata",
        ),
        (
            lambda service, mapper: service.getVolumeData3dService(
                projectId=1,
                protocolId=10,
                outputName="outputVolumes",
                volumeId=0,
                maxDim=32,
                method="binning",
                mapper=mapper,
            ),
            "Volume 3D data output is not available in PostgreSQL metadata",
        ),
        (
            lambda service, mapper: service.getVolumeSurfaceMesh(
                projectId=1,
                protocolId=10,
                outputName="outputVolumes",
                volumeId=0,
                level=0.1,
                maxDim=32,
                method="binning",
                maxTriangles=1000,
                currentUser={"id": 1},
                mapper=mapper,
            ),
            "Volume surface mesh output is not available in PostgreSQL metadata",
        ),
    ],
)
def test_VolumeServicesRequirePostgresqlWhenMapperIsPresent(
    service,
    monkeypatch,
    serviceCall,
    expectedDetail,
):
    monkeypatch.setattr(
        service,
        "_getPostgresqlVolumeReaderIfAvailable",
        lambda **kwargs: None,
    )

    def failRuntimeFallback(**kwargs):
        raise AssertionError("Legacy volume fallback should not be used")

    monkeypatch.setattr(service, "_resolveOutputForVolumes", failRuntimeFallback)

    with pytest.raises(HTTPException) as exc:
        serviceCall(service, object())

    assert exc.value.status_code == 404
    assert expectedDetail in exc.value.detail
    assert "reader_not_available" in exc.value.detail

def test_ResolveOutputForVolumesReturns404WhenProtocolMissing(service):
    service.currentProject = FakeCurrentProject(protocolError=RuntimeError("missing"))

    with pytest.raises(HTTPException) as exc:
        service._resolveOutputForVolumes(10, "outputVolumes")

    assert exc.value.status_code == 404
    assert str(exc.value.detail).startswith("Protocol not found in Scipion runtime: 10")


def test_ListOutputVolumesServiceDelegatesToOutputsPreview(projectServiceModule, service, monkeypatch):
    FakeOutputsPreview.instances = []
    volume = FakeVolumeOutput("/tmp/volume.mrc")
    protocol = FakeProtocol(outputVolumes=volume)
    service.currentProject = FakeCurrentProject(protocol=protocol)

    monkeypatch.setattr(projectServiceModule, "OutputsPreview", FakeOutputsPreview)

    result = service.listOutputVolumesService(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
    )

    assert result == [
        {"id": 0, "name": "vol-0"},
        {"id": 1, "name": "vol-1"},
    ]
    assert len(FakeOutputsPreview.instances) == 1
    assert FakeOutputsPreview.instances[0].protocol is protocol
    assert FakeOutputsPreview.instances[0].output is volume


def test_GetVolumeInfoServiceDelegatesToOutputsPreview(projectServiceModule, service, monkeypatch):
    FakeOutputsPreview.instances = []
    volume = FakeVolumeOutput("/tmp/volume.mrc")
    protocol = FakeProtocol(outputVolumes=volume)
    service.currentProject = FakeCurrentProject(protocol=protocol)

    monkeypatch.setattr(projectServiceModule, "OutputsPreview", FakeOutputsPreview)

    result = service.getVolumeInfoService(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=3,
    )

    assert result == {
        "id": 3,
        "dims": [16, 16, 16],
        "samplingRate": 1.5,
    }
    assert FakeOutputsPreview.instances[0].lastGetVolumeInfoCall == {
        "volumeId": 3,
    }


def test_GetVolumeHistogramServiceNormalizesKeysForSingleVolume(projectServiceModule, service, monkeypatch, tmp_path):
    FakeOutputsPreview.instances = []
    volumePath = tmp_path / "volume.mrc"
    volumePath.write_text("placeholder", encoding="utf-8")

    volume = FakeVolumeOutput(str(volumePath))
    protocol = FakeProtocol(outputVolumes=volume)
    service.currentProject = FakeCurrentProject(protocol=protocol)

    monkeypatch.setattr(projectServiceModule, "OutputsPreview", FakeOutputsPreview)
    monkeypatch.setattr(projectServiceModule, "SetOfVolumes", FakeSetOfVolumes)

    result = service.getVolumeHistogramService(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=0,
        bins=32,
    )

    assert result == {
        "binEdges": [0.0, 1.0, 2.0],
        "counts": [10, 20],
    }
    assert FakeOutputsPreview.instances[0].lastGetVolumeHistogramCall == {
        "volumePath": str(volumePath),
        "bins": 32,
    }


def test_GetVolumeHistogramServiceResolvesVolumeInsideSet(projectServiceModule, service, monkeypatch, tmp_path):
    FakeOutputsPreview.instances = []
    volumePath = tmp_path / "volume-1.mrc"
    volumePath.write_text("placeholder", encoding="utf-8")

    item = FakeVolumeOutput(str(volumePath))
    outputSet = FakeSetOfVolumes({2: item})
    protocol = FakeProtocol(outputVolumes=outputSet)
    service.currentProject = FakeCurrentProject(protocol=protocol)

    monkeypatch.setattr(projectServiceModule, "OutputsPreview", FakeOutputsPreview)
    monkeypatch.setattr(projectServiceModule, "SetOfVolumes", FakeSetOfVolumes)

    result = service.getVolumeHistogramService(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=1,
        bins=64,
    )

    assert result == {
        "binEdges": [0.0, 1.0, 2.0],
        "counts": [10, 20],
    }
    assert outputSet.lastGetItemCall == {
        "key": "_objId",
        "value": 2,
    }
    assert FakeOutputsPreview.instances[0].lastGetVolumeHistogramCall == {
        "volumePath": str(volumePath),
        "bins": 64,
    }


def test_GetVolumeHistogramServiceReturnsEmptyPayloadWhenPreviewReturnsNone(projectServiceModule, service, monkeypatch):
    class FakeOutputsPreviewNone(FakeOutputsPreview):
        # fakeOutputsPreviewNone
        def __init__(self, currentProject, protocol, output):
            FakeOutputsPreview.__init__(self, currentProject, protocol, output)
            self.getVolumeHistogramResult = None

    volume = FakeVolumeOutput("/tmp/volume.mrc")
    protocol = FakeProtocol(outputVolumes=volume)
    service.currentProject = FakeCurrentProject(protocol=protocol)

    monkeypatch.setattr(projectServiceModule, "OutputsPreview", FakeOutputsPreviewNone)
    monkeypatch.setattr(projectServiceModule, "SetOfVolumes", FakeSetOfVolumes)

    result = service.getVolumeHistogramService(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=0,
        bins=16,
    )

    assert result == {
        "binEdges": [],
        "counts": [],
    }


def test_RenderVolumeSliceServiceDelegatesToOutputsPreview(projectServiceModule, service, monkeypatch):
    FakeOutputsPreview.instances = []
    volume = FakeVolumeOutput("/tmp/volume.mrc")
    protocol = FakeProtocol(outputVolumes=volume)
    service.currentProject = FakeCurrentProject(protocol=protocol)

    monkeypatch.setattr(projectServiceModule, "OutputsPreview", FakeOutputsPreview)

    result = service.renderVolumeSliceService(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=4,
        sliceIndex=7,
        axis="y",
        colormap="viridis",
        normalize="minmax",
        windowMin=-0.25,
        windowMax=0.75,
        scale=1.5,
        inline=False,
        fmt="png",
        thumb=256,
        fast=False,
        quality=80,
    )

    assert result == {
        "rendered": True,
    }
    assert FakeOutputsPreview.instances[0].lastRenderVolumeSliceCall == {
        "volumeId": 4,
        "sliceIndex": 7,
        "axis": "y",
        "colormap": "viridis",
        "normalize": "minmax",
        "windowMin": -0.25,
        "windowMax": 0.75,
        "scale": 1.5,
        "inline": False,
        "fmt": "png",
        "thumb": 256,
        "fast": False,
        "quality": 80,
    }


def test_Normalize2dSliceUsesSharedIntensityWindow(service):
    sliceData = np.array(
        [
            [0.0, 5.0],
            [10.0, 20.0],
        ],
        dtype=np.float32,
    )

    result = service._normalize2dSlice(
        sliceData,
        mode="minmax",
        windowMin=0.0,
        windowMax=20.0,
    )

    assert result.tolist() == [
        [0, 63],
        [127, 255],
    ]


def test_VolumeSliceCacheKeyIncludesIntensityWindow(service, tmp_path):
    volumePath = tmp_path / "volume.mrc"
    volumePath.write_bytes(b"volume")

    commonArgs = {
        "volumePath": str(volumePath),
        "tomogramId": 1,
        "sliceIndex": 10,
        "axis": "z",
        "colormap": "gray",
        "normalize": "minmax",
        "scale": 1.0,
        "fmt": "webp",
        "thumb": 512,
        "fast": True,
        "quality": 70,
    }

    keyA = service._buildVolumeSliceCacheKey(
        **commonArgs,
        windowMin=0.0,
        windowMax=1.0,
    )

    keyB = service._buildVolumeSliceCacheKey(
        **commonArgs,
        windowMin=0.0,
        windowMax=2.0,
    )

    assert keyA != keyB


def test_GetVolumePathFromOutputReturnsPathForSingleVolume(service, tmp_path):
    volumePath = tmp_path / "volume.mrc"
    volumePath.write_text("placeholder", encoding="utf-8")
    output = FakeVolumeOutput(str(volumePath))

    result = service._getVolumePathFromOutput(output, volumeId=0)

    assert result == str(volumePath)


def test_GetVolumePathFromOutputRejectsNonIntegerVolumeIdForSet(projectServiceModule, service, monkeypatch):
    outputSet = FakeSetOfVolumes({})
    monkeypatch.setattr(projectServiceModule, "SetOfVolumes", FakeSetOfVolumes)

    with pytest.raises(HTTPException) as exc:
        service._getVolumePathFromOutput(outputSet, volumeId="abc")

    assert exc.value.status_code == 400
    assert exc.value.detail == "volumeId must be an integer"


def test_GetVolumePathFromOutputReturns404WhenSetItemMissing(projectServiceModule, service, monkeypatch):
    outputSet = FakeSetOfVolumes({})
    monkeypatch.setattr(projectServiceModule, "SetOfVolumes", FakeSetOfVolumes)

    with pytest.raises(HTTPException) as exc:
        service._getVolumePathFromOutput(outputSet, volumeId=5)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Volume not found in SetOfVolumes"


def test_GetVolumeData3dServiceReturnsDimsAndFlattenedValues(projectServiceModule, service, monkeypatch, tmp_path):
    volumePath = tmp_path / "volume.mrc"
    volumePath.write_text("placeholder", encoding="utf-8")

    volume = FakeVolumeOutput(str(volumePath))
    protocol = FakeProtocol(outputVolumes=volume)
    service.currentProject = FakeCurrentProject(protocol=protocol)

    monkeypatch.setattr(projectServiceModule, "SetOfVolumes", FakeSetOfVolumes)
    monkeypatch.setattr(
        projectServiceModule,
        "readVolumeArray3d",
        lambda path: (
            np.arange(24, dtype=np.float32).reshape((2, 3, 4)),
            {"source": path},
        ),
    )
    monkeypatch.setattr(
        service,
        "_downsampleVolumePreview",
        lambda vol, maxDim, method: vol,
    )

    result = service.getVolumeData3dService(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=0,
        maxDim=64,
        method="binning",
    )

    assert result == {
        "dims": [4, 3, 2],
        "order": "zyx",
        "values": [float(value) for value in range(24)],
        "min": 0.0,
        "max": 23.0,
    }


def test_GetVolumeData3dServiceReturns404WhenFileMissing(projectServiceModule, service, monkeypatch, tmp_path):
    volumePath = tmp_path / "volume.mrc"
    volumePath.write_text("placeholder", encoding="utf-8")

    volume = FakeVolumeOutput(str(volumePath))
    protocol = FakeProtocol(outputVolumes=volume)
    service.currentProject = FakeCurrentProject(protocol=protocol)

    monkeypatch.setattr(projectServiceModule, "SetOfVolumes", FakeSetOfVolumes)

    def raiseFileNotFound(path):
        raise FileNotFoundError("missing file")

    monkeypatch.setattr(projectServiceModule, "readVolumeArray3d", raiseFileNotFound)

    with pytest.raises(HTTPException) as exc:
        service.getVolumeData3dService(
            projectId=1,
            protocolId=10,
            outputName="outputVolumes",
            volumeId=0,
            maxDim=64,
            method="binning",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Volume file not found on disk"


def test_DownsampleVolumeForSurfaceHonorsMaxDimForNone(service):
    volume = np.zeros((96, 80, 64), dtype=np.float32)

    result = service._downsampleVolumeForSurface(volume, maxDim=48, method="none")

    assert result.shape == (48, 40, 32)
    assert result.dtype == np.float32


def test_DownsampleVolumeForSurfaceUsesLargerQualityBudgetForNone(
        projectServiceModule,
        service,
        monkeypatch,
):
    monkeypatch.setattr(
        projectServiceModule,
        "_VOLUME_SURFACE_INTERACTIVE_MAX_VOXELS",
        8_000,
    )
    monkeypatch.setattr(
        projectServiceModule,
        "_VOLUME_SURFACE_QUALITY_MAX_VOXELS",
        80_000,
    )

    volume = np.zeros((40, 40, 40), dtype=np.float32)

    qualityResult = service._downsampleVolumeForSurface(
        volume,
        maxDim=64,
        method="none",
    )

    interactiveResult = service._downsampleVolumeForSurface(
        volume,
        maxDim=64,
        method="stride",
    )

    assert qualityResult.shape == (40, 40, 40)
    assert interactiveResult.shape == (20, 20, 20)


def test_BinVolumeAveragesBlocks(service):
    volume = np.arange(64, dtype=np.float32).reshape((4, 4, 4))

    result = service._binVolume(volume, factor=2)

    assert result.shape == (2, 2, 2)
    assert result.tolist() == [
        [
            [10.5, 12.5],
            [18.5, 20.5],
        ],
        [
            [42.5, 44.5],
            [50.5, 52.5],
        ],
    ]


def test_DownsampleVolumePreviewUsesBinningWhenNeeded(service):
    volume = np.arange(64, dtype=np.float32).reshape((4, 4, 4))

    result = service._downsampleVolumePreview(volume, maxDim=2, method="binning")

    assert result.shape == (2, 2, 2)


def _fakeSliceResponse(axis, index):
    from fastapi.responses import Response

    return Response(
        content=b"fake-bytes-%s-%d" % (axis.encode(), index),
        media_type="image/webp",
        headers={
            "X-Preview-Width": "64",
            "X-Preview-Height": "64",
        },
    )


def test_RenderVolumeSlicesBatchServiceRendersEachItemInOrder(service, monkeypatch):
    calls = []

    def fakeRenderVolumeSliceService(self, **kwargs):
        calls.append(kwargs)
        return _fakeSliceResponse(kwargs["axis"], kwargs["sliceIndex"])

    monkeypatch.setattr(
        type(service),
        "renderVolumeSliceService",
        fakeRenderVolumeSliceService,
    )

    result = service.renderVolumeSlicesBatchService(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=4,
        items=[("z", 5), ("y", 6), ("x", 7)],
        colormap="viridis",
        fmt="webp",
    )

    assert [c["axis"] for c in calls] == ["z", "y", "x"]
    assert [c["sliceIndex"] for c in calls] == [5, 6, 7]
    assert all(c["colormap"] == "viridis" for c in calls)

    assert result["volumeId"] == "4"
    assert result["errors"] == []
    assert [item["axis"] for item in result["items"]] == ["z", "y", "x"]
    assert [item["index"] for item in result["items"]] == [5, 6, 7]
    for item in result["items"]:
        assert item["contentType"] == "image/webp"
        assert item["dataUrl"].startswith("data:image/webp;base64,")
        assert item["width"] == "64"
        assert item["height"] == "64"


def test_RenderVolumeSlicesBatchServiceCollectsPerItemErrorsWithoutFailingOthers(
    service, monkeypatch,
):
    def fakeRenderVolumeSliceService(self, **kwargs):
        if kwargs["sliceIndex"] == 6:
            raise HTTPException(status_code=404, detail="Slice out of range")
        return _fakeSliceResponse(kwargs["axis"], kwargs["sliceIndex"])

    monkeypatch.setattr(
        type(service),
        "renderVolumeSliceService",
        fakeRenderVolumeSliceService,
    )

    result = service.renderVolumeSlicesBatchService(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=4,
        items=[("z", 5), ("z", 6), ("z", 7)],
    )

    assert [item["index"] for item in result["items"]] == [5, 7]
    assert result["errors"] == [
        {"axis": "z", "index": 6, "error": "Slice out of range"},
    ]


def test_RenderVolumeSlicesBatchServiceDedupsAndCapsItems(service, monkeypatch):
    calls = []

    def fakeRenderVolumeSliceService(self, **kwargs):
        calls.append((kwargs["axis"], kwargs["sliceIndex"]))
        return _fakeSliceResponse(kwargs["axis"], kwargs["sliceIndex"])

    monkeypatch.setattr(
        type(service),
        "renderVolumeSliceService",
        fakeRenderVolumeSliceService,
    )

    duplicated = [("z", 1), ("z", 1), ("y", 2)]
    overCap = [("z", i) for i in range(100)]

    service.renderVolumeSlicesBatchService(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=4,
        items=duplicated,
    )
    assert calls == [("z", 1), ("y", 2)]

    calls.clear()
    service.renderVolumeSlicesBatchService(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=4,
        items=overCap,
    )
    assert len(calls) == 48


def test_RenderVolumeSlicesBatchServiceIgnoresMalformedItems(service, monkeypatch):
    calls = []

    def fakeRenderVolumeSliceService(self, **kwargs):
        calls.append((kwargs["axis"], kwargs["sliceIndex"]))
        return _fakeSliceResponse(kwargs["axis"], kwargs["sliceIndex"])

    monkeypatch.setattr(
        type(service),
        "renderVolumeSliceService",
        fakeRenderVolumeSliceService,
    )

    result = service.renderVolumeSlicesBatchService(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=4,
        items=[("w", 1), ("z", -1), ("z", "not-an-int"), ("z", 2)],
    )

    assert calls == [("z", 2)]
    assert [item["index"] for item in result["items"]] == [2]


def _fakeBuildVolumeSurfaceMesh(callTracker):
    def build(volumeSmall, level, maxTriangles, minComponentTriangles, smoothingIterations):
        callTracker.append(1)
        return {
            "kind": "surfaceMesh",
            "level": level,
            "vertices": [0.0, 0.0, 0.0],
            "faces": [0, 0, 0],
        }

    return build


def test_GetVolumeSurfaceMeshCachesResultForLegacyPath(
    projectServiceModule, service, monkeypatch, tmp_path,
):
    volumePath = tmp_path / "volume.mrc"
    volumePath.write_text("placeholder", encoding="utf-8")

    volume = FakeVolumeOutput(str(volumePath))
    protocol = FakeProtocol(outputVolumes=volume)
    service.currentProject = FakeCurrentProject(protocol=protocol)

    monkeypatch.setattr(projectServiceModule, "SetOfVolumes", FakeSetOfVolumes)
    monkeypatch.setattr(
        projectServiceModule,
        "readVolumeArray3d",
        lambda path: (
            np.arange(64, dtype=np.float32).reshape((4, 4, 4)),
            {"source": path},
        ),
    )

    buildCalls: list = []
    monkeypatch.setattr(
        projectServiceModule,
        "buildVolumeSurfaceMesh",
        _fakeBuildVolumeSurfaceMesh(buildCalls),
    )

    callKwargs = dict(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=0,
        level=0.5,
        maxDim=64,
        method="binning",
        maxTriangles=1000,
        currentUser={"id": 1},
    )

    first = service.getVolumeSurfaceMesh(**callKwargs)
    assert len(buildCalls) == 1
    assert first.headers["X-Preview-Cache"] == "miss"

    second = service.getVolumeSurfaceMesh(**callKwargs)
    assert len(buildCalls) == 1  # not recomputed
    assert second.headers["X-Preview-Cache"] == "hit"
    assert second.body == first.body

    # A different level is a different cache entry -- must recompute.
    service.getVolumeSurfaceMesh(**{**callKwargs, "level": 0.9})
    assert len(buildCalls) == 2


def test_GetVolumeSurfaceMeshCachesResultForPostgresqlPath(
    projectServiceModule, service, monkeypatch, tmp_path,
):
    volumePath = tmp_path / "volume.mrc"
    volumePath.write_text("placeholder", encoding="utf-8")

    class FakePgVolumeReader:
        lastSkipReason = None

        def getVolumeFile(self, volumeId):
            return {"fileName": str(volumePath), "path": str(volumePath)}

        def getVolumeArray(self, volumeId):
            volume = np.arange(64, dtype=np.float32).reshape((4, 4, 4))
            return volume, {}, {}

    monkeypatch.setattr(
        service,
        "_getPostgresqlVolumeReaderIfAvailable",
        lambda **kwargs: FakePgVolumeReader(),
    )

    buildCalls: list = []
    monkeypatch.setattr(
        projectServiceModule,
        "buildVolumeSurfaceMesh",
        _fakeBuildVolumeSurfaceMesh(buildCalls),
    )

    callKwargs = dict(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=0,
        level=0.5,
        maxDim=64,
        method="binning",
        maxTriangles=1000,
        currentUser={"id": 1},
        mapper=object(),
    )

    first = service.getVolumeSurfaceMesh(**callKwargs)
    assert len(buildCalls) == 1
    assert first.headers["X-Preview-Cache"] == "miss"

    second = service.getVolumeSurfaceMesh(**callKwargs)
    assert len(buildCalls) == 1
    assert second.headers["X-Preview-Cache"] == "hit"
    assert second.body == first.body


def test_GetVolumeSurfaceMeshReturns304WhenIfNoneMatchMatches(
    projectServiceModule, service, monkeypatch, tmp_path,
):
    volumePath = tmp_path / "volume.mrc"
    volumePath.write_text("placeholder", encoding="utf-8")

    class FakePgVolumeReader:
        lastSkipReason = None

        def getVolumeFile(self, volumeId):
            return {"fileName": str(volumePath), "path": str(volumePath)}

        def getVolumeArray(self, volumeId):
            volume = np.arange(64, dtype=np.float32).reshape((4, 4, 4))
            return volume, {}, {}

    monkeypatch.setattr(
        service,
        "_getPostgresqlVolumeReaderIfAvailable",
        lambda **kwargs: FakePgVolumeReader(),
    )

    buildCalls: list = []
    monkeypatch.setattr(
        projectServiceModule,
        "buildVolumeSurfaceMesh",
        _fakeBuildVolumeSurfaceMesh(buildCalls),
    )

    callKwargs = dict(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=0,
        level=0.5,
        maxDim=64,
        method="binning",
        maxTriangles=1000,
        currentUser={"id": 1},
        mapper=object(),
    )

    first = service.getVolumeSurfaceMesh(**callKwargs)
    etag = first.headers["ETag"]
    assert etag

    revalidated = service.getVolumeSurfaceMesh(**callKwargs, ifNoneMatch=etag)

    assert revalidated.status_code == 304
    assert revalidated.headers["ETag"] == etag
    assert len(buildCalls) == 1  # the 304 path never touched the mesh builder

    # A stale/mismatched If-None-Match still gets a real (cached) response.
    stillFresh = service.getVolumeSurfaceMesh(**callKwargs, ifNoneMatch='"not-the-etag"')
    assert stillFresh.status_code == 200
    assert stillFresh.headers["X-Preview-Cache"] == "hit"


def test_RenderVolumeSliceServiceReturns304WhenIfNoneMatchMatches(service, monkeypatch, tmp_path):
    volumePath = tmp_path / "volume.mrc"
    volumePath.write_bytes(b"volume")

    class FakePgVolumeReader:
        lastSkipReason = None

        def getVolumeFile(self, volumeId):
            return {"fileName": str(volumePath), "path": str(volumePath)}

    monkeypatch.setattr(
        service,
        "_getPostgresqlVolumeReaderIfAvailable",
        lambda **kwargs: FakePgVolumeReader(),
    )

    renderCalls: list = []

    def fakeRenderTomogramSliceFromPath(self=None, **kwargs):
        renderCalls.append(kwargs)
        from fastapi.responses import Response
        return Response(content=b"fake-slice-bytes", media_type="image/webp")

    monkeypatch.setattr(
        type(service),
        "_renderTomogramSliceFromPath",
        fakeRenderTomogramSliceFromPath,
    )

    callKwargs = dict(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=0,
        sliceIndex=5,
        axis="z",
        colormap="gray",
        normalize="minmax",
        scale=1.0,
        inline=True,
        fmt="webp",
    )

    first = service.renderVolumeSliceService(**callKwargs)
    assert len(renderCalls) == 1
    etag = first.headers["ETag"]
    assert etag

    revalidated = service.renderVolumeSliceService(**callKwargs, ifNoneMatch=etag)
    assert revalidated.status_code == 304
    assert revalidated.headers["ETag"] == etag
    assert len(renderCalls) == 1  # no re-render on a 304

    # A cache hit (no If-None-Match) still carries the same ETag.
    cached = service.renderVolumeSliceService(**callKwargs)
    assert len(renderCalls) == 1
    assert cached.headers["ETag"] == etag


def test_GetVolumeData3dServiceBinaryReturns304WhenIfNoneMatchMatches(
    projectServiceModule, service, monkeypatch, tmp_path,
):
    volumePath = tmp_path / "volume.mrc"
    volumePath.write_text("placeholder", encoding="utf-8")

    volume = FakeVolumeOutput(str(volumePath))
    protocol = FakeProtocol(outputVolumes=volume)
    service.currentProject = FakeCurrentProject(protocol=protocol)

    monkeypatch.setattr(projectServiceModule, "SetOfVolumes", FakeSetOfVolumes)

    readCalls: list = []

    def fakeReadVolumeArray3d(path):
        readCalls.append(path)
        return (
            np.arange(64, dtype=np.float32).reshape((4, 4, 4)),
            {"source": path},
        )

    monkeypatch.setattr(projectServiceModule, "readVolumeArray3d", fakeReadVolumeArray3d)

    callKwargs = dict(
        projectId=1,
        protocolId=10,
        outputName="outputVolumes",
        volumeId=0,
        maxDim=64,
        method="binning",
        binary=True,
    )

    first = service.getVolumeData3dService(**callKwargs)
    assert len(readCalls) == 1
    etag = first.headers["ETag"]
    assert etag
    assert first.headers["Cache-Control"] != "no-store"

    revalidated = service.getVolumeData3dService(**callKwargs, ifNoneMatch=etag)
    assert revalidated.status_code == 304
    assert revalidated.headers["ETag"] == etag
    assert len(readCalls) == 1  # the volume file is never re-read on a 304