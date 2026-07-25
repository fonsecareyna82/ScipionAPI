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

class FakeDb:
    def __init__(self, runtimeProtocolIdByDbId=None):
        self.runtimeProtocolIdByDbId = runtimeProtocolIdByDbId or {}
        self.fetchCalls = []

    def fetchOne(self, query, params):
        self.fetchCalls.append({
            "query": query,
            "params": params,
        })

        if len(params) < 3:
            return None

        protocolDbId = params[1]
        runtimeProtocolId = self.runtimeProtocolIdByDbId.get(int(protocolDbId))
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

    def listProtocolThumbnailItems(
            self,
            projectId,
            force=False,
            size=320,
            maxProtocols=12,
            maxOutputsPerProtocol=4,
            inlineImages=False,
    ):
        self.calls.append(
            {
                "method": "listProtocolThumbnailItems",
                "projectId": projectId,
                "force": force,
                "size": size,
                "maxProtocols": maxProtocols,
                "maxOutputsPerProtocol": maxOutputsPerProtocol,
                "inlineImages": inlineImages,
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


def test_OutputPreviewResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    monkeypatch,
    tmp_path,
):
    FakeOutputsPreview.instances = []

    outputFile = tmp_path / "output.sqlite"
    outputFile.write_text("placeholder", encoding="utf-8")

    output = FakeOutput(str(outputFile))
    protocol = FakeProtocol(protocolId=10, outputName="outputMetadata", output=output)
    service.currentProject = FakeCurrentProject(protocols={10: protocol})

    mapper = FakeMapper(runtimeProtocolIdByDbId={500: 10})

    monkeypatch.setattr(projectServiceModule, "OutputsPreview", FakeOutputsPreview)
    monkeypatch.setattr(service, "_createObjectManager", lambda: {"manager": "fresh"})

    result = service.outputPreview(
        protocolId=500,
        outputName="outputMetadata",
        requestHeaders={"x-preview-colormap": "viridis"},
        colormap="plasma",
        mapper=mapper,
        projectId=1,
    )

    assert result == {
        "preview": True,
        "protocolId": 10,
        "outputPath": str(outputFile),
        "colormap": "plasma",
    }
    assert FakeOutputsPreview.instances[0].lastPreviewCall == {
        "protocolId": 10,
        "outputPath": str(outputFile),
        "objMgr": {"manager": "fresh"},
    }
    assert mapper.db.fetchCalls[0]["params"] == (1, 500, "500")


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


def test_BuildProtocolThumbnailResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    monkeypatch,
):
    FakeThumbnailService.instances = []
    monkeypatch.setattr(projectServiceModule, "ThumbnailService", FakeThumbnailService)

    mapper = FakeMapper(runtimeProtocolIdByDbId={500: 10})

    result = service.buildProtocolThumbnail(
        protocolId=500,
        force=True,
        size=400,
        outputName="outputA",
        mapper=mapper,
        projectId=1,
    )

    assert result == {
        "kind": "protocol",
        "protocolId": 10,
        "outputName": "outputA",
    }
    assert FakeThumbnailService.instances[0].calls == [
        {
            "method": "buildProtocolThumbnail",
            "protocolId": 10,
            "force": True,
            "size": 400,
            "outputName": "outputA",
        }
    ]
    assert mapper.db.fetchCalls[0]["params"] == (1, 500, "500")


def test_BuildProjectThumbnailDelegatesToThumbnailService(projectServiceModule, service, monkeypatch):
    FakeThumbnailService.instances = []
    monkeypatch.setattr(projectServiceModule, "ThumbnailService", FakeThumbnailService)

    result = service.buildProjectThumbnail(force=True, size=800, maxProtocols=9)

    assert result == {"kind": "project", "size": 800}
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


def test_BuildProtocolOutputThumbnailResolvesPostgresqlProtocolId(
    projectServiceModule,
    service,
    monkeypatch,
):
    FakeThumbnailService.instances = []
    monkeypatch.setattr(projectServiceModule, "ThumbnailService", FakeThumbnailService)

    mapper = FakeMapper(runtimeProtocolIdByDbId={501: 11})

    result = service.buildProtocolOutputThumbnail(
        protocolId=501,
        outputName="outputVol",
        force=False,
        size=256,
        mapper=mapper,
        projectId=1,
    )

    assert result == {
        "kind": "output",
        "protocolId": 11,
        "outputName": "outputVol",
    }
    assert FakeThumbnailService.instances[0].calls == [
        {
            "method": "buildProtocolOutputThumbnail",
            "protocolId": 11,
            "outputName": "outputVol",
            "force": False,
            "size": 256,
        }
    ]
    assert mapper.db.fetchCalls[0]["params"] == (1, 501, "501")


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
            "inlineImages": False,
        }
    ]


