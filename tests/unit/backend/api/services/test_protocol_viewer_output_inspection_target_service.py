"""RED 169: a constrained hand-off to the EXISTING output viewer, never a callback."""
from __future__ import annotations

import copy
import importlib

import pytest

SUBJECT = "app.backend.api.services.protocol_viewer_output_inspection_target_service"
BINDING = "app.backend.api.services.protocol_viewer_action_binding_service"
VIEWER = "xmipp3.viewers.DemonstrationViewer"
PROJECT = 7
PROTOCOL = 142
ACTION = "displayVolume"
DECLARATION = {"outputName": "outputData", "outputClassName": "SetOfVolumes", "adapterKind": "volume"}


def subject():
    return importlib.import_module(SUBJECT)


def report():
    return {
        "status": "advisory-only", "source": "server-declaration+registered-static-ast+postgresql",
        "projectId": PROJECT, "protocolId": str(PROTOCOL), "viewerId": VIEWER,
        "actionId": ACTION, "declaredOutputName": "outputData",
        "sourceCorrelation": "single-reference-matches-declaration", "persistedOutputConfirmed": True,
        "bindingVerified": False, "scientificSemanticsVerified": False,
        "instanceVerified": False, "availability": "blocked",
        "blockers": ["action_semantics_not_verified", "runtime_instance_not_verified",
                     "action_adapter_not_integrated", "web_action_not_implemented"],
        "renderable": False, "executionAllowed": False,
    }


@pytest.fixture
def ctx(monkeypatch):
    service = subject()
    evidence = report()
    declared = copy.deepcopy(DECLARATION)
    calls = []

    def check(**kwargs):
        calls.append(("check", kwargs))
        return evidence

    def get_declared(viewer_id, action_id):
        calls.append(("declaration", (viewer_id, action_id)))
        return declared

    monkeypatch.setattr(service, "inspectDeclaredProtocolViewerActionSourceConsistency", check)
    monkeypatch.setattr(service, "_validated_declaration", get_declared)
    return service, evidence, declared, calls


def run(ctx, **kwargs):
    params = {"mapper": object(), "set_mapper": object(), "snapshot": {},
              "viewer_registry": {}, "project_id": PROJECT, "protocol_id": PROTOCOL,
              "viewer_id": VIEWER, "action_id": ACTION}
    params.update(kwargs)
    return ctx[0].prepareProtocolViewerOutputInspectionTarget(**params)


def error(ctx, code, **kwargs):
    with pytest.raises(ctx[0].ProtocolViewerInspectionTargetError) as raised:
        run(ctx, **kwargs)
    assert raised.value.code == code


def test_safe_normalized_output_handoff_without_browser_launch(ctx):
    old_report = copy.deepcopy(ctx[1])
    old_decl = copy.deepcopy(ctx[2])
    result = run(ctx)
    assert result == {
        "status": "inspection-target-described",
        "source": "server-declaration+registered-static-ast+postgresql",
        "projectId": PROJECT, "protocolId": str(PROTOCOL), "viewerId": VIEWER,
        "actionId": ACTION, "sourceCorrelation": "single-reference-matches-declaration",
        "target": {"projectId": 7, "protocolId": "142", "outputName": "outputData",
                   "outputClassName": "SetOfVolumes", "webViewerKind": "volume",
                   "inspectionMode": "manual-persisted-output"},
        "bindingVerified": False, "scientificSemanticsVerified": False,
        "inspectionAuthorized": False, "actionExecutionAllowed": False,
        "requiresCallerAuthorization": True,
    }
    assert ctx[1] == old_report and ctx[2] == old_decl
    assert [x[0] for x in ctx[3]] == ["check", "declaration"]
    assert "callback" not in str(result).lower()


@pytest.mark.parametrize("correlation", [
    "indeterminate", "no-direct-reference", "ambiguous-references", "declared-output-not-referenced",
])
def test_unconfirmed_source_only_yields_no_inspection_target(ctx, correlation):
    ctx[1]["sourceCorrelation"] = correlation
    ctx[1]["persistedOutputConfirmed"] = False
    value = run(ctx)
    assert value["status"] == "inspection-target-pending" and value["target"] is None
    assert value["inspectionAuthorized"] is False and value["actionExecutionAllowed"] is False
    assert [x[0] for x in ctx[3]] == ["check"]


