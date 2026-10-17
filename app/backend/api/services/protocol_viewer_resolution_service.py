"""Match registered protocol viewer *classes* without executing plugin viewers.

Mirrors the static parts of pyworkflow Domain.findViewers ordering:
configured preferred, exact target, inherited target, then registry name.
This is an advisory class-level lookup; per-instance can_handle_this_instance
(and overridden can_handle_this) is NOT called. The returned viewer is never
approved for web launch by this service.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, Mapping, Optional

from pyworkflow.protocol import Protocol
from pyworkflow.viewer import Viewer

from app.backend.api.services.protocol_viewer_inventory_service import (
    buildProtocolViewerInventory,
    _static_value,
    _class_identity,
)


class ProtocolViewerResolutionError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _registered_protocol_class(registry: Mapping[str, Any], identifier: str) -> type:
    identifier = str(identifier or "").strip()
    classes: Dict[str, type] = {}
    for candidate in registry.values():
        if isinstance(candidate, type) and issubclass(candidate, Protocol):
            classes[_class_identity(candidate)] = candidate

    if identifier in classes:
        return classes[identifier]
    matches = [cls for cls in classes.values() if cls.__name__ == identifier]
    if len(matches) > 1:
        raise ProtocolViewerResolutionError(
            "ambiguous",
            "Ambiguous protocol class %r; use its fully qualified name" % identifier,
        )
    if not matches:
        raise ProtocolViewerResolutionError(
            "not_found", "Unknown registered protocol class: %s" % identifier,
        )
    return matches[0]


def resolveProtocolViewerCandidates(
        protocol_registry: Mapping[str, Any],
        viewer_registry: Mapping[str, Any],
        protocol_class_id: str,
        preferred_viewers: Optional[Mapping[str, Any]] = None,
        environment: str = "tkinter",
) -> Dict[str, Any]:
    """Rank candidates using only class metadata; never invoke plugin callbacks.

    Important: Domain.findViewers may also call plugin-specific
    can_handle_this_instance/can_handle_this; this deliberately does not.
    No result from this method authorizes executing a viewer in ScipionAPI.
    """
    protocol_class = _registered_protocol_class(protocol_registry, protocol_class_id)
    mro = protocol_class.mro()
    preferred = preferred_viewers if isinstance(preferred_viewers, Mapping) else {}
    configured = preferred.get(protocol_class.__name__, ())
    if not isinstance(configured, (list, tuple)):
        configured = ()
    preferred_ids = [p for p in configured if isinstance(p, str)]
    candidates = {}
    # Resolve preferred viewer identity by already loaded, registered class.
    # Do not import modules named by VIEWERS config.
    for registration_name in sorted(viewer_registry):
        viewer = viewer_registry[registration_name]
        if not isinstance(viewer, type) or not issubclass(viewer, Viewer):
            continue
        envs = _static_value(viewer, "_environments", ())
        if not isinstance(envs, (tuple, list, set, frozenset)) or environment not in envs:
            continue
        targets = _static_value(viewer, "_targets", ())
        if not isinstance(targets, (tuple, list)):
            continue
        matched = [t for t in targets if isinstance(t, type) and t in mro]
        if not matched:
            continue
        exact = protocol_class in matched
        target = protocol_class if exact else min(matched, key=mro.index)
        ident = _class_identity(viewer)
        if ident in candidates:
            continue
        lookup_name = "%s.%s" % (viewer.__module__, viewer.__name__)
        try:
            pref_index = preferred_ids.index(lookup_name)
        except ValueError:
            pref_index = None
        reason = "preferred" if pref_index is not None else "exact" if exact else "inherited"
        instance_method = inspect.getattr_static(viewer, "can_handle_this_instance", None)
        default_instance_method = inspect.getattr_static(Viewer, "can_handle_this_instance", None)
        can_handle = inspect.getattr_static(viewer, "can_handle_this", None)
        default_can_handle = inspect.getattr_static(Viewer, "can_handle_this", None)
        candidates[ident] = {
            "class": viewer,
            "reason": reason,
            "preferredIndex": pref_index,
            "registration": str(registration_name),
            "matchedTarget": _class_identity(target),
            "instanceConditionUnverified": (
                instance_method is not default_instance_method
                or can_handle is not default_can_handle
            ),
        }

    def order(value):
        reason_rank = {"preferred": 0, "exact": 1, "inherited": 2}
        return (
            reason_rank[value["reason"]],
            value["preferredIndex"] if value["preferredIndex"] is not None else 0,
            value["registration"],
        )

    ordered = sorted(candidates.items(), key=lambda item: order(item[1]))
    # Use canonical inventory descriptors; these are read-only metadata.
    inventory = {item["id"]: item for item in buildProtocolViewerInventory(viewer_registry)}
    resolved = []
    for rank, (ident, match) in enumerate(ordered, start=1):
        descriptor = dict(inventory[ident])
        descriptor.update({
            "rank": rank,
            "matchReason": match["reason"],
            "matchedTarget": match["matchedTarget"],
            "instanceConditionUnverified": match["instanceConditionUnverified"],
        })
        resolved.append(descriptor)
    return {
        "protocol": {
            "id": _class_identity(protocol_class),
            "name": protocol_class.__name__,
        },
        "environment": environment,
        "selectionMode": "class-only",
        "instanceChecksApplied": False,
        "hasUnverifiedInstanceConditions": any(
            item["instanceConditionUnverified"] for item in resolved
        ),
        "autoLaunchAllowed": False,
        "viewerCount": len(resolved),
        "viewers": resolved,
        "firstCandidateId": resolved[0]["id"] if resolved else None,
    }
