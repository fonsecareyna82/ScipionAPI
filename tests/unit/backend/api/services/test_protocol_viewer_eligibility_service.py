"""RED 117: classify viewer instance hooks without running plugin code."""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


def eligibility_module():
    return importlib.import_module(
        "app.backend.api.services.protocol_viewer_eligibility_service"
    )


def fixture():
    from pyworkflow.protocol import Protocol
    from pyworkflow.viewer import ProtocolViewer, Viewer

    class Prot(Protocol):
        pass

    class OrdinaryViewer(Viewer):
        _targets = [Prot]
        _environments = ["tkinter", "django"]
        def __init__(self, *args, **kwargs):
            raise AssertionError("Never instantiate viewers during eligibility inspection")
        def _visualize(self, *args, **kwargs):
            raise AssertionError("Never visualize")

    class InstanceRestricted(Viewer):
        _targets = [Prot]
        _environments = ["tkinter"]
        @classmethod
        def can_handle_this_instance(cls, instance):
            raise AssertionError("Never call plugin instance predicates")

    class ClassRestricted(Viewer):
        _targets = [Prot]
        _environments = ["tkinter"]
        @classmethod
        def can_handle_this(cls, classes, instance=None):
            raise AssertionError("Never call plugin matching predicates")

    class DescendantRestricted(InstanceRestricted):
        pass

    class FormViewer(ProtocolViewer):
        _targets = [Prot]
        _environments = ["tkinter"]
        def __init__(self, *args, **kwargs):
            raise AssertionError("Never construct protocol viewers")
        def _defineParams(self, form):
            raise AssertionError("Never generate forms during discovery")

    for cls in (OrdinaryViewer, InstanceRestricted, ClassRestricted,
                DescendantRestricted, FormViewer):
        cls.__module__ = "fake_plugin.viewers"
    Prot.__module__ = "fake_plugin.protocols"
    registry = {cls.__name__: cls for cls in (
        OrdinaryViewer, InstanceRestricted, ClassRestricted,
        DescendantRestricted, FormViewer
    )}
    return Prot, registry


def candidate_resolution(registry=None):
    from app.backend.api.services.protocol_viewer_resolution_service import (
        resolveProtocolViewerCandidates,
    )
    prot, default_registry = fixture()
    registered = registry if registry is not None else default_registry
    return resolveProtocolViewerCandidates(
        {"Prot": prot}, registered, "Prot"
    ), registered


def assessed():
    candidates, registry = candidate_resolution()
    return eligibility_module().assessProtocolViewerEligibility(
        candidates, registry
    )


def by_name(result, name):
    return next(item for item in result["viewers"] if item["name"] == name)


def test_default_hooks_are_identified_statically_without_claiming_instance_approval():
    result = assessed()
    item = by_name(result, "OrdinaryViewer")
    assessment = item["eligibilityAssessment"]
    assert assessment["hookPolicy"] == "default-hooks"
    assert assessment["customClassHook"] is False
    assert assessment["customInstanceHook"] is False
    assert assessment["requiresControlledRuntimeEvaluation"] is False
    assert assessment["instanceVerified"] is False
    assert item["runtimeEligibility"] == "unverified"
    assert item["webSupport"] == "unassessed"
    assert result["selectedViewerId"] is None
    assert result["autoLaunchAllowed"] is False


def test_overridden_instance_predicate_requires_controlled_evaluation():
    result = assessed()
    assessment = by_name(result, "InstanceRestricted")["eligibilityAssessment"]
    assert assessment["hookPolicy"] == "custom-hooks-unverified"
    assert assessment["customInstanceHook"] is True
    assert assessment["customClassHook"] is False
    assert assessment["requiresControlledRuntimeEvaluation"] is True


def test_overridden_class_matcher_requires_controlled_evaluation():
    assessment = by_name(assessed(), "ClassRestricted")["eligibilityAssessment"]
    assert assessment["customClassHook"] is True
    assert assessment["customInstanceHook"] is False
    assert assessment["requiresControlledRuntimeEvaluation"] is True


def test_inherited_overrides_are_detected_without_calling_parent_hooks():
    assessment = by_name(assessed(), "DescendantRestricted")["eligibilityAssessment"]
    assert assessment["customInstanceHook"] is True
    assert assessment["requiresControlledRuntimeEvaluation"] is True


