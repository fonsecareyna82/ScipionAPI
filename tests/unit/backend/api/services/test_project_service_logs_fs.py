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


class FakeProtocol:
    # fakeProtocol
    def __init__(self, protocolPath=None, stdoutLog=None, stderrLog=None, scheduleLog=None):
        self._protocolPath = protocolPath
        self._stdoutLog = stdoutLog
        self._stderrLog = stderrLog
        self._scheduleLog = scheduleLog

    def getPath(self):
        return self._protocolPath

    def getStdoutLog(self):
        return self._stdoutLog

    def getStderrLog(self):
        return self._stderrLog

    def getScheduleLog(self):
        return self._scheduleLog


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(self, projectPath):
        self._projectPath = projectPath
        self.protocols = {}

    def getPath(self):
        return self._projectPath

    def getProtocol(self, protocolId):
        return self.protocols[int(protocolId)]


class FakeFileHandlers:
    # fakeFileHandlers
    lastInstance = None

    def __init__(self, currentProject):
        self.currentProject = currentProject
        self.calls = []
        FakeFileHandlers.lastInstance = self

    def listRemoteDirectoryUnderRoot(self, root, path):
        self.calls.append(("listRemoteDirectoryUnderRoot", root, path))
        return {"mode": "global", "root": str(root), "path": path}

    def listProtocolDir(self, protocolId, path):
        self.calls.append(("listProtocolDir", protocolId, path))
        return {"mode": "protocol", "protocolId": protocolId, "path": path}

    def previewTextFileUnderRoot(self, root, path):
        self.calls.append(("previewTextFileUnderRoot", root, path))
        return {"mode": "global-text", "root": str(root), "path": path}

    def previewProtocolTextFile(self, protocolId, path):
        self.calls.append(("previewProtocolTextFile", protocolId, path))
        return {"mode": "protocol-text", "protocolId": protocolId, "path": path}

    def previewRemoteEntryUnderRoot(self, root, path, databaseInspector=None):
        self.calls.append(("previewRemoteEntryUnderRoot", root, path))
        return {"mode": "global-preview", "root": str(root), "path": path}

    def previewProtocolRemoteEntry(self, protocolId, path, databaseInspector=None):
        self.calls.append(("previewProtocolRemoteEntry", protocolId, path))
        return {"mode": "protocol-preview", "protocolId": protocolId, "path": path}

    def previewImageFileUnderRoot(self, root, path, inline):
        self.calls.append(("previewImageFileUnderRoot", root, path, inline))
        return {
            "mode": "global-image",
            "root": str(root),
            "path": path,
            "inline": inline,
        }

    def previewProtocolImageFile(self, protocolId, path, inline):
        self.calls.append(("previewProtocolImageFile", protocolId, path, inline))
        return {
            "mode": "protocol-image",
            "protocolId": protocolId,
            "path": path,
            "inline": inline,
        }


@pytest.fixture
def projectServiceModule(authTestEnv):
    # projectServiceModule
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule, tmp_path):
    # service
    projectRoot = tmp_path / "DemoProject"
    projectRoot.mkdir(parents=True, exist_ok=True)

    instance = object.__new__(projectServiceModule.ProjectService)
    instance.currentProject = FakeCurrentProject(str(projectRoot))
    instance.tomoList = {}
    return instance


def test_ListProtocolLogChannelsServiceReturnsStableChannels(service, tmp_path):
    stdoutLog = tmp_path / "stdout.log"
    stderrLog = tmp_path / "stderr.log"
    scheduleLog = tmp_path / "schedule.log"

    stdoutLog.write_text("hello\n", encoding="utf-8")
    stderrLog.write_text("error\n", encoding="utf-8")
    scheduleLog.write_text("schedule\n", encoding="utf-8")

    service.currentProject.protocols[10] = FakeProtocol(
        stdoutLog=str(stdoutLog),
        stderrLog=str(stderrLog),
        scheduleLog=str(scheduleLog),
    )

    result = service.listProtocolLogChannelsService(projectId=1, protocolId=10)

    assert result == {
        "projectId": 1,
        "protocolId": 10,
        "channels": [
            {"id": "stdout", "label": "Output", "order": 1},
            {"id": "stderr", "label": "Errors", "order": 2},
            {"id": "schedule", "label": "Schedule", "order": 3},
        ],
    }


