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
def test_ListProjectWorkflowsReturnsServiceResult(projectClient):
    response = projectClient.get("/projects/workflows")

    assert response.status_code == 200
    assert response.json() == [{"id": "wf-1", "name": "Workflow 1"}]


def test_ListProjectWorkflowsWrapsUnexpectedErrorAs500(projectClient, fakeProjectService):
    fakeProjectService.listProjectWorkflowsError = RuntimeError("workflow exploded")

    response = projectClient.get("/projects/workflows")

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to load workflows: workflow exploded"


def test_GetProjectReturns404WhenProjectDoesNotExist(projectClient, fakeProjectService):
    fakeProjectService.projectByIdResult = None

    response = projectClient.get("/projects/1")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_GetProjectCallsServiceWithRefreshAndCheckPid(projectClient, fakeProjectService):
    response = projectClient.get("/projects/1")

    assert response.status_code == 200
    assert response.json()["id"] == 1
    assert fakeProjectService.lastGetProjectByIdCall == {
        "mapper": fakeProjectService.lastGetProjectByIdCall["mapper"],
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
        "refresh": True,
        "checkPid": True,
        "validateConsistency": False,
        "failOnConsistencyError": False,
    }


def test_CheckProjectPostgresqlConsistencyCallsService(projectClient, fakeProjectService):
    response = projectClient.post(
        "/projects/1/consistency/check?refresh=false&checkPid=false"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.consistencyResult
    assert fakeProjectService.lastValidateProjectPostgresqlConsistencyCall == {
        "mapper": fakeProjectService.lastValidateProjectPostgresqlConsistencyCall["mapper"],
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
        "refresh": False,
        "checkPid": False,
    }


def test_LoadProtocolsReturns404WhenProjectDoesNotExist(projectClient, fakeProjectService):
    fakeProjectService.projectByIdResult = None

    response = projectClient.get("/projects/1/protocols")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_LoadProtocolsReturns404WhenProtocolsAreMissing(projectClient, fakeProjectService):
    fakeProjectService.protocolsResult = []

    response = projectClient.get("/projects/1/protocols")

    assert response.status_code == 404
    assert response.json()["detail"] == "Protocols not found"


def test_LoadProtocolsReturnsProtocols(projectClient, fakeProjectService):
    fakeProjectService.protocolsResult = [{"id": 11, "name": "Prot A"}]

    response = projectClient.get("/projects/1/protocols")

    assert response.status_code == 200
    assert response.json() == [{"id": 11, "name": "Prot A"}]


def test_ListProtocolLogChannelsNormalizesStringAndDictItems(projectClient, fakeProjectService):
    fakeProjectService.logChannelsResult = [
        "stdout",
        {"id": "stderr", "label": "Errors"},
        {"bad": "shape"},
    ]

    response = projectClient.get("/projects/1/protocols/22/logs/channels")

    assert response.status_code == 200
    assert response.json() == {
        "channels": [
            {"id": "stdout"},
            {"id": "stderr", "label": "Errors"},
        ]
    }


def test_PollProtocolLogsNormalizesOffsetsAndIncludesDynamicChannels(projectClient, fakeProjectService):
    fakeProjectService.pollLogsResult = {
        "channels": {
            "stdout": {"content": "hello", "offset": 5, "truncated": False},
            "custom": {"content": "world", "offset": 9, "truncated": True},
        }
    }

    response = projectClient.post(
        "/projects/1/protocols/22/logs/chunk?includeDefault=true",
        json={
            "offsets": {"stdout": 2},
            "maxBytes": 123,
            "maxLines": 45,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "chunks": [
            {"channel": "stdout", "content": "hello", "offset": 5},
            {"channel": "stderr", "content": "", "offset": 0},
            {"channel": "schedule", "content": "", "offset": 0},
            {"channel": "custom", "content": "world", "offset": 9},
        ]
    }

    assert fakeProjectService.lastPollLogsCall == {
        "projectId": 1,
        "protocolId": 22,
        "offsets": {
            "stdout": 2,
            "stderr": 0,
            "schedule": 0,
        },
        "maxBytes": 123,
        "maxLines": 45,
        "mapper": fakeProjectService.lastPollLogsCall["mapper"],
    }


def test_ResolveAnalyzeViewerUnwrapsCtx(projectClient, fakeProjectService):
    response = projectClient.post(
        "/projects/1/protocols/22/viewer/resolve",
        json={"ctx": {"outputName": "particles", "outputClass": "SetOfParticles"}},
    )

    assert response.status_code == 200
    assert response.json() == {"handled": False}
    assert fakeProjectService.lastResolveViewerCall == {
        "projectId": 1,
        "protocolId": 22,
        "ctx": {"outputName": "particles", "outputClass": "SetOfParticles"},
        "mapper": fakeProjectService.lastResolveViewerCall["mapper"],
    }


def test_ResolveAnalyzeViewerReturnsHandledFalseOnUnexpectedError(projectClient, fakeProjectService):
    fakeProjectService.resolveViewerError = RuntimeError("viewer failed")

    response = projectClient.post(
        "/projects/1/protocols/22/viewer/resolve",
        json={"outputName": "particles"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "handled": False,
        "message": "viewer failed",
    }
    assert fakeProjectService.lastResolveViewerCall == {
        "projectId": 1,
        "protocolId": 22,
        "ctx": {"outputName": "particles"},
        "mapper": fakeProjectService.lastResolveViewerCall["mapper"],
    }


def test_ListMetadataTablesDelegatesMapperToService(projectClient, fakeProjectService):
    fakeProjectService.metadataTablesResult = [
        {
            "name": "objects",
            "alias": "Particles",
            "rowCount": 3,
            "hasColumnId": True,
        },
        {
            "name": "Properties",
            "alias": "Properties",
            "rowCount": 2,
            "hasColumnId": False,
        },
    ]

    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/metadata/tables"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.metadataTablesResult
    assert fakeProjectService.lastListOutputMetadataTablesCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "mapper": fakeProjectService.lastListOutputMetadataTablesCall["mapper"],
    }


def test_GetMetadataTableSchemaDelegatesMapperToService(projectClient, fakeProjectService):
    fakeProjectService.metadataTableSchemaResult = {
        "name": "objects",
        "alias": "Particles",
        "hasColumnId": True,
        "actions": ["Particle"],
        "columns": [],
    }

    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/metadata/tables/objects/schema"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.metadataTableSchemaResult
    assert fakeProjectService.lastGetMetadataTableSchemaCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "tableName": "objects",
        "mapper": fakeProjectService.lastGetMetadataTableSchemaCall["mapper"],
    }


def test_RunMetadataTableActionRejectsMissingIds(projectClient):
    response = projectClient.post(
        "/projects/1/protocols/2/outputs/out/metadata/tables/table/actions",
        json={"action": "create subset", "ids": []},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Missing ids"


def test_RunMetadataTableActionUsesDefaultSubsetNameAndNormalizesServiceResult(
    projectClient,
    fakeProjectService,
):
    fakeProjectService.runMetadataTableActionResult = {
        "success": True,
        "message": "Subset created",
        "errors": [],
    }

    response = projectClient.post(
        "/projects/1/protocols/2/outputs/out/metadata/tables/table/actions",
        json={"action": "create subset", "ids": [1, 2, 3]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Subset created",
    }

    assert fakeProjectService.lastRunMetadataTableActionCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "tableName": "table",
        "action": "create subset",
        "subsetName": "create subset",
        "ids": [1, 2, 3],
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
        "mapper": fakeProjectService.lastRunMetadataTableActionCall["mapper"],
    }


def test_GetMetadataTablePageDelegatesMapperToService(projectClient, fakeProjectService):
    fakeProjectService.metadataTablePageResult = {
        "pageNumber": 2,
        "pageSize": 50,
        "totalRows": 1,
        "rows": [{"id": 1, "values": ["row-1"]}],
    }

    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/metadata/tables/objects/page"
        "?page=2&pageSize=50&sortBy=id&asc=false&selectionOnly=true"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.metadataTablePageResult
    assert fakeProjectService.lastGetMetadataTablePageCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "tableName": "objects",
        "page": 2,
        "pageSize": 50,
        "sortBy": "id",
        "asc": False,
        "selectionOnly": True,
        "mapper": fakeProjectService.lastGetMetadataTablePageCall["mapper"],
    }


def test_ExportMetadataTableRejectsInvalidIds(projectClient):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/metadata/tables/table/export?ids=1,abc,3"
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid 'ids' parameter. Expected comma-separated integers."


def test_ExportMetadataTableParsesIdsAndDelegatesToService(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/metadata/tables/table/export?ids=1,2,3&format=csv"
    )

    assert response.status_code == 200
    assert "id,name" in response.text

    assert fakeProjectService.lastExportMetadataTableCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "tableName": "table",
        "fmt": "csv",
        "selectionOnly": False,
        "ids": [1, 2, 3],
        "mapper": fakeProjectService.lastExportMetadataTableCall["mapper"],
    }


def test_RenderMetadataImageCellDelegatesMapperToService(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/metadata/tables/objects/image"
        "?rowId=7&rowIndex=3&column=stack&size=128"
        "&applyTransform=true&inline=false&fmt=jpeg"
    )

    assert response.status_code == 200
    assert response.text == "image-bytes"

    call = fakeProjectService.lastRenderMetadataImageCellCall
    assert str(call["rowId"]) == "7"
    assert call == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "tableName": "objects",
        "rowId": call["rowId"],
        "rowIndex": 3,
        "columnName": "stack",
        "size": 128,
        "applyTransform": True,
        "inline": False,
        "fmt": "jpeg",
        "mapper": call["mapper"],
    }