@pytest.mark.parametrize("params", [
    {"project_id": 0}, {"project_id": False}, {"project_id": "7"},
    {"project_id": -7}, {"protocol_id": 0}, {"protocol_id": True},
    {"protocol_id": "142"}, {"viewer_id": "DemoViewer"},
    {"viewer_id": "../../secret"}, {"viewer_id": "a.B;__import__('os')"},
    {"viewer_id": None}, {"action_id": "_private"},
    {"action_id": "../../private"}, {"action_id": None},
    {"action_id": False}, {"action_id": "a" * 129},
])
def test_invalid_identity_fails_before_any_reads(ctx, params):
    error(ctx, "invalid_identity", **params)
    assert ctx[3] == []


@pytest.mark.parametrize("params", [
    {"mapper": None}, {"set_mapper": None}, {"snapshot": []},
    {"snapshot": "untrusted"}, {"viewer_registry": None},
    {"viewer_registry": []}, {"source_loader": "eval()"},
])
def test_bad_context_fails_before_any_reads(ctx, params):
    error(ctx, "invalid_context", **params)
    assert ctx[3] == []


def test_cannot_accept_browser_output_name_or_manually_override_declarations(ctx):
    for added in ("output_name", "file_path", "callback", "allow_execution", "declarations", "action_target"):
        with pytest.raises(TypeError):
            run(ctx, **{added: "/tmp/private.mrc"})
    assert ctx[3] == []


@pytest.mark.parametrize("field,bad", [
    ("status", "verified"), ("source", "client"),
    ("projectId", 8), ("projectId", True), ("protocolId", "143"),
    ("viewerId", "some.Other"), ("actionId", "other"),
    ("declaredOutputName", "../secret"),
    ("bindingVerified", True), ("scientificSemanticsVerified", True),
    ("instanceVerified", True), ("availability", "available"),
    ("renderable", True), ("executionAllowed", True),
    ("persistedOutputConfirmed", False), ("blockers", []),
    ("blockers", ["action_semantics_not_verified"]),
    ("sourceCorrelation", "verified"),
])
def test_forged_correlation_report_rejected(ctx, field, bad):
    ctx[1][field] = bad
    error(ctx, "invalid_consistency_evidence")
    assert [x[0] for x in ctx[3]] == ["check"]


def test_rejects_extra_sensitive_fields_in_consistency_report(ctx):
    ctx[1]["filePath"] = "/home/private/secret.mrc"
    error(ctx, "invalid_consistency_evidence")


@pytest.mark.parametrize("field,bad", [
    ("outputName", "outputElse"), ("outputName", "/tmp/private"),
    ("outputClassName", "CustomClass"), ("outputClassName", "Volume"),
    ("outputClassName", "SetOfParticles"),
    ("adapterKind", "external-command"), ("adapterKind", "metadata-table"),
])
def test_incompatible_or_forged_server_declaration_rejected(ctx, field, bad):
    ctx[2][field] = bad
    error(ctx, "incompatible_inspection_viewer" if field in ("outputClassName", "adapterKind") and bad in ("CustomClass", "Volume", "SetOfParticles", "metadata-table") else "invalid_server_declaration")


def test_extra_declaration_keys_cannot_leak_callback_paths(ctx):
    ctx[2]["url"] = "https://evil.example/download"
    error(ctx, "invalid_server_declaration")


def test_metadata_set_can_be_handed_to_existing_metadata_viewer(ctx):
    ctx[2].update({"outputClassName": "SetOfParticles", "adapterKind": "metadata-table"})
    value = run(ctx)
    assert value["target"]["webViewerKind"] == "metadata"
    assert value["target"]["outputClassName"] == "SetOfParticles"
    assert value["actionExecutionAllowed"] is False


