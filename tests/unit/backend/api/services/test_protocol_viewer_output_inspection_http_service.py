"""RED 171: authenticated HTTP boundary for advisory output inspection."""
from __future__ import annotations

import copy
import importlib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]

MODULE = "app.backend.api.services.protocol_viewer_output_inspection_http_service"
VIEWER = "xmipp3.viewers.DemonstrationViewer"
ACTION = "displayVolume"
PROJECT = 7
PROTOCOL = 142


def subject():
    return importlib.import_module(MODULE)


def descriptor():
    return {
        "status": "inspection-target-described",
        "source": "server-declaration+registered-static-ast+postgresql",
        "projectId": PROJECT, "protocolId": str(PROTOCOL),
        "viewerId": VIEWER, "actionId": ACTION,
        "sourceCorrelation": "single-reference-matches-declaration",
        "target": {"projectId": PROJECT, "protocolId": str(PROTOCOL), "outputName": "outputData",
                   "outputClassName": "SetOfVolumes", "webViewerKind": "volume",
                   "inspectionMode": "manual-persisted-output"},
        "bindingVerified": False, "scientificSemanticsVerified": False,
        "inspectionAuthorized": False, "actionExecutionAllowed": False,
        "requiresCallerAuthorization": True,
    }


@pytest.fixture
def ctx():
    calls = []
    result = descriptor()
    snapshot = {"viewers": {"some": object()}, "protocols": {}}

    class Service:
        def getProjectDbRow(self, mapper, project_id, user):
            calls.append(("authorize", mapper, project_id, user))
            return {"id": project_id}

    def snapshot_provider():
        calls.append(("snapshot",))
        return snapshot

    def factory(mapper):
        calls.append(("set_mapper", mapper))
        return object()

    def builder(**kwargs):
        calls.append(("build", kwargs))
        return result

    params = {
        "mapper": object(), "current_user": {"id": 8, "role": "user"},
        "project_service": Service(), "project_id": PROJECT, "protocol_id": PROTOCOL,
        "viewer_id": VIEWER, "action_id": ACTION,
        "snapshot_provider": snapshot_provider, "set_mapper_factory": factory,
        "target_builder": builder,
    }
    return params, calls, result, snapshot


def run(ctx, **changes):
    return subject().requestProtocolViewerOutputInspectionHttp(**dict(ctx[0], **changes))


def fail(ctx, code, **changes):
    with pytest.raises(subject().ProtocolViewerInspectionHttpError) as raised:
        run(ctx, **changes)
    assert raised.value.code == code


def test_successful_read_only_http_projection(ctx):
    original = copy.deepcopy(ctx[2])
    result = run(ctx)
    assert result == {
        "status": "inspection-target-described",
        "source": "server-declaration+registered-static-ast+postgresql",
        "projectId": 7, "protocolId": "142", "viewerId": VIEWER, "actionId": ACTION,
        "sourceCorrelation": "single-reference-matches-declaration",
        "target": {"projectId": 7, "protocolId": "142", "outputName": "outputData",
                   "outputClassName": "SetOfVolumes", "webViewerKind": "volume",
                   "inspectionMode": "manual-persisted-output"},
        "projectAccessVerified": True, "bindingVerified": False,
        "scientificSemanticsVerified": False, "inspectionAuthorized": False,
        "browserLaunchAllowed": False, "actionExecutionAllowed": False,
    }
    assert ctx[2] == original
    assert [x[0] for x in ctx[1]] == ["authorize", "snapshot", "set_mapper", "build"]
    assert ctx[1][-1][1]["viewer_registry"] is ctx[3]["viewers"]
    assert "source_loader" not in ctx[1][-1][1]


@pytest.mark.parametrize("bad", [
    {"project_id": 0}, {"project_id": True}, {"project_id": "7"},
    {"project_id": 2**31}, {"protocol_id": -1}, {"protocol_id": None},
    {"protocol_id": True}, {"viewer_id": "DemoViewer"},
    {"viewer_id": "x.<locals>.D"}, {"viewer_id": "x.D;rm -rf /"},
    {"viewer_id": "x." + "a" * 260}, {"action_id": ""},
    {"action_id": "_private"}, {"action_id": "../passwd"},
    {"action_id": "a" * 129}, {"action_id": None},
])
def test_invalid_identity_rejected_before_authorization_or_discovery(ctx, bad):
    fail(ctx, "invalid_identity", **bad)
    assert ctx[1] == []


