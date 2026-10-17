"""Pure, non-executing assessment of Scipion viewer eligibility hooks.

Inspect registered viewer *classes* only. Custom plugin callbacks must never
run during HTTP diagnostics. Runtime instance checks and React web adapters
will require their own explicitly controlled execution/registration paths.
"""
from __future__ import annotations

import inspect
from typing import Any, Dict, Mapping

from pyworkflow.viewer import Viewer

from app.backend.api.services.protocol_viewer_inventory_service import _class_identity


class ProtocolViewerEligibilityError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _registered_viewer_classes(registry: Mapping[str, Any]) -> Dict[str, type]:
    unique = {}
    for candidate in registry.values():
        if isinstance(candidate, type) and issubclass(candidate, Viewer):
            unique[_class_identity(candidate)] = candidate
    return unique


def _custom_hook(viewer_class: type, hook_name: str) -> bool:
    """Use static class lookup: never bind a descriptor or call a callback."""
    base_hook = inspect.getattr_static(Viewer, hook_name, None)
    implementation = inspect.getattr_static(viewer_class, hook_name, None)
    return implementation is not base_hook


def assessProtocolViewerEligibility(
    candidates: Dict[str, Any],
    viewer_registry: Mapping[str, Any],
) -> Dict[str, Any]:
    """Enrich advisory candidates with *static* instance-check requirements.

    This operation does not verify the runtime protocol instance, evaluate
    custom plugin hooks, or approve any viewer for browser execution.
    """
    if not isinstance(candidates, dict) or not isinstance(candidates.get("viewers"), list):
        raise ProtocolViewerEligibilityError("invalid_candidates", "Invalid viewer candidate list")
    if not isinstance(viewer_registry, Mapping):
        raise ProtocolViewerEligibilityError("invalid_registry", "Invalid viewer registry")

    registered = _registered_viewer_classes(viewer_registry)
    assessments = []
    # Validate the whole list before enriching anything. Unknown ids fail closed.
    for item in candidates["viewers"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ProtocolViewerEligibilityError("invalid_candidates", "Invalid viewer descriptor")
        cls = registered.get(item["id"])
        if cls is None:
            raise ProtocolViewerEligibilityError("unregistered_viewer", "Viewer identity is not registered")
        custom_class = _custom_hook(cls, "can_handle_this")
        custom_instance = _custom_hook(cls, "can_handle_this_instance")
        requires_check = custom_class or custom_instance
        assessments.append((item, {
            "hookPolicy": "custom-hooks-unverified" if requires_check else "default-hooks",
            "customClassHook": custom_class,
            "customInstanceHook": custom_instance,
            "requiresControlledRuntimeEvaluation": requires_check,
            "instanceVerified": False,
            "webAdapterStatus": "not-assessed",
            "webLaunchAllowed": False,
        }))

    for item, assessment in assessments:
        item["eligibilityAssessment"] = assessment
        item["runtimeEligibility"] = "unverified"
        item["webSupport"] = "unassessed"

    candidates["viewerEligibilitySummary"] = {
        "candidateCount": len(assessments),
        "defaultHookCandidates": sum(not a["requiresControlledRuntimeEvaluation"] for _, a in assessments),
        "controlledEvaluationRequired": sum(a["requiresControlledRuntimeEvaluation"] for _, a in assessments),
        "webReadyCount": 0,
    }
    candidates["instanceChecksApplied"] = False
    candidates["autoLaunchAllowed"] = False
    candidates["selectedViewerId"] = None
    return candidates
