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

from app.backend.api.services.project_service import ProjectService


class FakePostgresqlProject:
    def __init__(self, loadResult):
        self.loadResult = loadResult
        self.loadCalls = []

    def usingPostgresqlRuntimeMapper(self):
        raise AssertionError(
            "Workflow application must not inspect a runtime mapper mode switch"
        )

    def loadProtocols(self, *args, **kwargs):
        assert args == ()
        self.loadCalls.append(kwargs)
        return self.loadResult


class FakeWorkflowTemplate:
    id = "wf-1"
    source = "tests"
    name = "Workflow 1"
    params = {}

    def __init__(self, workflowFile):
        self.workflowFile = workflowFile

    def replaceEnvVariables(self):
        return None

    def createTemplateFile(self):
        return str(self.workflowFile)


def test_ApplyWorkflowPersistsOnlyImportedPostgresqlProtocols(tmp_path, monkeypatch):
    workflowContent = [
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

    workflowFile = tmp_path / "workflow.json"
    workflowFile.write_text(
        json.dumps(workflowContent),
        encoding="utf-8",
    )

    importedParent = object()
    importedChild = object()
    loadResult = {
        "1": importedParent,
        "2": importedChild,
    }

    service = object.__new__(ProjectService)
    service.currentProject = FakePostgresqlProject(loadResult)

    monkeypatch.setattr(
        service,
        "getProjectById",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Legacy project loading must not be used")
        ),
    )

    monkeypatch.setattr(
        service,
        "_syncLegacyProjectGraphToPostgresql",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("The complete legacy project graph must not be synchronized")
        ),
    )

    monkeypatch.setattr(
        service,
        "listProjectWorkflows",
        lambda raw=False: [
            FakeWorkflowTemplate(workflowFile),
        ],
    )

    monkeypatch.setattr(
        service,
        "_prepareWorkflowFileForImport",
        lambda path: {
            "workflowFile": str(path),
            "cleanupFile": None,
            "wrapped": False,
            "hasScipionWebMetadata": False,
            "requiredPluginNames": [],
        },
    )

    monkeypatch.setattr(
        service,
        "_normalizeWorkflowImportErrors",
        lambda result: [],
    )

    monkeypatch.setattr(
        service,
        "_workflowProtocolMapToProtocols",
        lambda result: [
            importedParent,
            importedChild,
        ],
    )

    monkeypatch.setattr(
        service,
        "_buildImportedWorkflowPointerParamsByProtocolId",
        lambda **kwargs: {
            "2": {
                "inputSets": "1.outputSet",
            },
        },
    )

    syncCalls = []

    def syncImportedProtocols(**kwargs):
        syncCalls.append(kwargs)

        return {
            "protocols": 2,
            "dependencies": 1,
            "inputRefs": 1,
            "reports": [
                {"protocolId": "1"},
                {"protocolId": "2"},
            ],
        }

    monkeypatch.setattr(
        service,
        "_syncImportedPostgresqlRuntimeProtocols",
        syncImportedProtocols,
    )

    result = service.applyWorkflowToProject(
        mapper=object(),
        projectId=364,
        workflowId="wf-1",
        currentUser={"id": 1},
    )

    assert service.currentProject.loadCalls == [
        {
            "jsonStr": json.dumps(
                workflowContent,
                ensure_ascii=False,
            ),
        },
    ]

    assert len(syncCalls) == 1
    assert syncCalls[0]["projectId"] == 364
    assert syncCalls[0]["protocols"] == [
        importedParent,
        importedChild,
    ]

    assert result["protocolsCount"] == 2
    assert result["dependenciesCount"] == 1
    assert result["inputRefsCount"] == 1