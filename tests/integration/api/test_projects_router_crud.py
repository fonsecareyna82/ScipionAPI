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
from fastapi import HTTPException


def test_ListProjectsReturnsProjects(projectClient):
    response = projectClient.get("/projects/")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == 1
    assert body[0]["name"] == "Demo Project"


def test_CreateProjectDelegatesToService(projectClient, fakeProjectService):
    response = projectClient.post(
        "/projects/",
        json={
            "name": "Created Project",
            "description": "Created description",
            "status": "active",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 2
    assert body["name"] == "Created Project"

    call = fakeProjectService.lastCreateProjectCall
    assert call["currentUser"] == {
        "id": 1,
        "email": "user@example.com",
        "role": "user",
    }
    assert call["projectData"].name == "Created Project"
    assert call["projectData"].description == "Created description"
    assert call["projectData"].status == "active"


def test_UpdateProjectDelegatesToService(projectClient, fakeProjectService):
    response = projectClient.put(
        "/projects/1",
        json={
            "name": "Updated Project",
            "description": "Updated description",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["name"] == "Updated Project"

    call = fakeProjectService.lastUpdateProjectCall
    assert call["projectId"] == 1
    assert call["currentUser"] == {
        "id": 1,
        "email": "user@example.com",
        "role": "user",
    }
    assert call["projectData"].dict(exclude_unset=True) == {
        "name": "Updated Project",
        "description": "Updated description",
    }


def test_DeleteProjectDelegatesToService(projectClient, fakeProjectService):
    response = projectClient.delete("/projects/1")

    assert response.status_code == 200
    assert response.json() == {"success": True}

    assert fakeProjectService.lastDeleteProjectCall == {
        "mapper": fakeProjectService.lastDeleteProjectCall["mapper"],
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
        "projectId": 1,
    }


def test_ShareProjectDelegatesToService(projectClient, fakeProjectService):
    response = projectClient.post(
        "/projects/1/share",
        json={
            "userIds": [2, 3],
            "permission": "read",
        },
    )

    assert response.status_code == 201
    assert response.json() == {"success": True, "sharedUserIds": [2, 3]}

    assert fakeProjectService.lastShareProjectCall == {
        "mapper": fakeProjectService.lastShareProjectCall["mapper"],
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
        "targetUserIds": [2, 3],
        "permission": "read",
    }


def test_RevokeProjectShareReturnsSuccess(projectClient, fakeProjectService):
    response = projectClient.delete("/projects/1/share/2")

    assert response.status_code == 200
    assert response.json() == {"success": True}

    assert fakeProjectService.lastRevokeProjectShareCall == {
        "mapper": fakeProjectService.lastRevokeProjectShareCall["mapper"],
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
        "targetUserId": 2,
    }


def test_ListProjectSharesReturnsServiceResult(projectClient, fakeProjectService):
    response = projectClient.get("/projects/1/shares")

    assert response.status_code == 200
    assert response.json() == [
        {"userId": 2, "permission": "read"},
        {"userId": 3, "permission": "full"},
    ]

    assert fakeProjectService.lastListProjectSharesCall == {
        "mapper": fakeProjectService.lastListProjectSharesCall["mapper"],
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }


def test_ApplyWorkflowToProjectReturns404WhenProjectMissing(projectClient, fakeProjectService):
    fakeProjectService.postgresqlRuntimeMutationResult = None

    response = projectClient.post(
        "/projects/1/workflows/load",
        json={"workflowId": "wf-1"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_ApplyWorkflowToProjectDelegatesToService(projectClient, fakeProjectService):
    response = projectClient.post(
        "/projects/1/workflows/load",
        json={"workflowId": "wf-1"},
    )

    assert fakeProjectService.lastLoadPostgresqlRuntimeProjectForMutationCall == {
        "mapper": fakeProjectService.lastLoadPostgresqlRuntimeProjectForMutationCall["mapper"],
        "projectId": 1,
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }
    assert response.status_code == 200
    assert response.json() == {"success": True, "workflowId": "wf-1"}

    assert fakeProjectService.lastApplyWorkflowCall == {
        "mapper": fakeProjectService.lastApplyWorkflowCall["mapper"],
        "projectId": 1,
        "workflowId": "wf-1",
        "currentUser": {
            "id": 1,
            "email": "user@example.com",
            "role": "user",
        },
    }


def test_ApplyWorkflowToProjectWrapsUnexpectedError(projectClient, fakeProjectService):
    fakeProjectService.applyWorkflowError = RuntimeError("workflow failed")

    response = projectClient.post(
        "/projects/1/workflows/load",
        json={"workflowId": "wf-1"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to apply workflow to project 1: workflow failed"