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

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeUserMapper:
    # fakeUserMapper
    def __init__(self):
        self.usersResult = [
            {"id": 2, "email": "alice@example.com", "firstName": "Alice", "lastName": "Doe"},
            {"id": 3, "email": "bob@example.com", "firstName": "Bob", "lastName": "Smith"},
        ]
        self.lastListUsersCall = None
        self.adminUsersResult = [
            {
                "id": 1,
                "email": "admin@example.com",
                "firstName": "Admin",
                "lastName": "User",
                "institution": "CNB-CSIC",
                "role": "admin",
                "isActive": True,
                "isVerified": True,
            },
            {
                "id": 2,
                "email": "alice@example.com",
                "firstName": "Alice",
                "lastName": "Doe",
                "institution": "Lab",
                "role": "user",
                "isActive": True,
                "isVerified": True,
            },
        ]

        self.usersById = {
            user["id"]: dict(user)
            for user in self.adminUsersResult
        }

        self.updatedUserFields = []

    def listUsers(self, excludeUserId=None):
        self.lastListUsersCall = {
            "excludeUserId": excludeUserId,
        }
        return self.usersResult

    def listUsersForAdmin(self):
        return self.adminUsersResult

    def getUserById(self, userId):
        return self.usersById.get(userId)

    def updateUserFields(self, userId, fields):
        self.usersById[userId].update(fields)
        self.updatedUserFields.append((userId, fields))


@pytest.fixture
def adminUserClient(userRouterModule, fakeUserMapper):
    app = FastAPI()
    app.include_router(userRouterModule.router)

    app.dependency_overrides[userRouterModule.getMapper] = lambda: fakeUserMapper
    app.dependency_overrides[userRouterModule.requireAdmin] = lambda: {
        "id": 1,
        "email": "admin@example.com",
        "role": "admin",
    }

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def userRouterModule(authTestEnv):
    # userRouterModule
    return importlib.import_module("app.backend.api.routers.user_router")


@pytest.fixture
def fakeUserMapper():
    # fakeUserMapperFixture
    return FakeUserMapper()


@pytest.fixture
def userClient(userRouterModule, fakeUserMapper):
    # userClient
    app = FastAPI()
    app.include_router(userRouterModule.router)

    app.dependency_overrides[userRouterModule.getMapper] = lambda: fakeUserMapper
    app.dependency_overrides[userRouterModule.getCurrentUser] = lambda: {
        "id": 1,
        "email": "current@example.com",
        "role": "user",
    }

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_ListUsersReturnsMapperResult(userClient):
    response = userClient.get("/users/")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 2, "email": "alice@example.com", "firstName": "Alice", "lastName": "Doe"},
        {"id": 3, "email": "bob@example.com", "firstName": "Bob", "lastName": "Smith"},
    ]


def test_ListUsersExcludesCurrentUserId(userClient, fakeUserMapper):
    response = userClient.get("/users/")

    assert response.status_code == 200
    assert fakeUserMapper.lastListUsersCall == {
        "excludeUserId": 1,
    }


def test_AdminCanListUsers(adminUserClient):
    response = adminUserClient.get("/users/admin")

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert response.json()[0]["role"] == "admin"
    assert response.json()[1]["isActive"] is True


def test_AdminCanDeactivateUser(adminUserClient, fakeUserMapper):
    response = adminUserClient.patch(
        "/users/admin/2",
        json={"isActive": False},
    )

    assert response.status_code == 200
    assert response.json()["isActive"] is False
    assert fakeUserMapper.updatedUserFields == [
        (2, {"isActive": False}),
    ]


def test_AdminCanChangeUserRole(adminUserClient, fakeUserMapper):
    response = adminUserClient.patch(
        "/users/admin/2",
        json={"role": "admin"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_AdminCannotDeactivateOwnAccount(adminUserClient):
    response = adminUserClient.patch(
        "/users/admin/1",
        json={"isActive": False},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "You cannot deactivate your own account"


def test_AdminCannotRemoveOwnAdminRole(adminUserClient):
    response = adminUserClient.patch(
        "/users/admin/1",
        json={"role": "user"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "You cannot remove your own admin role"


def test_AdminUserUpdateReturns404(adminUserClient):
    response = adminUserClient.patch(
        "/users/admin/999",
        json={"isActive": False},
    )

    assert response.status_code == 404


def test_NormalUserCannotAccessAdminUsers(userRouterModule, fakeUserMapper):
    app = FastAPI()
    app.include_router(userRouterModule.router)

    app.dependency_overrides[userRouterModule.getMapper] = lambda: fakeUserMapper
    app.dependency_overrides[userRouterModule.getCurrentUser] = lambda: {
        "id": 2,
        "email": "alice@example.com",
        "role": "user",
    }

    with TestClient(app) as client:
        response = client.get("/users/admin")

    assert response.status_code == 403


