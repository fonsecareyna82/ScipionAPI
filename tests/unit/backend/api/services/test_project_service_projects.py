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
import os
from pathlib import Path

import pytest
from fastapi import HTTPException


class FakeCreatedProject:
    # fakeCreatedProject
    def __init__(self):
        self.comment = None

    def setComment(self, value):
        self.comment = value


class FakeManager:
    # fakeManager
    def __init__(self, projectsRoot):
        self.PROJECTS = str(projectsRoot)
        self.createdProjects = []
        self.renamedProjects = []
        self.deletedProjects = []

    def getProjectPath(self, name):
        return str(Path(self.PROJECTS) / name)

    def createProject(self, name):
        self.createdProjects.append(name)
        return FakeCreatedProject()

    def renameProject(self, currentPath, newName):
        newPath = Path(self.getProjectPath(newName))
        os.rename(currentPath, str(newPath))
        self.renamedProjects.append(
            {
                "currentPath": currentPath,
                "newName": newName,
                "newPath": str(newPath),
            }
        )

    def deleteProject(self, projectPath):
        self.deletedProjects.append(projectPath)
        projectPathObj = Path(projectPath)
        if projectPathObj.exists():
            if projectPathObj.is_dir() and not projectPathObj.is_symlink():
                for child in projectPathObj.iterdir():
                    if child.is_dir():
                        for nested in child.rglob("*"):
                            if nested.is_file():
                                nested.unlink()
                        for nestedDir in sorted(child.rglob("*"), reverse=True):
                            if nestedDir.is_dir():
                                nestedDir.rmdir()
                        child.rmdir()
                    else:
                        child.unlink()
                projectPathObj.rmdir()
            else:
                projectPathObj.unlink()


class FakeMapper:
    # fakeMapper
    def __init__(self):
        self.projectsById = {}
        self.projectsListResult = []
        self.projectProtocolCounts = {}
        self.lastCountProjectProtocolsCall = None
        self.insertProjectResult = 101
        self.updateProjectResult = {
            "id": 1,
            "name": "/tmp/updated",
            "description": "updated description",
        }
        self.deleteProjectResult = True
        self.listProjectSharesResult = [
            {"userId": 2, "permission": "read"},
            {"userId": 3, "permission": "full"},
        ]
        self.revokeProjectShareResult = True
        self.shareProjectRows = [
            {
                "id": 700,
                "projectId": 1,
                "userId": 2,
                "permission": "read",
                "createdAt": "2026-04-15T10:00:00",
                "updatedAt": "2026-04-15T10:00:00",
            },
            {
                "id": 701,
                "projectId": 1,
                "userId": 3,
                "permission": "read",
                "createdAt": "2026-04-15T10:00:01",
                "updatedAt": "2026-04-15T10:00:01",
            },
        ]

        self.lastListProjectsCall = None
        self.lastInsertProjectCall = None
        self.lastGetProjectCall = None
        self.lastUpdateProjectCall = None
        self.lastDeleteProjectCall = None
        self.lastShareProjectWithUserCalls = []
        self.lastListProjectSharesCall = None
        self.lastRevokeProjectShareCall = None

    def listProjects(self, ownerId=None):
        self.lastListProjectsCall = {"ownerId": ownerId}
        return self.projectsListResult

    def countProjectProtocols(self, projectId):
        self.lastCountProjectProtocolsCall = {"projectId": projectId}
        return self.projectProtocolCounts.get(projectId, 0)

    def insertProject(self, ownerId, name, description, status):
        self.lastInsertProjectCall = {
            "ownerId": ownerId,
            "name": name,
            "description": description,
            "status": status,
        }
        return self.insertProjectResult

    def getProject(self, projectId, userId):
        self.lastGetProjectCall = {"projectId": projectId, "userId": userId}
        return self.projectsById.get((projectId, userId))

    def updateProject(self, projectId, userId, newPath, description):
        self.lastUpdateProjectCall = {
            "projectId": projectId,
            "userId": userId,
            "newPath": newPath,
            "description": description,
        }
        return self.updateProjectResult

    def deleteProject(self, projectId, userId):
        self.lastDeleteProjectCall = {"projectId": projectId, "userId": userId}
        return self.deleteProjectResult

    def shareProjectWithUser(self, projectId, targetUserId, permission):
        self.lastShareProjectWithUserCalls.append(
            {
                "projectId": projectId,
                "targetUserId": targetUserId,
                "permission": permission,
            }
        )
        return self.shareProjectRows[len(self.lastShareProjectWithUserCalls) - 1]

    def listProjectShares(self, projectId):
        self.lastListProjectSharesCall = {"projectId": projectId}
        return self.listProjectSharesResult

    def revokeProjectShare(self, projectId, userId):
        self.lastRevokeProjectShareCall = {
            "projectId": projectId,
            "userId": userId,
        }
        return self.revokeProjectShareResult


