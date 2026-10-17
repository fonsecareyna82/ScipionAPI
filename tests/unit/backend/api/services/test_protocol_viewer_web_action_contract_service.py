"""RED 155: static viewer action metadata never authorizes plugin execution."""
from __future__ import annotations

import copy
import importlib

import pytest


def subject():
    return importlib.import_module(
        "app.backend.api.services.protocol_viewer_web_action_contract_service"
    )


def fixture_data():
    from pyworkflow.protocol import Protocol
    from pyworkflow.viewer import ProtocolViewer, Viewer
    from app.backend.api.services.protocol_viewer_inventory_service import _class_identity

    class DemoProtocol(Protocol):
        pass

    class DemoViewer(ProtocolViewer):
        _targets = [DemoProtocol]
        def __init__(self, *args, **kwargs):
            raise AssertionError("Plugin viewer must not be instantiated")
        def _getVisualizeDict(self):
            raise AssertionError("Visualize map must not execute")
        def _show(self):
            raise AssertionError("Plugin callback must not execute")

    class PlainViewer(Viewer):
        _targets = [DemoProtocol]
        def __init__(self, *args, **kwargs):
            raise AssertionError("Plain viewer must not be instantiated")

    DemoProtocol.__module__ = "fixture.actions.protocols"
    DemoViewer.__module__ = "fixture.actions.viewers"
    PlainViewer.__module__ = "fixture.actions.viewers"
    viewer_id = _class_identity(DemoViewer)
    plain_id = _class_identity(PlainViewer)
    def field(name, control="label", label=None):
        return {"name": name, "label": label or name, "control": control,
                "hasCondition": False}
    def action(name, control="label", label=None):
        return {"id": name, "fieldName": name, "label": label or name,
                "control": control, "kind": "visualize",
                "previewOnly": True, "requiresRuntimeEvaluation": True,
                "executionAllowed": False}
    item = {
        "id": viewer_id, "name": "DemoViewer", "webReady": False,
        "formSchema": {"status": "static-preview", "source": "static-ast",
                       "sections": [{"label": "Visualization", "fields": [
                           field("showPlot"), field("displayVolume", "select")], "groups": []}]},
        "actionSchema": {"status": "static-preview", "source": "static-ast",
                         "actions": [action("showPlot"), action("displayVolume", "select")],
                         "executionAllowed": False, "renderable": False},
        "contractValidation": {"status": "described", "executionAllowed": False},
    }
    return {"viewers": [item], "autoLaunchAllowed": False}, {
        "v": DemoViewer, "other_alias": DemoViewer, "plain": PlainViewer,
    }, viewer_id, plain_id


def adapter(kind="plot", **changes):
    value = {"id": "view-plot", "kind": kind, "effect": "read-only", "surface": "react"}
    value.update(changes)
    return value


def describe(data=None, registry=None, adapters=None):
    if data is None and registry is None:
        data, registry, _, _ = fixture_data()
    return subject().describeProtocolViewerWebActionContracts(data, registry, adapters)


def test_default_registry_is_empty_and_actions_are_blocked():
    assert subject().REGISTERED_PROTOCOL_VIEWER_ACTION_ADAPTERS == {}
    result = describe()
    preview = result["viewers"][0]["webActionContracts"]
    assert preview["status"] == "advisory-only" and preview["actionCount"] == 2
    assert preview["declaredAdapterCount"] == preview["readyCount"] == 0
    assert preview["executionAllowed"] is False and preview["renderable"] is False
    assert all(a["availability"] == "blocked" and a["adapter"] is None for a in preview["actions"])
    assert all(a["blockers"][0] == "action_adapter_missing" for a in preview["actions"])
    assert result["webActionContractSummary"]["readyActionCount"] == 0


def test_declared_exact_adapter_is_advisory_only():
    data, registry, viewer_id, _ = fixture_data()
    result = describe(data, registry, {viewer_id: {"showPlot": adapter()}})
    actions = result["viewers"][0]["webActionContracts"]["actions"]
    assert actions[0]["adapterStatus"] == "declared-not-integrated"
    assert actions[0]["adapter"] == {**adapter(), "status": "declared-not-integrated"}
    assert "action_adapter_not_integrated" in actions[0]["blockers"]
    assert actions[0]["executionAllowed"] is False
    assert actions[1]["adapterStatus"] == "missing"
    assert result["webActionContractSummary"]["declaredAdapterCount"] == 1
    assert result["webActionContractSummary"]["readyActionCount"] == 0


