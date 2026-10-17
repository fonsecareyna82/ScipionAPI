"""RED 167: a direct source reference can corroborate, NEVER authorize, a reviewed binding."""
from __future__ import annotations

import copy
import importlib
import inspect

import pytest
from pyworkflow.viewer import ProtocolViewer
from app.backend.api.services.protocol_viewer_inventory_service import _class_identity

MODULE = "app.backend.api.services.protocol_viewer_action_source_consistency_service"
BINDING = "app.backend.api.services.protocol_viewer_action_binding_service"


def subject():
    return importlib.import_module(MODULE)


class DemoViewer(ProtocolViewer):
    def _getVisualizeDict(self):
        return {"displayVolume": self._viewVolume, "showPlot": self._viewPlot}

    def _viewVolume(self):
        return self.protocol.outputData

    def _viewPlot(self):
        return self.protocol._getExtraPath("secret.svg")


VIEWER = _class_identity(DemoViewer)
DECL = {"outputName": "outputData", "outputClassName": "SetOfVolumes", "adapterKind": "volume"}


def _candidate():
    actions = [
        {"id": ident, "fieldName": ident, "label": label, "control": "label", "kind": "visualize",
         "previewOnly": True, "requiresRuntimeEvaluation": True, "executionAllowed": False}
        for ident, label in (("displayVolume", "Display volume"), ("showPlot", "Show plot"))
    ]
    web = [
        {"id": x["id"], "fieldName": x["id"], "label": x["label"], "control": x["control"],
         "intent": "visualize", "source": "static-ast", "adapter": {"id": "safe-viewer", "kind": "volume",
         "effect": "read-only", "surface": "react", "status": "declared-not-integrated"},
         "adapterStatus": "declared-not-integrated", "availability": "blocked",
         "blockers": ["action_adapter_not_integrated", "runtime_instance_not_verified", "web_action_not_implemented"],
         "requiresRuntimeVerification": True, "renderable": False, "executionAllowed": False}
        for x in actions
    ]
    return {"projectId": 7, "protocolId": "142", "dataSource": "postgresql", "autoLaunchAllowed": False,
            "selectedViewerId": None, "instanceMaterialized": False, "instanceChecksApplied": False,
            "viewers": [{"id": VIEWER, "formSchema": {"status": "static-preview", "sections": [{"fields": [
                {"name": x["id"], "label": x["label"], "control": "label"} for x in actions]}]},
                "actionSchema": {"status": "static-preview", "source": "static-ast", "actions": actions,
                                 "renderable": False, "executionAllowed": False},
                "webActionContracts": {"status": "advisory-only", "source": "static-ast", "actions": web,
                                       "actionCount": 2, "readyCount": 0, "renderable": False,
                                       "executionAllowed": False},
                "webReady": False, "webLaunchAllowed": False, "renderable": False,
                "executionAllowed": False}]}


def _binding_result():
    return {"status": "declaration-and-persistence-checked", "source": "server-declaration+postgresql-static-ast",
            "projectId": 7, "protocolId": "142", "viewerId": VIEWER, "actionId": "displayVolume",
            "outputName": "outputData", "outputClassName": "SetOfVolumes", "webViewerKind": "volume",
            "adapterKind": "volume", "bindingStatus": "declared-output-confirmed",
            "scientificSemanticsVerified": False, "instanceVerified": False,
            "availability": "blocked", "blockers": ["action_adapter_not_integrated", "action_semantics_not_verified",
                                               "runtime_instance_not_verified", "web_action_not_implemented"],
            "renderable": False, "executionAllowed": False}