def test_protocol_form_needs_web_adapter_even_with_standard_hooks():
    assessment = by_name(assessed(), "FormViewer")["eligibilityAssessment"]
    assert assessment["hookPolicy"] == "default-hooks"
    assert assessment["webAdapterStatus"] == "not-assessed"
    assert assessment["webLaunchAllowed"] is False
    assert assessment["instanceVerified"] is False


def test_descriptor_based_custom_hook_is_not_invoked():
    prot, registry = fixture()
    from pyworkflow.viewer import Viewer
    class ExplosiveDescriptor:
        def __get__(self, instance, owner):
            raise AssertionError("Descriptor must not be evaluated")
    class DescriptorViewer(Viewer):
        _targets = [prot]
        _environments = ["tkinter"]
        can_handle_this_instance = ExplosiveDescriptor()
    DescriptorViewer.__module__ = "fake_plugin.viewers"
    from app.backend.api.services.protocol_viewer_inventory_service import _class_identity
    candidates = {"viewers": [{"id": _class_identity(DescriptorViewer),
                               "name": "DescriptorViewer"}]}
    answer = eligibility_module().assessProtocolViewerEligibility(
        candidates, {"descriptor": DescriptorViewer}
    )
    assert answer["viewers"][0]["eligibilityAssessment"]["customInstanceHook"] is True


def test_registry_aliases_do_not_duplicate_or_mismatch_classes():
    candidates, registry = candidate_resolution()
    registered = dict(registry)
    registered["AnotherAlias"] = registry["OrdinaryViewer"]
    answer = eligibility_module().assessProtocolViewerEligibility(candidates, registered)
    assert answer["viewerEligibilitySummary"]["candidateCount"] == len(candidates["viewers"])
    assert [x["name"] for x in answer["viewers"]].count("OrdinaryViewer") == 1


def test_unregistered_candidate_identity_fails_closed():
    candidates, registry = candidate_resolution()
    candidates["viewers"][0]["id"] = "unregistered.plugin.EvilViewer"
    with pytest.raises(eligibility_module().ProtocolViewerEligibilityError) as exc:
        eligibility_module().assessProtocolViewerEligibility(candidates, registry)
    assert exc.value.code == "unregistered_viewer"


def test_does_not_expose_stored_params_or_infer_web_support_from_legacy_django():
    from app.backend.api.services.protocol_viewer_persisted_resolution_service import (
        resolvePersistedProtocolViewerCandidates,
    )
    prot, viewers = fixture()
    row = {"id": 812, "projectId": 7, "protocolId": "142",
           "protocolClassName": "Prot", "status": "finished",
           "params": {"password": "DO_NOT_EXPOSE_THIS_VALUE"}}
    calls = []
    class Reader:
        def getProjectProtocolByProtocolId(self, *, projectId, protocolId):
            calls.append((projectId, protocolId))
            return row
        def getProjectProtocolByDbId(self, **kwargs):
            raise AssertionError("Never use database id fallback")
    result = resolvePersistedProtocolViewerCandidates(
        mapper=Reader(), project_id=7, protocol_id=142,
        snapshot={"protocols": {"Prot": prot},
                  "viewers": viewers, "preferredViewers": {}}
    )
    assert calls == [(7, 142)]
    assert result["dataSource"] == "postgresql"
    assert result["instanceMaterialized"] is False
    assert result["instanceChecksApplied"] is False
    assert result["autoLaunchAllowed"] is False
    assert result["viewerEligibilitySummary"]["candidateCount"] == 5
    assert result["viewerEligibilitySummary"]["controlledEvaluationRequired"] == 3
    assert result["viewerEligibilitySummary"]["defaultHookCandidates"] == 2
    assert all(x["eligibilityAssessment"]["webLaunchAllowed"] is False for x in result["viewers"])
    assert by_name(result, "OrdinaryViewer")["legacyDjangoDeclared"] is True
    assert "DO_NOT_EXPOSE_THIS_VALUE" not in str(result)


def test_service_no_viewers_is_a_normal_empty_advisory_result():
    answer = eligibility_module().assessProtocolViewerEligibility({"viewers": []}, {})
    assert answer["viewerEligibilitySummary"] == {
        "candidateCount": 0,
        "defaultHookCandidates": 0,
        "controlledEvaluationRequired": 0,
        "webReadyCount": 0,
    }
    assert answer["autoLaunchAllowed"] is False
    assert answer["selectedViewerId"] is None
