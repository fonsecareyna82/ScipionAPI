"""RED 125: contract validation must never enable an AST-only viewer."""
from __future__ import annotations

from copy import deepcopy
import importlib

import pytest


def validator():
    return importlib.import_module(
        "app.backend.api.services.protocol_viewer_contract_service"
    )


def fixtures():
    from pyworkflow.protocol import Protocol
    from pyworkflow.viewer import Viewer, ProtocolViewer
    from app.backend.api.services.protocol_viewer_inventory_service import _class_identity

    class ProtExample(Protocol):
        pass

    class FormViewer(ProtocolViewer):
        _targets = [ProtExample]

        def __init__(self, *args, **kwargs):
            raise AssertionError("ProtocolViewer instantiated during validation")

        def _defineParams(self, form):
            form.addSection(label="Visualization")
            form.addParam("displayVol", params.EnumParam, choices=["slices", "surface"], label="Display volume")
            form.addParam("showFsc", params.LabelParam, label="Show FSC")
            form.addParam("threshold", params.FloatParam, label="Threshold")

        def _getVisualizeDict(self):
            raise AssertionError("Viewer action map was executed")
            return {"displayVol": self._showVolume, "showFsc": self._showFSC}

        def _showVolume(self, *args):
            raise AssertionError("Viewer handler executed")

        def _showFSC(self, *args):
            raise AssertionError("Viewer handler executed")

    class SimpleViewer(Viewer):
        _targets = [ProtExample]

        def __init__(self, *args, **kwargs):
            raise AssertionError("Simple viewer instantiated")

    ProtExample.__module__ = "contractfixture.protocols"
    FormViewer.__module__ = "contractfixture.viewers"
    SimpleViewer.__module__ = "contractfixture.viewers"
    return ProtExample, FormViewer, SimpleViewer, {
        "form": FormViewer, "plain": SimpleViewer,
    }, _class_identity


def form_preview():
    return {
        "status": "static-preview", "source": "static-ast",
        "sections": [{"label": "Visualization", "fields": [
            {"name": "displayVol", "label": "Display volume", "control": "select",
             "hasCondition": False, "choices": ["slices", "surface"], "default": 0},
            {"name": "showFsc", "label": "Show FSC", "control": "label", "hasCondition": False},
        ], "groups": [{"label": "Advanced", "fields": [
            {"name": "threshold", "label": "Threshold", "control": "number", "hasCondition": False},
        ]}]}],
        "fieldsDiscovered": 3, "hiddenFields": 1,
        "dynamicDefinitionsSkipped": 0,
        "requiresRuntimeEvaluation": True, "renderable": False,
        "actionExecutionAllowed": False,
    }


def action_preview():
    return {
        "status": "static-preview", "source": "static-ast",
        "actions": [
            {"id": "displayVol", "fieldName": "displayVol", "label": "Display volume",
             "control": "select", "kind": "visualize", "previewOnly": True,
             "requiresRuntimeEvaluation": True, "executionAllowed": False},
            {"id": "showFsc", "fieldName": "showFsc", "label": "Show FSC",
             "control": "label", "kind": "visualize", "previewOnly": True,
             "requiresRuntimeEvaluation": True, "executionAllowed": False},
        ], "actionsDiscovered": 2, "unmatchedActionsOmitted": 0,
        "dynamicEntriesSkipped": 0,
        "requiresRuntimeEvaluation": True, "executionAllowed": False,
        "renderable": False,
    }


def example(viewer_id, *, form=True, actions=True, adapter=False):
    return {
        "viewers": [{"id": viewer_id, "name": "FormViewer",
                     "formSchema": form_preview() if form else None,
                     "actionSchema": action_preview() if actions else None,
                     "webAdapter": ({"id": "test-adapter", "surface": "react",
                                     "status": "declared-not-integrated"} if adapter else None),
                     "eligibilityAssessment": {"webLaunchAllowed": False},
                     "runtimeEligibility": "unverified"}],
        "autoLaunchAllowed": False, "selectedViewerId": None,
    }


