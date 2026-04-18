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
from PIL import Image


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(self, protocolPath):
        self._protocolPath = protocolPath

    def getPath(self):
        return self._protocolPath


class FakeProtocol:
    # fakeProtocol
    def __init__(self, protocolPath):
        self._protocolPath = protocolPath

    def getPath(self):
        return self._protocolPath

    def getObjId(self):
        return 10


class FakeColumn:
    # fakeColumn
    def __init__(self, name):
        self._name = name

    def getName(self):
        return self._name


class FakeRow:
    # fakeRow
    def __init__(self, rowId, values):
        self._id = rowId
        self._values = values

    def getId(self):
        return self._id

    def getValues(self):
        return self._values


class FakeObjectManager:
    # fakeObjectManager
    def __init__(self, rowsByTable):
        self.rowsByTable = rowsByTable

    def getTableRowCount(self, tableName):
        return len(self.rowsByTable.get(tableName, []))

    def getRows(self, tableName, offset, limit):
        rows = self.rowsByTable.get(tableName, [])
        return rows[offset:offset + limit]


class FakeFSC:
    # fakeFSC
    def __init__(self, label, x, y, resolution=None):
        self._label = label
        self._x = x
        self._y = y
        self._resolution = resolution

    def clone(self):
        return self

    def getObjLabel(self):
        return self._label

    def getData(self):
        return [self._x, self._y]

    def calculateResolution(self, threshold):
        return self._resolution


class FakeTiltSeries:
    # fakeTiltSeries
    def __init__(self, tsId, fileName, tiltAngles=None, label=None):
        self._tsId = tsId
        self._fileName = fileName
        self._tiltAngles = tiltAngles or []
        self._label = label

    def getTsId(self):
        return self._tsId

    def getObjLabel(self):
        return self._label

    def getFileName(self):
        return self._fileName

    def getTiltAngles(self):
        return self._tiltAngles


class FakeTiltSeriesSet(list):
    # fakeTiltSeriesSet
    pass


class FakeImageReader:
    # fakeImageReader
    instances = []

    def __init__(self, imageArray):
        self.imageArray = imageArray
        FakeImageReader.instances.append(self)

    def getImages(self):
        return self.imageArray

    def getImage(self, index=0, pilImage=False):
        slice2d = self.imageArray[index]
        img = Image.fromarray(slice2d.astype(np.uint8), mode="L")
        return img if pilImage else slice2d

    def getCentralImage(self, pilImage=False):
        mid = self.imageArray.shape[0] // 2
        slice2d = self.imageArray[mid]
        img = Image.fromarray(slice2d.astype(np.uint8), mode="L")
        return img if pilImage else slice2d

    def highlightSlice(self, arr):
        return arr

    def normalizeSlice(self, arr):
        return arr


@pytest.fixture
def outputsPreviewModule(authTestEnv):
    # outputsPreviewModule
    return importlib.import_module("app.backend.utils.outputs_preview")


@pytest.fixture
def preview(outputsPreviewModule, tmp_path):
    # preview
    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    currentProject = FakeCurrentProject(str(protocolPath.parent.parent))
    protocol = FakeProtocol(str(protocolPath))

    class GenericOutput:
        # genericOutput
        pass

    output = GenericOutput()

    return outputsPreviewModule.OutputsPreview(
        currentProject=currentProject,
        protocol=protocol,
        output=output,
    )


def test_MakeGalleryFromTilesBuildsGrayscaleGallery(preview):
    tiles = [
        np.full((20, 20), 50, dtype=np.uint8),
        np.full((20, 20), 180, dtype=np.uint8),
    ]

    pngBytes, meta = preview.makeGalleryFromTiles(
        tiles=tiles,
        cols=2,
        tileSize=32,
        labels=["A", "B"],
        summary="2 items",
    )

    assert isinstance(pngBytes, bytes)
    assert len(pngBytes) > 0
    assert meta["tiles"] == 2
    assert meta["grid"] == [1, 2]
    assert meta["tileSize"] == 32
    assert meta["hasSummary"] is True


def test_MakeGalleryFromTilesBuildsRgbGallery(preview):
    tiles = [
        np.zeros((16, 16, 3), dtype=np.uint8),
        np.full((16, 16, 3), 255, dtype=np.uint8),
    ]

    pngBytes, meta = preview.makeGalleryFromTiles(
        tiles=tiles,
        cols=2,
        tileSize=32,
        labels=None,
        summary=None,
        forceRgb=True,
    )

    assert isinstance(pngBytes, bytes)
    assert len(pngBytes) > 0
    assert meta["tiles"] == 2
    assert meta["grid"] == [1, 2]


def test_BuildPreviewHeadersFallbackIncludesExpectedFields(preview):
    headers = preview.buildPreviewHeadersFallback(
        {
            "mime": "image/png",
            "width": 320,
            "height": 180,
            "tiles": 6,
            "note": "gallery",
        }
    )

    assert headers["X-Preview-Mime"] == "image/png"
    assert headers["X-Preview-Width"] == "320"
    assert headers["X-Preview-Height"] == "180"
    assert headers["X-Preview-Tiles"] == "6"
    assert headers["X-Preview-Note"] == "gallery"
    assert "X-Preview-Mime" in headers["Access-Control-Expose-Headers"]


