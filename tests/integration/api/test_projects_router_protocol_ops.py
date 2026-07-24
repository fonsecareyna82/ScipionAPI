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


def patchRenameProtocolFake(fakeProjectService):
    # patchRenameProtocolFake
    def renameProtocol(mapper, projectId, protocolId, newName, newComment=""):
        fakeProjectService.lastRenameProtocolCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
            "newName": newName,
            "newComment": newComment,
        }
        if fakeProjectService.renameProtocolError is not None:
            raise fakeProjectService.renameProtocolError

    fakeProjectService.renameProtocol = renameProtocol


def test_LoadProtocolReturns404WhenPostgresqlRuntimeProjectMissing(
        projectClient,
        fakeProjectService,
):
    fakeProjectService.postgresqlRuntimeMutationResult = None

    response = projectClient.get(
        "/projects/1/protocols/10"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"

    assert fakeProjectService.lastGetProjectByIdCall is None
    assert fakeProjectService.lastGetProtocolParamsCall is None


def test_LoadProtocolUsesPostgresqlRuntimeContextAndReturnsParams(
        projectClient,
        fakeProjectService,
        fakeProjectMapper,
):
    response = projectClient.get(
        "/projects/1/protocols/10"
    )

    assert response.status_code == 200

    assert response.json() == {
        "protocolId": "10",
        "protocolClassName": "ProtClass",
        "params": {"a": 1},
    }

    assert (
        fakeProjectService
        .lastLoadPostgresqlRuntimeProjectForMutationCall
        == {
            "mapper": fakeProjectMapper,
            "projectId": 1,
            "currentUser": {
                "id": 1,
                "email": "user@example.com",
                "role": "user",
            },
            "enableWriteFallback": False,
        }
    )

    assert fakeProjectService.lastGetProjectByIdCall is None

    assert fakeProjectService.lastGetProtocolParamsCall == {
        "mapper": fakeProjectMapper,
        "projectId": 1,
        "protocolId": 10,
    }

def test_LoadProtocolsReturns404WhenProjectMissing(
    projectClient,
    fakeProjectService,
    fakeProjectMapper,
):
    fakeProjectService.projectDbRowResult = None

    response = projectClient.get("/projects/1/protocols")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"

    assert fakeProjectService.lastGetProjectDbRowCall == {
        "mapper": fakeProjectMapper,
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }

    assert fakeProjectService.lastGetProjectByIdCall is None


def test_LoadProtocolsUsesProjectDbRow(
    projectClient,
    fakeProjectService,
    fakeProjectMapper,
):
    response = projectClient.get("/projects/1/protocols")

    assert response.status_code == 200
    assert response.json() == fakeProjectService.protocolsResult

    assert fakeProjectService.lastGetProjectDbRowCall == {
        "mapper": fakeProjectMapper,
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }

    assert fakeProjectService.lastGetProjectByIdCall is None

    assert fakeProjectService.lastGetProtocolsCall == {
        "mapper": fakeProjectMapper,
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }


def test_LoadNewProtocolUsesPostgresqlRuntimeMutationContext(
        projectClient,
        fakeProjectService,
        fakeProjectMapper,
):
    response = projectClient.get(
        "/projects/1/protclass/MyProtClass"
    )

    assert response.status_code == 200

    assert response.json() == {
        "protocolClassName": "ProtClass",
        "params": {"x": 2},
    }

    assert (
        fakeProjectService
        .lastLoadPostgresqlRuntimeProjectForMutationCall
        == {
            "mapper": fakeProjectMapper,
            "projectId": 1,
            "currentUser": {
                "id": 1,
                "email": "user@example.com",
                "role": "user",
            },
            "enableWriteFallback": False,
        }
    )

    assert fakeProjectService.lastGetProjectByIdCall is None

    assert fakeProjectService.lastGetNewProtocolParamsCall == {
        "projectId": 1,
        "protClassName": "MyProtClass",
    }


def test_LoadNewProtocolReturns404WhenPostgresqlRuntimeProjectMissing(
        projectClient,
        fakeProjectService,
):
    fakeProjectService.postgresqlRuntimeMutationResult = None

    response = projectClient.get(
        "/projects/1/protclass/MyProtClass"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"

    assert fakeProjectService.lastGetNewProtocolParamsCall is None


@pytest.mark.parametrize(
    ("method", "url", "payload"),
    [
        (
            "post",
            "/projects/1/protocols/duplicate",
            {"items": [{"id": "10", "name": "Copy 1"}]},
        ),
        (
            "post",
            "/projects/1/protocols/delete",
            {"protocolIds": ["10"]},
        ),
        (
            "post",
            "/projects/1/protocols/10/restart-all",
            None,
        ),
        (
            "post",
            "/projects/1/protocols/10/continue-all",
            None,
        ),
        (
            "post",
            "/projects/1/protocols/10/reset-from",
            None,
        ),
        (
            "post",
            "/projects/1/protocols/stop",
            {"protocolIds": ["10"]},
        ),
    ],
)
def test_ProtocolOperationsReturn404EnvelopeWhenProjectMissing(
    projectClient,
    fakeProjectService,
    method,
    url,
    payload,
):
    fakeProjectService.projectByIdResult = None

    request = getattr(projectClient, method)
    kwargs = {}
    if payload is not None:
        kwargs["json"] = payload

    response = request(url, **kwargs)

    assert response.status_code == 404
    assert response.json() == {
        "status": 1,
        "errors": ["Project not found"],
        "workflow": [],
    }


def test_LaunchProtocolReturns404EnvelopeWhenProjectMissing(projectClient, fakeProjectService):
    fakeProjectService.projectByIdResult = None

    response = projectClient.post(
        "/projects/1/launch",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
            "mode": "resume",
        },
    )

    assert response.status_code == 404
    assert response.json() == {
        "status": 1,
        "errors": ["Project not found"],
        "workflow": [],
    }


def test_LaunchProtocolDelegatesToService(projectClient, fakeProjectService):
    response = projectClient.post(
        "/projects/1/launch",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
            "mode": "resume",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
    }

    assert fakeProjectService.lastLaunchProtocolCall == {
        "mapper": fakeProjectService.lastLaunchProtocolCall["mapper"],
        "projectId": 1,
        "protocolId": "10",
        "protocolClassName": "ProtClass",
        "params": {"a": 1},
        "executeMode": "resume",
    }


def test_LaunchProtocolDefaultsMissingModeToLaunch(projectClient, fakeProjectService):
    response = projectClient.post(
        "/projects/1/launch",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
    }

    assert fakeProjectService.lastLaunchProtocolCall["executeMode"] is None


def test_LaunchProtocolReturnsSyncCounts(
    projectClient,
    fakeProjectService,
    monkeypatch,
):
    def fakeLaunchProtocol(
        mapper,
        projectId,
        protocolId,
        protocolClassName,
        params,
        executeMode,
    ):
        fakeProjectService.lastLaunchProtocolCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
            "protocolClassName": protocolClassName,
            "params": params,
            "executeMode": executeMode,
        }
        return {
            "protocols": 2,
            "dependencies": 1,
        }

    monkeypatch.setattr(fakeProjectService, "launchProtocol", fakeLaunchProtocol)

    response = projectClient.post(
        "/projects/1/launch",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
            "mode": "resume",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "protocolsCount": 2,
        "dependenciesCount": 1,
    }


