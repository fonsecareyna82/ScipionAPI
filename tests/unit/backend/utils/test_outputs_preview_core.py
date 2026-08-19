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
import json
import zipfile
import pytest


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(self, protocolPath):
        self._protocolPath = protocolPath

    def getPath(self):
        return self._protocolPath

    def getProtocol(self, protocolId):
        return FakeProtocol(self._protocolPath)


class FakeProtocol:
    # fakeProtocol
    def __init__(self, protocolPath):
        self._protocolPath = protocolPath

    def getPath(self):
        return self._protocolPath

    def getObjId(self):
        return 10


class FakeOutput:
    # fakeOutput
    def __init__(self, objId=None):
        self._objId = objId

    def getObjId(self):
        return self._objId


class FakeObjectManager:
    # fakeObjectManager
    def __init__(self):
        self._fileName = None
        self._dao = None
        self._tables = {}
        self.selected = False
        self.loaded = False

    def selectDAO(self):
        self.selected = True

    def getTables(self):
        self.loaded = True
        return {}


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
    output = FakeOutput(objId=77)

    return outputsPreviewModule.OutputsPreview(
        currentProject=currentProject,
        protocol=protocol,
        output=output,
    )


def test_OutputSignatureUsesObjId(outputsPreviewModule):
    output = FakeOutput(objId=77)

    result = outputsPreviewModule._outputSignature(output)

    assert result == "FakeOutput:77"


def test_OutputSignatureFallsBackToPythonId(outputsPreviewModule):
    class NoObjId:
        pass

    output = NoObjId()
    result = outputsPreviewModule._outputSignature(output)

    assert result.startswith("NoObjId:")


def test_PreviewPdfReturnsInlineResponse(preview, tmp_path):
    pdfPath = tmp_path / "demo.pdf"
    pdfPath.write_bytes(b"%PDF-1.4 demo")

    response = preview._previewPdf(pdfPath, inline=True)

    assert response.media_type == "application/pdf"
    assert response.headers["Content-Disposition"] == 'inline; filename="demo.pdf"'
    assert response.body == b"%PDF-1.4 demo"


def test_IsArchiveSuffixRecognizesArchiveExtensions(preview):
    assert preview._isArchiveSuffix(".zip") is True
    assert preview._isArchiveSuffix(".tar") is True
    assert preview._isArchiveSuffix(".txt") is False


def test_PreviewArchiveInlineZipReturnsEntries(preview, tmp_path):
    zipPath = tmp_path / "demo.zip"
    with zipfile.ZipFile(zipPath, "w") as zf:
        zf.writestr("folder/", "")
        zf.writestr("folder/file.txt", "hello")

    response = preview._previewArchive(zipPath, inline=True)

    assert response.headers["X-Preview-Type"] == "archive"
    assert response.headers["X-Archive-Kind"] == "zip"

    payload = json.loads(response.body.decode("utf-8"))
    assert payload["entries"] == [
        {"name": "folder/", "isDir": True, "size": None, "compressedSize": None},
        {"name": "folder/file.txt", "isDir": False, "size": 5, "compressedSize": 5},
    ]


def test_PreviewArchiveAttachmentReturnsRawBytes(preview, tmp_path):
    zipPath = tmp_path / "demo.zip"
    with zipfile.ZipFile(zipPath, "w") as zf:
        zf.writestr("file.txt", "hello")

    response = preview._previewArchive(zipPath, inline=False)

    assert response.headers["Content-Disposition"] == 'attachment; filename="demo.zip"'
    assert response.body == zipPath.read_bytes()


def test_PreviewCsvTsvReturnsColumnsAndRows(preview, tmp_path):
    csvPath = tmp_path / "table.csv"
    csvPath.write_text("id,name\n1,alpha\n2,beta\n", encoding="utf-8")

    response = preview._previewCsvTsv(csvPath, limit=10, delimiter=",")

    assert response.headers["X-Preview-Type"] == "table"
    assert response.headers["X-Preview-Format"] == "csv"

    payload = json.loads(response.body.decode("utf-8"))
    assert payload == {
        "columns": ["id", "name"],
        "rows": [
            {"id": "1", "name": "alpha"},
            {"id": "2", "name": "beta"},
        ],
    }


def test_PreviewStarParsesLoopBlock(preview, tmp_path):
    starPath = tmp_path / "particles.star"
    starPath.write_text(
        "\n".join(
            [
                "data_particles",
                "loop_",
                "_rlnImageName #1",
                "_rlnDefocusU #2",
                "1@stack.mrcs 15000",
                "2@stack.mrcs 16000",
            ]
        ),
        encoding="utf-8",
    )

    response = preview._previewStar(starPath, limit=10)

    assert response.headers["X-Preview-Type"] == "table"
    assert response.headers["X-Preview-Format"] == "star"

    payload = json.loads(response.body.decode("utf-8"))
    assert payload == {
        "columns": ["rlnImageName", "rlnDefocusU"],
        "rows": [
            {"rlnImageName": "1@stack.mrcs", "rlnDefocusU": "15000"},
            {"rlnImageName": "2@stack.mrcs", "rlnDefocusU": "16000"},
        ],
    }


