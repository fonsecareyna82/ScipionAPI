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
import pytest
from fastapi import HTTPException


@pytest.mark.parametrize(
    ("method", "url"),
    [
        (
            "get",
            "/projects/1/protocols/2/outputs/out/metadata/tables",
        ),
        (
            "get",
            "/projects/1/protocols/2/outputs/out/metadata/tables/objects/schema",
        ),
        (
            "get",
            "/projects/1/protocols/2/outputs/out/metadata/tables/objects/page",
        ),
        (
            "get",
            "/projects/1/protocols/2/outputs/out/metadata/tables/objects/export",
        ),
        (
            "get",
            "/projects/1/protocols/2/outputs/out/metadata/tables/objects/image?column=stack",
        ),
    ],
)
def test_MetadataReadEndpointsReturn404WhenProjectMissing(
    projectClient,
    fakeProjectService,
    method,
    url,
):
    fakeProjectService.projectDbRowResult = None

    response = getattr(projectClient, method)(url)

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


def test_GetMetadataTableWindowDelegatesMapperToService(projectClient, fakeProjectService):
    fakeProjectService.metadataTableWindowResult = {
        "offset": 10,
        "limit": 25,
        "totalRows": 1,
        "rows": [{"id": 1, "values": ["row-1"]}],
    }

    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/metadata/tables/objects/rows"
        "?offset=10&limit=25&sortBy=id&asc=false&selectionOnly=true"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.metadataTableWindowResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetMetadataTableWindowCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "tableName": "objects",
        "offset": 10,
        "limit": 25,
        "selectionOnly": True,
        "sortBy": "id",
        "asc": False,
        "mapper": fakeProjectService.lastGetMetadataTableWindowCall["mapper"],
    }


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


def test_GetProjectCallsService(projectClient, fakeProjectService):
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


def test_LoadProtocolsReturns404WhenProjectDoesNotExist(projectClient, fakeProjectService):
    fakeProjectService.projectDbRowResult = None

    response = projectClient.get("/projects/1/protocols")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectByIdCall is None


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
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


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

    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
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
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
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
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
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
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


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
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


def test_RunMetadataTableActionReturns404WhenPostgresqlRuntimeProjectIsMissing(projectClient, fakeProjectService):
    fakeProjectService.postgresqlRuntimeMutationResult = None

    response = projectClient.post(
        "/projects/1/protocols/2/outputs/out/metadata/tables/table/actions",
        json={"action": "create subset", "ids": [1, 2]},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastLoadPostgresqlRuntimeProjectForMutationCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastRunMetadataTableActionCall is None


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

    assert fakeProjectService.lastLoadPostgresqlRuntimeProjectForMutationCall == {
        "mapper": fakeProjectService.lastLoadPostgresqlRuntimeProjectForMutationCall["mapper"],
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }
    assert fakeProjectService.lastGetProjectByIdCall is None

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
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


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
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


def test_RenderMetadataImageCellDelegatesMapperToService(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/metadata/tables/objects/image"
        "?rowId=7&rowIndex=3&column=stack&size=128"
        "&applyTransform=true&inline=false&fmt=jpeg"
    )

    assert response.status_code == 200
    assert response.text == "image-bytes"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None

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


def test_ListOutputVolumesUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/volumes"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.volumeItemsResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastListOutputVolumesCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "mapper": fakeProjectService.lastListOutputVolumesCall["mapper"],
    }


def test_GetVolumeInfoUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/volumes/vol-1/info"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.volumeInfoResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetVolumeInfoCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "volumeId": "vol-1",
        "mapper": fakeProjectService.lastGetVolumeInfoCall["mapper"],
    }


def test_GetVolumeHistogramUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/volumes/vol-1/histogram?bins=32"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.volumeHistogramResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetVolumeHistogramCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "volumeId": "vol-1",
        "bins": 32,
        "mapper": fakeProjectService.lastGetVolumeHistogramCall["mapper"],
    }


@pytest.mark.parametrize(
    "url",
    [
        "/projects/1/protocols/2/outputs/out/volumes",
        "/projects/1/protocols/2/outputs/out/volumes/vol-1/info",
        "/projects/1/protocols/2/outputs/out/volumes/vol-1/histogram",
    ],
)
def test_VolumeReadEndpointsReturn404WhenProjectMissing(
    projectClient,
    fakeProjectService,
    url,
):
    fakeProjectService.projectDbRowResult = None

    response = projectClient.get(url)

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


def test_ListOutputTiltSeriesUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/tiltseries"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.tiltSeriesResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastListOutputTiltSeriesCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "mapper": fakeProjectService.lastListOutputTiltSeriesCall["mapper"],
    }


def test_GetTiltSeriesFramesUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/tiltseries/TS_001/frames"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.tiltSeriesFramesResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetTiltSeriesFramesCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "tiltSeriesId": "TS_001",
        "mapper": fakeProjectService.lastGetTiltSeriesFramesCall["mapper"],
    }


def test_CreateNewSetOfTiltSeriesUsesPostgresqlRuntimeProject(
    projectClient,
    fakeProjectService,
):
    response = projectClient.post(
        "/projects/1/protocols/2/outputs/TiltSeries/tiltseries/new-set",
        json={
            "exclusions": {
                "TS_001": {
                    "excluded": False,
                    "tiltimages": [2],
                }
            },
            "restack": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.newTiltSeriesSetResult
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastLoadPostgresqlRuntimeProjectForMutationCall == {
        "mapper": fakeProjectService.lastLoadPostgresqlRuntimeProjectForMutationCall["mapper"],
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }
    assert fakeProjectService.lastCreateNewSetOfTiltSeriesCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "TiltSeries",
        "exclusions": {
            "TS_001": {
                "excluded": False,
                "tiltimages": [2],
            }
        },
        "restack": False,
        "mapper": fakeProjectService.lastCreateNewSetOfTiltSeriesCall["mapper"],
    }


def test_CreateNewSetOfTiltSeriesReturns404WhenRuntimeProjectIsMissing(
    projectClient,
    fakeProjectService,
):
    fakeProjectService.postgresqlRuntimeMutationResult = None

    response = projectClient.post(
        "/projects/1/protocols/2/outputs/TiltSeries/tiltseries/new-set",
        json={
            "exclusions": {},
            "restack": False,
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastLoadPostgresqlRuntimeProjectForMutationCall is not None
    assert fakeProjectService.lastCreateNewSetOfTiltSeriesCall is None


def test_ListCtftomoSeriesUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/ctftomo"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.ctftomoSeriesResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastListOutputCtftomoSeriesCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "mapper": fakeProjectService.lastListOutputCtftomoSeriesCall["mapper"],
    }


def test_GetCtftomoSeriesViewsUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/ctftomo/TS_001/views"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.ctftomoSeriesViewsResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetCtftomoSeriesViewsCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "tiltSeriesId": "TS_001",
        "mapper": fakeProjectService.lastGetCtftomoSeriesViewsCall["mapper"],
    }


def test_CreateNewSetOfCtftomoSeriesUsesPostgresqlRuntimeProject(
    projectClient,
    fakeProjectService,
):
    response = projectClient.post(
        "/projects/1/protocols/2/outputs/CTFTomoSeries/ctftomo/new-set",
        json={
            "exclusions": {
                "TS_001": {
                    "excluded": False,
                    "tiltimages": [2],
                }
            },
            "restack": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.newCtftomoSeriesSetResult
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastLoadPostgresqlRuntimeProjectForMutationCall == {
        "mapper": fakeProjectService.lastLoadPostgresqlRuntimeProjectForMutationCall["mapper"],
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }
    assert fakeProjectService.lastCreateNewSetOfCtftomoSeriesCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "CTFTomoSeries",
        "exclusions": {
            "TS_001": {
                "excluded": False,
                "tiltimages": [2],
            }
        },
        "restack": False,
        "mapper": fakeProjectService.lastCreateNewSetOfCtftomoSeriesCall["mapper"],
    }


def test_CreateNewSetOfCtftomoSeriesReturns404WhenRuntimeProjectIsMissing(
    projectClient,
    fakeProjectService,
):
    fakeProjectService.postgresqlRuntimeMutationResult = None

    response = projectClient.post(
        "/projects/1/protocols/2/outputs/CTFTomoSeries/ctftomo/new-set",
        json={
            "exclusions": {},
            "restack": False,
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastLoadPostgresqlRuntimeProjectForMutationCall is not None
    assert fakeProjectService.lastCreateNewSetOfCtftomoSeriesCall is None

@pytest.mark.parametrize(
    "url",
    [
        "/projects/1/protocols/2/outputs/out/tiltseries",
        "/projects/1/protocols/2/outputs/out/tiltseries/TS_001/frames",
        "/projects/1/protocols/2/outputs/out/ctftomo",
        "/projects/1/protocols/2/outputs/out/ctftomo/TS_001/views",
    ],
)
def test_TomographyReadEndpointsReturn404WhenProjectMissing(
    projectClient,
    fakeProjectService,
    url,
):
    fakeProjectService.projectDbRowResult = None

    response = projectClient.get(url)

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


def test_ListCoordinates3dTomogramsUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/coords3d/tomograms"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.coords3dTomogramsResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastListCoordinates3dTomogramsCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "mapper": fakeProjectService.lastListCoordinates3dTomogramsCall["mapper"],
    }


def test_GetCoordinates3dPointsUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/coords3d/tomograms/tomo-1"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.coords3dPointsResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetCoordinates3dPointsCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "tomogramId": "tomo-1",
        "mapper": fakeProjectService.lastGetCoordinates3dPointsCall["mapper"],
    }


def test_GetIntegratedAnalyzeContextUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/integrated-context"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.integratedAnalyzeContextResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetIntegratedAnalyzeContextCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "mapper": fakeProjectService.lastGetIntegratedAnalyzeContextCall["mapper"],
    }


@pytest.mark.parametrize(
    "url",
    [
        "/projects/1/protocols/2/outputs/out/coords3d/tomograms",
        "/projects/1/protocols/2/outputs/out/coords3d/tomograms/tomo-1",
        "/projects/1/protocols/2/outputs/out/integrated-context",
    ],
)
def test_Coordinates3dReadEndpointsReturn404WhenProjectMissing(
    projectClient,
    fakeProjectService,
    url,
):
    fakeProjectService.projectDbRowResult = None

    response = projectClient.get(url)

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


def test_ListProjectTagsUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get("/projects/1/tags")

    assert response.status_code == 200
    assert response.json() == fakeProjectService.projectTagsResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastListProjectTagsCall["projectId"] == 1


def test_CreateProjectTagUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.post(
        "/projects/1/tags",
        json={
            "title": "New tag",
            "description": None,
            "color": "#ff0000",
        },
    )

    assert response.status_code == 201
    assert response.json() == fakeProjectService.createProjectTagResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastCreateProjectTagCall["projectId"] == 1
    assert fakeProjectService.lastCreateProjectTagCall["payload"].title == "New tag"


def test_UpdateProjectTagUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.put(
        "/projects/1/tags/tag-1",
        json={
            "title": "Updated tag",
            "description": "Updated",
            "color": "#0000ff",
        },
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.updateProjectTagResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastUpdateProjectTagCall["projectId"] == 1
    assert fakeProjectService.lastUpdateProjectTagCall["tagId"] == "tag-1"


def test_DeleteProjectTagUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.delete("/projects/1/tags/tag-1")

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastDeleteProjectTagCall["projectId"] == 1
    assert fakeProjectService.lastDeleteProjectTagCall["tagId"] == "tag-1"


def test_ListProtocolTagsUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get("/projects/1/protocols/2/tags")

    assert response.status_code == 200
    assert response.json() == fakeProjectService.protocolTagsResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastListProtocolTagsCall["projectId"] == 1
    assert fakeProjectService.lastListProtocolTagsCall["protocolId"] == 2


def test_SetProtocolTagsUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.put(
        "/projects/1/protocols/2/tags",
        json={"tagIds": ["tag-1", "tag-2"]},
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.setProtocolTagsResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastSetProtocolTagsCall["projectId"] == 1
    assert fakeProjectService.lastSetProtocolTagsCall["protocolId"] == 2
    assert fakeProjectService.lastSetProtocolTagsCall["tagIds"] == ["tag-1", "tag-2"]


def test_GetContextMenuVisibilityUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get("/projects/1/context-menu-visibility")

    assert response.status_code == 200
    assert response.json() == fakeProjectService.contextMenuVisibilityResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetContextMenuVisibilityPolicyCall == {}


@pytest.mark.parametrize(
    ("method", "url", "payload"),
    [
        ("get", "/projects/1/tags", None),
        ("post", "/projects/1/tags", {"title": "New tag"}),
        ("put", "/projects/1/tags/tag-1", {"title": "Updated"}),
        ("delete", "/projects/1/tags/tag-1", None),
        ("get", "/projects/1/protocols/2/tags", None),
        ("put", "/projects/1/protocols/2/tags", {"tagIds": ["tag-1"]}),
        ("get", "/projects/1/context-menu-visibility", None),
    ],
)
def test_TagAndContextMenuEndpointsReturn404WhenProjectMissing(
    projectClient,
    fakeProjectService,
    method,
    url,
    payload,
):
    fakeProjectService.projectDbRowResult = None

    request = getattr(projectClient, method)
    if payload is None:
        response = request(url)
    else:
        response = request(url, json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


def test_GetFscRowsUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/fsc/rows"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.fscRowsResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetFscRowsCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "mapper": fakeProjectService.lastGetFscRowsCall["mapper"],
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


def test_GetFscRowsReturns404WhenProjectMissing(projectClient, fakeProjectService):
    fakeProjectService.projectDbRowResult = None

    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/fsc/rows"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


def test_GetProjectEffectiveSettingsUsesProjectDbRow(
    projectClient,
    fakeProjectService,
):
    response = projectClient.get("/projects/1/effective-settings")

    assert response.status_code == 200
    assert response.json() == fakeProjectService.projectEffectiveSettingsResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetProjectEffectiveSettingsCall == {
        "mapper": fakeProjectService.lastGetProjectEffectiveSettingsCall["mapper"],
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }


def test_GetProjectEffectiveSettingsReturns404WhenProjectMissing(
    projectClient,
    fakeProjectService,
):
    fakeProjectService.projectDbRowResult = None

    response = projectClient.get("/projects/1/effective-settings")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetProjectEffectiveSettingsCall is None


def test_RenderCoords3dTomogramSliceUsesProjectDbRow(
    projectClient,
    fakeProjectService,
):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/coords3d/tomograms/tomo-1/slice"
        "?index=4&axis=y&cmap=gray&normalize=zscore&scale=1.5"
        "&inline=false&format=png&thumb=128&fast=false&quality=80"
    )

    assert response.status_code == 200
    assert response.content == b"slice-bytes"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastRenderCoords3dTomogramSliceCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "tomogramId": "tomo-1",
        "sliceIndex": 4,
        "axis": "y",
        "colormap": "gray",
        "normalize": "zscore",
        "scale": 1.5,
        "inline": False,
        "fmt": "png",
        "thumb": 128,
        "fast": False,
        "quality": 80,
        "mapper": fakeProjectService.lastRenderCoords3dTomogramSliceCall["mapper"],
    }


def test_RenderCoords3dTomogramSliceReturns404WhenProjectMissing(
    projectClient,
    fakeProjectService,
):
    fakeProjectService.projectDbRowResult = None

    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/coords3d/tomograms/tomo-1/slice?index=4"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastRenderCoords3dTomogramSliceCall is None


def resolveAnalyzeViewerDecision(
        self,
        projectId,
        protocolId,
        ctx,
        mapper=None,
):
    self.lastResolveAnalyzeViewerDecisionCall = {
        "projectId": projectId,
        "protocolId": protocolId,
        "ctx": ctx,
        "mapper": mapper,
    }
    return self.resolveAnalyzeViewerDecisionResult


def test_ResolveAnalyzeViewerUnwrapsCtxAndUsesProjectDbRow(
    projectClient,
    fakeProjectService,
):
    ctx = {
        "outputName": "out",
        "objectId": "tomo-1",
        "objectKind": "tomogram",
    }

    response = projectClient.post(
        "/projects/1/protocols/2/viewer/resolve",
        json={"ctx": ctx},
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.resolveAnalyzeViewerDecisionResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None

    call = (
        fakeProjectService.lastResolveAnalyzeViewerDecisionCall
        or fakeProjectService.lastResolveViewerCall
    )

    assert call == {
        "projectId": 1,
        "protocolId": 2,
        "ctx": ctx,
        "mapper": call["mapper"],
    }


def test_ResolveAnalyzeViewerReturns404WhenProjectMissing(
    projectClient,
    fakeProjectService,
):
    fakeProjectService.projectDbRowResult = None

    response = projectClient.post(
        "/projects/1/protocols/2/viewer/resolve",
        json={"outputName": "out"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastResolveAnalyzeViewerDecisionCall is None


def test_RenderVolumeSliceUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/volumes/vol-1/slice"
        "?index=4&axis=y&cmap=gray&normalize=zscore&scale=1.5"
        "&inline=false&format=png&thumb=128&fast=false&quality=80"
    )

    assert response.status_code == 200
    assert response.content == b"volume-slice-bytes"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastRenderVolumeSliceCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "volumeId": "vol-1",
        "sliceIndex": 4,
        "axis": "y",
        "colormap": "gray",
        "normalize": "zscore",
        "scale": 1.5,
        "inline": False,
        "fmt": "png",
        "thumb": 128,
        "fast": False,
        "quality": 80,
        "mapper": fakeProjectService.lastRenderVolumeSliceCall["mapper"],
    }


def test_GetVolumeData3dUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/volumes/vol-1/data3d"
        "?maxDim=96&method=stride"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.volumeData3dResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetVolumeData3dCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "volumeId": "vol-1",
        "maxDim": 96,
        "method": "stride",
        "mapper": fakeProjectService.lastGetVolumeData3dCall["mapper"],
    }


def test_GetVolumeSurfaceMeshUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/volumes/vol-1/surface"
        "?level=0.5&maxDim=96&method=stride&maxTriangles=1234"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.volumeSurfaceMeshResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetVolumeSurfaceMeshCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "volumeId": "vol-1",
        "level": 0.5,
        "maxDim": 96,
        "method": "stride",
        "maxTriangles": 1234,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
        "mapper": fakeProjectService.lastGetVolumeSurfaceMeshCall["mapper"],
    }


@pytest.mark.parametrize(
    "url",
    [
        "/projects/1/protocols/2/outputs/out/volumes/vol-1/slice?index=4",
        "/projects/1/protocols/2/outputs/out/volumes/vol-1/data3d",
        "/projects/1/protocols/2/outputs/out/volumes/vol-1/surface",
    ],
)
def test_VolumeRenderEndpointsReturn404WhenProjectMissing(
    projectClient,
    fakeProjectService,
    url,
):
    fakeProjectService.projectDbRowResult = None

    response = projectClient.get(url)

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastRenderVolumeSliceCall is None
    assert fakeProjectService.lastGetVolumeData3dCall is None
    assert fakeProjectService.lastGetVolumeSurfaceMeshCall is None


def test_RenderTiltSeriesImageUsesProjectDbRow(projectClient, fakeProjectService):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/tiltseries/TS_001/tilt"
        "?index=3&size=256&fmt=webp&applyTransform=true&inline=false"
    )

    assert response.status_code == 200
    assert response.content == b"tilt-image-bytes"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastRenderTiltSeriesImageCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "tiltSeriesId": "TS_001",
        "index": 3,
        "size": 256,
        "fmt": "webp",
        "applyTransform": True,
        "inline": False,
        "requestHeaders": None,
        "mapper": fakeProjectService.lastRenderTiltSeriesImageCall["mapper"],
    }