def test_LaunchProtocolWrapsHttpException(projectClient, fakeProjectService):
    fakeProjectService.launchProtocolError = HTTPException(status_code=409, detail=["conflict", "busy"])

    response = projectClient.post(
        "/projects/1/launch",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
            "mode": "resume",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "status": 1,
        "errors": ["conflict", "busy"],
        "workflow": [],
    }


def test_LaunchProtocolWrapsUnexpectedException(
    projectClient,
    fakeProjectService,
    monkeypatch,
):
    def fakeLaunchProtocol(
        mapper,
        projectId,
        protocolId,
        protocolClassName,
        params,
        executeMode,
    ):
        raise RuntimeError("boom")

    monkeypatch.setattr(fakeProjectService, "launchProtocol", fakeLaunchProtocol)

    response = projectClient.post(
        "/projects/1/launch",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
            "mode": "resume",
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["Internal server error"],
        "workflow": [],
    }


def test_SaveProtocolReturnsSuccessWhenNoErrors(projectClient, fakeProjectService):
    fakeProjectService.saveProtocolResult = ({"protocolId": "10"}, [])

    response = projectClient.post(
        "/projects/1/save",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
    }

    assert fakeProjectService.lastSaveProtocolCall == {
        "mapper": fakeProjectService.lastSaveProtocolCall["mapper"],
        "projectId": 1,
        "protocolId": "10",
        "protocolClassName": "ProtClass",
        "params": {"a": 1},
    }


