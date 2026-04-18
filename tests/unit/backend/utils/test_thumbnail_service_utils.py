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


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(self, projectPath):
        self._projectPath = projectPath

    def getPath(self):
        return self._projectPath


class FakeProtocol:
    # fakeProtocol
    def __init__(self, objId=10, label="Protocol", status="finished", protocolPath=None):
        self._objId = objId
        self._label = label
        self._status = status
        self._protocolPath = protocolPath

    def getObjId(self):
        return self._objId

    def getObjLabel(self):
        return self._label

    def getStatus(self):
        return self._status

    def getPath(self):
        return self._protocolPath

    def __str__(self):
        return "ProtocolString"


class FakeOutput:
    # fakeOutput
    def __init__(self, className="SetOfParticles", size=5, fileName=None):
        self._className = className
        self._size = size
        self._fileName = fileName

    def getClassName(self):
        return self._className

    def getSize(self):
        return self._size

    def getFileName(self):
        return self._fileName


class FakeOutputBrokenSize:
    # fakeOutputBrokenSize
    def getSize(self):
        raise RuntimeError("size error")


class FakeItem:
    # fakeItem
    def __init__(self, fileName=None, enabled=True):
        self._fileName = fileName
        self._enabled = enabled

    def getFileName(self):
        return self._fileName

    def isEnabled(self):
        return self._enabled


class FakeOutputWithItems:
    # fakeOutputWithItems
    def __init__(self, fileName=None, items=None):
        self._fileName = fileName
        self._items = items or []

    def getFileName(self):
        return self._fileName

    def iterItems(self, iterate=False):
        return list(self._items)


class FakeRenderableByTomograms:
    # fakeRenderableByTomograms
    def getTomograms(self):
        return []


@pytest.fixture
def thumbnailServiceModule(authTestEnv):
    # thumbnailServiceModule
    return importlib.import_module("app.backend.utils.thumbnail_service")


@pytest.fixture
def service(thumbnailServiceModule, tmp_path):
    # service
    projectPath = tmp_path / "DemoProject"
    projectPath.mkdir(parents=True, exist_ok=True)

    currentProject = FakeCurrentProject(str(projectPath))
    return thumbnailServiceModule.ThumbnailService(currentProject)


def test_GetProtocolLabelUsesObjLabel(service):
    protocol = FakeProtocol(label="My Protocol")

    assert service._getProtocolLabel(protocol) == "My Protocol"


def test_GetProtocolLabelFallsBackToString(service):
    class NoLabelProtocol:
        # noLabelProtocol
        def __str__(self):
            return "StringFallback"

    assert service._getProtocolLabel(NoLabelProtocol()) == "StringFallback"


def test_GetProtocolStatusUsesCallable(service):
    protocol = FakeProtocol(status="running")

    assert service._getProtocolStatus(protocol) == "running"


def test_GetProtocolStatusFallsBackToUnknown(service):
    class NoStatusProtocol:
        pass

    assert service._getProtocolStatus(NoStatusProtocol()) == "unknown"


def test_GetOutputClassNameUsesGetter(service):
    output = FakeOutput(className="SetOfVolumes")

    assert service._getOutputClassName(output) == "SetOfVolumes"


def test_SafeOutputSizeReturnsInteger(service):
    output = FakeOutput(size=12)

    assert service._safeOutputSize(output) == 12


def test_SafeOutputSizeReturnsNoneOnFailure(service):
    assert service._safeOutputSize(FakeOutputBrokenSize()) is None


def test_IsEnabledUsesMethod(service):
    assert service._isEnabled(FakeItem(enabled=True)) is True
    assert service._isEnabled(FakeItem(enabled=False)) is False


def test_IsEnabledFallsBackToTrueWhenMissing(service):
    class NoEnabledInfo:
        pass

    assert service._isEnabled(NoEnabledInfo()) is True


def test_ResolveFilePathFindsAbsoluteExistingPath(service, tmp_path):
    filePath = tmp_path / "absolute.mrc"
    filePath.write_text("placeholder", encoding="utf-8")

    protocol = FakeProtocol(protocolPath=str(tmp_path / "Runs" / "Prot"))

    resolved = service._resolveFilePath(protocol, str(filePath))

    assert resolved == filePath.resolve()


def test_ResolveFilePathFindsRelativePathUnderProtocol(service, tmp_path):
    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    relativeFile = protocolPath / "extra" / "image.mrc"
    relativeFile.parent.mkdir(parents=True, exist_ok=True)
    relativeFile.write_text("placeholder", encoding="utf-8")

    protocol = FakeProtocol(protocolPath=str(protocolPath))

    resolved = service._resolveFilePath(protocol, "extra/image.mrc")

    assert resolved == relativeFile.resolve()


def test_ResolveFilePathReturnsNoneWhenMissing(service, tmp_path):
    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    protocol = FakeProtocol(protocolPath=str(protocolPath))

    resolved = service._resolveFilePath(protocol, "missing/file.mrc")

    assert resolved is None


def test_CollectDirectVolumePathsDeduplicates(thumbnailServiceModule, service, monkeypatch, tmp_path):
    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    vol1 = protocolPath / "vol1.mrc"
    vol2 = protocolPath / "vol2.mrc"
    vol1.write_text("placeholder", encoding="utf-8")
    vol2.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(thumbnailServiceModule, "EMSet", FakeOutputWithItems)

    protocol = FakeProtocol(protocolPath=str(protocolPath))
    output = FakeOutputWithItems(
        fileName="vol1.mrc",
        items=[
            FakeItem(fileName="vol1.mrc"),
            FakeItem(fileName="vol2.mrc"),
            FakeItem(fileName="vol2.mrc"),
        ],
    )

    paths = service._collectDirectVolumePaths(protocol, output, maxItems=6)


    assert paths == [vol1.resolve(), vol2.resolve()]


def test_LooksRenderableOutputRecognizesFileBackedOutput(service):
    output = FakeOutput(fileName="output.mrc")

    assert service._looksRenderableOutput(output) is True


def test_LooksRenderableOutputRecognizesIterableOutput(service):
    output = FakeOutputWithItems(fileName=None, items=[])

    assert service._looksRenderableOutput(output) is True


def test_LooksRenderableOutputRecognizesTomogramsGetter(service):
    assert service._looksRenderableOutput(FakeRenderableByTomograms()) is True


def test_LooksRenderableOutputRejectsNone(service):
    assert service._looksRenderableOutput(None) is False


def test_FilesystemPreviewSortKeyPrioritizesThumbnailNames(service, tmp_path):
    thumb = tmp_path / "thumb_preview.png"
    raw = tmp_path / "raw_data.mrc"

    thumb.write_text("thumb", encoding="utf-8")
    raw.write_text("raw", encoding="utf-8")

    keyThumb = service._filesystemPreviewSortKey(thumb)
    keyRaw = service._filesystemPreviewSortKey(raw)

    assert keyThumb < keyRaw


def test_VolumeLikeExtensionsContainsExpectedTypes(service):
    exts = service._volumeLikeExtensions()

    assert ".mrc" in exts
    assert ".map" in exts
    assert ".mrcs" in exts
    assert ".h5" in exts