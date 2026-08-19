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
        "scale": 1.5,
        "inline": False,
        "fmt": "png",
        "thumb": 256,
        "fast": False,
        "quality": 80,
    }


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