def test_distinct_actions_can_reference_different_safe_adapters():
    data, registry, ident, _ = fixture_data()
    bindings = {ident: {"showPlot": adapter(), "displayVolume": adapter("volume", id="view-volume", effect="derived-read")}}
    actions = describe(data, registry, bindings)["viewers"][0]["webActionContracts"]["actions"]
    assert [x["adapter"]["kind"] for x in actions] == ["plot", "volume"]
    assert [x["availability"] for x in actions] == ["blocked", "blocked"]


def test_unknown_installed_viewer_declarations_are_ignored():
    data, registry, _, _ = fixture_data()
    result = describe(data, registry, {"stale.plugin.Ghost": {"showPlot": adapter()}})
    assert result["webActionContractSummary"]["declaredAdapterCount"] == 0


def test_unknown_action_declarations_are_not_advertised():
    data, registry, ident, _ = fixture_data()
    result = describe(data, registry, {ident: {"privateAction": adapter()}})
    assert "privateAction" not in str(result)
    assert result["webActionContractSummary"]["declaredAdapterCount"] == 0


def test_plain_viewer_cannot_inherit_protocol_viewer_actions():
    data, registry, _, plain_id = fixture_data()
    clone = copy.deepcopy(data["viewers"][0]); clone["id"] = plain_id
    data["viewers"].append(clone)
    result = describe(data, registry)
    assert result["viewers"][1]["webActionContracts"] is None
    assert result["webActionContractSummary"]["describedActionCount"] == 2


def test_missing_action_schema_has_empty_safe_contract():
    data, registry, _, _ = fixture_data()
    data["viewers"][0]["actionSchema"] = {"status": "unavailable"}
    result = describe(data, registry)
    assert result["viewers"][0]["webActionContracts"]["actions"] == []


def test_hidden_or_non_public_actions_never_appear():
    data, registry, _, _ = fixture_data()
    data["viewers"][0]["formSchema"]["sections"][0]["fields"].pop()
    result = describe(data, registry)
    assert [a["id"] for a in result["viewers"][0]["webActionContracts"]["actions"]] == ["showPlot"]
    assert "displayVolume" in str(data)  # source input remains unchanged


def test_duplicate_action_is_not_published_twice():
    data, registry, _, _ = fixture_data()
    data["viewers"][0]["actionSchema"]["actions"].append(
        copy.deepcopy(data["viewers"][0]["actionSchema"]["actions"][0]))
    result = describe(data, registry)
    assert result["viewers"][0]["webActionContracts"]["actionCount"] == 2


def test_mismatched_action_label_or_control_is_rejected():
    data, registry, _, _ = fixture_data()
    data["viewers"][0]["actionSchema"]["actions"][0]["label"] = "Forged"
    data["viewers"][0]["actionSchema"]["actions"][1]["control"] = "text"
    result = describe(data, registry)
    assert result["viewers"][0]["webActionContracts"]["actions"] == []


def test_unsafe_preview_flags_cannot_publish_action():
    data, registry, _, _ = fixture_data()
    data["viewers"][0]["actionSchema"]["actions"][0]["executionAllowed"] = True
    result = describe(data, registry)
    assert [a["id"] for a in result["viewers"][0]["webActionContracts"]["actions"]] == ["displayVolume"]
    assert all(x["executionAllowed"] is False for x in result["viewers"][0]["actionSchema"]["actions"])


def test_unknown_fields_or_callback_metadata_are_never_copied():
    data, registry, _, _ = fixture_data()
    data["viewers"][0]["actionSchema"]["actions"][0]["handler"] = "_privateMethod"
    data["viewers"][0]["actionSchema"]["actions"][0]["secretPath"] = "/tmp/secret_file"
    result = describe(data, registry)
    descriptor = result["viewers"][0]["webActionContracts"]
    assert "secretPath" not in str(descriptor)
    assert "_privateMethod" not in str(descriptor)


def test_input_is_unchanged_and_aliases_do_not_duplicate():
    data, registry, _, _ = fixture_data()
    prior = copy.deepcopy(data)
    result = describe(data, registry)
    assert data == prior and result != prior
    assert result["webActionContractSummary"]["candidateCount"] == 1