class ProjectCreatePayload:
    # projectCreatePayload
    def __init__(self, name, description=None, status="active"):
        self.name = name
        self.description = description
        self.status = status


class ProjectUpdatePayload:
    # projectUpdatePayload
    def __init__(self, name=None, description=None, status=None):
        self.name = name
        self.description = description
        self.status = status


@pytest.fixture
def projectServiceModule(authTestEnv):
    # projectServiceModule
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule, tmp_path):
    # service
    projectsRoot = tmp_path / "projects"
    projectsRoot.mkdir(parents=True, exist_ok=True)

    instance = object.__new__(projectServiceModule.ProjectService)
    instance.manager = FakeManager(projectsRoot)
    instance.objectManager = None
    instance.currentProject = None
    instance.tomoList = {}
    return instance


@pytest.fixture
def mapper():
    # mapper
    return FakeMapper()


@pytest.fixture
def currentUser():
    # currentUser
    return {
        "id": 1,
        "email": "user@example.com",
        "role": "user",
    }


def test_CreateProjectSanitizesNameAndInsertsProject(service, mapper, currentUser):
    payload = ProjectCreatePayload(
        name="  my project / v1  ",
        description="demo project",
        status="active",
    )

    result = service.createProject(mapper, payload, currentUser)

    assert mapper.lastListProjectsCall == {"ownerId": 1}
    assert service.manager.createdProjects == ["my_project_v1"]
    assert mapper.lastInsertProjectCall == {
        "ownerId": 1,
        "name": os.path.join(service.manager.PROJECTS, "my_project_v1"),
        "description": "demo project",
        "status": "active",
    }
    assert result["id"] == 101
    assert result["name"] == "my_project_v1"
    assert result["description"] == "demo project"
    assert result["status"] == "active"
    assert result["isOwner"] is True
    assert result["permission"] == "full"
    assert result["projectOwnerId"] == 1
    assert result["thumbnailUrl"] == "/projects/101/thumbnail"


def test_CreateProjectRejectsDuplicateSanitizedName(service, mapper, currentUser):
    mapper.projectsListResult = [{"name": "my_project_v1"}]
    payload = ProjectCreatePayload(name="my project / v1")

    with pytest.raises(HTTPException) as exc:
        service.createProject(mapper, payload, currentUser)

    assert exc.value.status_code == 400
    assert "sanitized name: 'my_project_v1'" in exc.value.detail


def test_CreateProjectRejectsFilesystemCollision(service, mapper, currentUser):
    existingPath = Path(service.manager.getProjectPath("demo"))
    existingPath.mkdir(parents=True, exist_ok=True)

    payload = ProjectCreatePayload(name="demo")

    with pytest.raises(HTTPException) as exc:
        service.createProject(mapper, payload, currentUser)

    assert exc.value.status_code == 400
    assert "already exists in the file system" in exc.value.detail