def test_SaveProtocolReturns404EnvelopeWhenProjectMissing(
    projectClient,
    fakeProjectService,
):
    fakeProjectService.projectByIdResult = None

    response = projectClient.post(
        "/projects/1/save",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
        },
    )

    assert response.status_code == 404
    assert response.json() == {
        "status": 1,
        "errors": ["Project not found"],
        "workflow": [],
    }


def test_SaveProtocolReturnsStatusOneWhenServiceReturnsErrors(projectClient, fakeProjectService):
    fakeProjectService.saveProtocolResult = (
        {"protocolId": "10"},
        ["bad param", "missing input"],
    )

    response = projectClient.post(
        "/projects/1/save",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": 1,
        "errors": ["bad param", "missing input"],
        "workflow": [],
    }


def test_SaveProtocolWrapsHttpException(projectClient, fakeProjectService):
    fakeProjectService.saveProtocolError = HTTPException(
        status_code=500,
        detail="Protocol was saved in Scipion but graph sync to PostgreSQL failed",
    )

    response = projectClient.post(
        "/projects/1/save",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["Protocol was saved in Scipion but graph sync to PostgreSQL failed"],
        "workflow": [],
    }


def test_SaveProtocolWrapsUnexpectedException(
    projectClient,
    fakeProjectService,
    monkeypatch,
):
    def fakeSaveProtocol(
        mapper,
        projectId,
        protocolId,
        protocolClassName,
        params,
    ):
        raise RuntimeError("boom")

    monkeypatch.setattr(fakeProjectService, "saveProtocol", fakeSaveProtocol)

    response = projectClient.post(
        "/projects/1/save",
        json={
            "protocolId": "10",
            "protocolClassName": "ProtClass",
            "params": {"a": 1},
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["boom"],
        "workflow": [],
    }


def test_SuggestionProtocolReturns404EnvelopeWhenProjectMissing(projectClient, fakeProjectService):
    fakeProjectService.projectByIdResult = None

    response = projectClient.get("/projects/1/protocols/10/suggestions/next")

    assert response.status_code == 404
    assert response.json() == {
        "status": 1,
        "errors": ["Project not found"],
        "workflow": [],
    }


def test_SuggestionProtocolReturnsSuggestions(projectClient, fakeProjectService):
    response = projectClient.get("/projects/1/protocols/10/suggestions/next")

    assert response.status_code == 200
    assert response.json() == [{"id": "next-1", "name": "Next protocol"}]

    assert fakeProjectService.lastGetNextProtocolSuggestionsCall == {
        "protocolId": 10,
        "mapper": fakeProjectService.lastGetNextProtocolSuggestionsCall["mapper"],
        "projectId": 1,
    }


def test_SuggestionProtocolWrapsHttpException(projectClient, fakeProjectService):
    fakeProjectService.nextProtocolSuggestionsError = HTTPException(
        status_code=404,
        detail="Protocol not found",
    )

    response = projectClient.get("/projects/1/protocols/10/suggestions/next")

    assert response.status_code == 404
    assert response.json() == {
        "status": 1,
        "errors": ["Protocol not found"],
        "workflow": [],
    }


def test_SuggestionProtocolWrapsUnexpectedException(
    projectClient,
    fakeProjectService,
    monkeypatch,
):
    def fakeGetNextProtocolSuggestions(mapper, projectId, protocolId):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        fakeProjectService,
        "getNextProtocolSuggestions",
        fakeGetNextProtocolSuggestions,
    )

    response = projectClient.get("/projects/1/protocols/10/suggestions/next")

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["boom"],
        "workflow": [],
    }


