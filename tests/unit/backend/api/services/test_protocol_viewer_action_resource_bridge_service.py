"""RED 161: PostgreSQL resource evidence cannot authorize a ProtocolViewer action."""
from __future__ import annotations

import copy
import importlib

import pytest

MODULE = "app.backend.api.services.protocol_viewer_action_resource_bridge_service"
VIEWER = "example.viewers.DemoViewer"


def subject():
    return importlib.import_module(MODULE)


class ProtocolMapper:
    def __init__(self):
        self.row = {"id": 812, "projectId": 7, "protocolId": "142", "protocolClassName": "DemoProtocol", "params": {"secret": "DO_NOT_EXPOSE"}}
        self.calls = []

    def getProjectProtocolByProtocolId(self, *, projectId, protocolId):
        self.calls.append((projectId, protocolId))
        return self.row

    def getProjectProtocolByDbId(self, **kwargs):
        raise AssertionError("DB-ID fallback is not permitted")


class SetMapper:
    def __init__(self):
        self.stored = {"id": 56, "projectId": 7, "protocolDbId": 812, "outputName": "outputData", "setClassName": "SetOfVolumes", "properties": {"runtimeReserved": False, "path": "/secret/file.mrc"}, "items": [{"secret": "SECRET_ITEMS"}], "columns": [{"secret": "SECRET_COLUMNS"}]}
        self.calls = []

    def getStoredSet(self, **kwargs):
        self.calls.append(kwargs)
        return self.stored

    def listProjectSetOutputSummaryRows(self, *args, **kwargs):
        raise AssertionError("A project-wide output scan is not allowed")


def action(action_id="displayVolume", adapter_kind="volume", declared=True):
    return {
        "id": action_id, "fieldName": action_id, "label": "View results", "control": "select",
        "intent": "visualize", "source": "static-ast",
        "adapter": ({"id": "view-volume", "kind": adapter_kind, "effect": "read-only", "surface": "react", "status": "declared-not-integrated"} if declared else None),
        "adapterStatus": "declared-not-integrated" if declared else "missing",
        "availability": "blocked", "blockers": (["action_adapter_not_integrated"] if declared else ["action_adapter_missing"]) + ["runtime_instance_not_verified", "web_action_not_implemented"],
        "requiresRuntimeVerification": True, "renderable": False, "executionAllowed": False,
    }


def discovery():
    a = action()
    return {
        "projectId": 7, "protocolId": "142", "dataSource": "postgresql",
        "autoLaunchAllowed": False, "selectedViewerId": None,
        "instanceMaterialized": False, "instanceChecksApplied": False,
        "viewers": [{
            "id": VIEWER, "webReady": False, "webLaunchAllowed": False,
            "renderable": False, "executionAllowed": False,
            "actionSchema": {"status": "static-preview", "source": "static-ast", "renderable": False, "executionAllowed": False,
                             "actions": [{"id": "displayVolume", "fieldName": "displayVolume", "label": "View results", "control": "select", "kind": "visualize", "previewOnly": True, "executionAllowed": False, "requiresRuntimeEvaluation": True}]},
            "webActionContracts": {"status": "advisory-only", "source": "static-ast", "actions": [a], "actionCount": 1,
                                   "declaredAdapterCount": 1, "readyCount": 0, "renderable": False, "executionAllowed": False},
        }],
    }


@pytest.fixture
def context(monkeypatch):
    mapper, sets, descriptor = ProtocolMapper(), SetMapper(), discovery()
    calls = []

    def discover(*, mapper, project_id, protocol_id, snapshot):
        calls.append((mapper, project_id, protocol_id, snapshot))
        return descriptor

    monkeypatch.setattr(subject(), "resolvePersistedProtocolViewerCandidates", discover)
    return mapper, sets, descriptor, calls


def inspect(context, **overrides):
    mapper, sets, _, _ = context
    values = {"mapper": mapper, "set_mapper": sets, "snapshot": {"protocols": {}, "viewers": {}},
              "project_id": 7, "protocol_id": 142, "viewer_id": VIEWER,
              "action_id": "displayVolume", "output_name": "outputData"}
    values.update(overrides)
    return subject().inspectPersistedProtocolViewerActionResource(**values)


def code(context, **overrides):
    with pytest.raises(subject().ProtocolViewerActionResourceBridgeError) as exc:
        inspect(context, **overrides)
    return exc.value.code


