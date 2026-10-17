"""Conservative, per-action web-adapter contracts for Scipion ProtocolViewers.

Static _getVisualizeDict metadata is only a hint.  Declaring an action adapter
is never proof that a renderer, a backend operation or an instance check exists.
This module registers *no runnable adapters* and exposes no action endpoint.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any, Dict

from pyworkflow.viewer import ProtocolViewer, Viewer

from app.backend.api.services.protocol_viewer_capabilities_service import (
    CAPABILITY_KINDS,
)
from app.backend.api.services.protocol_viewer_inventory_service import _class_identity

# Declarative integration map: fully qualified registered viewer -> Scipion action
# field name -> reviewed adapter metadata. This does NOT register executable code.
REGISTERED_PROTOCOL_VIEWER_ACTION_ADAPTERS: Dict[str, Dict[str, Dict[str, str]]] = {}

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_ADAPTER_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,127}\Z")
_SAFE_EFFECTS = frozenset(("read-only", "derived-read"))
_SURFACES = frozenset(("react", "external"))
_MAX_VIEWERS = 512
_MAX_ACTIONS = 96


class ProtocolViewerWebActionContractError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _registered_viewers(viewer_registry: Any) -> dict:
    if not isinstance(viewer_registry, Mapping):
        raise ProtocolViewerWebActionContractError("invalid_registry")
    # Dict aliases must not result in duplicate action publication.
    return {
        _class_identity(value): value
        for value in viewer_registry.values()
        if isinstance(value, type) and issubclass(value, Viewer)
    }


def _adapter(metadata: Any) -> dict:
    """Reject arbitrary URLs/callbacks/paths; capabilities are just metadata."""
    if not isinstance(metadata, dict) or set(metadata) != {
        "id", "kind", "effect", "surface"
    }:
        raise ProtocolViewerWebActionContractError("invalid_adapter")
    ident, kind = metadata["id"], metadata["kind"]
    if not (type(ident) is str and _ADAPTER_ID.fullmatch(ident)):
        raise ProtocolViewerWebActionContractError("invalid_adapter")
    if type(kind) is not str or kind not in CAPABILITY_KINDS:
        raise ProtocolViewerWebActionContractError("invalid_adapter_kind")
    if (type(metadata["effect"]) is not str or metadata["effect"] not in _SAFE_EFFECTS
            or type(metadata["surface"]) is not str or metadata["surface"] not in _SURFACES):
        raise ProtocolViewerWebActionContractError("unsafe_adapter_effect")
    return {
        "id": ident, "kind": kind, "effect": metadata["effect"],
        "surface": metadata["surface"], "status": "declared-not-integrated",
    }


def _adapter_registry(adapters: Any, registered: Mapping[str, type]) -> dict:
    if not isinstance(adapters, Mapping) or len(adapters) > _MAX_VIEWERS:
        raise ProtocolViewerWebActionContractError("invalid_adapters")
    accepted = {}
    for viewer_id, by_action in adapters.items():
        if type(viewer_id) is not str or not isinstance(by_action, Mapping):
            raise ProtocolViewerWebActionContractError("invalid_adapters")
        if len(by_action) > _MAX_ACTIONS:
            raise ProtocolViewerWebActionContractError("invalid_adapters")
        if viewer_id not in registered:
            continue  # A stale declaration cannot import/activate a plugin.
        entries = {}
        for action_id, metadata in by_action.items():
            if type(action_id) is not str or not _NAME.fullmatch(action_id):
                raise ProtocolViewerWebActionContractError("invalid_adapters")
            entries[action_id] = _adapter(metadata)
        accepted[viewer_id] = entries
    return accepted


def _public_fields(schema: Any) -> dict:
    if not isinstance(schema, dict) or schema.get("status") != "static-preview":
        return {}
    sections = schema.get("sections")
    if not isinstance(sections, list) or len(sections) > _MAX_ACTIONS:
        return {}
    result = {}
    for section in sections:
        if not isinstance(section, dict):
            return {}
        groups = section.get("groups", [])
        if not isinstance(groups, list) or len(groups) > _MAX_ACTIONS:
            return {}
        buckets = [section.get("fields", [])]
        buckets += [group.get("fields", []) for group in groups if isinstance(group, dict)]
        for bucket in buckets:
            if not isinstance(bucket, list) or len(bucket) > _MAX_ACTIONS:
                return {}
            for field in bucket:
                if not isinstance(field, dict):
                    continue
                name = field.get("name")
                if (type(name) is str and _NAME.fullmatch(name)
                        and type(field.get("label")) is str
                        and 0 < len(field["label"]) <= 160
                        and type(field.get("control")) is str and 0 < len(field["control"]) <= 40):
                    result.setdefault(name, (field["label"], field["control"]))
    return result


def _preview_actions(schema: Any, public_fields: Mapping[str, tuple]) -> list:
    if not isinstance(schema, dict) or schema.get("status") != "static-preview":
        return []
    if schema.get("source") != "static-ast":
        return []
    entries = schema.get("actions")
    if not isinstance(entries, list) or len(entries) > _MAX_ACTIONS:
        return []
    accepted, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        action_id = entry.get("id")
        if (type(action_id) is not str or not _NAME.fullmatch(action_id)
                or action_id in seen or entry.get("fieldName") != action_id
                or entry.get("kind") != "visualize"
                or entry.get("previewOnly") is not True
                or entry.get("executionAllowed") is not False
                or entry.get("requiresRuntimeEvaluation") is not True
                or public_fields.get(action_id) != (entry.get("label"), entry.get("control"))):
            continue
        seen.add(action_id)
        accepted.append(entry)
    return accepted


def describeProtocolViewerWebActionContracts(
    candidates: Dict[str, Any], viewer_registry: Mapping[str, Any],
    adapters: Mapping[str, Any] = None,
) -> Dict[str, Any]:
    """Attach blocked action contracts to already-discovered protocol viewers.

    Trust is established in earlier discovery/AST validation stages; even with
    that metadata and an exact declarative adapter binding, execution stays off.
    """
    if (not isinstance(candidates, dict)
            or not isinstance(candidates.get("viewers"), list)
            or len(candidates["viewers"]) > _MAX_VIEWERS):
        raise ProtocolViewerWebActionContractError("invalid_candidates")
    registered = _registered_viewers(viewer_registry)
    for item in candidates["viewers"]:
        if not isinstance(item, dict) or type(item.get("id")) is not str:
            raise ProtocolViewerWebActionContractError("invalid_candidates")
        if item["id"] not in registered:
            raise ProtocolViewerWebActionContractError("unregistered_viewer")
    if adapters is None:
        adapters = REGISTERED_PROTOCOL_VIEWER_ACTION_ADAPTERS
    bindings = _adapter_registry(adapters, registered)
    output = copy.deepcopy(candidates)
    total = declared = 0
    for item in output["viewers"]:
        viewer_id = item["id"]
        if not issubclass(registered[viewer_id], ProtocolViewer):
            item["webActionContracts"] = None
            continue
        fields = _public_fields(item.get("formSchema"))
        actions = _preview_actions(item.get("actionSchema"), fields)
        published = []
        for action in actions:
            match = bindings.get(viewer_id, {}).get(action["id"])
            blockers = ["runtime_instance_not_verified", "web_action_not_implemented"]
            if match is None:
                blockers.insert(0, "action_adapter_missing")
            else:
                blockers.insert(0, "action_adapter_not_integrated")
                declared += 1
            published.append({
                "id": action["id"], "fieldName": action["fieldName"],
                "label": action["label"], "control": action["control"],
                "intent": "visualize", "source": "static-ast",
                "adapter": copy.deepcopy(match) if match is not None else None,
                "adapterStatus": "declared-not-integrated" if match else "missing",
                "availability": "blocked", "blockers": blockers,
                "requiresRuntimeVerification": True,
                "renderable": False, "executionAllowed": False,
            })
        total += len(published)
        item["webActionContracts"] = {
            "status": "advisory-only", "source": "static-ast",
            "actions": published, "actionCount": len(published),
            "declaredAdapterCount": sum(a["adapter"] is not None for a in published),
            "readyCount": 0, "renderable": False, "executionAllowed": False,
        }
        # Never promote a candidate or its previously built AST schema.
        item["webReady"] = False
        item["webLaunchAllowed"] = False
        item["renderable"] = False
        item["executionAllowed"] = False
        if isinstance(item.get("actionSchema"), dict):
            item["actionSchema"]["executionAllowed"] = False
            item["actionSchema"]["renderable"] = False
            for action in item["actionSchema"].get("actions", []):
                if isinstance(action, dict):
                    action["executionAllowed"] = False
                    action["previewOnly"] = True
    output["webActionContractSummary"] = {
        "candidateCount": len(output["viewers"]),
        "describedActionCount": total,
        "declaredAdapterCount": declared,
        "readyActionCount": 0,
    }
    output["autoLaunchAllowed"] = False
    output["selectedViewerId"] = None
    return output