def prepared():
    _, form_cls, _, registry, identify = fixtures()
    return registry, example(identify(form_cls))


def assess(data, registry):
    return validator().validateProtocolViewerContracts(data, registry)


def first(result):
    return result["viewers"][0]["contractValidation"]


def test_consistent_static_preview_is_described_not_executable():
    registry, data = prepared()
    result = assess(data, registry)
    c = first(result)
    assert c["status"] == "described"
    assert c["staticConsistency"] == "advisory-consistent"
    assert c["issues"] == []
    assert c["publicFieldCount"] == 3 and c["previewActionCount"] == 2
    assert c["formComplete"] is False and c["actionsComplete"] is False
    assert c["webReady"] is False and c["executionAllowed"] is False
    assert result["contractValidationSummary"]["describedCount"] == 1


def test_simple_viewer_has_no_protocol_form_contract():
    _, _, plain_cls, registry, identify = fixtures()
    data = example(identify(plain_cls), form=False, actions=False)
    result = assess(data, registry)
    assert first(result)["status"] == "discovered"
    assert result["contractValidationSummary"]["protocolViewerCount"] == 0


def test_unavailable_form_and_action_stay_discovered():
    registry, data = prepared()
    data["viewers"][0]["formSchema"] = {"status": "unavailable"}
    data["viewers"][0]["actionSchema"] = {"status": "unavailable"}
    result = assess(data, registry)
    assert first(result)["status"] == "discovered"
    assert "form_schema_unavailable" in first(result)["issues"]
    assert "action_schema_unavailable" in first(result)["issues"]


def test_dynamic_form_definitions_are_reported_as_incomplete():
    registry, data = prepared()
    data["viewers"][0]["formSchema"]["dynamicDefinitionsSkipped"] = 2
    result = assess(data, registry)
    assert first(result)["status"] == "pending"
    assert "dynamic_form_definition" in first(result)["issues"]


def test_unresolved_form_conditions_are_not_auto_evaluated():
    registry, data = prepared()
    data["viewers"][0]["formSchema"]["sections"][0]["fields"][0]["hasCondition"] = True
    result = assess(data, registry)
    assert "unresolved_form_condition" in first(result)["issues"]
    assert first(result)["status"] == "pending"


def test_unresolved_defaults_require_runtime_evaluation():
    registry, data = prepared()
    data["viewers"][0]["formSchema"]["sections"][0]["fields"][1]["unresolvedDefault"] = True
    assert "unresolved_form_default" in first(assess(data, registry))["issues"]


def test_dynamic_and_unmatched_action_definitions_block_consistency():
    registry, data = prepared()
    data["viewers"][0]["actionSchema"]["dynamicEntriesSkipped"] = 3
    data["viewers"][0]["actionSchema"]["unmatchedActionsOmitted"] = 1
    result = assess(data, registry)
    assert first(result)["status"] == "pending"
    assert "dynamic_action_definition" in first(result)["issues"]
    assert "unmatched_action_omitted" in first(result)["issues"]


def test_duplicate_public_fields_and_actions_are_detected():
    registry, data = prepared()
    data["viewers"][0]["formSchema"]["sections"][0]["groups"][0]["fields"][0]["name"] = "showFsc"
    data["viewers"][0]["actionSchema"]["actions"][1]["id"] = "displayVol"
    data["viewers"][0]["actionSchema"]["actions"][1]["fieldName"] = "displayVol"
    result = assess(data, registry)
    assert "duplicate_form_field" in first(result)["issues"]
    assert "duplicate_action" in first(result)["issues"]


def test_unknown_action_field_is_rejected_by_contract():
    registry, data = prepared()
    data["viewers"][0]["actionSchema"]["actions"][0]["id"] = "nonExistent"
    data["viewers"][0]["actionSchema"]["actions"][0]["fieldName"] = "nonExistent"
    assert "unknown_action_field" in first(assess(data, registry))["issues"]