@pytest.fixture
def context(monkeypatch):
    service = subject()
    binding = importlib.import_module(BINDING)
    source = _candidate()
    expected = _binding_result()
    calls = []
    monkeypatch.setattr(binding, "SERVER_DECLARED_ACTION_OUTPUT_BINDINGS", {VIEWER: {"displayVolume": copy.deepcopy(DECL)}})

    def discovery(**kwargs):
        calls.append(("discovery", kwargs))
        return source

    def verify(**kwargs):
        calls.append(("persistence", kwargs))
        return expected

    monkeypatch.setattr(service, "resolvePersistedProtocolViewerCandidates", discovery)
    monkeypatch.setattr(service, "inspectDeclaredProtocolViewerActionBinding", verify)
    return service, source, expected, calls, object(), object()


def run(context, **changes):
    s, _, _, _, mapper, set_mapper = context
    args = {"mapper": mapper, "set_mapper": set_mapper, "snapshot": {"protocols": {}, "viewers": {}},
            "viewer_registry": {"test": DemoViewer}, "project_id": 7, "protocol_id": 142,
            "viewer_id": VIEWER, "action_id": "displayVolume"}
    args.update(changes)
    return s.inspectDeclaredProtocolViewerActionSourceConsistency(**args)


def err(context, code, **changes):
    with pytest.raises(context[0].ProtocolViewerActionSourceConsistencyError) as exc:
        run(context, **changes)
    assert exc.value.code == code


def test_correlates_exact_declaration_source_and_persistence_but_never_verifies_semantics(context):
    before = copy.deepcopy(context[1])
    result = run(context)
    assert context[1] == before
    assert result == {"status": "advisory-only", "source": "server-declaration+registered-static-ast+postgresql",
                      "projectId": 7, "protocolId": "142", "viewerId": VIEWER, "actionId": "displayVolume",
                      "declaredOutputName": "outputData", "sourceCorrelation": "single-reference-matches-declaration",
                      "persistedOutputConfirmed": True, "bindingVerified": False,
                      "scientificSemanticsVerified": False, "instanceVerified": False,
                      "availability": "blocked", "blockers": ["action_semantics_not_verified",
                         "runtime_instance_not_verified", "action_adapter_not_integrated", "web_action_not_implemented"],
                      "renderable": False, "executionAllowed": False}
    assert [kind for kind, _ in context[3]] == ["discovery", "persistence"]
    assert context[3][1][1]["action_id"] == "displayVolume"
    assert context[3][1][1]["viewer_id"] == VIEWER
    assert context[3][1][1]["project_id"] == 7
    assert context[3][1][1]["protocol_id"] == 142
    assert "secret.svg" not in repr(result)


def test_default_server_registry_is_empty_and_does_not_scan_db(context, monkeypatch):
    binding = importlib.import_module(BINDING)
    monkeypatch.setattr(binding, "SERVER_DECLARED_ACTION_OUTPUT_BINDINGS", {})
    err(context, "binding_not_declared")
    assert context[3] == []


@pytest.mark.parametrize("patch", [
    {"project_id": 0}, {"project_id": False}, {"project_id": "7"}, {"project_id": -1},
    {"protocol_id": True}, {"protocol_id": 0}, {"protocol_id": "142"},
    {"viewer_id": "bad"}, {"viewer_id": "../../foo"}, {"viewer_id": "other.Viewer;run"},
    {"viewer_id": None}, {"action_id": "../../secret"}, {"action_id": ""},
    {"action_id": False}, {"action_id": "_private"}, {"action_id": "a" * 129},
])
def test_invalid_identity_before_any_inspection(context, patch):
    err(context, "invalid_identity", **patch)
    assert context[3] == []


@pytest.mark.parametrize("patch", [
    {"mapper": None}, {"set_mapper": None}, {"snapshot": None},
    {"snapshot": "forged"}, {"snapshot": []}, {"viewer_registry": None},
    {"viewer_registry": "bad"}, {"source_loader": "call __import__('os')"},
])
def test_invalid_context_before_any_inspection(context, patch):
    err(context, "invalid_context", **patch)
    assert context[3] == []


def test_output_path_cannot_be_supplied_as_client_argument(context):
    with pytest.raises(TypeError):
        run(context, output_name="/secret/volume.mrc")
    assert context[3] == []