@pytest.mark.parametrize("bad", [None, {}, {"id": "8"}, {"id": True}, {"id": 0}, {"id": -1}, [], "admin"])
def test_unauthenticated_requests_blocked_before_project_access(ctx, bad):
    fail(ctx, "unauthenticated", current_user=bad)
    assert ctx[1] == []


def test_non_admin_project_member_can_inspect_without_dynamic_execution_flags(ctx, monkeypatch):
    monkeypatch.delenv("SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_HTTP", raising=False)
    monkeypatch.delenv("SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL", raising=False)
    assert run(ctx)["projectAccessVerified"] is True
    assert run(ctx)["actionExecutionAllowed"] is False


def test_missing_or_forbidden_project_blocks_before_snapshot(ctx):
    class Denied:
        def getProjectDbRow(self, mapper, project_id, current_user):
            ctx[1].append(("deny",))
            return None
    fail(ctx, "project_not_found", project_service=Denied())
    assert ctx[1] == [("deny",)]


@pytest.mark.parametrize("bad", [{}, {"viewers": None}, {"viewers": []}, [], None])
def test_bad_snapshot_fails_before_set_mapper_and_builder(ctx, bad):
    fail(ctx, "invalid_context", snapshot_provider=lambda: bad)
    assert [x[0] for x in ctx[1]] == ["authorize"]


@pytest.mark.parametrize("bad", [
    {"mapper": None}, {"project_service": None},
    {"project_service": object()}, {"snapshot_provider": None},
    {"set_mapper_factory": 12}, {"target_builder": "eval"},
])
def test_invalid_server_context_rejected_without_io(ctx, bad):
    fail(ctx, "invalid_context", **bad)
    assert not ctx[1]


def test_pending_advisory_is_valid_but_contains_no_target(ctx):
    ctx[2]["status"] = "inspection-target-pending"
    ctx[2]["sourceCorrelation"] = "indeterminate"
    ctx[2]["target"] = None
    value = run(ctx)
    assert value["target"] is None
    assert value["projectAccessVerified"] is True
    assert value["browserLaunchAllowed"] is False


@pytest.mark.parametrize("corr", ["no-direct-reference", "ambiguous-references", "declared-output-not-referenced"])
def test_other_pending_evidence_states_never_launch(ctx, corr):
    ctx[2].update(status="inspection-target-pending", sourceCorrelation=corr, target=None)
    assert run(ctx)["actionExecutionAllowed"] is False


@pytest.mark.parametrize("bad", [
    {"projectId": 8}, {"protocolId": "143"}, {"viewerId": "a.B"},
    {"actionId": "other"}, {"source": "client"}, {"status": "ready"},
    {"bindingVerified": True}, {"scientificSemanticsVerified": True},
    {"inspectionAuthorized": True}, {"actionExecutionAllowed": True},
    {"requiresCallerAuthorization": False}, {"sourceCorrelation": "unverified-ready"},
])
def test_forged_metadata_never_reaches_browser(ctx, bad):
    ctx[2].update(bad)
    fail(ctx, "invalid_inspection_target")


@pytest.mark.parametrize("key,bad", [
    ("projectId", 9), ("protocolId", "9"), ("outputName", "../../secret"),
    ("outputName", "secret/path"), ("outputClassName", "CustomObject"),
    ("outputClassName", "SetOfParticles"), ("webViewerKind", "custom"),
    ("webViewerKind", "metadata"), ("inspectionMode", "auto-launch"),
    ("callback", "some_method"), ("url", "/secret"), ("filePath", "/tmp/data"),
])
def test_invalid_or_extra_target_fields_are_rejected(ctx, key, bad):
    ctx[2]["target"][key] = bad
    fail(ctx, "invalid_inspection_target")


def test_extra_untrusted_top_level_values_never_escape(ctx):
    ctx[2].update(callback="_dangerous", url="/etc/passwd", secret={"token": "x"}, executionAllowed=True)
    result = run(ctx)
    assert "callback" not in result and "url" not in result and "secret" not in result
    assert "executionAllowed" not in result and result["actionExecutionAllowed"] is False