def test_RenameProtocolRejectsBlankName(projectClient):
    response = projectClient.put(
        "/projects/1/protocols/10/rename",
        json={"runName": "   ", "comment": "Ignored comment"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "status": 1,
        "errors": ["Missing name"],
        "workflow": [],
    }


def test_RenameProtocolDelegatesToService(projectClient, fakeProjectService):
    patchRenameProtocolFake(fakeProjectService)

    response = projectClient.put(
        "/projects/1/protocols/10/rename",
        json={
            "runName": "  Renamed protocol  ",
            "comment": "  Updated comment  ",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "protocolsCount": 1,
        "dependenciesCount": 0,
    }

    assert fakeProjectService.lastRenameProtocolCall == {
        "mapper": fakeProjectService.lastRenameProtocolCall["mapper"],
        "projectId": 1,
        "protocolId": 10,
        "newName": "Renamed protocol",
        "newComment": "Updated comment",
    }

    assert fakeProjectService.lastSyncProjectGraphAfterMutationCall == {
        "mapper": fakeProjectService.lastSyncProjectGraphAfterMutationCall["mapper"],
        "projectId": 1,
        "actionLabel": "rename protocol",
        "refresh": True,
        "checkPid": True,
    }


def test_RenameProtocolWrapsUnexpectedException(
    projectClient,
    fakeProjectService,
    monkeypatch,
):
    def fakeRenameProtocol(
        mapper,
        projectId,
        protocolId,
        newName,
        newComment,
    ):
        raise RuntimeError("boom")

    monkeypatch.setattr(fakeProjectService, "renameProtocol", fakeRenameProtocol)

    response = projectClient.put(
        "/projects/1/protocols/10/rename",
        json={
            "runName": "Renamed protocol",
            "comment": "Updated comment",
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["boom"],
        "workflow": [],
    }


def test_RenameProtocolWrapsHttpException(
    projectClient,
    fakeProjectService,
):
    patchRenameProtocolFake(fakeProjectService)
    fakeProjectService.renameProtocolError = HTTPException(
        status_code=404,
        detail="Protocol not found",
    )

    response = projectClient.put(
        "/projects/1/protocols/10/rename",
        json={
            "runName": "Renamed protocol",
            "comment": "Updated comment",
        },
    )

    assert response.status_code == 404
    assert response.json() == {
        "status": 1,
        "errors": ["Protocol not found"],
        "workflow": [],
    }


def test_DuplicateProtocolRejectsMissingItems(projectClient):
    response = projectClient.post(
        "/projects/1/protocols/duplicate",
        json={"items": []},
    )

    assert response.status_code == 422
    assert response.json() == {
        "status": 1,
        "errors": ["Missing items"],
        "workflow": [],
    }


def test_DuplicateProtocolDelegatesToService(projectClient, fakeProjectService):
    response = projectClient.post(
        "/projects/1/protocols/duplicate",
        json={
            "items": [
                {"id": "10", "name": "Copy 1"},
                {"id": "11"},
            ]
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "duplicated": [],
    }

    items = fakeProjectService.lastDuplicateProtocolCall["items"]
    assert fakeProjectService.lastDuplicateProtocolCall["projectId"] == 1
    assert len(items) == 2
    assert items[0].id == "10"
    assert items[0].name == "Copy 1"
    assert items[1].id == "11"
    assert items[1].name is None


def test_DuplicateProtocolReturnsSyncCounts(
    projectClient,
    fakeProjectService,
):
    fakeProjectService.duplicateProtocolResult = {
        "status": 0,
        "errors": [],
        "duplicated": [{"sourceId": "10", "newId": "20"}],
        "protocolsCount": 4,
        "dependenciesCount": 3,
    }

    response = projectClient.post(
        "/projects/1/protocols/duplicate",
        json={
            "items": [
                {"id": "10", "name": "Copy 1"},
            ]
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "duplicated": [{"sourceId": "10", "newId": "20"}],
        "protocolsCount": 4,
        "dependenciesCount": 3,
    }


def test_DuplicateProtocolWrapsHttpException(projectClient, fakeProjectService):
    fakeProjectService.duplicateProtocolError = HTTPException(
        status_code=500,
        detail="Failed to duplicate protocols: copy failed",
    )

    response = projectClient.post(
        "/projects/1/protocols/duplicate",
        json={
            "items": [
                {"id": "10", "name": "Copy 1"},
            ]
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["Failed to duplicate protocols: copy failed"],
        "workflow": [],
    }


def test_DuplicateProtocolWrapsUnexpectedException(
    projectClient,
    fakeProjectService,
    monkeypatch,
):
    def fakeDuplicateProtocol(mapper, projectId, items):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        fakeProjectService,
        "duplicateProtocol",
        fakeDuplicateProtocol,
    )

    response = projectClient.post(
        "/projects/1/protocols/duplicate",
        json={
            "items": [
                {"id": "10", "name": "Copy 1"},
            ]
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["boom"],
        "workflow": [],
    }


def test_DeleteProtocolRejectsMissingProtocolIds(projectClient):
    response = projectClient.post(
        "/projects/1/protocols/delete",
        json={"protocolIds": []},
    )

    assert response.status_code == 422
    assert response.json() == {
        "status": 1,
        "errors": ["Missing protocolIds"],
        "workflow": [],
    }


def test_DeleteProtocolDelegatesToService(projectClient, fakeProjectService):
    response = projectClient.post(
        "/projects/1/protocols/delete",
        json={"protocolIds": ["10", "11"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
    }

    assert fakeProjectService.lastDeleteProtocolCall == {
        "mapper": fakeProjectService.lastDeleteProtocolCall["mapper"],
        "projectId": 1,
        "protocolIds": ["10", "11"],
    }


def test_DeleteProtocolWrapsHttpException(projectClient, fakeProjectService):
    fakeProjectService.deleteProtocolError = HTTPException(
        status_code=500,
        detail="Failed to delete protocols",
    )

    response = projectClient.post(
        "/projects/1/protocols/delete",
        json={"protocolIds": ["10"]},
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["Failed to delete protocols"],
        "workflow": [],
    }


def test_DeleteProtocolWrapsUnexpectedException(
    projectClient,
    fakeProjectService,
    monkeypatch,
):
    def fakeDeleteProtocol(mapper, projectId, protocolIds):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        fakeProjectService,
        "deleteProtocol",
        fakeDeleteProtocol,
    )

    response = projectClient.post(
        "/projects/1/protocols/delete",
        json={"protocolIds": ["10"]},
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["boom"],
        "workflow": [],
    }


def test_RestartProtocolAllReturnsErrorsWhenServiceRaisesHttpException(projectClient, fakeProjectService):
    fakeProjectService.restartProtocolAllError = HTTPException(
        status_code=422,
        detail=["cannot restart", "blocked"],
    )

    response = projectClient.post("/projects/1/protocols/10/restart-all")

    assert response.status_code == 422
    assert response.json() == {
        "status": 1,
        "errors": ["cannot restart", "blocked"],
        "workflow": [],
    }


def test_RestartProtocolAllWrapsUnexpectedException(
    projectClient,
    fakeProjectService,
    monkeypatch,
):
    def fakeRestartProtocolAll(mapper, projectId, protocolId):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        fakeProjectService,
        "restartProtocolAll",
        fakeRestartProtocolAll,
    )

    response = projectClient.post("/projects/1/protocols/10/restart-all")

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["boom"],
        "workflow": [],
    }


def test_RestartProtocolAllReturnsSuccess(projectClient, fakeProjectService):
    fakeProjectService.restartProtocolAllResult = []

    response = projectClient.post("/projects/1/protocols/10/restart-all")

    assert response.status_code == 200
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "protocolsCount": 1,
        "dependenciesCount": 0,
    }

    assert fakeProjectService.lastRestartProtocolAllCall == {
        "mapper": fakeProjectService.lastRestartProtocolAllCall["mapper"],
        "projectId": 1,
        "protocolId": 10,
    }
    assert fakeProjectService.lastSyncProjectGraphAfterMutationCall == {
        "mapper": fakeProjectService.lastSyncProjectGraphAfterMutationCall["mapper"],
        "projectId": 1,
        "actionLabel": "restart protocol subtree",
        "refresh": True,
        "checkPid": True,
    }


def test_ContinueProtocolAllWrapsHttpException(projectClient, fakeProjectService):
    fakeProjectService.continueProtocolAllError = HTTPException(
        status_code=422,
        detail=["cannot continue", "blocked"],
    )

    response = projectClient.post("/projects/1/protocols/10/continue-all")

    assert response.status_code == 422
    assert response.json() == {
        "status": 1,
        "errors": ["cannot continue", "blocked"],
        "workflow": [],
    }


def test_ContinueProtocolAllWrapsUnexpectedException(
    projectClient,
    fakeProjectService,
    monkeypatch,
):
    def fakeContinueProtocolAll(mapper, projectId, protocolId, currentUser):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        fakeProjectService,
        "continueProtocolAll",
        fakeContinueProtocolAll,
    )

    response = projectClient.post("/projects/1/protocols/10/continue-all")

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["boom"],
        "workflow": [],
    }


def test_ContinueProtocolAllDelegatesToService(projectClient, fakeProjectService):
    response = projectClient.post("/projects/1/protocols/10/continue-all")

    assert response.status_code == 200
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "protocolsCount": 1,
        "dependenciesCount": 0,
    }

    assert fakeProjectService.lastSyncProjectGraphAfterMutationCall == {
        "mapper": fakeProjectService.lastSyncProjectGraphAfterMutationCall["mapper"],
        "projectId": 1,
        "actionLabel": "continue protocol subtree",
        "refresh": True,
        "checkPid": True,
    }

    assert fakeProjectService.lastContinueProtocolAllCall == {
        "mapper": fakeProjectService.lastContinueProtocolAllCall["mapper"],
        "projectId": 1,
        "protocolId": 10,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }


def test_ResetProtocolFromWrapsHttpException(projectClient, fakeProjectService):
    fakeProjectService.resetProtocolFromError = HTTPException(
        status_code=422,
        detail=["cannot reset", "blocked"],
    )

    response = projectClient.post("/projects/1/protocols/10/reset-from")

    assert response.status_code == 422
    assert response.json() == {
        "status": 1,
        "errors": ["cannot reset", "blocked"],
        "workflow": [],
    }


def test_ResetProtocolFromWrapsUnexpectedException(
    projectClient,
    fakeProjectService,
    monkeypatch,
):
    def fakeResetProtocolFrom(mapper, projectId, protocolId):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        fakeProjectService,
        "resetProtocolFrom",
        fakeResetProtocolFrom,
    )

    response = projectClient.post("/projects/1/protocols/10/reset-from")

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["boom"],
        "workflow": [],
    }


