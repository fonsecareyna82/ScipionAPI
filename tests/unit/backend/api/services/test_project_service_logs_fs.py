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

class FakeDb:
    def __init__(
            self,
            runtimeProtocolIdByDbId=None,
    ):
        self.runtimeProtocolIdByDbId = (
            runtimeProtocolIdByDbId
            or {}
        )
        self.fetchCalls = []

    def fetchOne(
            self,
            query,
            params,
    ):
        self.fetchCalls.append({
            "query": query,
            "params": params,
        })

        if len(params) < 2:
            return None

        protocolDbId = params[1]

        runtimeProtocolId = (
            self.runtimeProtocolIdByDbId.get(
                int(protocolDbId)
            )
        )

        if runtimeProtocolId is None:
            return None

        return {
            "protocolId": runtimeProtocolId,
        }


class FakeMapper:
    def __init__(self, runtimeProtocolIdByDbId=None):
        self.db = FakeDb(runtimeProtocolIdByDbId=runtimeProtocolIdByDbId)


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

class FakePgDb:
    def __init__(self, projectPath, runtimeProtocolIdByDbId=None):
        self.projectPath = projectPath
        self.runtimeProtocolIdByDbId = runtimeProtocolIdByDbId or {}
        self.fetchCalls = []

    def fetchOne(self, query, params):
        self.fetchCalls.append({"query": query, "params": params})

        if "FROM projects" in query:
            return {"name": str(self.projectPath)}

        if "FROM protocols" in query:
            protocolDbId = params[1]
            runtimeProtocolId = self.runtimeProtocolIdByDbId.get(int(protocolDbId))
            if runtimeProtocolId is None:
                return None
            return {"protocolId": runtimeProtocolId}

        return None


class FakePgMapper:
    def __init__(self, projectPath, runtimeProtocolIdByDbId=None):
        self.db = FakePgDb(
            projectPath=projectPath,
            runtimeProtocolIdByDbId=runtimeProtocolIdByDbId,
        )


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


def test_GetProtocolLogsUsesPostgresqlPathsBeforeRuntime(
        service,
        tmp_path,
):
    projectPath = tmp_path / "DemoProject"
    protocolPath = projectPath / "Runs" / "000010_ProtImport"
    logsPath = protocolPath / "logs"
    logsPath.mkdir(parents=True, exist_ok=True)

    (logsPath / "run.stdout").write_text("abc\ndef\n", encoding="utf-8")
    (logsPath / "run.stderr").write_text("ERR1\nERR2\n", encoding="utf-8")
    (logsPath / "schedule.log").write_text("SCH1\nSCH2\n", encoding="utf-8")

    mapper = FakePgMapper(
        projectPath=projectPath,
        runtimeProtocolIdByDbId={500: 10},
    )

    def failRuntime(*args, **kwargs):
        raise AssertionError("runtime should not be used")

    service._getScipionProtocolByRuntimeId = failRuntime
    service.getProjectById = failRuntime

    result = service.getProtocolLogs(
        projectId=1,
        protocolId=500,
        offset=4,
        errOffset=5,
        scheduleOffset=5,
        mapper=mapper,
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


@pytest.mark.parametrize("protocolId", [None, "", "None", "none", "null", "undefined", "fake-protocol-id-for-browser-paths-resolution"])
def test_GetProtocolPathReturnsProjectRootForUnpersistedProtocol(service, protocolId):
    projectRoot = Path(service.currentProject.getPath()).resolve()
    result = service.getProtocolPath(protocolId)

    assert result == {
        "rootAbs": str(projectRoot),
        "startPath": "",
        "protocolRoot": "",
    }


def test_ListProtocolDirUsesProjectRootForUnpersistedProtocol(service):
    projectRoot = Path(service.currentProject.getPath()).resolve()
    inputDir = projectRoot / "input"
    inputDir.mkdir()

    result = service.listProtocolDir(protocolId="None", path="")

    assert len(result) == 1
    assert result[0]["name"] == "input"
    assert result[0]["path"] == "input"
    assert result[0]["isDir"] is True


def test_PreviewRemoteEntryUsesProjectRootForUnpersistedProtocol(service):
    projectRoot = Path(service.currentProject.getPath()).resolve()
    inputFile = projectRoot / "movies.txt"
    inputFile.write_text("movie_001.mrc", encoding="utf-8")

    response = service.previewRemoteEntry(protocolId="None", path="movies.txt")

    assert response.status_code == 200
    assert response.body.decode("utf-8") == "movie_001.mrc"


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


def test_GetProtocolPathResolvesPostgresqlProtocolId(service, tmp_path):
    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    service.currentProject.protocols[10] = FakeProtocol(protocolPath=str(protocolPath))
    mapper = FakeMapper(runtimeProtocolIdByDbId={500: 10})

    result = service.getProtocolPath(
        protocolId=500,
        mapper=mapper,
        projectId=1,
    )

    assert result == {
        "rootAbs": str((tmp_path / "DemoProject").resolve()),
        "startPath": "Runs/000010_ProtImport",
        "protocolRoot": "Runs/000010_ProtImport",
    }
    assert mapper.db.fetchCalls[0]["params"] == (1, 500)


def test_ListProtocolDirResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "FileHandlers", FakeFileHandlers)

    mapper = FakeMapper(runtimeProtocolIdByDbId={500: 10})

    result = service.listProtocolDir(
        protocolId="500",
        path="extra",
        mapper=mapper,
        projectId=1,
    )

    assert result == {
        "mode": "protocol",
        "protocolId": "10",
        "path": "extra",
    }
    assert FakeFileHandlers.lastInstance.calls == [
        ("listProtocolDir", "10", "extra"),
    ]
    assert mapper.db.fetchCalls[0]["params"] == (1, 500)


def test_PreviewProtocolTextFileResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "FileHandlers", FakeFileHandlers)

    mapper = FakeMapper(runtimeProtocolIdByDbId={500: 10})

    result = service.previewProtocolTextFile(
        protocolId="500",
        path="notes.txt",
        mapper=mapper,
        projectId=1,
    )

    assert result == {
        "mode": "protocol-text",
        "protocolId": "10",
        "path": "notes.txt",
    }
    assert FakeFileHandlers.lastInstance.calls == [
        ("previewProtocolTextFile", "10", "notes.txt"),
    ]
    assert mapper.db.fetchCalls[0]["params"] == (1, 500)


def test_PreviewRemoteEntryResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "FileHandlers", FakeFileHandlers)

    mapper = FakeMapper(runtimeProtocolIdByDbId={500: 10})

    result = service.previewRemoteEntry(
        protocolId="500",
        path="image.png",
        mapper=mapper,
        projectId=1,
    )

    assert result == {
        "mode": "protocol-preview",
        "protocolId": "10",
        "path": "image.png",
    }
    assert FakeFileHandlers.lastInstance.calls == [
        ("previewProtocolRemoteEntry", "10", "image.png"),
    ]
    assert mapper.db.fetchCalls[0]["params"] == (1, 500)


def test_PreviewProtocolImageFileResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    monkeypatch,
):
    monkeypatch.setattr(projectServiceModule, "FileHandlers", FakeFileHandlers)

    mapper = FakeMapper(runtimeProtocolIdByDbId={500: 10})

    result = service.previewProtocolImageFile(
        protocolId="500",
        path="preview.webp",
        inline=False,
        mapper=mapper,
        projectId=1,
    )

    assert result == {
        "mode": "protocol-image",
        "protocolId": "10",
        "path": "preview.webp",
        "inline": False,
    }
    assert FakeFileHandlers.lastInstance.calls == [
        ("previewProtocolImageFile", "10", "preview.webp", False),
    ]
    assert mapper.db.fetchCalls[0]["params"] == (1, 500)


def test_WriteRemoteFileServiceResolvesPostgresqlProtocolId(service, tmp_path):
    protocolPath = tmp_path / "DemoProject" / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    service.currentProject.protocols[10] = FakeProtocol(protocolPath=str(protocolPath))
    mapper = FakeMapper(runtimeProtocolIdByDbId={500: 10})

    class FakePayload:
        path = "exports/result.json"
        content = '{"ok": true}'
        mimeType = "application/json"

    result = service.writeRemoteFileService(
        protocolId=500,
        payload=FakePayload(),
        mapper=mapper,
        projectId=1,
    )

    targetPath = tmp_path / "DemoProject" / "exports" / "result.json"

    assert targetPath.exists() is True
    assert targetPath.read_text(encoding="utf-8") == '{"ok": true}'
    assert result == {
        "success": True,
        "path": str(targetPath.resolve()),
        "size": targetPath.stat().st_size,
        "mimeType": "application/json",
    }
    assert mapper.db.fetchCalls[0]["params"] == (1, 500)


def test_GetProtocolLogsNormalizesNegativeOffsets(service, tmp_path):
    stdoutLog = tmp_path / "stdout.log"
    stderrLog = tmp_path / "stderr.log"
    scheduleLog = tmp_path / "schedule.log"

    stdoutLog.write_text("abc\n", encoding="utf-8")
    stderrLog.write_text("ERR\n", encoding="utf-8")
    scheduleLog.write_text("SCH\n", encoding="utf-8")

    service.currentProject.protocols[10] = FakeProtocol(
        stdoutLog=str(stdoutLog),
        stderrLog=str(stderrLog),
        scheduleLog=str(scheduleLog),
    )

    result = service.getProtocolLogs(
        projectId=1,
        protocolId=10,
        offset=-10,
        errOffset=-5,
        scheduleOffset=-1,
    )

    assert result == {
        "stdoutLog": "abc\n",
        "stderrLog": "ERR\n",
        "stdoutOffset": 4,
        "stderrOffset": 4,
        "scheduleLog": "SCH\n",
        "scheduleOffset": 4,
    }