def test_RenderTiltSeriesImagesBatchUsesProjectDbRow(
    projectClient,
    fakeProjectService,
):
    response = projectClient.post(
        "/projects/1/protocols/2/outputs/out/tiltseries/TS_001/tilt/batch",
        json={
            "indices": [0, 2, 4],
            "size": 256,
            "fmt": "webp",
            "applyTransform": True,
            "inline": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.tiltSeriesBatchResult
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastRenderTiltSeriesImagesBatchCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "tiltSeriesId": "TS_001",
        "indices": [0, 2, 4],
        "size": 256,
        "fmt": "webp",
        "applyTransform": True,
        "inline": False,
        "requestHeaders": None,
        "mapper": fakeProjectService.lastRenderTiltSeriesImagesBatchCall["mapper"],
    }


@pytest.mark.parametrize(
    ("method", "url", "payload"),
    [
        (
            "get",
            "/projects/1/protocols/2/outputs/out/tiltseries/TS_001/tilt?index=3",
            None,
        ),
        (
            "post",
            "/projects/1/protocols/2/outputs/out/tiltseries/TS_001/tilt/batch",
            {"indices": [0, 2]},
        ),
    ],
)
def test_TiltSeriesRenderEndpointsReturn404WhenProjectMissing(
    projectClient,
    fakeProjectService,
    method,
    url,
    payload,
):
    fakeProjectService.projectDbRowResult = None

    request = getattr(projectClient, method)
    if payload is None:
        response = request(url)
    else:
        response = request(url, json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastRenderTiltSeriesImageCall is None
    assert fakeProjectService.lastRenderTiltSeriesImagesBatchCall is None


def test_RenderCtftomoPsdImageUsesProjectDbRow(
    projectClient,
    fakeProjectService,
):
    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/ctftomo/psd"
        "?spec=3%40%2Ftmp%2Fpsd.mrc&size=256&fmt=webp"
        "&applyTransform=true&inline=false"
    )

    assert response.status_code == 200
    assert response.content == b"ctftomo-psd-bytes"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastRenderCtfTomoPsdImageCall == {
        "projectId": 1,
        "protocolId": 2,
        "outputName": "out",
        "psdPath": "3@/tmp/psd.mrc",
        "size": 256,
        "fmt": "webp",
        "inline": False,
        "index": 0,
        "quality": 75,
        "applyTransform": True,
        "rot": None,
        "shifts": None,
        "mapper": fakeProjectService.lastRenderCtfTomoPsdImageCall["mapper"],
    }


def test_RenderCtftomoPsdImageReturns404WhenProjectMissing(
    projectClient,
    fakeProjectService,
):
    fakeProjectService.projectDbRowResult = None

    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/ctftomo/psd"
        "?spec=3%40%2Ftmp%2Fpsd.mrc"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastRenderCtfTomoPsdImageCall is None


def test_RenderCtftomoPsdImagePreservesHttpException(
    projectClient,
    fakeProjectService,
):
    fakeProjectService.renderCtfTomoPsdImageError = HTTPException(
        status_code=404,
        detail="PSD image file not found",
    )

    response = projectClient.get(
        "/projects/1/protocols/2/outputs/out/ctftomo/psd"
        "?spec=3%40%2Ftmp%2Fpsd.mrc"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "PSD image file not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None


def test_ListProtocolLogChannelsUsesProjectDbRow(
    projectClient,
    fakeProjectService,
):
    response = projectClient.get("/projects/1/protocols/2/logs/channels")

    assert response.status_code == 200
    assert response.json() == {
        "channels": fakeProjectService.logChannelsResult,
    }
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastListProtocolLogChannelsCall == {
        "projectId": 1,
        "protocolId": 2,
        "mapper": fakeProjectService.lastListProtocolLogChannelsCall["mapper"],
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }


def test_PollProtocolLogsUsesProjectDbRow(
    projectClient,
    fakeProjectService,
):
    response = projectClient.post(
        "/projects/1/protocols/2/logs/chunk",
        json={
            "offsets": {
                "stdout": 0,
            },
            "maxBytes": 32,
            "maxLines": 10,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "chunks": [
            {
                "channel": "stdout",
                "content": "hello",
                "offset": 5,
            }
        ]
    }
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastPollLogsCall == {
        "projectId": 1,
        "protocolId": 2,
        "offsets": {"stdout": 0},
        "maxBytes": 32,
        "maxLines": 10,
        "mapper": fakeProjectService.lastPollLogsCall["mapper"],
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }


@pytest.mark.parametrize(
    ("method", "url", "payload"),
    [
        ("get", "/projects/1/protocols/2/logs/channels", None),
        ("post", "/projects/1/protocols/2/logs/chunk", {"offsets": {"stdout": 0}}),
    ],
)
def test_ProtocolLogEndpointsReturn404WhenProjectMissing(
    projectClient,
    fakeProjectService,
    method,
    url,
    payload,
):
    fakeProjectService.projectDbRowResult = None

    request = getattr(projectClient, method)
    response = request(url) if payload is None else request(url, json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastListProtocolLogChannelsCall is None
    assert fakeProjectService.lastPollLogsCall is None


def test_GetFscRowsUsesProjectDbRowAndPassesCurrentUser(
    projectClient,
    fakeProjectService,
):
    response = projectClient.get(
        "/projects/1/protocols/22/outputs/outputFsc/fsc/rows"
    )

    assert response.status_code == 200
    assert response.json() == fakeProjectService.fscRowsResult

    assert fakeProjectService.lastGetProjectDbRowCall is not None
    assert fakeProjectService.lastGetProjectByIdCall is None

    call = fakeProjectService.lastGetFscRowsCall
    assert call["projectId"] == 1
    assert call["protocolId"] == 22
    assert call["outputName"] == "outputFsc"
    assert call["mapper"] is not None
    assert call["currentUser"] == {
        "id": 1,
        "email": "user@example.com",
        "role": "user",
    }


def test_GetProjectWithValidateConsistencyPassesAuditFlag(
    projectClient,
    fakeProjectService,
):
    response = projectClient.get("/projects/1?validateConsistency=true")

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
    }