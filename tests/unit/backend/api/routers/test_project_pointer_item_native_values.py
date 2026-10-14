# describe contract: RED 68 native Scipion member references are opt-in
# Metadata-only requests and responses remain backwards compatible with RED 55.
# The backend, not React, owns the native Pointer(parentProtocol,
# extended="outputVolumes.34") textual representation.

import pytest

from app.backend.api.services.project_service import ProjectService
import app.backend.api.services.project_service as projectServiceModule

URL = "/projects/7/protocols/2202/outputs/outputVolumes/pointer-items"


def member(item_id=34, enabled=True, item_class="Volume"):
    return {
        "scipionItemId": item_id,
        "name": "Member %s" % item_id,
        "enabled": enabled,
        "itemClassName": item_class,
    }


def read_service_page(monkeypatch, rows, *, protocol_id="2202", output_name="outputVolumes", cursor=None):
    """Run the production service with a strictly resolved Scipion producer."""
    calls = []
    db = object()

    class Identity:
        def __init__(self, mapper, projectId):
            assert mapper.db is db
            assert projectId == 7

        def resolvePostgresqlProtocolDbIdFromScipionProtocolId(self, candidate):
            calls.append(("identity", candidate))
            assert str(candidate) == "2202"
            return 205

        def resolvePostgresqlProtocolDbId(self, _candidate):
            raise AssertionError("Never confuse the Scipion ID with protocols.id")

    class SetMapper:
        def __init__(self, database):
            assert database is db

        def listPointerSelectableSetItemsPage(self, **kwargs):
            calls.append(("set-page", kwargs))
            return {"items": [dict(row) for row in rows], "nextCursor": "91"}

    monkeypatch.setattr(projectServiceModule, "ProtocolIdentityResolver", Identity)
    monkeypatch.setattr(projectServiceModule, "ScipionSetPostgresqlMapper", SetMapper)
    mapper = type("Mapper", (), {"db": db})()
    service = ProjectService.__new__(ProjectService)
    page = service.listPointerSelectableSetItemsPageService(
        mapper=mapper, projectId=7, protocolId=protocol_id,
        outputName=output_name, cursor=cursor, limit=2,
        protocolIdIsScipionId=True, includePointerValues=True,
    )
    return page, calls


def test_MetadataOnlyRouteIsStillUnchanged_RED68_baseline(
        projectClient, fakeProjectService,
):
    original = {"items": [member()], "nextCursor": "34"}
    calls = []

    def page(**kwargs):
        calls.append(kwargs)
        return original

    fakeProjectService.listPointerSelectableSetItemsPageService = page
    response = projectClient.get(URL)

    assert response.status_code == 200
    assert response.json() == original
    assert "value" not in response.json()["items"][0]
    assert calls[0]["protocolIdIsScipionId"] is True
    # Default callers must not need the new opt-in argument.
    assert "includePointerValues" not in calls[0]


def test_RouteForwardsExplicitNativePointerOptIn_RED68(
        projectClient, fakeProjectService,
):
    calls = []

    def page(**kwargs):
        calls.append(kwargs)
        return {"items": [dict(member(), value="2202.outputVolumes.34")], "nextCursor": None}

    fakeProjectService.listPointerSelectableSetItemsPageService = page
    response = projectClient.get(URL, params={"includePointerValues": "true"})

    assert response.status_code == 200
    assert calls[0]["protocolId"] == 2202
    assert calls[0]["includePointerValues"] is True
    assert response.json()["items"][0]["value"] == "2202.outputVolumes.34"
    assert "no-store" in response.headers.get("cache-control", "")


def test_ServerCreatesNativeItemReferenceFromPersistedScipionIdentity_RED68(monkeypatch):
    page, calls = read_service_page(monkeypatch, [member(34)])
    item = page["items"][0]

    assert item["value"] == "2202.outputVolumes.34"
    assert item["pointerClass"] == "Volume"
    assert item["selectionKind"] == "set-item"
    assert item["scipionItemId"] == 34
    assert str(item["parentId"]) == "2202"
    assert item["key"] == "outputVolumes"
    assert page["nextCursor"] == "91"
    assert calls == [
        ("identity", "2202"),
        ("set-page", {
            "projectId": 7, "protocolDbId": 205,
            "outputName": "outputVolumes", "cursor": None, "limit": 2,
        }),
    ]


def test_DisabledMembersAreNeverAdvertisedAsSelectable_RED68(monkeypatch):
    page, _ = read_service_page(monkeypatch, [member(34, False), member(91)])
    disabled, enabled = page["items"]

    assert disabled["enabled"] is False
    assert disabled.get("selectable") is False
    assert "value" not in disabled
    assert enabled["value"] == "2202.outputVolumes.91"
    assert enabled["selectable"] is True


def test_InvalidOrUnknownMemberIdentityCannotBecomeExecutable_RED68(monkeypatch):
    page, _ = read_service_page(monkeypatch, [
        member(0), member("bad-id"), member(True), member(34, item_class=""),
    ])
    for item in page["items"]:
        assert item.get("selectable") is False
        assert "value" not in item
        assert item.get("selectionKind") != "set-item"


def test_CursorAndUnsafeOutputNamesNeverInventPointerReferences_RED68(monkeypatch):
    page, calls = read_service_page(
        monkeypatch, [member(91)], cursor="34",
        output_name="outputVolumes.999",
    )
    assert page["nextCursor"] == "91"
    assert page["items"][0].get("selectable") is False
    assert "value" not in page["items"][0]
    assert calls[1][1]["cursor"] == "34"
    assert calls[1][1]["outputName"] == "outputVolumes.999"
