# RED 55: authenticated generic Set item metadata paging contract.
#
# The public route accepts the Scipion protocol ID, while the mapper takes
# protocols.id (PostgreSQL PK). All member IDs are scipionItemId, not SQL PKs
# or list positions. Discovery returns metadata only, NEVER an invented
# executable pointer value. That runtime contract will be tested separately.

import pytest
from fastapi import HTTPException

from app.backend.api.services.project_service import ProjectService
import app.backend.api.services.project_service as projectServiceModule


URL = "/projects/7/protocols/21/outputs/outputVolumes/pointer-items"


def member(item_id, label, enabled=True):
    return {
        "scipionItemId": item_id,
        "name": label,
        "enabled": enabled,
        "itemClassName": "Volume",
    }


def test_ExistingVolumeRouteRemainsRegistered_RED55_baseline(projectRouterModule):
    """Existing API remains untouched while adding a generic sibling route."""
    registered_paths = {route.path for route in projectRouterModule.router.routes}
    assert (
        "/projects/{projectId}/protocols/{protocolId}/outputs/"
        "{outputName}/volumes"
    ) in registered_paths


def test_PointerItemsRouteIsAuthenticatedAndReturnsOpaquePage_RED55(
        projectClient, fakeProjectService, fakeProjectMapper,
):
    page = {
        "items": [member(34, "First volume", True), member(35, "Second volume", False)],
        "nextCursor": "35",
    }
    calls = []

    def load_page(**kwargs):
        calls.append(kwargs)
        return page

    fakeProjectService.listPointerSelectableSetItemsPageService = load_page
    response = projectClient.get(URL, params={"cursor": "18", "limit": 2})

    assert response.status_code == 200
    assert response.json() == page
    assert calls == [{
        "mapper": fakeProjectMapper,
        "projectId": 7,
        "protocolId": 21,
        "outputName": "outputVolumes",
        "cursor": "18",
        "limit": 2,
        "protocolIdIsScipionId": True,
    }]
    assert fakeProjectService.lastGetProjectDbRowCall["projectId"] == 7
    assert "no-store" in response.headers.get("cache-control", "")
    assert response.headers.get("vary") == "Authorization"
    assert all("value" not in item for item in response.json()["items"])


def test_PointerItemsRouteDefaultsToFirstPage_RED55(
        projectClient, fakeProjectService,
):
    calls = []

    def load_page(**kwargs):
        calls.append(kwargs)
        return {"items": [], "nextCursor": None}

    fakeProjectService.listPointerSelectableSetItemsPageService = load_page
    response = projectClient.get(URL)

    assert response.status_code == 200
    assert response.json() == {"items": [], "nextCursor": None}
    assert calls and calls[0]["cursor"] is None
    assert calls[0]["limit"] == 50


def test_PointerItemsRouteDeniesProjectBeforeAnyItemRead_RED55(
        projectClient, fakeProjectService,
):
    fakeProjectService.projectDbRowResult = None
    calls = []

    def load_page(**kwargs):
        calls.append(kwargs)
        raise AssertionError("Never read set items for unauthorized projects")

    fakeProjectService.listPointerSelectableSetItemsPageService = load_page
    response = projectClient.get(URL)

    assert response.status_code == 404
    assert fakeProjectService.lastGetProjectDbRowCall["projectId"] == 7
    assert calls == []


def test_PointerItemsRouteRejectsUnboundedOrUnsafePaging_RED55(
        projectClient, fakeProjectService,
):
    calls = []

    def load_page(**kwargs):
        calls.append(kwargs)
        return {"items": [], "nextCursor": None}

    fakeProjectService.listPointerSelectableSetItemsPageService = load_page
    for query in (
        {"limit": 0},
        {"limit": 101},
        {"cursor": "-1"},
        {"cursor": "34; DELETE FROM scipion_set_items"},
    ):
        response = projectClient.get(URL, params=query)
        assert response.status_code == 422, (query, response.status_code)
    assert calls == []


def test_PointerItemsServiceMapsScipionIdToDbIdStrictly_RED55(monkeypatch):
    identity_calls = []
    mapper_calls = []
    database = object()

    class Identity:
        def __init__(self, mapper, projectId):
            assert mapper.db is database
            assert projectId == 7

        def resolvePostgresqlProtocolDbIdFromScipionProtocolId(self, protocolId):
            identity_calls.append(protocolId)
            return 205 if protocolId == 21 else None

    class SetMapper:
        def __init__(self, db):
            assert db is database

        def listPointerSelectableSetItemsPage(self, **kwargs):
            mapper_calls.append(kwargs)
            return {"items": [member(34, "Reference")], "nextCursor": None}

    monkeypatch.setattr(projectServiceModule, "ProtocolIdentityResolver", Identity)
    monkeypatch.setattr(projectServiceModule, "ScipionSetPostgresqlMapper", SetMapper, raising=False)
    mapper = type("Mapper", (), {"db": database})()
    service = ProjectService.__new__(ProjectService)

    result = service.listPointerSelectableSetItemsPageService(
        mapper=mapper, projectId=7, protocolId=21,
        outputName="outputVolumes", cursor="12", limit=2,
        protocolIdIsScipionId=True,
    )

    assert result == {"items": [member(34, "Reference")], "nextCursor": None}
    assert identity_calls == [21]
    assert mapper_calls == [{
        "projectId": 7,
        "protocolDbId": 205,
        "outputName": "outputVolumes",
        "cursor": "12",
        "limit": 2,
    }]
    with pytest.raises(HTTPException) as error:
        service.listPointerSelectableSetItemsPageService(
            mapper=mapper, projectId=7, protocolId=999,
            outputName="outputVolumes", cursor=None, limit=50,
            protocolIdIsScipionId=True,
        )
    assert error.value.status_code == 404
    assert identity_calls == [21, 999]
    assert len(mapper_calls) == 1