def test_PreviewStarWithoutLoopReturnsTextPreview(preview, tmp_path):
    starPath = tmp_path / "nolook.star"
    starPath.write_text("data_particles\n# no loop block here\n", encoding="utf-8")

    response = preview._previewStar(starPath, limit=10)

    assert response.headers["X-Preview-Type"] == "text"
    assert "STAR without loop_ block" in response.headers["X-Preview-Note"]

    payload = json.loads(response.body.decode("utf-8"))
    assert "data_particles" in payload["text"]


def test_FallbackBinaryAddsPreviewHeaders(preview, tmp_path):
    binPath = tmp_path / "data.bin"
    binPath.write_bytes(b"\x00\x01\x02\x03")

    response = preview._fallbackBinary(binPath, inline=True)

    assert response.headers["Content-Disposition"] == 'inline; filename="data.bin"'
    assert response.headers["X-Preview-Mime"] == "application/octet-stream"
    assert response.headers["X-Preview-SizeBytes"] == "4"
    assert response.body == b"\x00\x01\x02\x03"


def test_MergeHeadersAndGetHeaderAreCaseInsensitive(preview):
    preview._mergeHeaders(
        {
            "X-Scipion-Colormap": "viridis",
            "X-Preview-Colormap": "plasma",
        }
    )

    assert preview.requestHeaders["x-scipion-colormap"] == "viridis"
    assert preview.requestHeaders["x-preview-colormap"] == "plasma"
    assert preview._getHeader("X-Preview-Colormap") == "plasma"


def test_ResolveColormapForOutputTypeUsesOverrideFirst(outputsPreviewModule, tmp_path, monkeypatch):
    class FakeSetOfVolumes:
        # fakeSetOfVolumes
        pass

    monkeypatch.setattr(outputsPreviewModule, "SetOfVolumes", FakeSetOfVolumes)
    monkeypatch.setattr(outputsPreviewModule, "SetOfClasses3D", type("FakeSetOfClasses3D", (), {}))
    monkeypatch.setattr(
        outputsPreviewModule.RegistryViewerConfig,
        "getConfig",
        staticmethod(lambda outputType: {}),
    )

    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    preview = outputsPreviewModule.OutputsPreview(
        currentProject=FakeCurrentProject(str(protocolPath.parent.parent)),
        protocol=FakeProtocol(str(protocolPath)),
        output=FakeSetOfVolumes(),
        colormapOverride="inferno",
    )

    assert preview._resolveColormapForOutputType(defaultCmap="viridis") == "inferno"


def test_ResolveColormapForOutputTypeUsesHeaderWhenValid(outputsPreviewModule, tmp_path, monkeypatch):
    class FakeSetOfVolumes:
        # fakeSetOfVolumes
        pass

    monkeypatch.setattr(outputsPreviewModule, "SetOfVolumes", FakeSetOfVolumes)
    monkeypatch.setattr(outputsPreviewModule, "SetOfClasses3D", type("FakeSetOfClasses3D", (), {}))
    monkeypatch.setattr(
        outputsPreviewModule.RegistryViewerConfig,
        "getConfig",
        staticmethod(lambda outputType: {}),
    )

    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    preview = outputsPreviewModule.OutputsPreview(
        currentProject=FakeCurrentProject(str(protocolPath.parent.parent)),
        protocol=FakeProtocol(str(protocolPath)),
        output=FakeSetOfVolumes(),
        requestHeaders={"X-Scipion-Colormap": "viridis"},
    )

    assert preview._resolveColormapForOutputType(defaultCmap="plasma") == "viridis"


def test_PreviewDispatchesToPdf(preview, monkeypatch, tmp_path):
    pdfPath = tmp_path / "demo.pdf"
    pdfPath.write_bytes(b"%PDF-1.4 demo")

    monkeypatch.setattr(preview, "_previewPdf", lambda filePath, inline: {"kind": "pdf", "path": str(filePath)})

    result = preview.preview(protocolId=10, path=str(pdfPath), objectManager=FakeObjectManager())

    assert result == {"kind": "pdf", "path": str(pdfPath)}


def test_PreviewDispatchesToTextDelegate(preview, monkeypatch, tmp_path):
    textPath = tmp_path / "notes.txt"
    textPath.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(preview, "previewProtocolTextFile", lambda protocolId, path: {"kind": "text", "path": path})

    result = preview.preview(protocolId=10, path=str(textPath), objectManager=FakeObjectManager())

    assert result == {"kind": "text", "path": str(textPath)}


def test_PreviewDispatchesToImageDelegate(preview, monkeypatch, tmp_path):
    imgPath = tmp_path / "slice.mrc"
    imgPath.write_bytes(b"dummy")

    monkeypatch.setattr(preview, "_isPreviewableMrc", lambda filePath: True)
    monkeypatch.setattr(
        preview,
        "previewProtocolImageFile",
        lambda protocolId, path, inline: {"kind": "image", "path": path, "inline": inline},
    )

    result = preview.preview(protocolId=10, path=str(imgPath), objectManager=FakeObjectManager())

    assert result == {"kind": "image", "path": str(imgPath), "inline": True}