def test_PollProtocolLogsServiceNormalizesOffsetsAndReadsChunks(service, tmp_path):
    stdoutLog = tmp_path / "stdout.log"
    scheduleLog = tmp_path / "schedule.log"

    stdoutLog.write_text("line1\nline2\nline3\n", encoding="utf-8")
    scheduleLog.write_text("sched1\nsched2\n", encoding="utf-8")

    service.currentProject.protocols[10] = FakeProtocol(
        stdoutLog=str(stdoutLog),
        stderrLog=str(tmp_path / "missing-stderr.log"),
        scheduleLog=str(scheduleLog),
    )

    result = service.pollProtocolLogsService(
        projectId=1,
        protocolId=10,
        offsets={
            "stdoutLog": 6,
            "err": 0,
            "schedule": 7,
        },
        maxBytes=64,
        maxLines=1,
    )

    assert result == {
        "projectId": 1,
        "protocolId": 10,
        "channels": {
            "stdout": {
                "content": "line2\n",
                "offset": 12,
            },
            "stderr": {
                "content": "",
                "offset": 0,
            },
            "schedule": {
                "content": "sched2\n",
                "offset": 14,
            },
        },
    }


def test_GetProtocolLogsReturns404WhenNoLogsExist(service, tmp_path):
    service.currentProject.protocols[10] = FakeProtocol(
        stdoutLog=str(tmp_path / "missing-stdout.log"),
        stderrLog=str(tmp_path / "missing-stderr.log"),
        scheduleLog=str(tmp_path / "missing-schedule.log"),
    )

    with pytest.raises(HTTPException) as exc:
        service.getProtocolLogs(projectId=1, protocolId=10, offset=0, errOffset=0, scheduleOffset=0)

    assert exc.value.status_code == 404
    assert exc.value.detail == "No logs found"


def test_GetProtocolLogsReadsAllChannelsFromOffsets(service, tmp_path):
    stdoutLog = tmp_path / "stdout.log"
    stderrLog = tmp_path / "stderr.log"
    scheduleLog = tmp_path / "schedule.log"

    stdoutLog.write_text("abc\ndef\n", encoding="utf-8")
    stderrLog.write_text("ERR1\nERR2\n", encoding="utf-8")
    scheduleLog.write_text("SCH1\nSCH2\n", encoding="utf-8")

    service.currentProject.protocols[10] = FakeProtocol(
        stdoutLog=str(stdoutLog),
        stderrLog=str(stderrLog),
        scheduleLog=str(scheduleLog),
    )

    result = service.getProtocolLogs(
        projectId=1,
        protocolId=10,
        offset=4,
        errOffset=5,
        scheduleOffset=5,
    )

    assert result == {
        "stdoutLog": "def\n",
        "stderrLog": "ERR2\n",
        "stdoutOffset": 8,
        "stderrOffset": 10,
        "scheduleLog": "SCH2\n",
        "scheduleOffset": 10,
    }


def test_GetProtocolPathReturnsGlobalBrowserPayload(service, monkeypatch, tmp_path):
    browserRoot = tmp_path / "browser-root"
    browserRoot.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SCIPION_IMPORT_BROWSER_ROOT", str(browserRoot))

    result = service.getProtocolPath("-1")

    assert result == {
        "rootAbs": str(browserRoot.resolve()),
        "startPath": "",
    }


def test_GetProtocolPathReturnsProtocolRelativePayload(service, tmp_path):
    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    service.currentProject.protocols[10] = FakeProtocol(protocolPath=str(protocolPath))

    result = service.getProtocolPath(10)

    assert result == {
        "rootAbs": str((tmp_path / "DemoProject").resolve()),
        "startPath": "Runs/000010_ProtImport",
        "protocolRoot": "Runs/000010_ProtImport",
    }


def test_InferProjectRootAbsUsesRunsMarker(service, tmp_path):
    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport" / "extra"

    result = service._inferProjectRootAbs(str(protocolPath))

    assert result == str((tmp_path / "DemoProject").resolve())


def test_ListProtocolDirDelegatesToGlobalBrowser(projectServiceModule, service, monkeypatch, tmp_path):
    browserRoot = tmp_path / "browser-root"
    browserRoot.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SCIPION_IMPORT_BROWSER_ROOT", str(browserRoot))
    monkeypatch.setattr(projectServiceModule, "FileHandlers", FakeFileHandlers)

    result = service.listProtocolDir(protocolId="-1", path="data")

    assert result == {
        "mode": "global",
        "root": str(browserRoot.resolve()),
        "path": "data",
    }
    assert FakeFileHandlers.lastInstance.calls == [
        ("listRemoteDirectoryUnderRoot", browserRoot.resolve(), "data"),
    ]