def test_verified_scoped_resource_matches_declared_capability_but_cannot_launch(context):
    result = inspect(context)
    mapper, sets, _, discovery_calls = context
    assert discovery_calls == [(mapper, 7, 142, {"protocols": {}, "viewers": {}})]
    assert mapper.calls == [(7, 142)]
    assert sets.calls == [{"projectId": 7, "protocolDbId": 812, "outputName": "outputData", "limit": 0, "offset": 0}]
    assert result["projectId"] == 7 and result["protocolId"] == "142"
    assert (result["viewerId"], result["actionId"], result["outputName"]) == (VIEWER, "displayVolume", "outputData")
    assert result["webViewerKind"] == "volume" and result["resourceCompatibility"] == "kind-match"
    assert result["bindingStatus"] == "unverified"
    assert result["availability"] == "blocked" and result["executionAllowed"] is False and result["renderable"] is False
    assert result["instanceVerified"] is False
    assert "action_binding_not_verified" in result["blockers"]
    assert "action_adapter_not_integrated" in result["blockers"]


def test_missing_adapter_stays_blocked_even_with_compatible_output(context):
    a = context[2]["viewers"][0]["webActionContracts"]
    a["actions"] = [action(declared=False)]
    a["declaredAdapterCount"] = 0
    result = inspect(context)
    assert result["adapterStatus"] == "missing" and result["adapterKind"] is None
    assert result["resourceCompatibility"] == "not-assessed"
    assert result["blockers"][0] == "action_adapter_missing"
    assert result["executionAllowed"] is False


@pytest.mark.parametrize("kind,output_class,expected", [
    ("volume", "SetOfVolumes", "kind-match"), ("volume", "SetOfParticles", "kind-mismatch"),
    ("metadata-table", "SetOfParticles", "kind-match"), ("metadata-table", "SetOfMicrographs", "kind-match"),
    ("metadata-table", "SetOfFSCs", "kind-mismatch"),
    ("plot", "SetOfFSCs", "not-assessed"), ("plot", "SetOfVolumes", "not-assessed"),
    ("image", "SetOfVolumes", "not-assessed"), ("classes", "SetOfParticles", "not-assessed"),
    ("particles", "SetOfParticles", "not-assessed"),
    ("protocol-action", "SetOfVolumes", "not-assessed"),
])
def test_compatibility_is_not_an_action_output_binding(context, kind, output_class, expected):
    context[2]["viewers"][0]["webActionContracts"]["actions"][0]["adapter"]["kind"] = kind
    context[1].stored["setClassName"] = output_class
    result = inspect(context)
    assert result["resourceCompatibility"] == expected
    assert result["bindingStatus"] == "unverified"
    assert result["executionAllowed"] is False
    assert ("resource_kind_incompatible" in result["blockers"]) == (expected == "kind-mismatch")


@pytest.mark.parametrize("patch", [
    {"project_id": 0}, {"project_id": True}, {"protocol_id": "142"}, {"protocol_id": False},
    {"viewer_id": "../DemoViewer"}, {"viewer_id": "x"}, {"viewer_id": "evil.viewer;run"},
    {"viewer_id": 4}, {"action_id": "show/plot"}, {"action_id": ""}, {"action_id": True},
    {"output_name": "../outputData"}, {"output_name": "outputData/file.mrc"},
    {"output_name": "_private"}, {"output_name": ""}, {"output_name": None},
    {"output_name": "a" * 129}, {"snapshot": None}, {"mapper": None}, {"set_mapper": None},
])
def test_invalid_context_does_not_call_discovery_or_database(context, patch):
    assert code(context, **patch) in {"invalid_identity", "invalid_context"}
    assert context[1].calls == [] and context[3] == [] and context[0].calls == []


def test_unregistered_viewer_never_reads_set(context):
    assert code(context, viewer_id="evil.viewers.OtherViewer") == "viewer_not_found"
    assert context[1].calls == []


def test_similar_label_never_binds_a_different_action(context):
    assert code(context, action_id="showPlot") == "action_not_found"
    assert context[1].calls == []


def test_duplicate_viewer_identity_fails_closed(context):
    context[2]["viewers"].append(copy.deepcopy(context[2]["viewers"][0]))
    assert code(context) == "duplicate_viewer"
    assert context[1].calls == []


def test_duplicate_action_identity_fails_closed(context):
    c = context[2]["viewers"][0]["webActionContracts"]
    c["actions"].append(copy.deepcopy(c["actions"][0]))
    c["actionCount"] = 2
    assert code(context) == "invalid_action_contract"
    assert context[1].calls == []


def test_old_contract_absent_fails_closed_without_set_scan(context):
    context[2]["viewers"][0]["webActionContracts"] = None
    assert code(context) == "action_contract_unavailable"
    assert context[1].calls == []


@pytest.mark.parametrize("key,value", [
    ("autoLaunchAllowed", True), ("selectedViewerId", VIEWER),
    ("instanceMaterialized", True), ("instanceChecksApplied", True),
    ("projectId", 8), ("protocolId", "143"), ("dataSource", "sqlite"),
])
def test_forged_discovery_flags_are_not_promoted(context, key, value):
    context[2][key] = value
    assert code(context) == "invalid_discovery"
    assert context[1].calls == []