@pytest.mark.parametrize("change", [
    {"status": "inspection-target-pending"},
    {"target": None},
    {"sourceCorrelation": "indeterminate"},
])
def test_described_metadata_must_have_exact_matching_target(ctx, change):
    ctx[2].update(change)
    fail(ctx, "invalid_inspection_target")


def test_unknown_internal_error_is_sanitized(ctx):
    from app.backend.api.services.protocol_viewer_output_inspection_target_service import ProtocolViewerInspectionTargetError
    def bad(**kwargs):
        raise ProtocolViewerInspectionTargetError("bad_internal_file_/etc/passwd")
    fail(ctx, "inspection_target_unavailable", target_builder=bad)


@pytest.mark.parametrize("error", ["binding_not_declared", "viewer_not_found", "action_not_found"])
def test_missing_action_or_binding_is_sanitized_to_same_not_found(ctx, error):
    from app.backend.api.services.protocol_viewer_output_inspection_target_service import ProtocolViewerInspectionTargetError
    def bad(**kwargs):
        raise ProtocolViewerInspectionTargetError(error)
    fail(ctx, "inspection_target_not_found", target_builder=bad)


def test_router_has_strict_schema_and_no_client_output_or_paths():
    source = _REPO_ROOT.joinpath("app/backend/api/routers/project_router.py").read_text(encoding="utf-8")
    body = source[source.index("# BEGIN PROTOCOLVIEWER INSPECTION HTTP 172"):source.index("# END PROTOCOLVIEWER INSPECTION HTTP 172")]
    assert '"/{projectId}/protocols/{protocolId}/viewers/inspection-target"' in body
    assert "@router.post(" in body
    assert "viewerId: StrictStr" in body and "actionId: StrictStr" in body
    assert 'extra = "forbid"' in body
    assert "Depends(getCurrentUser)" in body and "Depends(getMapper)" in body
    assert "Depends(getProjectService)" in body
    assert "requestProtocolViewerOutputInspectionHttp(" in body
    assert "getScipionViewerResolutionSnapshot" in body
    assert "outputName:" not in body and "path:" not in body and "source_loader" not in body
    assert "_getVisualizeDict" not in body and "eval(" not in body
    assert "loadPostgresqlRuntimeProjectForMutation" not in body


def test_router_maps_authorization_and_invalid_payload_to_fixed_http_errors():
    source = _REPO_ROOT.joinpath("app/backend/api/routers/project_router.py").read_text(encoding="utf-8")
    body = source[source.index("# BEGIN PROTOCOLVIEWER INSPECTION HTTP 172"):source.index("# END PROTOCOLVIEWER INSPECTION HTTP 172")]
    assert '"project_not_found": 404' in body
    assert '"unauthenticated": 401' in body
    assert '"invalid_identity": 422' in body
    assert '"inspection_target_unavailable": 409' in body
    assert '"invalid_inspection_target": 502' in body
    assert "detail=exc.code" in body
    assert 'detail="inspection_unavailable"' in body
    assert "except HTTPException:" in body
    assert "traceback" not in body

from pyworkflow.viewer import ProtocolViewer


class DemoHttpViewer(ProtocolViewer):
    def _getVisualizeDict(self):
        return {"displayVolume": self._viewVolume}

    def _viewVolume(self):
        return self.protocol.outputData


