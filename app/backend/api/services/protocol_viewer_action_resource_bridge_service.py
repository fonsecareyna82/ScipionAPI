"""Read-only evidence about a ProtocolViewer action and a PostgreSQL output.

This internal service does not bind the output to the action, authorize access,
run plugin code, or open a browser viewer. Its caller must authorize the user
and project *before* calling it; no HTTP route is exposed by this module.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Dict

from app.backend.api.services.protocol_viewer_persisted_resolution_service import resolvePersistedProtocolViewerCandidates
from app.backend.api.services.protocol_viewer_persisted_resource_service import resolvePersistedProtocolViewerOutputResource

_ACTION_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_VIEWER_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z")
_OUTPUT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_ADAPTER_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,127}\Z")
_MAX_VIEWERS = 512
_MAX_ACTIONS = 96

# Strictly advisory compatibility hints for already-existing React viewer kinds.
# A kind match is NOT proof that an action emits that output, nor that the
# adapter is actually integrated. Do not infer convergence plots from FSCs.
_ADVISORY_KIND_MATCHES = {
    "volume": frozenset(("volume",)),
    "metadata-table": frozenset(("metadata",)),
}
_SAFE_KINDS = frozenset(("metadata-table", "volume", "particles", "classes", "plot", "image", "html-report", "message", "monitor", "external-app", "protocol-action"))
_EXPECTED_ACTION_KEYS = frozenset(("id", "fieldName", "label", "control", "intent", "source", "adapter", "adapterStatus", "availability", "blockers", "requiresRuntimeVerification", "renderable", "executionAllowed"))
_EXPECTED_ADAPTER_KEYS = frozenset(("id", "kind", "effect", "surface", "status"))


class ProtocolViewerActionResourceBridgeError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _checked_action(contract: Any, action_id: str) -> dict:
    if (not isinstance(contract, dict) or contract.get("status") != "advisory-only"
            or contract.get("source") != "static-ast" or contract.get("renderable") is not False
            or contract.get("executionAllowed") is not False or contract.get("readyCount") != 0
            or type(contract.get("readyCount")) is not int):
        raise ProtocolViewerActionResourceBridgeError("action_contract_unavailable")
    actions = contract.get("actions")
    if (not isinstance(actions, list) or len(actions) > _MAX_ACTIONS
            or type(contract.get("actionCount")) is not int or contract["actionCount"] != len(actions)):
        raise ProtocolViewerActionResourceBridgeError("invalid_action_contract")
    found = []
    seen = set()
    for action in actions:
        if not isinstance(action, dict) or set(action) != _EXPECTED_ACTION_KEYS:
            raise ProtocolViewerActionResourceBridgeError("invalid_action_contract")
        ident = action.get("id")
        if type(ident) is not str or not _ACTION_ID.fullmatch(ident) or ident in seen:
            raise ProtocolViewerActionResourceBridgeError("invalid_action_contract")
        seen.add(ident)
        if ident == action_id:
            found.append(action)
    if not found:
        raise ProtocolViewerActionResourceBridgeError("action_not_found")
    return found[0]


def _checked_advisory_action(action: dict, schema: Any) -> tuple:
    action_id = action["id"]
    if (action.get("fieldName") != action_id or action.get("intent") != "visualize"
            or action.get("source") != "static-ast" or action.get("availability") != "blocked"
            or action.get("requiresRuntimeVerification") is not True
            or action.get("renderable") is not False or action.get("executionAllowed") is not False
            or type(action.get("label")) is not str or not action["label"]
            or type(action.get("control")) is not str):
        raise ProtocolViewerActionResourceBridgeError("invalid_action_contract")
    if (not isinstance(schema, dict) or schema.get("status") != "static-preview"
            or schema.get("source") != "static-ast" or schema.get("executionAllowed") is not False
            or schema.get("renderable") is not False or not isinstance(schema.get("actions"), list)):
        raise ProtocolViewerActionResourceBridgeError("action_schema_mismatch")
    matches = [a for a in schema["actions"] if isinstance(a, dict) and a.get("id") == action_id]
    if (len(matches) != 1 or matches[0].get("fieldName") != action_id
            or matches[0].get("label") != action["label"]
            or matches[0].get("control") != action["control"]
            or matches[0].get("kind") != "visualize"
            or matches[0].get("previewOnly") is not True
            or matches[0].get("executionAllowed") is not False
            or matches[0].get("requiresRuntimeEvaluation") is not True):
        raise ProtocolViewerActionResourceBridgeError("action_schema_mismatch")
    status = action.get("adapterStatus")
    adapter = action.get("adapter")
    blockers = action.get("blockers")
    if not isinstance(blockers, list) or not all(type(b) is str for b in blockers):
        raise ProtocolViewerActionResourceBridgeError("invalid_action_contract")
    if status == "missing" and adapter is None:
        required = ["action_adapter_missing", "runtime_instance_not_verified", "web_action_not_implemented"]
        kind = None
    elif status == "declared-not-integrated" and isinstance(adapter, dict):
        if (set(adapter) != _EXPECTED_ADAPTER_KEYS
                or type(adapter.get("id")) is not str or not _ADAPTER_ID.fullmatch(adapter["id"])
                or type(adapter.get("kind")) is not str or adapter["kind"] not in _SAFE_KINDS
                or adapter.get("effect") not in ("read-only", "derived-read")
                or adapter.get("surface") not in ("react", "external")
                or adapter.get("status") != "declared-not-integrated"):
            raise ProtocolViewerActionResourceBridgeError("invalid_action_contract")
        required = ["action_adapter_not_integrated", "runtime_instance_not_verified", "web_action_not_implemented"]
        kind = adapter["kind"]
    else:
        raise ProtocolViewerActionResourceBridgeError("invalid_action_contract")
    if blockers != required:
        raise ProtocolViewerActionResourceBridgeError("invalid_action_contract")
    return status, kind


def inspectPersistedProtocolViewerActionResource(*, mapper: Any, set_mapper: Any, snapshot: Any,
                                                 project_id: int, protocol_id: int,
                                                 viewer_id: str, action_id: str,
                                                 output_name: str) -> Dict[str, Any]:
    """Compare trusted static action evidence with a scoped, persisted output.

    Both upstream resolvers perform their own PostgreSQL identity validation.
    No supplied action-to-output binding is accepted and no result is runnable.
    """
    if (type(project_id) is not int or project_id <= 0 or type(protocol_id) is not int or protocol_id <= 0
            or type(viewer_id) is not str or not _VIEWER_ID.fullmatch(viewer_id)
            or type(action_id) is not str or not _ACTION_ID.fullmatch(action_id)
            or type(output_name) is not str or not _OUTPUT_NAME.fullmatch(output_name)):
        raise ProtocolViewerActionResourceBridgeError("invalid_identity")
    if mapper is None or set_mapper is None or not isinstance(snapshot, Mapping):
        raise ProtocolViewerActionResourceBridgeError("invalid_context")

    # Discover from the installed registry, never from browser-supplied actions.
    discovered = resolvePersistedProtocolViewerCandidates(mapper=mapper, project_id=project_id,
                                                          protocol_id=protocol_id, snapshot=snapshot)
    if (not isinstance(discovered, dict) or discovered.get("projectId") != project_id
            or discovered.get("protocolId") != str(protocol_id) or discovered.get("dataSource") != "postgresql"
            or discovered.get("autoLaunchAllowed") is not False
            or discovered.get("selectedViewerId") is not None
            or discovered.get("instanceMaterialized") is not False
            or discovered.get("instanceChecksApplied") is not False):
        raise ProtocolViewerActionResourceBridgeError("invalid_discovery")
    viewers = discovered.get("viewers")
    if not isinstance(viewers, list) or len(viewers) > _MAX_VIEWERS:
        raise ProtocolViewerActionResourceBridgeError("invalid_discovery")
    found = [v for v in viewers if isinstance(v, dict) and v.get("id") == viewer_id]
    if len(found) != 1:
        raise ProtocolViewerActionResourceBridgeError("viewer_not_found" if not found else "duplicate_viewer")
    viewer = found[0]
    if any(viewer.get(key) is not False for key in ("webReady", "webLaunchAllowed", "renderable", "executionAllowed")):
        raise ProtocolViewerActionResourceBridgeError("invalid_discovery")
    action = _checked_action(viewer.get("webActionContracts"), action_id)
    adapter_status, adapter_kind = _checked_advisory_action(action, viewer.get("actionSchema"))

    # Only resolve the output AFTER the action and viewer are verified. Never
    # request an output from some other project/protocol or scan all Sets.
    resource = resolvePersistedProtocolViewerOutputResource(mapper=mapper, set_mapper=set_mapper,
                                                            project_id=project_id, protocol_id=protocol_id,
                                                            output_name=output_name)
    if (not isinstance(resource, dict) or resource.get("status") != "metadata-verified"
            or resource.get("source") != "postgresql" or resource.get("projectId") != project_id
            or resource.get("protocolId") != str(protocol_id) or resource.get("outputName") != output_name
            or resource.get("resourceKind") != "persisted-set" or resource.get("availability") != "blocked"
            or resource.get("renderable") is not False or resource.get("executionAllowed") is not False
            or resource.get("instanceVerified") is not False):
        raise ProtocolViewerActionResourceBridgeError("invalid_resource")
    resource_kind = resource.get("webViewerKind")
    output_class = resource.get("outputClassName")
    if type(resource_kind) is not str or type(output_class) is not str:
        raise ProtocolViewerActionResourceBridgeError("invalid_resource")

    compatibility = "not-assessed"
    if adapter_kind in _ADVISORY_KIND_MATCHES:
        compatibility = "kind-match" if resource_kind in _ADVISORY_KIND_MATCHES[adapter_kind] else "kind-mismatch"
    blockers = ["action_adapter_missing" if adapter_status == "missing" else "action_adapter_not_integrated"]
    blockers.extend(("action_binding_not_verified", "runtime_instance_not_verified", "web_action_not_implemented"))
    if compatibility == "kind-mismatch":
        blockers.append("resource_kind_incompatible")

    # Never copy protocol params, source paths, adapter id, callbacks, or URLs.
    return {
        "status": "advisory-only", "source": "postgresql-static-ast",
        "projectId": project_id, "protocolId": str(protocol_id),
        "viewerId": viewer_id, "actionId": action_id, "outputName": output_name,
        "resourceKind": "persisted-set", "outputClassName": output_class,
        "webViewerKind": resource_kind, "adapterStatus": adapter_status,
        "adapterKind": adapter_kind, "resourceCompatibility": compatibility,
        "bindingStatus": "unverified", "availability": "blocked",
        "blockers": blockers, "instanceVerified": False,
        "renderable": False, "executionAllowed": False,
    }