@pytest.mark.parametrize("key", ["webReady", "webLaunchAllowed", "renderable", "executionAllowed"])
def test_forged_viewer_flags_are_not_promoted(context, key):
    context[2]["viewers"][0][key] = True
    assert code(context) == "invalid_discovery"
    assert context[1].calls == []


@pytest.mark.parametrize("key,value", [
    ("status", "ready"), ("source", "worker"), ("renderable", True),
    ("executionAllowed", True), ("readyCount", 1), ("actionCount", 100),
])
def test_forged_contract_summary_is_rejected(context, key, value):
    context[2]["viewers"][0]["webActionContracts"][key] = value
    assert code(context) in {"invalid_action_contract", "action_contract_unavailable"}
    assert context[1].calls == []


@pytest.mark.parametrize("key,value", [
    ("id", "otherAction"), ("fieldName", "different"), ("intent", "execute"),
    ("source", "plugin-runtime"), ("availability", "available"),
    ("requiresRuntimeVerification", False), ("renderable", True),
    ("executionAllowed", True), ("blockers", []), ("adapterStatus", "ready"),
])
def test_forged_action_claims_rejected_before_output_read(context, key, value):
    context[2]["viewers"][0]["webActionContracts"]["actions"][0][key] = value
    assert code(context) in {"action_not_found", "invalid_action_contract"}
    assert context[1].calls == []


@pytest.mark.parametrize("key,value", [
    ("label", "Forged"), ("control", "text"), ("previewOnly", False),
    ("executionAllowed", True), ("requiresRuntimeEvaluation", False),
])
def test_static_action_schema_mismatch_is_rejected(context, key, value):
    context[2]["viewers"][0]["actionSchema"]["actions"][0][key] = value
    assert code(context) == "action_schema_mismatch"
    assert context[1].calls == []


@pytest.mark.parametrize("patch", [
    {"kind": "python-callback"}, {"effect": "mutating"}, {"surface": "shell"},
    {"id": "http://attacker"}, {"url": "https://evil.example/secret"},
    {"status": "ready"}, {"kind": None},
])
def test_adapter_metadata_cannot_inject_callback_or_execution(context, patch):
    context[2]["viewers"][0]["webActionContracts"]["actions"][0]["adapter"].update(patch)
    assert code(context) == "invalid_action_contract"
    assert context[1].calls == []


def test_unrecognized_action_fields_are_rejected(context):
    context[2]["viewers"][0]["webActionContracts"]["actions"][0]["callback"] = "private.run"
    assert code(context) == "invalid_action_contract"
    assert context[1].calls == []


@pytest.mark.parametrize("key,value", [
    ("projectId", 8), ("protocolDbId", 142), ("outputName", "otherOutput"),
    ("setClassName", "PluginUnknown"), ("properties", {"runtimeReserved": True}),
])
def test_real_persistence_resolver_blocks_foreign_or_unsupported_set(context, key, value):
    context[1].stored[key] = value
    with pytest.raises(Exception) as exc:
        inspect(context)
    assert isinstance(exc.value, subject().ProtocolViewerActionResourceBridgeError) is False
    assert len(context[1].calls) == 1


def test_response_whitelist_does_not_leak_paths_protocol_params_or_callback(context):
    source = copy.deepcopy(context[2]); protocol = copy.deepcopy(context[0].row)
    stored = copy.deepcopy(context[1].stored)
    result = inspect(context)
    assert context[2] == source and context[0].row == protocol and context[1].stored == stored
    assert set(result) == {"status", "source", "projectId", "protocolId", "viewerId", "actionId", "outputName", "resourceKind", "outputClassName", "webViewerKind", "adapterStatus", "adapterKind", "resourceCompatibility", "bindingStatus", "availability", "blockers", "instanceVerified", "renderable", "executionAllowed"}
    assert result["source"] == "postgresql-static-ast"
    assert result["status"] == "advisory-only"
    assert result["resourceKind"] == "persisted-set"
    assert not any(s in repr(result) for s in ("DO_NOT_EXPOSE", "SECRET_ITEMS", "SECRET_COLUMNS", "/secret/file.mrc", "callback", "https://"))
    assert "protocolDbId" not in result and "setId" not in result


def test_no_untrusted_extra_flags_become_permission(context):
    context[1].stored.update({"renderable": True, "executionAllowed": True, "launch": "/bin/sh"})
    result = inspect(context)
    assert result["executionAllowed"] is False and result["availability"] == "blocked"
    assert "launch" not in repr(result)
