"""RED 163: only explicit server declarations may identify an action's output.

A declared output's PostgreSQL existence verifies identity, not scientific
meaning or permission to execute or render a plugin action.
"""
from __future__ import annotations

import copy
import importlib
from types import MappingProxyType

import pytest

MODULE = "app.backend.api.services.protocol_viewer_action_binding_service"
VIEWER = "example.viewers.DemoViewer"
ACTION = "displayVolume"
DECLARATION = {"outputName": "outputData", "outputClassName": "SetOfVolumes", "adapterKind": "volume"}


def subject():
    return importlib.import_module(MODULE)


def evidence():
    return {
        "status": "advisory-only", "source": "postgresql-static-ast",
        "projectId": 7, "protocolId": "142", "viewerId": VIEWER, "actionId": ACTION,
        "outputName": "outputData", "resourceKind": "persisted-set",
        "outputClassName": "SetOfVolumes", "webViewerKind": "volume",
        "adapterStatus": "declared-not-integrated", "adapterKind": "volume",
        "resourceCompatibility": "kind-match", "bindingStatus": "unverified",
        "availability": "blocked", "blockers": [
            "action_adapter_not_integrated", "action_binding_not_verified",
            "runtime_instance_not_verified", "web_action_not_implemented",
        ], "instanceVerified": False, "renderable": False, "executionAllowed": False,
    }


@pytest.fixture
def ctx(monkeypatch):
    service = subject()
    bridge_data = evidence()
    calls = []
    mapper, set_mapper = object(), object()
    snapshot = {"protocols": {}, "viewers": {}, "secret": "DO_NOT_EXPOSE"}
    # Only the SERVER registry is modified in tests; the production registry is empty.
    monkeypatch.setattr(service, "SERVER_DECLARED_ACTION_OUTPUT_BINDINGS", {
        VIEWER: {ACTION: copy.deepcopy(DECLARATION)}
    })

    def bridge(**kwargs):
        calls.append(kwargs)
        return bridge_data

    monkeypatch.setattr(service, "inspectPersistedProtocolViewerActionResource", bridge)
    return service, mapper, set_mapper, snapshot, bridge_data, calls


def run(ctx, **overrides):
    service, mapper, set_mapper, snapshot, _, _ = ctx
    args = {"mapper": mapper, "set_mapper": set_mapper, "snapshot": snapshot,
            "project_id": 7, "protocol_id": 142, "viewer_id": VIEWER, "action_id": ACTION}
    args.update(overrides)
    return service.inspectDeclaredProtocolViewerActionBinding(**args)


def fails(ctx, expected, **kwargs):
    with pytest.raises(ctx[0].ProtocolViewerActionBindingError) as exc:
        run(ctx, **kwargs)
    assert exc.value.code == expected


def test_production_registry_is_empty():
    assert dict(subject().SERVER_DECLARED_ACTION_OUTPUT_BINDINGS) == {}


def test_known_server_declaration_uses_only_exact_persisted_output(ctx):
    result = run(ctx)
    assert len(ctx[5]) == 1
    assert ctx[5][0] == {
        "mapper": ctx[1], "set_mapper": ctx[2], "snapshot": ctx[3],
        "project_id": 7, "protocol_id": 142, "viewer_id": VIEWER,
        "action_id": ACTION, "output_name": "outputData",
    }
    assert result["status"] == "declaration-and-persistence-checked"
    assert result["bindingStatus"] == "declared-output-confirmed"
    assert result["scientificSemanticsVerified"] is False
    assert result["instanceVerified"] is False
    assert result["availability"] == "blocked"
    assert result["renderable"] is False and result["executionAllowed"] is False
    assert "action_semantics_not_verified" in result["blockers"]


def test_exact_output_name_is_not_a_client_argument(ctx):
    with pytest.raises(TypeError):
        run(ctx, output_name="otherOutput")
    assert ctx[5] == []


def test_cannot_supply_client_registry(ctx):
    with pytest.raises(TypeError):
        run(ctx, bindings={VIEWER: {ACTION: DECLARATION}})
    assert ctx[5] == []


def test_undeclared_viewer_cannot_read_a_resource(ctx):
    fails(ctx, "binding_not_declared", viewer_id="fake.viewers.FakeViewer")
    assert ctx[5] == []


