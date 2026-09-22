from typing import Any, Dict, Iterator, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.mapper.tomogram_review_mapper import (
    TomogramReviewRevisionConflict,
)


class FakeTomogramReviewService:
    def __init__(self):
        self.projectDbRowResult: Optional[Dict[str, Any]] = {
            "id": 7,
            "isOwner": True,
            "permission": "owner",
        }
        self.contextResult = {
            "setId": 47,
            "schema": None,
            "progress": {
                "total": 120,
                "reviewed": 37,
            },
            "reviews": {
                "31": {
                    "setId": 47,
                    "scipionItemId": 31,
                    "reviewed": True,
                    "values": {"quality": "Good", "mito": True},
                    "comment": "Good membrane contrast",
                    "revision": 4,
                },
            },
        }
        self.saveResult = {
            "setId": 47,
            "scipionItemId": 31,
            "reviewed": True,
            "values": {"quality": "Excellent", "mito": True},
            "comment": "Updated review",
            "revision": 5,
        }
        self.saveError: Optional[Exception] = None
        self.lastGetProjectDbRowCall = None
        self.lastContextCall = None
        self.lastSaveCall = None

    def getProjectDbRow(self, mapper, projectId, currentUser):
        self.lastGetProjectDbRowCall = {
            "mapper": mapper,
            "projectId": projectId,
            "currentUser": currentUser,
        }
        return self.projectDbRowResult

    def getTomogramReviewContextService(
            self,
            mapper,
            projectId,
            protocolId,
            outputName,
    ):
        self.lastContextCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
        }
        return self.contextResult

    def saveTomogramReviewService(
            self,
            mapper,
            projectId,
            protocolId,
            outputName,
            scipionItemId,
            payload,
            reviewedByUserId,
    ):
        self.lastSaveCall = {
            "mapper": mapper,
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "scipionItemId": scipionItemId,
            "payload": payload,
            "reviewedByUserId": reviewedByUserId,
        }

        if self.saveError is not None:
            raise self.saveError

        return self.saveResult


@pytest.fixture
def fakeTomogramReviewService():
    return FakeTomogramReviewService()


@pytest.fixture
def tomogramReviewClient(
        projectRouterModule,
        fakeProjectMapper,
        fakeTomogramReviewService,
) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(projectRouterModule.router)

    app.dependency_overrides[projectRouterModule.getMapper] = lambda: fakeProjectMapper
    app.dependency_overrides[projectRouterModule.getCurrentUser] = lambda: {
        "id": 13,
        "email": "reviewer@example.com",
        "role": "user",
    }
    app.dependency_overrides[projectRouterModule.getProjectService] = (
        lambda: fakeTomogramReviewService
    )

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_GetTomogramReviewContextDelegatesToPostgresqlService(
        tomogramReviewClient,
        fakeTomogramReviewService,
        fakeProjectMapper,
):
    response = tomogramReviewClient.get(
        "/projects/7/protocols/42/outputs/outputTomograms/reviews"
    )

    assert response.status_code == 200
    assert response.json() == fakeTomogramReviewService.contextResult
    assert fakeTomogramReviewService.lastContextCall == {
        "mapper": fakeProjectMapper,
        "projectId": 7,
        "protocolId": 42,
        "outputName": "outputTomograms",
    }


def test_PatchTomogramReviewDelegatesRevisionedWrite(
        tomogramReviewClient,
        fakeTomogramReviewService,
        fakeProjectMapper,
):
    payload = {
        "reviewed": True,
        "values": {"quality": "Excellent", "mito": True},
        "comment": "Updated review",
        "revision": 4,
    }

    response = tomogramReviewClient.patch(
        "/projects/7/protocols/42/outputs/outputTomograms/tomograms/31/review",
        json=payload,
    )

    assert response.status_code == 200
    assert response.json() == fakeTomogramReviewService.saveResult
    assert fakeTomogramReviewService.lastSaveCall == {
        "mapper": fakeProjectMapper,
        "projectId": 7,
        "protocolId": 42,
        "outputName": "outputTomograms",
        "scipionItemId": 31,
        "payload": payload,
        "reviewedByUserId": 13,
    }


def test_PatchTomogramReviewReturnsCurrentStateOnRevisionConflict(
        tomogramReviewClient,
        fakeTomogramReviewService,
):
    current = {
        "setId": 47,
        "scipionItemId": 31,
        "reviewed": True,
        "values": {"quality": "Good"},
        "comment": "Winning update",
        "revision": 5,
    }
    fakeTomogramReviewService.saveError = TomogramReviewRevisionConflict(
        current=current
    )

    response = tomogramReviewClient.patch(
        "/projects/7/protocols/42/outputs/outputTomograms/tomograms/31/review",
        json={
            "reviewed": True,
            "values": {"quality": "Bad"},
            "comment": "Stale update",
            "revision": 4,
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "message": "Tomogram review was modified by another user",
            "current": current,
        },
    }


def test_PatchTomogramReviewRejectsReadOnlyProjectAccess(
        tomogramReviewClient,
        fakeTomogramReviewService,
):
    fakeTomogramReviewService.projectDbRowResult = {
        "id": 7,
        "isOwner": False,
        "permission": "read",
    }

    response = tomogramReviewClient.patch(
        "/projects/7/protocols/42/outputs/outputTomograms/tomograms/31/review",
        json={
            "reviewed": True,
            "values": {},
            "comment": None,
            "revision": 0,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Project write permission is required"
    assert fakeTomogramReviewService.lastSaveCall is None
