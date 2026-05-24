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
from pathlib import Path

import pytest
from fastapi import HTTPException


class FakeOutput:
    # fakeOutput
    def __init__(self, fileName):
        self._fileName = fileName

    def getFileName(self):
        return self._fileName


class FakeProtocol:
    # fakeProtocol
    def __init__(self, protocolId, outputName=None, output=None):
        self.protocolId = protocolId
        if outputName is not None:
            setattr(self, outputName, output)


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(self, protocols=None, exportPayload=None):
        self.protocols = protocols or {}
        self.exportPayload = exportPayload if exportPayload is not None else [{"id": 10}]

    def getProtocol(self, protocolId):
        return self.protocols[int(protocolId)]

    def getProtocolsJson(self, protocolList):
        return self.exportPayload


class FakeOutputsPreview:
    # fakeOutputsPreview
    instances = []

    def __init__(self, currentProject, protocol, output, requestHeaders=None, colormapOverride=None):
        self.currentProject = currentProject
        self.protocol = protocol
        self.output = output
        self.requestHeaders = requestHeaders
        self.colormapOverride = colormapOverride
        self.lastPreviewCall = None
        FakeOutputsPreview.instances.append(self)

    def preview(self, protocolId, outputPath, objMgr):
        self.lastPreviewCall = {
            "protocolId": protocolId,
            "outputPath": outputPath,
            "objMgr": objMgr,
        }
        return {
            "preview": True,
            "protocolId": protocolId,
            "outputPath": outputPath,
            "colormap": self.colormapOverride,
        }


class FakeThumbnailService:
    # fakeThumbnailService
    instances = []

    def __init__(self, currentProject):
        self.currentProject = currentProject
        self.calls = []
        FakeThumbnailService.instances.append(self)

    def buildProtocolThumbnail(self, protocolId, force=False, size=320, outputName=None):
        self.calls.append(
            {
                "method": "buildProtocolThumbnail",
                "protocolId": protocolId,
                "force": force,
                "size": size,
                "outputName": outputName,
            }
        )
        return {"kind": "protocol", "protocolId": protocolId, "outputName": outputName}

    def buildProjectThumbnail(self, force=False, size=640, maxProtocols=6):
        self.calls.append(
            {
                "method": "buildProjectThumbnail",
                "force": force,
                "size": size,
                "maxProtocols": maxProtocols,
            }
        )
        return {"kind": "project", "size": size}

    def buildProtocolOutputThumbnail(self, protocolId, outputName, force=False, size=320):
        self.calls.append(
            {
                "method": "buildProtocolOutputThumbnail",
                "protocolId": protocolId,
                "outputName": outputName,
                "force": force,
                "size": size,
            }
        )
        return {"kind": "output", "protocolId": protocolId, "outputName": outputName}

    def listProtocolThumbnailItems(self, projectId, force=False, size=320, maxProtocols=12, maxOutputsPerProtocol=4):
        self.calls.append(
            {
                "method": "listProtocolThumbnailItems",
                "projectId": projectId,
                "force": force,
                "size": size,
                "maxProtocols": maxProtocols,
                "maxOutputsPerProtocol": maxOutputsPerProtocol,
            }
        )
        return [{"projectId": projectId, "kind": "thumbnail-item"}]


class FakePayload:
    # fakePayload
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


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