def test_ListProtocolDirDelegatesToProtocolBrowser(projectServiceModule, service, monkeypatch):
    monkeypatch.setattr(projectServiceModule, "FileHandlers", FakeFileHandlers)

    result = service.listProtocolDir(protocolId="10", path="extra")

    assert result == {
        "mode": "protocol",
        "protocolId": "10",
        "path": "extra",
    }
    assert FakeFileHandlers.lastInstance.calls == [
        ("listProtocolDir", "10", "extra"),
    ]


def test_PreviewProtocolTextFileDelegatesToGlobalBrowser(projectServiceModule, service, monkeypatch, tmp_path):
    browserRoot = tmp_path / "browser-root"
    browserRoot.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SCIPION_IMPORT_BROWSER_ROOT", str(browserRoot))
    monkeypatch.setattr(projectServiceModule, "FileHandlers", FakeFileHandlers)

    result = service.previewProtocolTextFile(protocolId="-1", path="notes.txt")

    assert result == {
        "mode": "global-text",
        "root": str(browserRoot.resolve()),
        "path": "notes.txt",
    }
    assert FakeFileHandlers.lastInstance.calls == [
        ("previewTextFileUnderRoot", browserRoot.resolve(), "notes.txt"),
    ]


def test_PreviewProtocolTextFileDelegatesToProtocolBrowser(projectServiceModule, service, monkeypatch):
    monkeypatch.setattr(projectServiceModule, "FileHandlers", FakeFileHandlers)

    result = service.previewProtocolTextFile(protocolId="10", path="notes.txt")

    assert result == {
        "mode": "protocol-text",
        "protocolId": "10",
        "path": "notes.txt",
    }
    assert FakeFileHandlers.lastInstance.calls == [
        ("previewProtocolTextFile", "10", "notes.txt"),
    ]


def test_PreviewRemoteEntryDelegatesToGlobalBrowser(projectServiceModule, service, monkeypatch, tmp_path):
    browserRoot = tmp_path / "browser-root"
    browserRoot.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SCIPION_IMPORT_BROWSER_ROOT", str(browserRoot))
    monkeypatch.setattr(projectServiceModule, "FileHandlers", FakeFileHandlers)

    result = service.previewRemoteEntry(protocolId="-1", path="image.png")

    assert result == {
        "mode": "global-preview",
        "root": str(browserRoot.resolve()),
        "path": "image.png",
    }
    assert FakeFileHandlers.lastInstance.calls == [
        ("previewRemoteEntryUnderRoot", browserRoot.resolve(), "image.png"),
    ]


def test_PreviewRemoteEntryDelegatesToProtocolBrowser(projectServiceModule, service, monkeypatch):
    monkeypatch.setattr(projectServiceModule, "FileHandlers", FakeFileHandlers)

    result = service.previewRemoteEntry(protocolId="10", path="image.png")

    assert result == {
        "mode": "protocol-preview",
        "protocolId": "10",
        "path": "image.png",
    }
    assert FakeFileHandlers.lastInstance.calls == [
        ("previewProtocolRemoteEntry", "10", "image.png"),
    ]


def test_PreviewProtocolImageFileDelegatesToGlobalBrowser(projectServiceModule, service, monkeypatch, tmp_path):
    browserRoot = tmp_path / "browser-root"
    browserRoot.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SCIPION_IMPORT_BROWSER_ROOT", str(browserRoot))
    monkeypatch.setattr(projectServiceModule, "FileHandlers", FakeFileHandlers)

    result = service.previewProtocolImageFile(protocolId="-1", path="preview.webp", inline=True)

    assert result == {
        "mode": "global-image",
        "root": str(browserRoot.resolve()),
        "path": "preview.webp",
        "inline": True,
    }
    assert FakeFileHandlers.lastInstance.calls == [
        ("previewImageFileUnderRoot", browserRoot.resolve(), "preview.webp", True),
    ]


def test_PreviewProtocolImageFileDelegatesToProtocolBrowser(projectServiceModule, service, monkeypatch):
    monkeypatch.setattr(projectServiceModule, "FileHandlers", FakeFileHandlers)

    result = service.previewProtocolImageFile(protocolId="10", path="preview.webp", inline=False)

    assert result == {
        "mode": "protocol-image",
        "protocolId": "10",
        "path": "preview.webp",
        "inline": False,
    }
    assert FakeFileHandlers.lastInstance.calls == [
        ("previewProtocolImageFile", "10", "preview.webp", False),
    ]