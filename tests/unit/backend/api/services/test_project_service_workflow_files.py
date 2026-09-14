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
import json

import pytest
from fastapi import HTTPException

from app.backend.api.services.project_service import ProjectService


@pytest.fixture
def workflowFileService(tmp_path, monkeypatch):
    browserRoot = tmp_path / "browser"
    browserRoot.mkdir()

    monkeypatch.setenv(
        "SCIPION_IMPORT_BROWSER_ROOT",
        str(browserRoot),
    )

    service = object.__new__(ProjectService)
    service.currentProject = None

    return service, browserRoot


def writeWrappedWorkflow(path, requiredPlugins=None, content=None):
    payload = {
        "scipionWeb": {
            "format": "scipionweb.workflow.export",
            "version": 1,
            "requiredPluginNames": requiredPlugins or [],
        },
        "content": content or [
            {
                "object.id": "1",
                "object.className": "ProtImportMovies",
            }
        ],
    }

    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    return payload


def test_InspectWorkflowFileAcceptsScipionWebExport(
        workflowFileService,
        monkeypatch,
):
    service, browserRoot = workflowFileService

    workflowFile = browserRoot / "workflow.json"

    payload = writeWrappedWorkflow(
        workflowFile,
        requiredPlugins=["xmipp3", "relion"],
        content=[
            {
                "object.id": "1",
                "object.className": "ProtImportMovies",
            },
            {
                "object.id": "2",
                "object.className": "ProtMotionCorr",
                "inputMovies": "1.outputMovies",
            },
        ],
    )

    checkedPluginNames = []

    def getMissingPluginNames(requiredPluginNames):
        checkedPluginNames.append(list(requiredPluginNames))
        return []

    monkeypatch.setattr(
        service,
        "_getMissingWorkflowPluginNames",
        getMissingPluginNames,
    )

    result = service.inspectWorkflowFile(
        workflowPath="workflow.json",
        includeWorkflow=True,
    )

    assert checkedPluginNames == [
        ["xmipp3", "relion"],
    ]

    assert result["path"] == "workflow.json"
    assert result["fileName"] == "workflow.json"
    assert result["scipionWebWrapped"] is True
    assert result["protocolsCount"] == 2
    assert result["requiredPluginNames"] == ["xmipp3", "relion"]
    assert result["missingPluginNames"] == []
    assert result["canLoad"] is True
    assert result["disabledReason"] == ""
    assert result["workflow"] == payload["content"]


def test_InspectWorkflowFileReportsMissingPlugins(
        workflowFileService,
        monkeypatch,
):
    service, browserRoot = workflowFileService

    workflowFile = browserRoot / "workflow.json"

    writeWrappedWorkflow(
        workflowFile,
        requiredPlugins=["xmipp3", "relion"],
    )

    monkeypatch.setattr(
        service,
        "_getMissingWorkflowPluginNames",
        lambda requiredPluginNames: ["relion"],
    )

    result = service.inspectWorkflowFile(
        workflowPath="workflow.json",
    )

    assert result["requiredPluginNames"] == ["xmipp3", "relion"]
    assert result["missingPluginNames"] == ["relion"]
    assert result["canLoad"] is False
    assert result["disabledReason"] == "Missing required plugins: relion"
    assert "workflow" not in result


def test_InspectWorkflowFileAcceptsLegacyWorkflowJson(
        workflowFileService,
        monkeypatch,
):
    service, browserRoot = workflowFileService

    workflow = [
        {
            "object.id": "1",
            "object.className": "ProtImportFiles",
        },
        {
            "object.id": "2",
            "object.className": "ProtUnionSet",
            "inputSets": "1.outputSet",
        },
    ]

    workflowFile = browserRoot / "legacy.json"
    workflowFile.write_text(
        json.dumps(workflow),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        service,
        "_getMissingWorkflowPluginNames",
        lambda requiredPluginNames: [],
    )

    result = service.inspectWorkflowFile(
        workflowPath="legacy.json",
        includeWorkflow=True,
    )

    assert result["scipionWebWrapped"] is False
    assert result["protocolsCount"] == 2
    assert result["missingPluginNames"] == []
    assert result["canLoad"] is True
    assert result["workflow"] == workflow


def test_InspectWorkflowFileRejectsInvalidJson(
        workflowFileService,
):
    service, browserRoot = workflowFileService

    workflowFile = browserRoot / "broken.json"
    workflowFile.write_text(
        '{"content": [}',
        encoding="utf-8",
    )

    with pytest.raises(HTTPException) as error:
        service.inspectWorkflowFile(
            workflowPath="broken.json",
        )

    assert error.value.status_code == 422
    assert "Invalid workflow JSON" in str(error.value.detail)


def test_InspectWorkflowFileRejectsUnsupportedFiles(
        workflowFileService,
):
    service, browserRoot = workflowFileService

    workflowFile = browserRoot / "workflow.txt"
    workflowFile.write_text(
        "not a workflow",
        encoding="utf-8",
    )

    with pytest.raises(HTTPException) as error:
        service.inspectWorkflowFile(
            workflowPath="workflow.txt",
        )

    assert error.value.status_code == 422
    assert error.value.detail == "Workflow file must be a .json or .template file."


def test_InspectWorkflowFileRejectsPathOutsideBrowserRoot(
        workflowFileService,
        tmp_path,
):
    service, _ = workflowFileService

    outsideFile = tmp_path / "outside.json"
    outsideFile.write_text(
        "[]",
        encoding="utf-8",
    )

    with pytest.raises(HTTPException) as error:
        service.inspectWorkflowFile(
            workflowPath="../outside.json",
        )

    assert error.value.status_code == 403
    assert error.value.detail == "Workflow file is outside the allowed browser root."


def test_InspectWorkflowFileRejectsEmptyWorkflow(
        workflowFileService,
        monkeypatch,
):
    service, browserRoot = workflowFileService

    workflowFile = browserRoot / "empty.json"
    workflowFile.write_text(
        "[]",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        service,
        "_getMissingWorkflowPluginNames",
        lambda requiredPluginNames: [],
    )

    with pytest.raises(HTTPException) as error:
        service.inspectWorkflowFile(
            workflowPath="empty.json",
        )

    assert error.value.status_code == 422
    assert error.value.detail == "Workflow does not contain any protocols."


def test_InspectWorkflowFileAcceptsTemplateWorkflow(
        workflowFileService,
        monkeypatch,
):
    service, browserRoot = workflowFileService

    workflowFile = browserRoot / "workflow.template"

    payload = writeWrappedWorkflow(
        workflowFile,
        requiredPlugins=["xmipp3"],
        content=[
            {
                "object.id": "1",
                "object.className": "ProtImportMovies",
            },
            {
                "object.id": "2",
                "object.className": "ProtMotionCorr",
                "inputMovies": "1.outputMovies",
            },
        ],
    )

    monkeypatch.setattr(
        service,
        "_getMissingWorkflowPluginNames",
        lambda requiredPluginNames: [],
    )

    result = service.inspectWorkflowFile(
        workflowPath="workflow.template",
        includeWorkflow=True,
    )

    assert result["path"] == "workflow.template"
    assert result["fileName"] == "workflow.template"
    assert result["protocolsCount"] == 2
    assert result["requiredPluginNames"] == ["xmipp3"]
    assert result["missingPluginNames"] == []
    assert result["canLoad"] is True
    assert result["workflow"] == payload["content"]