def test_UpdateProjectReturns404WhenProjectMissing(service, mapper, currentUser):
    payload = ProjectUpdatePayload(name="renamed")

    with pytest.raises(HTTPException) as exc:
        service.updateProject(mapper, 1, currentUser, payload)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Project not found"


def test_UpdateProjectReturns404WhenProjectPathMissingOnDisk(service, mapper, currentUser):
    missingPath = service.manager.getProjectPath("demo")
    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": missingPath,
        "description": "demo description",
    }

    payload = ProjectUpdatePayload(name="renamed")

    with pytest.raises(HTTPException) as exc:
        service.updateProject(mapper, 1, currentUser, payload)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Project path not found on disk"


def test_UpdateProjectRejectsExternalImportedProjects(service, mapper, currentUser, tmp_path):
    externalPath = tmp_path / "external" / "demo"
    externalPath.mkdir(parents=True, exist_ok=True)

    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": str(externalPath),
        "description": "demo description",
    }

    payload = ProjectUpdatePayload(name="renamed")

    with pytest.raises(HTTPException) as exc:
        service.updateProject(mapper, 1, currentUser, payload)

    assert exc.value.status_code == 422
    assert exc.value.detail == "Renaming external imported projects is not supported"


def test_UpdateProjectRenamesManagedProjectAndFallsBackDescription(service, mapper, currentUser):
    currentPath = Path(service.manager.getProjectPath("demo"))
    currentPath.mkdir(parents=True, exist_ok=True)

    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": str(currentPath),
        "description": "old description",
    }

    payload = ProjectUpdatePayload(name="renamed project", description=None)

    result = service.updateProject(mapper, 1, currentUser, payload)

    expectedNewPath = os.path.join(service.manager.PROJECTS, "renamed_project")
    assert service.manager.renamedProjects == [
        {
            "currentPath": str(currentPath),
            "newName": "renamed_project",
            "newPath": expectedNewPath,
        }
    ]
    assert mapper.lastUpdateProjectCall == {
        "projectId": 1,
        "userId": 1,
        "newPath": expectedNewPath,
        "description": "old description",
    }
    assert result == mapper.updateProjectResult


def test_UpdateProjectRenamesLinkedProjectUsingOsRename(service, mapper, currentUser, tmp_path):
    targetPath = tmp_path / "external-target"
    targetPath.mkdir(parents=True, exist_ok=True)

    linkPath = Path(service.manager.PROJECTS) / "linked-project"
    linkPath.symlink_to(targetPath, target_is_directory=True)

    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": str(linkPath),
        "description": "linked description",
    }

    payload = ProjectUpdatePayload(name="renamed-link", description="new description")

    service.updateProject(mapper, 1, currentUser, payload)

    expectedNewPath = Path(service.manager.PROJECTS) / "renamed-link"
    assert linkPath.exists() is False
    assert expectedNewPath.is_symlink() is True
    assert mapper.lastUpdateProjectCall == {
        "projectId": 1,
        "userId": 1,
        "newPath": str(expectedNewPath),
        "description": "new description",
    }


def test_DeleteProjectReturns404WhenProjectMissing(service, mapper, currentUser):
    with pytest.raises(HTTPException) as exc:
        service.deleteProject(mapper, currentUser, 1)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Project not found"


def test_DeleteProjectUnregistersLinkedProjectAndRemovesSymlink(service, mapper, currentUser, tmp_path):
    targetPath = tmp_path / "external-target"
    targetPath.mkdir(parents=True, exist_ok=True)

    linkPath = Path(service.manager.PROJECTS) / "linked-project"
    linkPath.symlink_to(targetPath, target_is_directory=True)

    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": str(linkPath),
        "ownerId": 1,
    }

    result = service.deleteProject(mapper, currentUser, 1)

    assert result == {"message": "Linked project unregistered successfully"}
    assert linkPath.exists() is False
    assert mapper.lastDeleteProjectCall == {"projectId": 1, "userId": 1}