def test_ListProtocolLogChannelsServiceUsesPostgresqlPathsBeforeRuntime(
    service,
    tmp_path,
):
    projectPath = tmp_path / "DemoProject"
    protocolPath = projectPath / "Runs" / "000010_ProtImport"
    logsPath = protocolPath / "logs"
    logsPath.mkdir(parents=True, exist_ok=True)

    (logsPath / "run.stdout").write_text("hello\n", encoding="utf-8")
    (logsPath / "run.stderr").write_text("error\n", encoding="utf-8")
    (logsPath / "schedule.log").write_text("schedule\n", encoding="utf-8")

    mapper = FakePgMapper(
        projectPath=projectPath,
        runtimeProtocolIdByDbId={500: 10},
    )

    def failRuntime(*args, **kwargs):
        raise AssertionError("runtime should not be used")

    service._getScipionProtocolByRuntimeId = failRuntime

    result = service.listProtocolLogChannelsService(
        projectId=1,
        protocolId=500,
        mapper=mapper,
    )

    assert result == {
        "projectId": 1,
        "protocolId": 10,
        "channels": [
            {"id": "stdout", "label": "Output", "order": 1},
            {"id": "stderr", "label": "Errors", "order": 2},
            {"id": "schedule", "label": "Schedule", "order": 3},
        ],
    }


def test_PollProtocolLogsServiceUsesPostgresqlPathsBeforeRuntime(
    service,
    tmp_path,
):
    projectPath = tmp_path / "DemoProject"
    protocolPath = projectPath / "Runs" / "000010_ProtImport"
    logsPath = protocolPath / "logs"
    logsPath.mkdir(parents=True, exist_ok=True)

    (logsPath / "run.stdout").write_text("line1\nline2\nline3\n", encoding="utf-8")
    (logsPath / "run.stderr").write_text("err1\nerr2\n", encoding="utf-8")
    (logsPath / "schedule.log").write_text("sched1\nsched2\n", encoding="utf-8")

    mapper = FakePgMapper(
        projectPath=projectPath,
        runtimeProtocolIdByDbId={500: 10},
    )

    def failRuntime(*args, **kwargs):
        raise AssertionError("runtime should not be used")

    service._getScipionProtocolByRuntimeId = failRuntime

    result = service.pollProtocolLogsService(
        projectId=1,
        protocolId=500,
        offsets={
            "stdoutLog": 6,
            "err": 0,
            "schedule": 7,
        },
        maxBytes=64,
        maxLines=1,
        mapper=mapper,
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
                "content": "err1\n",
                "offset": 5,
            },
            "schedule": {
                "content": "sched2\n",
                "offset": 14,
            },
        },
    }


def test_PostgresqlProtocolLogsDoNotFallbackToRuntimeWhenFilesAreMissing(
        service,
        tmp_path,
):
    projectPath = tmp_path / "DemoProject"
    protocolPath = projectPath / "Runs" / "000010_ProtImport"
    protocolPath.mkdir(parents=True, exist_ok=True)

    mapper = FakePgMapper(
        projectPath=projectPath,
        runtimeProtocolIdByDbId={500: 10},
    )

    def failRuntime(*args, **kwargs):
        raise AssertionError("runtime should not be used")

    service._getScipionProtocolByRuntimeId = failRuntime
    service.getProjectById = failRuntime

    channels = service.listProtocolLogChannelsService(
        projectId=1,
        protocolId=500,
        mapper=mapper,
    )

    assert channels == {
        "projectId": 1,
        "protocolId": 10,
        "channels": [
            {"id": "stdout", "label": "Output", "order": 1},
            {"id": "stderr", "label": "Errors", "order": 2},
            {"id": "schedule", "label": "Schedule", "order": 3},
        ],
    }

    pollResult = service.pollProtocolLogsService(
        projectId=1,
        protocolId=500,
        offsets={
            "stdout": 0,
            "stderr": 0,
            "schedule": 0,
        },
        maxBytes=64,
        maxLines=10,
        mapper=mapper,
    )

    assert pollResult == {
        "projectId": 1,
        "protocolId": 10,
        "channels": {
            "stdout": {
                "content": "",
                "offset": 0,
            },
            "stderr": {
                "content": "",
                "offset": 0,
            },
            "schedule": {
                "content": "",
                "offset": 0,
            },
        },
    }

    with pytest.raises(HTTPException) as exc:
        service.getProtocolLogs(
            projectId=1,
            protocolId=500,
            mapper=mapper,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "No logs found"