def test_undeclared_action_cannot_read_a_resource(ctx):
    fails(ctx, "binding_not_declared", action_id="otherAction")
    assert ctx[5] == []


def test_empty_registry_cannot_scan_outputs(ctx, monkeypatch):
    monkeypatch.setattr(ctx[0], "SERVER_DECLARED_ACTION_OUTPUT_BINDINGS", MappingProxyType({}))
    fails(ctx, "binding_not_declared")
    assert ctx[5] == []


@pytest.mark.parametrize("identity", [
    {"project_id": 0}, {"project_id": -1}, {"project_id": True}, {"project_id": "7"},
    {"protocol_id": 0}, {"protocol_id": -1}, {"protocol_id": False}, {"protocol_id": "142"},
    {"viewer_id": "bad"}, {"viewer_id": "../../x"}, {"viewer_id": "a.b;system"},
    {"viewer_id": 20}, {"action_id": "../../x"}, {"action_id": ""},
    {"action_id": False}, {"action_id": "a" * 129},
])
def test_bad_identity_rejected_before_io(ctx, identity):
    fails(ctx, "invalid_identity", **identity)
    assert ctx[5] == []


@pytest.mark.parametrize("invalid", [
    {"mapper": None}, {"set_mapper": None}, {"snapshot": None},
    {"snapshot": "opaque"}, {"snapshot": []},
])
def test_missing_context_rejected_before_io(ctx, invalid):
    fails(ctx, "invalid_context", **invalid)
    assert ctx[5] == []


@pytest.mark.parametrize("malformed", [
    {"outputName": "../outputData", "outputClassName": "SetOfVolumes", "adapterKind": "volume"},
    {"outputName": "/home/user/secret", "outputClassName": "SetOfVolumes", "adapterKind": "volume"},
    {"outputName": "outputData/sqlite", "outputClassName": "SetOfVolumes", "adapterKind": "volume"},
    {"outputName": "https://evil", "outputClassName": "SetOfVolumes", "adapterKind": "volume"},
    {"outputName": "_internal", "outputClassName": "SetOfVolumes", "adapterKind": "volume"},
    {"outputName": "a" * 129, "outputClassName": "SetOfVolumes", "adapterKind": "volume"},
    {"outputName": 9, "outputClassName": "SetOfVolumes", "adapterKind": "volume"},
    {"outputName": "outputData", "outputClassName": "bad.mod.Class", "adapterKind": "volume"},
    {"outputName": "outputData", "outputClassName": "SetOfVolumes", "adapterKind": "plot"},
    {"outputName": "outputData", "outputClassName": "SetOfVolumes", "adapterKind": "python-callback"},
    {"outputName": "outputData", "outputClassName": "SetOfVolumes", "adapterKind": True},
    {"outputName": "outputData", "outputClassName": "SetOfVolumes", "adapterKind": "volume", "url": "https://evil"},
    {"outputName": "outputData", "outputClassName": "SetOfVolumes", "adapterKind": "volume", "callback": "exec"},
    {"outputName": "outputData", "outputClassName": "SetOfVolumes"},
    {"outputName": "outputData", "outputClassName": "SetOfVolumes", "adapterKind": "volume", "execute": True},
    ["outputData", "SetOfVolumes", "volume"],
])
def test_malformed_server_declaration_rejected_before_io(ctx, monkeypatch, malformed):
    monkeypatch.setattr(ctx[0], "SERVER_DECLARED_ACTION_OUTPUT_BINDINGS", {VIEWER: {ACTION: malformed}})
    fails(ctx, "invalid_binding_declaration")
    assert ctx[5] == []


@pytest.mark.parametrize("registry", [
    [], "unsafe", {"not_a_viewer": {ACTION: DECLARATION}},
    {VIEWER: []}, {VIEWER: {"../otherAction": DECLARATION}},
    {"x.y": {} , VIEWER: {ACTION: DECLARATION}, "wrong": {}},
    {VIEWER: {str(True): DECLARATION, ACTION: DECLARATION, "../bad": DECLARATION}},
])
def test_invalid_server_registry_rejected_before_io(ctx, monkeypatch, registry):
    monkeypatch.setattr(ctx[0], "SERVER_DECLARED_ACTION_OUTPUT_BINDINGS", registry)
    fails(ctx, "invalid_server_registry")
    assert ctx[5] == []