def test_DeleteProjectUnregistersExternalProjectWithoutRemovingFolder(service, mapper, currentUser, tmp_path):
    externalPath = tmp_path / "external-project"
    externalPath.mkdir(parents=True, exist_ok=True)

    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": str(externalPath),
        "ownerId": 1,
    }

    result = service.deleteProject(mapper, currentUser, 1)

    assert result == {"message": "Project unregistered successfully"}
    assert externalPath.exists() is True


def test_DeleteProjectReturnsSuccessWhenManagedFolderAlreadyMissing(service, mapper, currentUser):
    managedPath = service.manager.getProjectPath("demo-missing")

    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": managedPath,
        "ownerId": 1,
    }

    result = service.deleteProject(mapper, currentUser, 1)

    assert result == {"message": "Project deleted successfully"}


def test_DeleteProjectDeletesManagedFolder(service, mapper, currentUser):
    managedPath = Path(service.manager.getProjectPath("demo-project"))
    managedPath.mkdir(parents=True, exist_ok=True)

    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": str(managedPath),
        "ownerId": 1,
    }

    result = service.deleteProject(mapper, currentUser, 1)

    assert result == {"message": "Project deleted successfully"}
    assert service.manager.deletedProjects == [str(managedPath)]
    assert managedPath.exists() is False


def test_ListProjectsBuildsComputedFields(service, mapper, currentUser, monkeypatch, tmp_path):
    storedPath = Path(service.manager.PROJECTS) / "demo-project"
    storedPath.mkdir(parents=True, exist_ok=True)

    runsPath = storedPath / "Runs"
    runsPath.mkdir(parents=True, exist_ok=True)

    mapper.projectsListResult = [
        {
            "id": 1,
            "name": str(storedPath),
            "description": "demo description",
            "createdAt": "2026-04-15T10:00:00",
            "updatedAt": "2026-04-15T11:00:00",
            "status": "active",
            "ownerId": 1,
        }
    ]

    monkeypatch.setattr(service, "getProjectSize", lambda path: 3 * 1024 ** 3)
    mapper.projectProtocolCounts[1] = 7
    monkeypatch.setattr(service, "countProtocols", lambda path: 999)
    monkeypatch.setattr(service, "_buildProjectThumbnailVersion", lambda **kwargs: "thumb-v1")

    result = service.listProjects(mapper, currentUser)

    assert result == [
        {
            "id": 1,
            "name": "demo-project",
            "description": "demo description",
            "createdAt": "2026-04-15T10:00:00",
            "status": "active",
            "protocolsCount": 7,
            "diskUsage": "3.00 GB",
            "isOwner": True,
            "isShared": False,
            "permission": "owner",
            "projectOwnerId": 1,
            "updatedAt": "2026-04-15T11:00:00",
            "thumbnailUrl": "/projects/1/thumbnail",
            "thumbnailRebuildUrl": "/projects/1/thumbnail/rebuild",
            "thumbnailItemsUrl": "/projects/1/thumbnail-items",
            "thumbnailVersion": "1:2026-04-15T11:00:00:7:postgresql",
        }
    ]
    assert mapper.lastCountProjectProtocolsCall == {"projectId": 1}


def test_ListProjectsRaisesWhenPostgresqlProtocolCountFails(
    service,
    mapper,
    currentUser,
):
    mapper.projectsListResult = [
        {
            "id": 1,
            "name": "/some/scipion/projects/demo-project",
            "description": "demo description",
            "createdAt": "2026-04-15T10:00:00",
            "updatedAt": "2026-04-15T11:00:00",
            "status": "active",
            "ownerId": 1,
        }
    ]

    def failCountProjectProtocols(projectId):
        raise RuntimeError("postgresql count failed")

    mapper.countProjectProtocols = failCountProjectProtocols

    with pytest.raises(HTTPException) as exc:
        service.listProjects(mapper, currentUser)

    assert exc.value.status_code == 500
    assert "Failed to count project protocols from PostgreSQL" in exc.value.detail