def test_ResetProtocolFromDelegatesToService(projectClient, fakeProjectService):
    response = projectClient.post("/projects/1/protocols/10/reset-from")

    assert response.status_code == 200
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "protocolsCount": 1,
        "dependenciesCount": 0,
    }

    assert fakeProjectService.lastResetProtocolFromCall == {
        "mapper": fakeProjectService.lastResetProtocolFromCall["mapper"],
        "projectId": 1,
        "protocolId": 10,
    }
    assert fakeProjectService.lastSyncProjectGraphAfterMutationCall == {
        "mapper": fakeProjectService.lastSyncProjectGraphAfterMutationCall["mapper"],
        "projectId": 1,
        "actionLabel": "reset protocol from node",
        "refresh": True,
        "checkPid": True,
    }


def test_RenameProtocolReturnsErrorWhenGraphSyncFails(projectClient, fakeProjectService):
    patchRenameProtocolFake(fakeProjectService)
    fakeProjectService.syncProjectGraphAfterMutationError = HTTPException(
        status_code=500,
        detail="rename protocol succeeded but graph sync to PostgreSQL failed",
    )

    response = projectClient.put(
        "/projects/1/protocols/10/rename",
        json={"runName": "Renamed protocol", "comment": "Updated comment"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["rename protocol succeeded but graph sync to PostgreSQL failed"],
        "workflow": [],
    }

    assert fakeProjectService.lastRenameProtocolCall == {
        "mapper": fakeProjectService.lastRenameProtocolCall["mapper"],
        "projectId": 1,
        "protocolId": 10,
        "newName": "Renamed protocol",
        "newComment": "Updated comment",
    }


def test_RestartProtocolAllReturnsErrorWhenGraphSyncFails(projectClient, fakeProjectService):
    fakeProjectService.restartProtocolAllResult = []
    fakeProjectService.syncProjectGraphAfterMutationError = HTTPException(
        status_code=500,
        detail="restart protocol subtree succeeded but graph sync to PostgreSQL failed",
    )

    response = projectClient.post("/projects/1/protocols/10/restart-all")

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["restart protocol subtree succeeded but graph sync to PostgreSQL failed"],
        "workflow": [],
    }

    assert fakeProjectService.lastRestartProtocolAllCall == {
        "mapper": fakeProjectService.lastRestartProtocolAllCall["mapper"],
        "projectId": 1,
        "protocolId": 10,
    }