def test_real_service_chain_authorizes_then_reads_one_exact_set_without_exposing_paths(monkeypatch):
    """Exercise 160/162/164/166/168/170 through HTTP without fake target-building."""
    from app.backend.api.services.protocol_viewer_inventory_service import _class_identity

    identity = _class_identity(DemoHttpViewer)
    static = {"id": "displayVolume", "fieldName": "displayVolume", "label": "Display volume",
              "control": "label", "kind": "visualize", "previewOnly": True,
              "requiresRuntimeEvaluation": True, "executionAllowed": False}
    web = {"id": "displayVolume", "fieldName": "displayVolume", "label": "Display volume",
           "control": "label", "intent": "visualize", "source": "static-ast",
           "adapter": {"id": "safe-volume", "kind": "volume", "effect": "read-only",
                       "surface": "react", "status": "declared-not-integrated"},
           "adapterStatus": "declared-not-integrated", "availability": "blocked",
           "blockers": ["action_adapter_not_integrated", "runtime_instance_not_verified",
                        "web_action_not_implemented"],
           "requiresRuntimeVerification": True, "renderable": False, "executionAllowed": False}
    found = {"projectId": 7, "protocolId": "142", "dataSource": "postgresql",
             "autoLaunchAllowed": False, "selectedViewerId": None,
             "instanceMaterialized": False, "instanceChecksApplied": False,
             "viewers": [{"id": identity,
                          "formSchema": {"status": "static-preview", "sections": [{"fields": [
                              {"name": "displayVolume", "label": "Display volume", "control": "label"}]}]},
                          "actionSchema": {"status": "static-preview", "source": "static-ast",
                                           "actions": [static], "renderable": False, "executionAllowed": False},
                          "webActionContracts": {"status": "advisory-only", "source": "static-ast",
                                                 "actions": [web], "actionCount": 1, "readyCount": 0,
                                                 "renderable": False, "executionAllowed": False},
                          "webReady": False, "webLaunchAllowed": False,
                          "renderable": False, "executionAllowed": False}]}
    calls = []

    class DbMapper:
        def getProjectProtocolByProtocolId(self, **kwargs):
            calls.append(("protocol", kwargs))
            return {"id": 812, "projectId": 7, "protocolId": "142", "params": {"secret": "NOT_FOR_UI"}}

    class SetMapper:
        def getStoredSet(self, **kwargs):
            calls.append(("set", kwargs))
            assert kwargs == {"projectId": 7, "protocolDbId": 812,
                              "outputName": "outputData", "limit": 0, "offset": 0}
            return {"id": 93, "projectId": 7, "protocolDbId": 812,
                    "outputName": "outputData", "setClassName": "SetOfVolumes",
                    "properties": {"runtimeReserved": False, "path": "/private/file.mrc"}}

        def listProjectSetOutputSummaryRows(self, **kwargs):
            pytest.fail("must not scan outputs")

        def getStoredSetItems(self, **kwargs):
            pytest.fail("must not load Set members")

    class Authorized:
        def getProjectDbRow(self, mapper, project_id, user):
            calls.append(("authorize", project_id, user["id"]))
            return {"id": project_id}

    def snapshot():
        calls.append(("snapshot",))
        return {"protocols": {}, "viewers": {"demo": DemoHttpViewer}}

    def discover(**kwargs):
        calls.append(("discovery", kwargs))
        return copy.deepcopy(found)

    binding = importlib.import_module("app.backend.api.services.protocol_viewer_action_binding_service")
    bridge = importlib.import_module("app.backend.api.services.protocol_viewer_action_resource_bridge_service")
    consistency = importlib.import_module("app.backend.api.services.protocol_viewer_action_source_consistency_service")
    monkeypatch.setattr(binding, "SERVER_DECLARED_ACTION_OUTPUT_BINDINGS", {
        identity: {"displayVolume": {"outputName": "outputData", "outputClassName": "SetOfVolumes",
                                     "adapterKind": "volume"}}})
    monkeypatch.setattr(bridge, "resolvePersistedProtocolViewerCandidates", discover)
    monkeypatch.setattr(consistency, "resolvePersistedProtocolViewerCandidates", discover)

    result = subject().requestProtocolViewerOutputInspectionHttp(
        mapper=DbMapper(), current_user={"id": 8, "role": "user"}, project_service=Authorized(),
        project_id=7, protocol_id=142, viewer_id=identity, action_id="displayVolume",
        snapshot_provider=snapshot, set_mapper_factory=lambda _: SetMapper())
    assert result["target"] == {"projectId": 7, "protocolId": "142", "outputName": "outputData",
                                "outputClassName": "SetOfVolumes", "webViewerKind": "volume",
                                "inspectionMode": "manual-persisted-output"}
    assert result["projectAccessVerified"] is True
    assert result["browserLaunchAllowed"] is False and result["actionExecutionAllowed"] is False
    assert [x[0] for x in calls] == ["authorize", "snapshot", "discovery", "discovery", "protocol", "set"]
    assert "/private/file.mrc" not in repr(result) and "NOT_FOR_UI" not in repr(result)