def test_spoofed_launch_flags_are_reset():
    data, registry, _, _ = fixture_data()
    data["autoLaunchAllowed"] = True; data["selectedViewerId"] = "spoof"
    data["viewers"][0]["webReady"] = True
    data["viewers"][0]["executionAllowed"] = True
    result = describe(data, registry)
    assert result["autoLaunchAllowed"] is False and result["selectedViewerId"] is None
    assert result["viewers"][0]["webReady"] is False
    assert result["viewers"][0]["executionAllowed"] is False


def test_registered_classes_never_instantiated_or_invoked():
    # Both mock constructors and the callback raise. This test passes only if
    # inspection never constructs a plugin class or calls _getVisualizeDict.
    result = describe()
    assert result["webActionContractSummary"]["describedActionCount"] == 2


def test_unregistered_candidate_rejected_before_inspection():
    data, registry, _, _ = fixture_data()
    data["viewers"][0]["id"] = "fake.package.Inject"
    with pytest.raises(subject().ProtocolViewerWebActionContractError) as exc:
        describe(data, registry)
    assert exc.value.code == "unregistered_viewer"


@pytest.mark.parametrize("broken", [None, [], {"viewer": []}, {"viewer": {"showPlot": adapter()}}])
def test_malformed_registry_or_unknown_candidate_fail_closed(broken):
    data, registry, _, _ = fixture_data()
    if broken is None:
        registry = None
    elif isinstance(broken, list):
        data = broken
    else:
        data["viewers"] = ["not-a-descriptor"]
    with pytest.raises(subject().ProtocolViewerWebActionContractError):
        describe(data, registry)


@pytest.mark.parametrize("patch", [
    {"effect": "mutating"}, {"effect": "external-process"},
    {"effect": ["read-only"]}, {"surface": "python"},
    {"surface": ["react"]}, {"kind": "unknown_kind"},
    {"id": "https://evil.invalid/run"}, {"handler": "somePlugin.execute"},
    {"effect": True},
])
def test_unsafe_adapter_metadata_rejected(patch):
    data, registry, ident, _ = fixture_data()
    metadata = adapter(**patch)
    with pytest.raises(subject().ProtocolViewerWebActionContractError):
        describe(data, registry, {ident: {"showPlot": metadata}})


def test_integration_with_persisted_postgresql_resolution(monkeypatch):
    """Discovery should include a blocked action contract, no row parameters."""
    from pyworkflow.protocol import Protocol
    from pyworkflow.viewer import ProtocolViewer
    from app.backend.api.services.protocol_viewer_persisted_resolution_service import (
        resolvePersistedProtocolViewerCandidates,
    )
    class Proto(Protocol):
        pass
    class ProtoViewer(ProtocolViewer):
        _targets = [Proto]
        def __init__(self, *a, **kw):
            raise AssertionError("No viewer construction")
        def _defineParams(self, form):
            from pyworkflow.protocol import params
            form.addSection(label="Visualization")
            form.addParam("showPlot", params.LabelParam, label="Show plot")
        def _getVisualizeDict(self):
            return {"showPlot": self._showPlot}
        def _showPlot(self):
            raise AssertionError("No plugin callback")
    class Mapper:
        def getProjectProtocolByProtocolId(self, *, projectId, protocolId):
            assert (projectId, protocolId) == (9, 21)
            return {"id": 123, "projectId": 9, "protocolId": "21",
                    "protocolClassName": "Proto", "status": "finished",
                    "params": {"secret": "NEVER_PUBLISH_123"}}
        def getProjectProtocolByDbId(self, **kwargs):
            raise AssertionError("Never lookup by DB ID")
    response = resolvePersistedProtocolViewerCandidates(
        mapper=Mapper(), project_id=9, protocol_id=21,
        snapshot={"protocols": {"Proto": Proto}, "viewers": {"proto": ProtoViewer},
                  "preferredViewers": {}},
    )
    viewer = response["viewers"][0]
    assert viewer["webActionContracts"]["readyCount"] == 0
    assert viewer["webActionContracts"]["executionAllowed"] is False
    assert response["webActionContractSummary"]["readyActionCount"] == 0
    assert "NEVER_PUBLISH_123" not in str(response)