def test_registry_cannot_be_overridden_by_caller(context):
    with pytest.raises(TypeError):
        run(context, bindings={VIEWER: {"displayVolume": DECL}})
    assert context[3] == []


@pytest.mark.parametrize("key,value", [
    ("projectId", 8), ("projectId", True), ("protocolId", "143"),
    ("dataSource", "sqlite"), ("autoLaunchAllowed", True), ("autoLaunchAllowed", 0),
    ("selectedViewerId", VIEWER), ("instanceMaterialized", True),
    ("instanceChecksApplied", True), ("viewers", []),
])
def test_discovery_identity_and_executable_flags_fail_closed(context, key, value):
    context[1][key] = value
    err(context, "viewer_not_found" if key == "viewers" else "invalid_discovery")
    assert not any(x[0] == "persistence" for x in context[3])


@pytest.mark.parametrize("key,value", [
    ("webReady", True), ("webLaunchAllowed", True), ("renderable", True),
    ("executionAllowed", True), ("executionAllowed", 0),
])
def test_forged_viewer_permissions_fail_closed(context, key, value):
    context[1]["viewers"][0][key] = value
    err(context, "invalid_discovery")
    assert not any(x[0] == "persistence" for x in context[3])


def test_duplicate_discovered_viewer_fails_closed(context):
    context[1]["viewers"].append(copy.deepcopy(context[1]["viewers"][0]))
    err(context, "duplicate_viewer")
    assert not any(x[0] == "persistence" for x in context[3])


def test_discovery_of_unregistered_class_rejected_by_ast(context):
    err(context, "static_analysis_unavailable", viewer_registry={})
    assert not any(x[0] == "persistence" for x in context[3])


def _loader_replacing(body):
    def loader(function):
        if function.__name__ == "_viewVolume":
            return "def _viewVolume(self):\n    " + body.replace("\n", "\n    ") + "\n"
        return inspect.getsource(function)
    return loader


@pytest.mark.parametrize("body,expected", [
    ("return self.protocol.outputOther", "declared-output-not-referenced"),
    ("return self.protocol.outputOther, self.protocol.outputData", "ambiguous-references"),
    ("return None", "no-direct-reference"),
    ("return self.protocol._getExtraPath('volume.mrc')", "no-direct-reference"),
    ("return getattr(self.protocol, 'outputData')", "indeterminate"),
    ("return self.protocol.outputData; exec('1')", "indeterminate"),
    ("return self.protocol.outputData; __import__('os')", "indeterminate"),
    ("return self.protocol.outputData, self.protocol.outputData", "single-reference-matches-declaration"),
])
def test_reference_correlation_never_infers_an_output_or_executes(context, body, expected):
    result = run(context, source_loader=_loader_replacing(body))
    assert result["sourceCorrelation"] == expected
    assert result["persistedOutputConfirmed"] == (expected == "single-reference-matches-declaration")
    assert [x[0] for x in context[3]].count("persistence") == (1 if expected == "single-reference-matches-declaration" else 0)
    assert result["bindingVerified"] is False and result["executionAllowed"] is False
    assert "outputOther" not in repr(result)
    assert "volume.mrc" not in repr(result)


def test_unavailable_source_never_reads_set(context):
    def not_found(_fn):
        raise OSError("missing source")
    result = run(context, source_loader=not_found)
    assert result["sourceCorrelation"] == "indeterminate"
    assert result["persistedOutputConfirmed"] is False
    assert [x[0] for x in context[3]] == ["discovery"]


def test_failed_source_contract_cannot_be_used_as_trusted_ast(context):
    context[1]["viewers"][0]["webActionContracts"]["actions"][0]["availability"] = "available"
    err(context, "action_not_found")
    assert [x[0] for x in context[3]] == ["discovery"]