def test_ContinueProtocolAllReturnsErrorWhenGraphSyncFails(projectClient, fakeProjectService):
    fakeProjectService.syncProjectGraphAfterMutationError = HTTPException(
        status_code=500,
        detail="continue protocol subtree succeeded but graph sync to PostgreSQL failed",
    )

    response = projectClient.post("/projects/1/protocols/10/continue-all")

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["continue protocol subtree succeeded but graph sync to PostgreSQL failed"],
        "workflow": [],
    }

    assert fakeProjectService.lastContinueProtocolAllCall == {
        "mapper": fakeProjectService.lastContinueProtocolAllCall["mapper"],
        "projectId": 1,
        "protocolId": 10,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }


def test_ResetProtocolFromReturnsErrorWhenGraphSyncFails(projectClient, fakeProjectService):
    fakeProjectService.syncProjectGraphAfterMutationError = HTTPException(
        status_code=500,
        detail="reset protocol from node succeeded but graph sync to PostgreSQL failed",
    )

    response = projectClient.post("/projects/1/protocols/10/reset-from")

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["reset protocol from node succeeded but graph sync to PostgreSQL failed"],
        "workflow": [],
    }

    assert fakeProjectService.lastResetProtocolFromCall == {
        "mapper": fakeProjectService.lastResetProtocolFromCall["mapper"],
        "projectId": 1,
        "protocolId": 10,
    }