def test_ListProjectsKeepsSharedFlagsFromMapper(service, mapper, currentUser):
    mapper.projectsListResult = [
        {
            "id": 2,
            "name": "/some/scipion/projects/shared-project",
            "description": "shared description",
            "createdAt": "2026-04-15T10:00:00",
            "updatedAt": "2026-04-15T11:00:00",
            "status": "active",
            "ownerId": 99,
            "isOwner": False,
            "isShared": True,
            "permission": "read",
        }
    ]

    mapper.projectProtocolCounts[2] = 4

    result = service.listProjects(mapper, currentUser)

    assert result[0]["name"] == "shared-project"
    assert result[0]["protocolsCount"] == 4
    assert result[0]["isOwner"] is False
    assert result[0]["isShared"] is True
    assert result[0]["permission"] == "read"
    assert result[0]["projectOwnerId"] == 99
    assert result[0]["thumbnailVersion"] == "2:2026-04-15T11:00:00:4:postgresql"


def test_ShareProjectWithUserReturns404WhenProjectMissing(service, mapper, currentUser):
    with pytest.raises(HTTPException) as exc:
        service.shareProjectWithUser(
            mapper=mapper,
            projectId=1,
            currentUser=currentUser,
            targetUserIds=[2, 3],
            permission="read",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Project not found or you are not the owner"


def test_ShareProjectWithUserDelegatesAndReturnsLastShareRow(service, mapper, currentUser):
    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": service.manager.getProjectPath("demo"),
        "ownerId": 1,
    }

    result = service.shareProjectWithUser(
        mapper=mapper,
        projectId=1,
        currentUser=currentUser,
        targetUserIds=[2, 3],
        permission="read",
    )

    assert mapper.lastShareProjectWithUserCalls == [
        {"projectId": 1, "targetUserId": 2, "permission": "read"},
        {"projectId": 1, "targetUserId": 3, "permission": "read"},
    ]
    assert result == {
        "id": 701,
        "projectId": 1,
        "userId": 3,
        "permission": "read",
        "createdAt": "2026-04-15T10:00:01",
        "updatedAt": "2026-04-15T10:00:01",
    }


def test_ListProjectSharesReturns404WhenProjectMissing(service, mapper, currentUser):
    with pytest.raises(HTTPException) as exc:
        service.listProjectShares(mapper=mapper, projectId=1, currentUser=currentUser)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Project not found or you are not the owner"


def test_ListProjectSharesReturnsMapperResult(service, mapper, currentUser):
    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": service.manager.getProjectPath("demo"),
        "ownerId": 1,
    }

    result = service.listProjectShares(mapper=mapper, projectId=1, currentUser=currentUser)

    assert result == mapper.listProjectSharesResult
    assert mapper.lastListProjectSharesCall == {"projectId": 1}


