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
from fastapi import HTTPException, Response


class FakeProtocol:
    # fakeProtocol
    def __init__(self, protocolPath):
        self._protocolPath = protocolPath

    def getPath(self):
        return self._protocolPath


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(self, projectPath, protocolPath):
        self._projectPath = projectPath
        self._protocol = FakeProtocol(protocolPath)

    def getProtocol(self, protocolId):
        return self._protocol

    def getPath(self):
        return self._projectPath


@pytest.fixture
def fileHandlersModule(authTestEnv):
    # fileHandlersModule
    return importlib.import_module("app.backend.utils.file_handlers")


@pytest.fixture
def handlers(fileHandlersModule, tmp_path):
    # handlers
    projectRoot = tmp_path / "DemoProject"
    protocolPath = projectRoot / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    currentProject = FakeCurrentProject(
        projectPath=str(projectRoot),
        protocolPath=str(protocolPath),
    )
    return fileHandlersModule.FileHandlers(currentProject)


def test_GetProtocolPathBuildsBrowserContract(handlers):
    result = handlers.getProtocolPath("10")

    assert result["rootAbs"].endswith("/DemoProject")
    assert result["startPath"] == "Runs/000010_ProtImport"
    assert result["protocolRoot"] == "Runs/000010_ProtImport"
    assert result["path"].endswith("/DemoProject/Runs/000010_ProtImport")


def test_NormalizeRelPathClampsTraversal(fileHandlersModule):
    assert fileHandlersModule.FileHandlers._normalizeRelPath("../a/../../b/./c") == "b/c"
    assert fileHandlersModule.FileHandlers._normalizeRelPath("") == ""
    assert fileHandlersModule.FileHandlers._normalizeRelPath("/") == ""


def test_GuardJoinRejectsAbsolutePaths(fileHandlersModule, tmp_path):
    root = (tmp_path / "root").resolve()
    root.mkdir(parents=True, exist_ok=True)

    with pytest.raises(HTTPException) as exc:
        fileHandlersModule.FileHandlers._guardJoin(root, "/etc/passwd")

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid path"


def test_ResolveWithinRootAcceptsAbsoluteChildPath(handlers, tmp_path):
    root = (tmp_path / "root").resolve()
    root.mkdir(parents=True, exist_ok=True)

    child = root / "folder" / "file.txt"
    child.parent.mkdir(parents=True, exist_ok=True)
    child.write_text("hello", encoding="utf-8")

    resolved = handlers._resolveWithinRoot(root, str(child))

    assert resolved == child


def test_ListRemoteDirectoryUnderRootReturnsSortedEntries(handlers, tmp_path):
    root = tmp_path / "browser-root"
    root.mkdir(parents=True, exist_ok=True)

    folder = root / "FolderA"
    folder.mkdir()

    fileTxt = root / "zeta.txt"
    fileTxt.write_text("demo", encoding="utf-8")

    result = handlers.listRemoteDirectoryUnderRoot(root, "")

    assert result[0]["name"] == "FolderA"
    assert result[0]["isDir"] is True
    assert result[0]["path"] == "FolderA"

    assert result[1]["name"] == "zeta.txt"
    assert result[1]["isDir"] is False
    assert result[1]["path"] == "zeta.txt"
    assert result[1]["size"] == 4
    assert result[1]["mime"] == "text/plain"


def test_PreviewTextFileUnderRootReturnsPlainText(handlers, tmp_path):
    root = tmp_path / "browser-root"
    root.mkdir(parents=True, exist_ok=True)

    fileTxt = root / "notes.txt"
    fileTxt.write_text("hello file handlers", encoding="utf-8")

    response = handlers.previewTextFileUnderRoot(root, "notes.txt")

    assert isinstance(response, Response)
    assert response.media_type == "text/plain; charset=utf-8"
    assert response.body.decode("utf-8") == "hello file handlers"


def test_PreviewTextFileUnderRootRejectsBinaryFile(handlers, tmp_path):
    root = tmp_path / "browser-root"
    root.mkdir(parents=True, exist_ok=True)

    fileBin = root / "data.bin"
    fileBin.write_bytes(b"\x00\x01\x02")

    with pytest.raises(HTTPException) as exc:
        handlers.previewTextFileUnderRoot(root, "data.bin")

    assert exc.value.status_code == 415
    assert exc.value.detail == "Preview not available for this file type"


def test_BuildPreviewHeadersIncludesExposeList(handlers):
    headers = handlers._buildPreviewHeaders(
        {
            "kind": "text",
            "name": "notes.txt",
            "mime": "text/plain",
            "responseMime": "text/plain; charset=utf-8",
            "width": 10,
            "height": 20,
            "sizeBytes": 123,
            "note": "preview note",
        }
    )

    assert headers["X-Preview-Kind"] == "text"
    assert headers["X-Preview-Name"] == "notes.txt"
    assert headers["X-Preview-Mime"] == "text/plain"
    assert headers["X-Preview-ResponseMime"] == "text/plain; charset=utf-8"
    assert headers["X-Preview-Width"] == "10"
    assert headers["X-Preview-Height"] == "20"
    assert headers["X-Preview-SizeBytes"] == "123"
    assert headers["X-Preview-Note"] == "preview note"
    assert headers["X-Preview-Schema"] == "scipion"
    assert "X-Preview-Kind" in headers["Access-Control-Expose-Headers"]


def test_AttachPreviewContractAddsHeaders(handlers):
    response = Response(content=b"hello", media_type="text/plain")

    enriched = handlers._attachPreviewContract(
        response=response,
        kind="text",
        name="notes.txt",
        meta={"mime": "text/plain", "sizeBytes": 5},
    )

    assert enriched.headers["Content-Disposition"] == 'inline; filename="notes.txt"'
    assert enriched.headers["X-Preview-Kind"] == "text"
    assert enriched.headers["X-Preview-Name"] == "notes.txt"
    assert enriched.headers["X-Preview-Mime"] == "text/plain"
    assert enriched.headers["X-Preview-ResponseMime"] == "text/plain"
    assert enriched.headers["X-Preview-SizeBytes"] == "5"


def test_PreviewRemoteEntryUnderRootWrapsTextPreviewWithContract(handlers, tmp_path):
    root = tmp_path / "browser-root"
    root.mkdir(parents=True, exist_ok=True)

    fileTxt = root / "notes.txt"
    fileTxt.write_text("hello preview contract", encoding="utf-8")

    response = handlers.previewRemoteEntryUnderRoot(root, "notes.txt")

    assert response.media_type == "text/plain; charset=utf-8"
    assert response.body.decode("utf-8") == "hello preview contract"
    assert response.headers["X-Preview-Kind"] == "text"
    assert response.headers["X-Preview-Name"] == "notes.txt"
    assert response.headers["X-Preview-Mime"] == "text/plain"
    assert response.headers["X-Preview-Schema"] == "scipion"