def test_StopProtocolWrapsHttpException(projectClient, fakeProjectService):
    fakeProjectService.stopProtocolError = HTTPException(
        status_code=422,
        detail=["cannot stop", "blocked"],
    )

    response = projectClient.post(
        "/projects/1/protocols/stop",
        json={"protocolIds": ["10"]},
    )

    assert response.status_code == 422
    assert response.json() == {
        "status": 1,
        "errors": ["cannot stop", "blocked"],
        "workflow": [],
    }


def test_StopProtocolWrapsUnexpectedException(
    projectClient,
    fakeProjectService,
    monkeypatch,
):
    def fakeStopProtocol(mapper, projectId, protocolIds):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        fakeProjectService,
        "stopProtocol",
        fakeStopProtocol,
    )

    response = projectClient.post(
        "/projects/1/protocols/stop",
        json={"protocolIds": ["10"]},
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["boom"],
        "workflow": [],
    }


def test_StopProtocolReturnsErrorWhenGraphSyncFails(projectClient, fakeProjectService):
    fakeProjectService.syncProjectGraphAfterMutationError = HTTPException(
        status_code=500,
        detail="stop protocol succeeded but graph sync to PostgreSQL failed",
    )

    response = projectClient.post(
        "/projects/1/protocols/stop",
        json={"protocolIds": ["10", "11"]},
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": 1,
        "errors": ["stop protocol succeeded but graph sync to PostgreSQL failed"],
        "workflow": [],
    }

    assert fakeProjectService.lastStopProtocolCall == {
        "mapper": fakeProjectService.lastStopProtocolCall["mapper"],
        "projectId": 1,
        "protocolIds": ["10", "11"],
    }