def test_RevokeProjectShareForUserReturns404WhenProjectMissing(service, mapper, currentUser):
    with pytest.raises(HTTPException) as exc:
        service.revokeProjectShareForUser(
            mapper=mapper,
            projectId=1,
            targetUserId=2,
            currentUser=currentUser,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Project not found"


def test_RevokeProjectShareForUserReturns403WhenCurrentUserIsNotOwner(service, mapper, currentUser):
    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": service.manager.getProjectPath("demo"),
        "ownerId": 99,
    }

    with pytest.raises(HTTPException) as exc:
        service.revokeProjectShareForUser(
            mapper=mapper,
            projectId=1,
            targetUserId=2,
            currentUser=currentUser,
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Only project owner can revoke shares"


def test_RevokeProjectShareForUserRejectsRemovingOwner(service, mapper, currentUser):
    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": service.manager.getProjectPath("demo"),
        "ownerId": 1,
    }

    with pytest.raises(HTTPException) as exc:
        service.revokeProjectShareForUser(
            mapper=mapper,
            projectId=1,
            targetUserId=1,
            currentUser=currentUser,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Owner cannot be removed from the project"


def test_RevokeProjectShareForUserReturns404WhenShareMissing(service, mapper, currentUser):
    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": service.manager.getProjectPath("demo"),
        "ownerId": 1,
    }
    mapper.revokeProjectShareResult = False

    with pytest.raises(HTTPException) as exc:
        service.revokeProjectShareForUser(
            mapper=mapper,
            projectId=1,
            targetUserId=2,
            currentUser=currentUser,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Share entry not found"


def test_RevokeProjectShareForUserReturnsSuccess(service, mapper, currentUser):
    mapper.projectsById[(1, 1)] = {
        "id": 1,
        "name": service.manager.getProjectPath("demo"),
        "ownerId": 1,
    }

    result = service.revokeProjectShareForUser(
        mapper=mapper,
        projectId=1,
        targetUserId=2,
        currentUser=currentUser,
    )

    assert result == {"success": True}
    assert mapper.lastRevokeProjectShareCall == {
        "projectId": 1,
        "userId": 2,
    }


def test_ListProjectsBuildsProjectOutFromPostgresqlOnly(
    service,
    mapper,
    currentUser,
    monkeypatch,
):
    mapper.projectsListResult = [
        {
            "id": 1,
            "name": "/some/scipion/projects/demo-project",
            "description": "demo description",
            "createdAt": "2026-04-15T10:00:00",
            "updatedAt": "2026-04-15T11:00:00",
            "status": "active",
            "ownerId": 1,
            "isOwner": True,
            "isShared": False,
            "permission": "owner",
        }
    ]

    mapper.projectProtocolCounts[1] = 7

    def failFilesystemCall(*args, **kwargs):
        raise AssertionError("listProjects should not touch filesystem helpers")

    monkeypatch.setattr(service, "getProjectSize", failFilesystemCall)
    monkeypatch.setattr(service, "countProtocols", failFilesystemCall)
    monkeypatch.setattr(service, "_buildProjectThumbnailVersion", failFilesystemCall)

    result = service.listProjects(mapper, currentUser)

    assert result == [
        {
            "id": 1,
            "name": "demo-project",
            "description": "demo description",
            "createdAt": "2026-04-15T10:00:00",
            "status": "active",
            "protocolsCount": 7,
            "diskUsage": "0.00 GB",
            "isOwner": True,
            "isShared": False,
            "permission": "owner",
            "projectOwnerId": 1,
            "updatedAt": "2026-04-15T11:00:00",
            "thumbnailUrl": "/projects/1/thumbnail",
            "thumbnailRebuildUrl": "/projects/1/thumbnail/rebuild",
            "thumbnailItemsUrl": "/projects/1/thumbnail-items",
            "thumbnailVersion": "1:2026-04-15T11:00:00:7:postgresql",
        }
    ]

    assert mapper.lastListProjectsCall == {"ownerId": 1}
    assert mapper.lastCountProjectProtocolsCall == {"projectId": 1}


def test_ListProjectsReturnsZeroDiskUsageWhenFilesystemSizeFails(
    service,
    mapper,
    currentUser,
    monkeypatch,
):
    mapper.projectsListResult = [
        {
            "id": 1,
            "name": "/some/scipion/projects/demo-project",
            "description": "demo description",
            "createdAt": "2026-04-15T10:00:00",
            "updatedAt": "2026-04-15T11:00:00",
            "status": "active",
            "ownerId": 1,
        }
    ]

    mapper.projectProtocolCounts[1] = 7

    def failGetProjectSize(path):
        raise RuntimeError("du failed")

    monkeypatch.setattr(service, "getProjectSize", failGetProjectSize)

    result = service.listProjects(mapper, currentUser)

    assert result[0]["diskUsage"] == "0.00 GB"
    assert result[0]["protocolsCount"] == 7