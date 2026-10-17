"""Read-only contract for explicit Scipion protocol-viewer web adapters.

A declaration describes a possible integration; it NEVER certifies that React,
its backend action handler, or protocol-instance checks are available. No class
is constructed and no callbacks, plugin methods, or external programs are run.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from pyworkflow.viewer import Viewer

from app.backend.api.services.protocol_viewer_inventory_service import _class_identity


# Deliberately empty: support is NOT inferred from Scipion/Tkinter/Django or
# from a viewer's return types. Future adapters must be reviewed and declared.
# Key: fully qualified Viewer class identity (module + qualname).
# Value: {"id": ..., "surface": "react" | "external",
#         "capabilities": [{"kind": ..., "effect": ...}, ...]}.
REGISTERED_PROTOCOL_VIEWER_WEB_ADAPTERS: Dict[str, Dict[str, Any]] = {}

CAPABILITY_KINDS = frozenset({
    "metadata-table", "volume", "particles", "classes", "plot", "image",
    "html-report", "message", "monitor", "external-app", "protocol-action",
})
CAPABILITY_EFFECTS = frozenset({
    "read-only", "derived-read", "mutating", "external-process",
})
SURFACES = frozenset({"react", "external"})


class ProtocolViewerCapabilitiesError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _validate_adapter(value: Any) -> Dict[str, Any]:
    """Validate plain symbolic metadata; never resolve arbitrary callables."""
    if not isinstance(value, dict) or set(value) != {"id", "surface", "capabilities"}:
        raise ProtocolViewerCapabilitiesError(
            "invalid_adapter", "Adapter declarations require id, surface, and capabilities only"
        )
    ident, surface, capabilities = value["id"], value["surface"], value["capabilities"]
    if not isinstance(ident, str) or not ident.strip() or len(ident) > 128:
        raise ProtocolViewerCapabilitiesError("invalid_adapter", "Invalid adapter identifier")
    if not isinstance(surface, str) or surface not in SURFACES:
        raise ProtocolViewerCapabilitiesError("invalid_adapter", "Invalid adapter presentation surface")
    if not isinstance(capabilities, (list, tuple)) or not 1 <= len(capabilities) <= 32:
        raise ProtocolViewerCapabilitiesError("invalid_adapter", "Invalid adapter capabilities list")
    normalized = []
    seen = set()
    for capability in capabilities:
        if not isinstance(capability, dict) or set(capability) != {"kind", "effect"}:
            raise ProtocolViewerCapabilitiesError("invalid_adapter", "Invalid capability declaration")
        kind, effect = capability["kind"], capability["effect"]
        if not isinstance(kind, str) or kind not in CAPABILITY_KINDS:
            raise ProtocolViewerCapabilitiesError("invalid_capability", "Unsupported capability kind")
        if not isinstance(effect, str) or effect not in CAPABILITY_EFFECTS:
            raise ProtocolViewerCapabilitiesError("invalid_effect", "Unsupported capability effect")
        if (kind, effect) in seen:
            raise ProtocolViewerCapabilitiesError("duplicate_capability", "Duplicate capability declaration")
        seen.add((kind, effect))
        normalized.append({"kind": kind, "effect": effect})
    return {
        "id": ident,
        "surface": surface,
        "status": "declared-not-integrated",
        "capabilities": normalized,
    }


def describeProtocolViewerWebCapabilities(
    candidates: Dict[str, Any],
    viewer_registry: Mapping[str, Any],
    adapters: Mapping[str, Any] = None,
) -> Dict[str, Any]:
    """Annotate advisory viewer candidates with reviewed *declarations*.

    Backend execution and UI rendering require separate future opt-in gates.
    A caller cannot turn a declaration into web readiness by setting a flag.
    """
    if not isinstance(candidates, dict) or not isinstance(candidates.get("viewers"), list):
        raise ProtocolViewerCapabilitiesError("invalid_candidates", "Invalid viewer candidate result")
    if not isinstance(viewer_registry, Mapping):
        raise ProtocolViewerCapabilitiesError("invalid_registry", "Invalid viewer registry")
    if adapters is None:
        adapters = REGISTERED_PROTOCOL_VIEWER_WEB_ADAPTERS
    if not isinstance(adapters, Mapping):
        raise ProtocolViewerCapabilitiesError("invalid_adapters", "Invalid web adapter registry")

    registered = {
        _class_identity(cls)
        for cls in viewer_registry.values()
        if isinstance(cls, type) and issubclass(cls, Viewer)
    }
    # Validate the candidates before adding any metadata; don't approve
    # forged/stale viewer ids just because someone declared an adapter.
    for viewer in candidates["viewers"]:
        if not isinstance(viewer, dict) or not isinstance(viewer.get("id"), str):
            raise ProtocolViewerCapabilitiesError("invalid_candidates", "Invalid viewer descriptor")
        if viewer["id"] not in registered:
            raise ProtocolViewerCapabilitiesError("unregistered_viewer", "Viewer is not registered")

    # Only declarations for currently registered viewers can be relevant.
    # Uninstalled plugins' declarations are ignored, not imported or executed.
    normalized = {}
    for viewer_id, value in adapters.items():
        if not isinstance(viewer_id, str):
            raise ProtocolViewerCapabilitiesError("invalid_adapter", "Invalid viewer adapter key")
        if viewer_id in registered:
            normalized[viewer_id] = _validate_adapter(value)

    result = dict(candidates)
    result_viewers = []
    matched = 0
    for viewer in candidates["viewers"]:
        item = dict(viewer)
        adapter = normalized.get(item["id"])
        if adapter is None:
            item["webAdapter"] = None
            item["webCapabilities"] = []
            adapter_status = "not-registered"
        else:
            matched += 1
            item["webAdapter"] = {"id": adapter["id"], "surface": adapter["surface"],
                                  "status": adapter["status"]}
            item["webCapabilities"] = [dict(cap) for cap in adapter["capabilities"]]
            adapter_status = "declared-not-integrated"
        # Keep legacy webSupport semantics until a runnable web integration exists.
        item["webSupport"] = "unassessed"
        if isinstance(item.get("eligibilityAssessment"), dict):
            assessment = dict(item["eligibilityAssessment"])
            assessment["webAdapterStatus"] = adapter_status
            assessment["webLaunchAllowed"] = False
            item["eligibilityAssessment"] = assessment
        item["runtimeEligibility"] = "unverified"
        result_viewers.append(item)
    result["viewers"] = result_viewers
    result["webCapabilitySummary"] = {
        "candidateCount": len(result_viewers),
        "declaredAdapterCount": matched,
        "unadaptedCount": len(result_viewers) - matched,
        "webReadyCount": 0,
    }
    result["autoLaunchAllowed"] = False
    result["selectedViewerId"] = None
    return result