def test_mapping_proxies_are_supported_for_trusted_server_declarations(ctx, monkeypatch):
    reg = MappingProxyType({VIEWER: MappingProxyType({ACTION: MappingProxyType(DECLARATION)})})
    monkeypatch.setattr(ctx[0], "SERVER_DECLARED_ACTION_OUTPUT_BINDINGS", reg)
    assert run(ctx)["bindingStatus"] == "declared-output-confirmed"


@pytest.mark.parametrize("field,value,error", [
    ("status", "ready", "invalid_bridge_evidence"),
    ("source", "plugin-runtime", "invalid_bridge_evidence"),
    ("projectId", 8, "invalid_bridge_evidence"),
    ("protocolId", "143", "invalid_bridge_evidence"),
    ("viewerId", "other.viewers.Viewer", "invalid_bridge_evidence"),
    ("actionId", "otherAction", "invalid_bridge_evidence"),
    ("outputName", "otherOutput", "invalid_bridge_evidence"),
    ("resourceKind", "untrusted-file", "invalid_bridge_evidence"),
    ("bindingStatus", "verified", "invalid_bridge_evidence"),
    ("resourceCompatibility", "kind-mismatch", "invalid_bridge_evidence"),
    ("adapterStatus", "missing", "invalid_bridge_evidence"),
    ("availability", "available", "invalid_bridge_evidence"),
    ("instanceVerified", True, "invalid_bridge_evidence"),
    ("renderable", True, "invalid_bridge_evidence"),
    ("executionAllowed", True, "invalid_bridge_evidence"),
    ("adapterKind", "metadata-table", "binding_type_mismatch"),
    ("webViewerKind", "metadata", "binding_type_mismatch"),
    ("outputClassName", "SetOfParticles", "binding_type_mismatch"),
    ("blockers", [], "invalid_bridge_evidence"),
])
def test_upstream_evidence_must_reconfirm_identity_and_inert_status(ctx, field, value, error):
    ctx[4][field] = value
    fails(ctx, error)


@pytest.mark.parametrize("value", [
    None, [], "verified", {"status": "advisory-only"},
])
def test_incomplete_bridge_evidence_is_rejected(ctx, value):
    ctx[4].clear()
    if isinstance(value, dict):
        ctx[4].update(value)
    else:
        ctx[5].clear()
        # Replace the mocked bridge's return value without altering production.
        from unittest.mock import Mock
        ctx[0].inspectPersistedProtocolViewerActionResource = Mock(return_value=value)
    fails(ctx, "invalid_bridge_evidence")


def test_upstream_cannot_add_opaque_callbacks_or_paths(ctx):
    ctx[4]["launchCommand"] = "python -c 'malicious'"
    fails(ctx, "invalid_bridge_evidence")


def test_missing_expected_blocker_fails_closed(ctx):
    ctx[4]["blockers"].remove("runtime_instance_not_verified")
    fails(ctx, "invalid_bridge_evidence")


def test_declaration_class_must_match_even_if_web_kind_matches(ctx, monkeypatch):
    monkeypatch.setattr(ctx[0], "SERVER_DECLARED_ACTION_OUTPUT_BINDINGS", {
        VIEWER: {ACTION: {"outputName": "outputData", "outputClassName": "Volume", "adapterKind": "volume"}}
    })
    fails(ctx, "binding_type_mismatch")


def test_metadata_table_requires_persisted_metadata_output(ctx, monkeypatch):
    ctx[4]["adapterKind"] = "metadata-table"
    ctx[4]["webViewerKind"] = "metadata"
    ctx[4]["outputClassName"] = "SetOfParticles"
    monkeypatch.setattr(ctx[0], "SERVER_DECLARED_ACTION_OUTPUT_BINDINGS", {
        VIEWER: {ACTION: {"outputName": "outputData", "outputClassName": "SetOfParticles", "adapterKind": "metadata-table"}}
    })
    result = run(ctx)
    assert result["webViewerKind"] == "metadata"
    assert result["executionAllowed"] is False