def test_ListProjectThumbnailItemsKeepsDetachedPostgresqlOutputs(
        projectServiceModule,
        service,
        monkeypatch,
):
    expectedItems = [
        {
            "projectId": 1,
            "protocolId": 10,
            "outputs": [
                {
                    "outputName": (
                        "outputTiltSeries"
                    ),
                },
            ],
        },
    ]

    class FakeThumbnailServiceWithItems:
        def __init__(
                self,
                currentProject,
        ):
            self.currentProject = (
                currentProject
            )

        def listProtocolThumbnailItems(
                self,
                projectId,
                force=False,
                size=320,
                maxProtocols=12,
                maxOutputsPerProtocol=4,
                inlineImages=False,
        ):
            return expectedItems

    monkeypatch.setattr(
        projectServiceModule,
        "ThumbnailService",
        FakeThumbnailServiceWithItems,
    )

    result = (
        service
        .listProjectThumbnailItems(
            projectId=1,
            force=False,
            size=128,
            maxProtocols=4,
            maxOutputsPerProtocol=2,
            inlineImages=True,
            mapper=object(),
        )
    )

    assert result == expectedItems


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

    monkeypatch.setattr(
        service,
        "_resolveFsRootForWrite",
        lambda protocolId, mapper=None, projectId=None: rootPath,
    )

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

    monkeypatch.setattr(
        service,
        "_resolveFsRootForWrite",
        lambda protocolId, mapper=None, projectId=None: rootPath,
    )

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


def test_GetProtocolOutputThumbnailsBatchResolvesPostgresqlProtocolId(
    service,
    monkeypatch,
    tmp_path,
):
    projectRouterModule = importlib.import_module("app.backend.api.routers.project_router")

    outputFile = tmp_path / "output.sqlite"
    outputFile.write_text("placeholder", encoding="utf-8")

    thumbnailFile = tmp_path / "thumbnail.png"
    thumbnailFile.write_bytes(b"fake-thumbnail")

    output = FakeOutput(str(outputFile))
    protocol = FakeProtocol(protocolId=10, outputName="outputVol", output=output)
    service.currentProject = FakeCurrentProject(protocols={10: protocol})

    mapper = FakeMapper(runtimeProtocolIdByDbId={500: 10})

    monkeypatch.setattr(
        service,
        "getProjectDbRow",
        lambda mapper, projectId, currentUser: {"id": projectId, "name": str(tmp_path)},
    )
    monkeypatch.setattr(
        service,
        "loadProjectForThumbnails",
        lambda dbProj: service.currentProject,
    )

    buildCalls = []

    def fakeBuildProtocolOutputThumbnail(
        protocolId,
        outputName,
        force=False,
        size=320,
        mapper=None,
        projectId=None,
    ):
        buildCalls.append({
            "protocolId": protocolId,
            "outputName": outputName,
            "force": force,
            "size": size,
            "mapper": mapper,
            "projectId": projectId,
        })
        return {
            "absolutePath": str(thumbnailFile),
            "exists": True,
            "cached": False,
        }

    monkeypatch.setattr(
        service,
        "buildProtocolOutputThumbnail",
        fakeBuildProtocolOutputThumbnail,
    )

    payload = FakePayload(
        outputs=[
            FakePayload(protocolId=500, outputName="outputVol"),
        ],
        size=256,
        inlineImages=False,
    )

    response = projectRouterModule.getProtocolOutputThumbnailsBatch(
        projectId=1,
        payload=payload,
        currentUser={"id": 1},
        mapper=mapper,
        service=service,
    )

    payloadJson = json.loads(response.body.decode("utf-8"))

    assert payloadJson == {
        "projectId": 1,
        "size": 256,
        "items": [
            {
                "protocolId": 500,
                "outputName": "outputVol",
                "outputClassName": "FakeOutput",
                "exists": True,
                "cached": False,
                "thumbnailUrl": "/projects/1/protocols/500/outputs/outputVol/thumbnail",
                "thumbnailDataUrl": None,
                "error": None,
            }
        ],
    }

    assert buildCalls == [
        {
            "protocolId": 500,
            "outputName": "outputVol",
            "force": False,
            "size": 256,
            "mapper": mapper,
            "projectId": 1,
        }
    ]

    assert mapper.db.fetchCalls[0]["params"] == (1, 500, "500")


