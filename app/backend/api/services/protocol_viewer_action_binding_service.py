"""Resolve server-declared ProtocolViewer action/output associations conservatively.

An explicit *server-owned* declaration selects exactly one named output, never
user-submitted paths, matching labels, inferred output names, or arbitrary
plugin callbacks. PostgreSQL and the independent action/resource bridge must
confirm its identity and type. This does not establish scientific semantics,
runtime eligibility, authorization, or a runnable web adapter.

This service exposes no HTTP route. Every future caller must authorize the
user's project *before* calling it. No built-in declarations are shipped.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Dict

from app.backend.api.services.protocol_viewer_action_resource_bridge_service import inspectPersistedProtocolViewerActionResource

_VIEWER_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_OUTPUT_CLASS = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_EXACT_DECLARATION_KEYS = frozenset(("outputName", "outputClassName", "adapterKind"))
_EXACT_BRIDGE_KEYS = frozenset((
    "status", "source", "projectId", "protocolId", "viewerId", "actionId",
    "outputName", "resourceKind", "outputClassName", "webViewerKind",
    "adapterStatus", "adapterKind", "resourceCompatibility", "bindingStatus",
    "availability", "blockers", "instanceVerified", "renderable", "executionAllowed",
))
_KIND_TO_WEB_VIEWER = MappingProxyType({"volume": "volume", "metadata-table": "metadata"})
_MAX_VIEWERS = 512
_MAX_ACTIONS = 96

# Deliberately EMPTY. A reviewed server change must explicitly opt in one
# exact (viewerId, actionId, outputName, outputClassName, adapterKind).
# No plugin-provided runtime dict and no browser request may populate it.
SERVER_DECLARED_ACTION_OUTPUT_BINDINGS = MappingProxyType({})


class ProtocolViewerActionBindingError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _validated_declaration(viewer_id: str, action_id: str) -> dict:
    registry = SERVER_DECLARED_ACTION_OUTPUT_BINDINGS
    if not isinstance(registry, Mapping) or len(registry) > _MAX_VIEWERS:
        raise ProtocolViewerActionBindingError("invalid_server_registry")
    for key in registry:
        if type(key) is not str or not _VIEWER_ID.fullmatch(key):
            raise ProtocolViewerActionBindingError("invalid_server_registry")
    actions = registry.get(viewer_id)
    if actions is None:
        raise ProtocolViewerActionBindingError("binding_not_declared")
    if not isinstance(actions, Mapping) or len(actions) > _MAX_ACTIONS:
        raise ProtocolViewerActionBindingError("invalid_server_registry")
    for key in actions:
        if type(key) is not str or not _NAME.fullmatch(key):
            raise ProtocolViewerActionBindingError("invalid_server_registry")
    declared = actions.get(action_id)
    if declared is None:
        raise ProtocolViewerActionBindingError("binding_not_declared")
    if not isinstance(declared, Mapping) or set(declared) != _EXACT_DECLARATION_KEYS:
        raise ProtocolViewerActionBindingError("invalid_binding_declaration")
    output_name = declared.get("outputName")
    output_class = declared.get("outputClassName")
    adapter_kind = declared.get("adapterKind")
    if (type(output_name) is not str or not _NAME.fullmatch(output_name)
            or type(output_class) is not str or not _OUTPUT_CLASS.fullmatch(output_class)
            or type(adapter_kind) is not str or adapter_kind not in _KIND_TO_WEB_VIEWER):
        raise ProtocolViewerActionBindingError("invalid_binding_declaration")
    return {"outputName": output_name, "outputClassName": output_class, "adapterKind": adapter_kind}


def _validated_bridge_evidence(evidence: Any, expected: dict, identity: tuple) -> None:
    project_id, protocol_id, viewer_id, action_id = identity
    if (not isinstance(evidence, dict) or set(evidence) != _EXACT_BRIDGE_KEYS
            or evidence.get("status") != "advisory-only"
            or evidence.get("source") != "postgresql-static-ast"
            or type(evidence.get("projectId")) is not int or evidence["projectId"] != project_id
            or evidence.get("protocolId") != str(protocol_id)
            or evidence.get("viewerId") != viewer_id or evidence.get("actionId") != action_id
            or evidence.get("outputName") != expected["outputName"]
            or evidence.get("resourceKind") != "persisted-set"
            or evidence.get("bindingStatus") != "unverified"
            or evidence.get("resourceCompatibility") != "kind-match"
            or evidence.get("adapterStatus") != "declared-not-integrated"
            or evidence.get("availability") != "blocked"
            or evidence.get("instanceVerified") is not False
            or evidence.get("renderable") is not False
            or evidence.get("executionAllowed") is not False):
        raise ProtocolViewerActionBindingError("invalid_bridge_evidence")
    if (evidence.get("outputClassName") != expected["outputClassName"]
            or evidence.get("adapterKind") != expected["adapterKind"]
            or evidence.get("webViewerKind") != _KIND_TO_WEB_VIEWER[expected["adapterKind"]]):
        raise ProtocolViewerActionBindingError("binding_type_mismatch")
    if evidence.get("blockers") != [
        "action_adapter_not_integrated", "action_binding_not_verified",
        "runtime_instance_not_verified", "web_action_not_implemented",
    ]:
        raise ProtocolViewerActionBindingError("invalid_bridge_evidence")


def inspectDeclaredProtocolViewerActionBinding(*, mapper: Any, set_mapper: Any, snapshot: Any,
                                               project_id: int, protocol_id: int,
                                               viewer_id: str, action_id: str) -> Dict[str, Any]:
    """Confirm a server-declared output's persisted identity, NOT permission.

    The exact output name is taken solely from the backend declaration. This
    is still declaration evidence, not proof that the plugin callback consumes
    the output or that the current runtime/adapter can render it.
    """
    if (type(project_id) is not int or project_id <= 0
            or type(protocol_id) is not int or protocol_id <= 0
            or type(viewer_id) is not str or not _VIEWER_ID.fullmatch(viewer_id)
            or type(action_id) is not str or not _NAME.fullmatch(action_id)):
        raise ProtocolViewerActionBindingError("invalid_identity")
    if mapper is None or set_mapper is None or not isinstance(snapshot, Mapping):
        raise ProtocolViewerActionBindingError("invalid_context")
    declaration = _validated_declaration(viewer_id, action_id)

    # The existing independent bridge validates the registered viewer,
    # action schema, PostgreSQL protocol identity and persisted output.
    evidence = inspectPersistedProtocolViewerActionResource(
        mapper=mapper, set_mapper=set_mapper, snapshot=snapshot, project_id=project_id,
        protocol_id=protocol_id, viewer_id=viewer_id, action_id=action_id,
        output_name=declaration["outputName"],
    )
    _validated_bridge_evidence(evidence, declaration, (project_id, protocol_id, viewer_id, action_id))

    # Explicit result whitelist: never copy source paths, plugin parameters,
    # callback identifiers, SQL row IDs, or external addresses.
    return {
        "status": "declaration-and-persistence-checked",
        "source": "server-declaration+postgresql-static-ast",
        "projectId": project_id, "protocolId": str(protocol_id),
        "viewerId": viewer_id, "actionId": action_id,
        "outputName": declaration["outputName"], "outputClassName": declaration["outputClassName"],
        "webViewerKind": evidence["webViewerKind"], "adapterKind": declaration["adapterKind"],
        "bindingStatus": "declared-output-confirmed",
        "scientificSemanticsVerified": False,
        "instanceVerified": False,
        "availability": "blocked",
        "blockers": ["action_adapter_not_integrated", "action_semantics_not_verified",
                     "runtime_instance_not_verified", "web_action_not_implemented"],
        "renderable": False, "executionAllowed": False,
    }
