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

    def listUsers(self, excludeUserId=None):
        self.lastListUsersCall = {
            "excludeUserId": excludeUserId,
        }
        return self.usersResult


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