def test_ExportProtocolsServiceResolvesPostgresqlProtocolIdsAndWritesJsonFile(
    service,
    monkeypatch,
    tmp_path,
):
    rootPath = tmp_path / "browser-root"
    rootPath.mkdir(parents=True, exist_ok=True)

    protocol10 = FakeProtocol(protocolId=10)
    protocol11 = FakeProtocol(protocolId=11)

    service.currentProject = FakeCurrentProject(
        protocols={
            10: protocol10,
            11: protocol11,
        },
        exportPayload=[
            {"protocolId": 10},
            {"protocolId": 11},
        ],
    )

    exportedProtocolLists = []

    def fakeGetProtocolsJson(protocolList):
        exportedProtocolLists.append(protocolList)
        return [
            {"protocolId": 10},
            {"protocolId": 11},
        ]

    service.currentProject.getProtocolsJson = fakeGetProtocolsJson

    mapper = FakeMapper(runtimeProtocolIdByDbId={
        500: 10,
        501: 11,
    })

    monkeypatch.setattr(
        service,
        "_resolveFsRootForWrite",
        lambda protocolId, mapper=None, projectId=None: rootPath,
    )

    payload = FakePayload(
        protocolIds=["500", "501"],
        directoryPath="exports",
        filename="workflow-export",
    )

    result = service.exportProtocolsService(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 1},
        payload=payload,
    )

    exportedPath = rootPath / "exports" / "workflow-export.json"

    assert exportedProtocolLists == [[protocol10, protocol11]]
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
        "protocolIds": ["500", "501"],
    }

    assert mapper.db.fetchCalls[0]["params"] == (1, 500, "500")
    assert mapper.db.fetchCalls[1]["params"] == (1, 501, "501")


def test_OutputPreviewDelegatesToRuntimeFallback(service, monkeypatch):
    captured = {}

    def fakeRuntime(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(service, "_outputPreviewRuntime", fakeRuntime)

    result = service.outputPreview(
        protocolId=500,
        outputName="outputMetadata",
        requestHeaders={"x-preview-colormap": "viridis"},
        colormap="plasma",
        mapper="mapper",
        projectId=1,
    )

    assert result == {"ok": True}
    assert captured == {
        "protocolId": 500,
        "outputName": "outputMetadata",
        "requestHeaders": {"x-preview-colormap": "viridis"},
        "colormap": "plasma",
        "mapper": "mapper",
        "projectId": 1,
    }


def test_LoadProjectForThumbnailsUsesPostgresqlWhenProjectDbIsMissing(
        projectServiceModule,
        service,
        monkeypatch,
        tmp_path,
):
    projectPath = (
        tmp_path
        / "PostgresqlProject"
    )

    projectPath.mkdir()

    class FakeLegacyProject:
        def __init__(
                self,
                domain,
                path,
        ):
            self.domain = domain
            self.path = path
            self.loadCalls = []

        def getDbPath(self):
            return str(
                projectPath
                / "project.sqlite"
            )

        def load(
                self,
                dbPath,
        ):
            self.loadCalls.append(
                dbPath
            )

    monkeypatch.setattr(
        projectServiceModule,
        "ScipionProject",
        FakeLegacyProject,
    )

    mapper = object()
    postgresqlProject = object()
    loadCalls = []

    def loadPostgresqlRuntimeProject(
            **kwargs,
    ):
        loadCalls.append(
            dict(kwargs)
        )

        return postgresqlProject

    monkeypatch.setattr(
        service,
        "_loadPostgresqlRuntimeProject",
        loadPostgresqlRuntimeProject,
    )

    result = (
        service
        .loadProjectForThumbnails(
            dbProj={
                "id": 342,
                "name": str(
                    projectPath
                ),
            },
            mapper=mapper,
        )
    )

    assert result is postgresqlProject

    assert loadCalls == [{
        "mapper": mapper,
        "projectId": 342,
        "projectPath": str(
            projectPath
        ),
        "enableWriteFallback": False,
    }]


def test_LoadProjectForThumbnailsKeepsLegacySqlitePath(
        projectServiceModule,
        service,
        monkeypatch,
        tmp_path,
):
    projectPath = (
        tmp_path
        / "LegacyProject"
    )

    projectPath.mkdir()

    projectDbPath = (
        projectPath
        / "project.sqlite"
    )

    projectDbPath.write_bytes(
        b"sqlite"
    )

    createdProjects = []

    class FakeLegacyProject:
        def __init__(
                self,
                domain,
                path,
        ):
            self.domain = domain
            self.path = path
            self.loadCalls = []

            createdProjects.append(
                self
            )

        def getDbPath(self):
            return str(
                projectDbPath
            )

        def load(
                self,
                dbPath,
        ):
            self.loadCalls.append(
                dbPath
            )

    monkeypatch.setattr(
        projectServiceModule,
        "ScipionProject",
        FakeLegacyProject,
    )

    def failPostgresqlLoad(
            **kwargs,
    ):
        raise AssertionError(
            "PostgreSQL runtime must not be "
            "used when project.sqlite exists."
        )

    monkeypatch.setattr(
        service,
        "_loadPostgresqlRuntimeProject",
        failPostgresqlLoad,
    )

    result = (
        service
        .loadProjectForThumbnails(
            dbProj={
                "id": 17,
                "name": str(
                    projectPath
                ),
            },
            mapper=object(),
        )
    )

    assert result is createdProjects[0]

    assert (
        createdProjects[0].loadCalls
        == [
            str(projectDbPath),
        ]
    )