def test_action_field_mismatch_and_invalid_select_choices():
    registry, data = prepared()
    data["viewers"][0]["actionSchema"]["actions"][0]["control"] = "number"
    data["viewers"][0]["formSchema"]["sections"][0]["fields"][0]["choices"] = [object()]
    result = assess(data, registry)
    assert "action_field_mismatch" in first(result)["issues"]
    assert "invalid_form_field" in first(result)["issues"]


def test_forged_and_malformed_candidate_ids_fail_before_inspection():
    registry, data = prepared()
    data["viewers"][0]["id"] = "forged.plugin.OtherViewer"
    with pytest.raises(validator().ProtocolViewerContractError) as exc:
        assess(data, registry)
    assert exc.value.code == "unregistered_viewer"


def test_client_flags_and_declared_adapter_cannot_enable_launch():
    registry, data = prepared()
    data["viewers"][0]["webAdapter"] = {"id": "fake", "status": "ready"}
    data["viewers"][0]["webReady"] = True
    data["viewers"][0]["eligibilityAssessment"]["webLaunchAllowed"] = True
    data["viewers"][0]["actionSchema"]["executionAllowed"] = True
    data["viewers"][0]["actionSchema"]["actions"][0]["executionAllowed"] = True
    data["autoLaunchAllowed"] = True
    data["selectedViewerId"] = data["viewers"][0]["id"]
    result = assess(data, registry)
    item = result["viewers"][0]
    assert result["autoLaunchAllowed"] is False and result["selectedViewerId"] is None
    assert item["webReady"] is False
    assert item["webLaunchAllowed"] is False and item["renderable"] is False
    assert item["executionAllowed"] is False
    assert item["webAdapter"]["status"] == "declared-not-integrated"
    assert item["eligibilityAssessment"]["webLaunchAllowed"] is False
    assert item["actionSchema"]["executionAllowed"] is False
    assert all(action["executionAllowed"] is False for action in item["actionSchema"]["actions"])
    assert "unsafe_action_preview_flags" in first(result)["issues"]
    assert "web_adapter_not_integrated" in first(result)["blockers"]


def test_validate_does_not_mutate_candidates_or_execute_plugin_code():
    registry, data = prepared()
    before = deepcopy(data)
    result = assess(data, registry)
    assert data == before
    assert result != before
    assert result["contractValidationSummary"]["webReadyCount"] == 0


def test_postgresql_endpoint_integrates_contract_without_loading_runtime():
    from app.backend.api.services.protocol_viewer_persisted_resolution_service import (
        resolvePersistedProtocolViewerCandidates,
    )
    protocol_cls, form_cls, _, registry, _ = fixtures()
    class Mapper:
        def getProjectProtocolByProtocolId(self, *, projectId, protocolId):
            assert (projectId, protocolId) == (4, 27)
            return {"id": 504, "projectId": 4, "protocolId": "27",
                    "protocolClassName": "ProtExample", "status": "finished",
                    "params": {"privateToken": "NEVER_SEND_THIS"}}
        def getProjectProtocolByDbId(self, **kwargs):
            raise AssertionError("Wrong protocol ID namespace")
    result = resolvePersistedProtocolViewerCandidates(
        mapper=Mapper(), project_id=4, protocol_id=27,
        snapshot={"protocols": {"ProtExample": protocol_cls},
                  "viewers": registry, "preferredViewers": {}},
    )
    item = next(viewer for viewer in result["viewers"] if viewer["name"] == "FormViewer")
    assert "contractValidation" in item
    assert item["contractValidation"]["webReady"] is False
    assert result["contractValidationSummary"]["candidateCount"] == len(result["viewers"])
    assert result["autoLaunchAllowed"] is False
    assert "NEVER_SEND_THIS" not in str(result)