def test_StopProtocolRejectsMissingProtocolIds(projectClient):
    response = projectClient.post(
        "/projects/1/protocols/stop",
        json={"protocolIds": []},
    )

    assert response.status_code == 422
    assert response.json() == {
        "status": 1,
        "errors": ["Missing protocolIds"],
        "workflow": [],
    }


def test_StopProtocolDelegatesToService(projectClient, fakeProjectService):
    response = projectClient.post(
        "/projects/1/protocols/stop",
        json={"protocolIds": ["10", "11"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "protocolsCount": 1,
        "dependenciesCount": 0,
    }

    assert fakeProjectService.lastStopProtocolCall == {
        "mapper": fakeProjectService.lastStopProtocolCall["mapper"],
        "projectId": 1,
        "protocolIds": ["10", "11"],
    }

    assert fakeProjectService.lastSyncProjectGraphAfterMutationCall == {
        "mapper": fakeProjectService.lastSyncProjectGraphAfterMutationCall["mapper"],
        "projectId": 1,
        "actionLabel": "stop protocol",
        "refresh": True,
        "checkPid": True,
    }


def test_DeleteProtocolReturnsErrorsWhenServiceRaisesHttpException(
    projectClient,
    fakeProjectService,
):
    fakeProjectService.deleteProtocolError = HTTPException(
        status_code=422,
        detail=["cannot delete protocol"],
    )

    response = projectClient.post(
        "/projects/1/protocols/delete",
        json={"protocolIds": ["10"]},
    )

    assert response.status_code == 422
    assert response.json() == {
        "status": 1,
        "errors": ["cannot delete protocol"],
        "workflow": [],
    }

    assert fakeProjectService.lastDeleteProtocolCall == {
        "mapper": fakeProjectService.lastDeleteProtocolCall["mapper"],
        "projectId": 1,
        "protocolIds": ["10"],
    }


def test_DeleteProtocolReturnsSyncCounts(
    projectClient,
    fakeProjectService,
    monkeypatch,
):
    def fakeDeleteProtocol(mapper, projectId, protocolIds):
        fakeProjectService.lastDeleteProtocolCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolIds": protocolIds,
        }
        return {
            "protocolsCount": 3,
            "dependenciesCount": 2,
        }

    monkeypatch.setattr(fakeProjectService, "deleteProtocol", fakeDeleteProtocol)

    response = projectClient.post(
        "/projects/1/protocols/delete",
        json={"protocolIds": ["10"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": 0,
        "errors": [],
        "workflow": [],
        "protocolsCount": 3,
        "dependenciesCount": 2,
    }

    assert fakeProjectService.lastDeleteProtocolCall == {
        "mapper": fakeProjectService.lastDeleteProtocolCall["mapper"],
        "projectId": 1,
        "protocolIds": ["10"],
    }