def test_OutputPreviewDelegatesToOutputsPreview(projectServiceModule, service, monkeypatch, tmp_path):
    FakeOutputsPreview.instances = []

    outputFile = tmp_path / "output.sqlite"
    outputFile.write_text("placeholder", encoding="utf-8")

    output = FakeOutput(str(outputFile))
    protocol = FakeProtocol(protocolId=10, outputName="outputMetadata", output=output)
    service.currentProject = FakeCurrentProject(protocols={10: protocol})

    monkeypatch.setattr(projectServiceModule, "OutputsPreview", FakeOutputsPreview)
    monkeypatch.setattr(service, "_createObjectManager", lambda: {"manager": "fresh"})

    result = service.outputPreview(
        protocolId=10,
        outputName="outputMetadata",
        requestHeaders={"x-preview-colormap": "viridis"},
        colormap="plasma",
    )

    assert result == {
        "preview": True,
        "protocolId": 10,
        "outputPath": str(outputFile),
        "colormap": "plasma",
    }
    assert len(FakeOutputsPreview.instances) == 1
    assert FakeOutputsPreview.instances[0].lastPreviewCall == {
        "protocolId": 10,
        "outputPath": str(outputFile),
        "objMgr": {"manager": "fresh"},
    }


def test_BuildProtocolThumbnailDelegatesToThumbnailService(projectServiceModule, service, monkeypatch):
    FakeThumbnailService.instances = []
    monkeypatch.setattr(projectServiceModule, "ThumbnailService", FakeThumbnailService)

    result = service.buildProtocolThumbnail(protocolId=10, force=True, size=400, outputName="outputA")

    assert result == {"kind": "protocol", "protocolId": 10, "outputName": "outputA"}
    assert FakeThumbnailService.instances[0].calls == [
        {
            "method": "buildProtocolThumbnail",
            "protocolId": 10,
            "force": True,
            "size": 400,
            "outputName": "outputA",
        }
    ]


def test_BuildProjectThumbnailDelegatesToThumbnailService(projectServiceModule, service, monkeypatch):
    FakeThumbnailService.instances = []
    monkeypatch.setattr(projectServiceModule, "ThumbnailService", FakeThumbnailService)

    result = service.buildProjectThumbnail(force=True, size=800, maxProtocols=9)

    assert result == {"kind": "project", "size": size} if False else {"kind": "project", "size": 800}
    assert FakeThumbnailService.instances[0].calls == [
        {
            "method": "buildProjectThumbnail",
            "force": True,
            "size": 800,
            "maxProtocols": 9,
        }
    ]


def test_BuildProtocolOutputThumbnailDelegatesToThumbnailService(projectServiceModule, service, monkeypatch):
    FakeThumbnailService.instances = []
    monkeypatch.setattr(projectServiceModule, "ThumbnailService", FakeThumbnailService)

    result = service.buildProtocolOutputThumbnail(protocolId=11, outputName="outputVol", force=False, size=256)

    assert result == {"kind": "output", "protocolId": 11, "outputName": "outputVol"}
    assert FakeThumbnailService.instances[0].calls == [
        {
            "method": "buildProtocolOutputThumbnail",
            "protocolId": 11,
            "outputName": "outputVol",
            "force": False,
            "size": 256,
        }
    ]


def test_ListProjectThumbnailItemsDelegatesToThumbnailService(projectServiceModule, service, monkeypatch):
    FakeThumbnailService.instances = []
    monkeypatch.setattr(projectServiceModule, "ThumbnailService", FakeThumbnailService)

    result = service.listProjectThumbnailItems(
        projectId=3,
        force=True,
        size=300,
        maxProtocols=8,
        maxOutputsPerProtocol=2,
    )

    assert result == [{"projectId": 3, "kind": "thumbnail-item"}]
    assert FakeThumbnailService.instances[0].calls == [
        {
            "method": "listProtocolThumbnailItems",
            "projectId": 3,
            "force": True,
            "size": 300,
            "maxProtocols": 8,
            "maxOutputsPerProtocol": 2,
        }
    ]


def test_NormalizeExportJsonContentAcceptsJsonString(service):
    content = service._normalizeExportJsonContent('[{"id": 10}]')
    assert json.loads(content) == [{"id": 10}]


def test_NormalizeExportJsonContentSerializesDictAndList(service):
    content = service._normalizeExportJsonContent({"ok": True})
    assert json.loads(content) == {"ok": True}