@pytest.mark.parametrize("key,value", [
    ("status", "verified"), ("source", "plugin"), ("projectId", 9),
    ("protocolId", "other"), ("viewerId", "forged.viewers.V"), ("actionId", "other"),
    ("outputName", "outputOther"), ("outputClassName", "SetOfParticles"),
    ("adapterKind", "image"), ("webViewerKind", "other"),
    ("bindingStatus", "verified"), ("scientificSemanticsVerified", True),
    ("instanceVerified", True), ("availability", "available"),
    ("renderable", True), ("executionAllowed", True),
    ("blockers", []),
])
def test_forged_backend_binding_evidence_rejected(context, key, value):
    context[2][key] = value
    err(context, "invalid_binding_evidence")
    assert [x[0] for x in context[3]] == ["discovery", "persistence"]


def test_malicious_extra_binding_fields_never_exposed(context):
    context[2]["callback"] = "evil.os.system"
    err(context, "invalid_binding_evidence")


def test_refusal_when_binding_service_cannot_confirm_output(context, monkeypatch):
    def fail(**kwargs):
        raise ValueError("persisted output missing")
    monkeypatch.setattr(context[0], "inspectDeclaredProtocolViewerActionBinding", fail)
    with pytest.raises(ValueError, match="persisted output missing"):
        run(context)
    assert [x[0] for x in context[3]] == ["discovery"]


def test_do_not_execute_plugin_or_read_files_during_static_correlation(context, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("plugin must not run")
    monkeypatch.setattr(DemoViewer, "_viewVolume", forbidden)
    monkeypatch.setattr(DemoViewer, "_viewPlot", forbidden)
    # With dynamic replacement source cannot be inspected: indeterminate is safe.
    result = run(context)
    assert result["persistedOutputConfirmed"] is False
    assert result["executionAllowed"] is False
    assert [x[0] for x in context[3]] == ["discovery"]


def test_real_160_162_164_166_chain_uses_only_scoped_zero_item_postgresql_read(context, monkeypatch):
    """Exercise the real independently tested services, not a synthetic binding result."""
    binding = importlib.import_module(BINDING)
    bridge = importlib.import_module("app.backend.api.services.protocol_viewer_action_resource_bridge_service")
    calls = context[3]

    class Mapper:
        def getProjectProtocolByProtocolId(self, **kwargs):
            calls.append(("protocol", kwargs))
            return {"id": 812, "projectId": 7, "protocolId": "142", "params": {"secret": "NO_LEAK"}}

        def getProjectProtocolByDbId(self, **kwargs):
            raise AssertionError("No fallback lookup")

    class Sets:
        def getStoredSet(self, **kwargs):
            calls.append(("set", kwargs))
            assert kwargs == {"projectId": 7, "protocolDbId": 812, "outputName": "outputData",
                              "limit": 0, "offset": 0}
            return {"id": 93, "projectId": 7, "protocolDbId": 812,
                    "outputName": "outputData", "setClassName": "SetOfVolumes",
                    "properties": {"runtimeReserved": False, "path": "/private/secret.mrc"}}

        def listProjectSetOutputSummaryRows(self, *args, **kwargs):
            raise AssertionError("Never enumerate project outputs")

    def discovery(**kwargs):
        calls.append(("discovery", kwargs))
        return context[1]

    monkeypatch.setattr(bridge, "resolvePersistedProtocolViewerCandidates", discovery)
    monkeypatch.setattr(context[0], "inspectDeclaredProtocolViewerActionBinding",
                        binding.inspectDeclaredProtocolViewerActionBinding)
    result = run(context, mapper=Mapper(), set_mapper=Sets())
    assert result["sourceCorrelation"] == "single-reference-matches-declaration"
    assert result["persistedOutputConfirmed"] is True
    assert result["bindingVerified"] is False and result["executionAllowed"] is False
    assert [kind for kind, _ in calls] == ["discovery", "discovery", "protocol", "set"]
    assert "/private/secret.mrc" not in repr(result)
    assert "NO_LEAK" not in repr(result)