@pytest.mark.parametrize("klass", ["SetOfParticles", "SetOfMicrographs", "SetOfClasses2D", "SetOfClasses3D"])
def test_existing_metadata_kinds_are_generic_not_xmipp_specific(ctx, klass):
    ctx[2].update({"outputClassName": klass, "adapterKind": "metadata-table"})
    value = run(ctx)
    assert value["target"]["webViewerKind"] == "metadata"


def test_no_target_carries_paths_pointer_handles_or_plugin_parameters(ctx):
    text = repr(run(ctx))
    for forbidden in ("/private/", "_getVisualizeDict", "_viewVolume", "getObjId", "fileName", "outputRaw"):
        assert forbidden not in text


def test_propagates_declared_binding_failure_without_scanning_outputs(ctx, monkeypatch):
    def absent(*args, **kwargs):
        raise ValueError("binding_not_declared")
    monkeypatch.setattr(ctx[0], "_validated_declaration", absent)
    with pytest.raises(ValueError, match="binding_not_declared"):
        run(ctx)
    assert [x[0] for x in ctx[3]] == ["check"]


def test_propagates_scientific_source_failure_without_fabricating_target(ctx, monkeypatch):
    def fail(**kwargs):
        raise ValueError("invalid_source_evidence")
    monkeypatch.setattr(ctx[0], "inspectDeclaredProtocolViewerActionSourceConsistency", fail)
    with pytest.raises(ValueError, match="invalid_source_evidence"):
        run(ctx)
    assert ctx[3] == []


def test_uses_checked_identity_once_in_source_consistency(ctx):
    result = run(ctx, source_loader=lambda _fn: "source")
    assert result["target"]["outputName"] == "outputData"
    params = ctx[3][0][1]
    assert params["project_id"] == 7 and params["protocol_id"] == 142
    assert params["viewer_id"] == VIEWER and params["action_id"] == ACTION
    assert callable(params["source_loader"])


from pyworkflow.viewer import ProtocolViewer


class DemoViewer(ProtocolViewer):
    def _getVisualizeDict(self):
        return {"displayVolume": self._viewVolume}

    def _viewVolume(self):
        return self.protocol.outputData


def test_real_previous_services_resolve_exact_postgresql_output_once(monkeypatch):
    """Exercise real GREEN 160/162/164/166/168 with no Set item enumeration."""
    from app.backend.api.services.protocol_viewer_inventory_service import _class_identity

    identity = _class_identity(DemoViewer)
    assert "<locals>" not in identity
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

    def discover(**kwargs):
        calls.append(("discovery", kwargs))
        return copy.deepcopy(found)

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
            raise AssertionError("must not scan outputs")

        def getStoredSetItems(self, **kwargs):
            raise AssertionError("must not load Set members")

    binding = importlib.import_module(BINDING)
    bridge = importlib.import_module("app.backend.api.services.protocol_viewer_action_resource_bridge_service")
    consistency = importlib.import_module("app.backend.api.services.protocol_viewer_action_source_consistency_service")
    monkeypatch.setattr(binding, "SERVER_DECLARED_ACTION_OUTPUT_BINDINGS", {
        identity: {"displayVolume": copy.deepcopy(DECLARATION)}})
    monkeypatch.setattr(bridge, "resolvePersistedProtocolViewerCandidates", discover)
    monkeypatch.setattr(consistency, "resolvePersistedProtocolViewerCandidates", discover)
    value = subject().prepareProtocolViewerOutputInspectionTarget(
        mapper=DbMapper(), set_mapper=SetMapper(), snapshot={"protocols": {}, "viewers": {}},
        viewer_registry={"test": DemoViewer}, project_id=7, protocol_id=142,
        viewer_id=identity, action_id="displayVolume")
    assert value["status"] == "inspection-target-described"
    assert value["target"]["outputName"] == "outputData"
    assert value["target"]["webViewerKind"] == "volume"
    assert value["actionExecutionAllowed"] is False
    assert value["inspectionAuthorized"] is False
    assert [entry[0] for entry in calls] == ["discovery", "discovery", "protocol", "set"]
    assert "/private/file.mrc" not in repr(value)
    assert "NOT_FOR_UI" not in repr(value)