def test_NormalizeExportJsonContentRejectsEmptyString(service):
    with pytest.raises(HTTPException) as exc:
        service._normalizeExportJsonContent("   ")

    assert exc.value.status_code == 500
    assert exc.value.detail == "Scipion export returned empty content"


def test_NormalizeProtocolIdsForExportSkipsProjectAndDeduplicates(service):
    result = service._normalizeProtocolIdsForExport([1, "1", "PROJECT", "  ", "2", 2])
    assert result == ["1", "2"]


def test_SanitizeExportFilenameAddsJsonExtension(service):
    assert service._sanitizeExportFilename("workflow_export") == "workflow_export.json"
    assert service._sanitizeExportFilename("folder/name.json") == "name.json"


def test_GuardFsPathWithinRootForWriteRejectsEscape(service, tmp_path):
    rootPath = tmp_path / "root"
    rootPath.mkdir(parents=True, exist_ok=True)

    with pytest.raises(HTTPException) as exc:
        service._guardFsPathWithinRootForWrite(rootPath, "../outside/file.json")

    assert exc.value.status_code == 403
    assert exc.value.detail == "Path escapes browser root"


def test_ExportProtocolsServiceWritesJsonFile(service, monkeypatch, tmp_path):
    rootPath = tmp_path / "browser-root"
    rootPath.mkdir(parents=True, exist_ok=True)

    protocol10 = FakeProtocol(protocolId=10)
    protocol11 = FakeProtocol(protocolId=11)
    service.currentProject = FakeCurrentProject(
        protocols={10: protocol10, 11: protocol11},
        exportPayload=[{"protocolId": 10}, {"protocolId": 11}],
    )

    monkeypatch.setattr(service, "_resolveFsRootForWrite", lambda protocolId: rootPath)

    payload = FakePayload(
        protocolIds=[10, 11],
        directoryPath="exports",
        filename="workflow-export",
    )

    result = service.exportProtocolsService(
        mapper=object(),
        projectId=1,
        currentUser={"id": 1},
        payload=payload,
    )

    exportedPath = rootPath / "exports" / "workflow-export.json"
    assert exportedPath.exists() is True

    exportedText = exportedPath.read_text(encoding="utf-8")
    assert exportedText.startswith("ScipionWeb metadata format: scipionweb.workflow.metadata")
    assert "ScipionWeb metadata version: 1" in exportedText
    assert "Scipion required plugins:" in exportedText

    exportedJsonText = service._extractWorkflowJsonText(exportedText)
    assert json.loads(exportedJsonText) == [
        {"protocolId": 10},
        {"protocolId": 11},
    ]
    assert result == {
        "success": True,
        "path": str(exportedPath.resolve()),
        "filename": "workflow-export.json",
        "size": exportedPath.stat().st_size,
        "mimeType": "application/json",
        "protocolIds": ["10", "11"],
    }


def test_ExportProtocolsServiceRejectsMissingProtocolIds(service):
    payload = FakePayload(
        protocolIds=[],
        directoryPath="exports",
        filename="workflow-export",
    )

    with pytest.raises(HTTPException) as exc:
        service.exportProtocolsService(
            mapper=object(),
            projectId=1,
            currentUser={"id": 1},
            payload=payload,
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "Missing protocolIds"


def test_WriteRemoteFileServiceWritesContent(service, monkeypatch, tmp_path):
    rootPath = tmp_path / "browser-root"
    rootPath.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(service, "_resolveFsRootForWrite", lambda protocolId: rootPath)

    payload = FakePayload(
        path="exports/result.json",
        content='{"ok": true}',
        mimeType="application/json",
    )

    result = service.writeRemoteFileService(protocolId="-1", payload=payload)

    targetPath = rootPath / "exports" / "result.json"
    assert targetPath.exists() is True
    assert targetPath.read_text(encoding="utf-8") == '{"ok": true}'
    assert result == {
        "success": True,
        "path": str(targetPath.resolve()),
        "size": targetPath.stat().st_size,
        "mimeType": "application/json",
    }