def test_response_cannot_leak_registry_secrets_paths_or_input_metadata(ctx):
    original_evidence = copy.deepcopy(ctx[4]); original_snapshot = copy.deepcopy(ctx[3])
    result = run(ctx)
    assert ctx[4] == original_evidence and ctx[3] == original_snapshot
    assert set(result) == {
        "status", "source", "projectId", "protocolId", "viewerId", "actionId",
        "outputName", "outputClassName", "webViewerKind", "adapterKind",
        "bindingStatus", "scientificSemanticsVerified", "instanceVerified",
        "availability", "blockers", "renderable", "executionAllowed",
    }
    assert "DO_NOT_EXPOSE" not in repr(result)
    assert "callback" not in repr(result) and "protocolDbId" not in result
    assert "http" not in repr(result) and "setId" not in result


def test_upstream_errors_are_not_replaced_with_success(ctx):
    from app.backend.api.services.protocol_viewer_action_resource_bridge_service import ProtocolViewerActionResourceBridgeError
    def failed(**kwargs):
        raise ProtocolViewerActionResourceBridgeError("viewer_not_found")
    ctx[0].inspectPersistedProtocolViewerActionResource = failed
    with pytest.raises(ProtocolViewerActionResourceBridgeError):
        run(ctx)


def test_no_implicit_scientific_binding_even_after_persisted_confirmation(ctx):
    result = run(ctx)
    assert result["bindingStatus"] != "scientifically-verified"
    assert result["scientificSemanticsVerified"] is False
    assert result["renderable"] is False and result["executionAllowed"] is False
    assert "web_action_not_implemented" in result["blockers"]


def test_end_to_end_existing_bridge_checks_exact_postgresql_output(ctx, monkeypatch):
    # Integration with GREEN 162 and GREEN 160, not just a mocked bridge.
    bridge = importlib.import_module("app.backend.api.services.protocol_viewer_action_resource_bridge_service")
    monkeypatch.setattr(ctx[0], "inspectPersistedProtocolViewerActionResource", bridge.inspectPersistedProtocolViewerActionResource)

    class Mapper:
        def __init__(self): self.calls = []
        def getProjectProtocolByProtocolId(self, *, projectId, protocolId):
            self.calls.append((projectId, protocolId))
            return {"id": 812, "projectId": 7, "protocolId": "142"}

    class Sets:
        def __init__(self): self.calls = []
        def getStoredSet(self, **kwargs):
            self.calls.append(kwargs)
            return {"id": 56, "projectId": 7, "protocolDbId": 812, "outputName": "outputData", "setClassName": "SetOfVolumes", "properties": {"runtimeReserved": False}, "items": []}

    def registered(**kwargs):
        return {
            "projectId": 7, "protocolId": "142", "dataSource": "postgresql",
            "autoLaunchAllowed": False, "selectedViewerId": None,
            "instanceMaterialized": False, "instanceChecksApplied": False,
            "viewers": [{
                "id": VIEWER, "webReady": False, "webLaunchAllowed": False,
                "renderable": False, "executionAllowed": False,
                "actionSchema": {"status": "static-preview", "source": "static-ast", "renderable": False, "executionAllowed": False,
                                 "actions": [{"id": ACTION, "fieldName": ACTION, "label": "View results", "control": "select",
                                              "kind": "visualize", "previewOnly": True, "executionAllowed": False, "requiresRuntimeEvaluation": True}]},
                "webActionContracts": {"status": "advisory-only", "source": "static-ast", "actionCount": 1,
                                       "readyCount": 0, "renderable": False, "executionAllowed": False,
                                       "actions": [{"id": ACTION, "fieldName": ACTION, "label": "View results", "control": "select",
                                                    "intent": "visualize", "source": "static-ast",
                                                    "adapter": {"id": "view-volume", "kind": "volume", "effect": "read-only", "surface": "react", "status": "declared-not-integrated"},
                                                    "adapterStatus": "declared-not-integrated", "availability": "blocked",
                                                    "blockers": ["action_adapter_not_integrated", "runtime_instance_not_verified", "web_action_not_implemented"],
                                                    "requiresRuntimeVerification": True, "renderable": False, "executionAllowed": False}]},
            }],
        }

    monkeypatch.setattr(bridge, "resolvePersistedProtocolViewerCandidates", registered)
    mapper, sets = Mapper(), Sets()
    result = run(ctx, mapper=mapper, set_mapper=sets)
    assert result["bindingStatus"] == "declared-output-confirmed"
    assert mapper.calls == [(7, 142)]
    assert sets.calls == [{"projectId": 7, "protocolDbId": 812, "outputName": "outputData", "limit": 0, "offset": 0}]
    assert result["executionAllowed"] is False