def test_PickSampleRowsReturnsFirstDeterministicRows(preview):
    rows = [FakeRow(i, [i]) for i in range(10)]
    objMgr = FakeObjectManager({"objects": rows})

    result = preview._pickSampleRows(objMgr, "objects", want=4)

    assert [row._id for row in result] == [0, 1, 2, 3]


def test_GetRenderColumnIndexSupportsCaseInsensitiveAndSubstring(preview):
    columns = [
        FakeColumn("_filename"),
        FakeColumn("MicName"),
        FakeColumn("stackReference"),
    ]

    assert preview.getRenderColumnIndex(["micname"], columns) == 0
    assert preview.getRenderColumnIndex(["stack"], columns) == 0


def test_ExtractPathFromRowParsesStackSpec(preview):
    row = FakeRow(1, ["3@Runs/stack.mrcs"])

    relPath, sliceIndex = preview.extractPathFromRow(row, 0)

    assert relPath == "Runs/stack.mrcs"
    assert sliceIndex == 3


def test_MakeFSCResponseBuildsPng(outputsPreviewModule, tmp_path, monkeypatch):
    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    class FakeSetOfFSCs(list):
        # fakeSetOfFSCs
        pass

    monkeypatch.setattr(outputsPreviewModule, "SetOfFSCs", FakeSetOfFSCs)

    output = FakeSetOfFSCs(
        [
            FakeFSC(
                label="gold-standard",
                x=np.array([0.05, 0.1, 0.15, 0.2], dtype=float),
                y=np.array([0.9, 0.6, 0.3, 0.1], dtype=float),
                resolution=5.2,
            )
        ]
    )

    preview = outputsPreviewModule.OutputsPreview(
        currentProject=FakeCurrentProject(str(protocolPath.parent.parent)),
        protocol=FakeProtocol(str(protocolPath)),
        output=output,
    )

    response = preview._makeFSCResponse("fsc_preview.png")

    assert response.media_type == "image/png"
    assert response.headers["Content-Disposition"] == 'inline; filename="fsc_preview.png"'
    assert response.headers["X-Preview-Mime"] == "image/png"
    assert len(response.body) > 0


def test_ListTiltSeriesFramesReturnsMetadata(outputsPreviewModule, tmp_path, monkeypatch):
    FakeImageReader.instances = []

    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    stackPath = protocolPath / "ts1.mrcs"
    stackPath.write_text("placeholder", encoding="utf-8")

    imageArray = np.arange(3 * 4 * 5, dtype=np.uint8).reshape((3, 4, 5))
    monkeypatch.setattr(
        outputsPreviewModule.ImageReadersRegistry,
        "open",
        staticmethod(lambda path: FakeImageReader(imageArray)),
    )
    monkeypatch.setattr(outputsPreviewModule, "SetOfTiltSeries", FakeTiltSeriesSet)

    output = FakeTiltSeriesSet(
        [
            FakeTiltSeries(
                tsId="TS_001",
                fileName=str(stackPath),
                tiltAngles=[-60.0, -58.0, -56.0],
                label="Series 1",
            )
        ]
    )

    preview = outputsPreviewModule.OutputsPreview(
        currentProject=FakeCurrentProject(str(protocolPath.parent.parent)),
        protocol=FakeProtocol(str(protocolPath)),
        output=output,
    )

    result = preview.listTiltSeriesFrames("TS_001")

    assert result == {
        "name": "TS_001",
        "nFrames": 3,
        "dims": [5, 4],
        "stackRelPath": "ts1.mrcs",
        "tiltAngles": [-60.0, -58.0, -56.0],
    }


def test_RenderTiltSeriesFrameBuildsImageResponse(outputsPreviewModule, tmp_path, monkeypatch):
    FakeImageReader.instances = []

    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    stackPath = protocolPath / "ts1.mrcs"
    stackPath.write_text("placeholder", encoding="utf-8")

    imageArray = np.arange(3 * 4 * 5, dtype=np.uint8).reshape((3, 4, 5))
    monkeypatch.setattr(
        outputsPreviewModule.ImageReadersRegistry,
        "open",
        staticmethod(lambda path: FakeImageReader(imageArray)),
    )
    monkeypatch.setattr(outputsPreviewModule, "SetOfTiltSeries", FakeTiltSeriesSet)

    output = FakeTiltSeriesSet(
        [
            FakeTiltSeries(
                tsId="TS_001",
                fileName=str(stackPath),
                tiltAngles=[-60.0, -58.0, -56.0],
                label="Series 1",
            )
        ]
    )

    preview = outputsPreviewModule.OutputsPreview(
        currentProject=FakeCurrentProject(str(protocolPath.parent.parent)),
        protocol=FakeProtocol(str(protocolPath)),
        output=output,
    )

    response = preview.renderTiltSeriesFrame(
        tiltSeriesName="TS_001",
        index=1,
        size=64,
        fmt="png",
        inline=True,
        applyTransform=True,
    )

    assert response.media_type == "image/png"
    assert response.headers["Content-Disposition"] == 'inline; filename="TS_001_tilt-1.png"'
    assert response.headers["X-Preview-Mime"] == "image/png"
    assert response.headers["X-Preview-Note"] == "tiltSeries=TS_001 index=1"
    assert len(response.body) > 0