"""Advisory cross-check of independently derived ProtocolViewer action/output evidence.

Only a server-owned exact binding can select a candidate output. An AST direct
reference to that name is additional *source-consistency evidence*, NOT a
scientific proof or a web execution permission. This has NO HTTP route and
must only be called after authorization by its eventual server-side caller.

Never execute a plugin callback, instantiate a protocol, load a Set, scan
outputs, open paths, derive an output name from an action label, or register a
binding from AST output. No current browser action is made executable.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Dict

from app.backend.api.services.protocol_viewer_action_binding_service import (
    ProtocolViewerActionBindingError,
    _validated_declaration,
    inspectDeclaredProtocolViewerActionBinding,
)
from app.backend.api.services.protocol_viewer_persisted_resolution_service import resolvePersistedProtocolViewerCandidates
from app.backend.api.services.protocol_viewer_static_action_reference_service import (
    describeProtocolViewerStaticResourceReferences,
)

_VIEWER_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z")
_ACTION_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_MAX_VIEWERS = 512
_MAX_ACTIONS = 96
_EXPECTED_BINDING_KEYS = frozenset((
    "status", "source", "projectId", "protocolId", "viewerId", "actionId",
    "outputName", "outputClassName", "webViewerKind", "adapterKind", "bindingStatus",
    "scientificSemanticsVerified", "instanceVerified", "availability", "blockers",
    "renderable", "executionAllowed",
))
_EXPECTED_SOURCE_KEYS = frozenset((
    "actionId", "status", "source", "candidateOutputNames", "scientificSemanticsVerified",
    "bindingVerified", "availability", "renderable", "executionAllowed",
))
_EXPECTED_SOURCE_BLOCK = frozenset((
    "status", "source", "actions", "actionCount", "verifiedBindings",
    "renderable", "executionAllowed",
))


class ProtocolViewerActionSourceConsistencyError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _check_identity(*, mapper, set_mapper, snapshot, viewer_registry, project_id, protocol_id,
                    viewer_id, action_id, source_loader):
    if (type(project_id) is not int or project_id <= 0
            or type(protocol_id) is not int or protocol_id <= 0
            or type(viewer_id) is not str or not _VIEWER_ID.fullmatch(viewer_id)
            or type(action_id) is not str or not _ACTION_ID.fullmatch(action_id)):
        raise ProtocolViewerActionSourceConsistencyError("invalid_identity")
    if (mapper is None or set_mapper is None or not isinstance(snapshot, Mapping)
            or not isinstance(viewer_registry, Mapping)
            or (source_loader is not None and not callable(source_loader))):
        raise ProtocolViewerActionSourceConsistencyError("invalid_context")


def _validated_discovery(data: Any, project_id: int, protocol_id: int, viewer_id: str) -> None:
    if (not isinstance(data, dict) or data.get("projectId") != project_id
            or data.get("protocolId") != str(protocol_id)
            or data.get("dataSource") != "postgresql"
            or data.get("selectedViewerId") is not None
            or data.get("autoLaunchAllowed") is not False
            or data.get("instanceMaterialized") is not False
            or data.get("instanceChecksApplied") is not False):
        raise ProtocolViewerActionSourceConsistencyError("invalid_discovery")
    viewers = data.get("viewers")
    if not isinstance(viewers, list) or len(viewers) > _MAX_VIEWERS:
        raise ProtocolViewerActionSourceConsistencyError("invalid_discovery")
    matches = [v for v in viewers if isinstance(v, dict) and v.get("id") == viewer_id]
    if len(matches) != 1:
        raise ProtocolViewerActionSourceConsistencyError("viewer_not_found" if not matches else "duplicate_viewer")
    for field in ("webReady", "webLaunchAllowed", "renderable", "executionAllowed"):
        if matches[0].get(field) is not False:
            raise ProtocolViewerActionSourceConsistencyError("invalid_discovery")


def _checked_source_report(discovered: Any, viewer_id: str, action_id: str) -> dict:
    if (not isinstance(discovered, dict) or discovered.get("autoLaunchAllowed") is not False
            or not isinstance(discovered.get("viewers"), list)):
        raise ProtocolViewerActionSourceConsistencyError("invalid_source_evidence")
    matches = [v for v in discovered["viewers"] if isinstance(v, dict) and v.get("id") == viewer_id]
    if len(matches) != 1:
        raise ProtocolViewerActionSourceConsistencyError("invalid_source_evidence")
    block = matches[0].get("staticResourceReferences")
    if (not isinstance(block, dict) or set(block) != _EXPECTED_SOURCE_BLOCK
            or block.get("status") != "advisory-only" or block.get("source") != "static-ast"
            or block.get("verifiedBindings") != 0 or type(block.get("verifiedBindings")) is not int
            or block.get("renderable") is not False or block.get("executionAllowed") is not False):
        raise ProtocolViewerActionSourceConsistencyError("invalid_source_evidence")
    actions = block.get("actions")
    if (not isinstance(actions, list) or len(actions) > _MAX_ACTIONS
            or type(block.get("actionCount")) is not int or block["actionCount"] != len(actions)):
        raise ProtocolViewerActionSourceConsistencyError("invalid_source_evidence")
    seen = set()
    selected = None
    for action in actions:
        if not isinstance(action, dict) or set(action) != _EXPECTED_SOURCE_KEYS:
            raise ProtocolViewerActionSourceConsistencyError("invalid_source_evidence")
        ident = action.get("actionId")
        names = action.get("candidateOutputNames")
        if (type(ident) is not str or not _ACTION_ID.fullmatch(ident) or ident in seen
                or action.get("source") != "static-ast" or action.get("status") not in (
                    "indeterminate", "source-reference-observed", "no-direct-reference-observed")
                or not isinstance(names, list) or len(names) > _MAX_ACTIONS
                or any(type(x) is not str or not re.fullmatch(r"output[A-Z0-9_][A-Za-z0-9_]{0,121}", x) for x in names)
                or names != sorted(set(names))
                or (action["status"] == "source-reference-observed") != bool(names)
                or action.get("scientificSemanticsVerified") is not False
                or action.get("bindingVerified") is not False
                or action.get("availability") != "blocked"
                or action.get("renderable") is not False
                or action.get("executionAllowed") is not False):
            raise ProtocolViewerActionSourceConsistencyError("invalid_source_evidence")
        seen.add(ident)
        if ident == action_id:
            selected = action
    if selected is None:
        raise ProtocolViewerActionSourceConsistencyError("action_not_found")
    return selected


def _checked_binding_result(result: Any, declared: dict, identity: tuple) -> None:
    project_id, protocol_id, viewer_id, action_id = identity
    if (not isinstance(result, dict) or set(result) != _EXPECTED_BINDING_KEYS
            or result.get("status") != "declaration-and-persistence-checked"
            or result.get("source") != "server-declaration+postgresql-static-ast"
            or type(result.get("projectId")) is not int or result["projectId"] != project_id
            or result.get("protocolId") != str(protocol_id)
            or result.get("viewerId") != viewer_id or result.get("actionId") != action_id
            or result.get("outputName") != declared["outputName"]
            or result.get("outputClassName") != declared["outputClassName"]
            or result.get("adapterKind") != declared["adapterKind"]
            or result.get("bindingStatus") != "declared-output-confirmed"
            or result.get("scientificSemanticsVerified") is not False
            or result.get("instanceVerified") is not False
            or result.get("availability") != "blocked"
            or result.get("renderable") is not False
            or result.get("executionAllowed") is not False
            or result.get("blockers") != [
                "action_adapter_not_integrated", "action_semantics_not_verified",
                "runtime_instance_not_verified", "web_action_not_implemented"]):
        raise ProtocolViewerActionSourceConsistencyError("invalid_binding_evidence")
    if result.get("webViewerKind") not in ("volume", "metadata"):
        raise ProtocolViewerActionSourceConsistencyError("invalid_binding_evidence")
    if (result["adapterKind"] == "volume" and result["webViewerKind"] != "volume"
            or result["adapterKind"] == "metadata-table" and result["webViewerKind"] != "metadata"):
        raise ProtocolViewerActionSourceConsistencyError("invalid_binding_evidence")


def inspectDeclaredProtocolViewerActionSourceConsistency(*, mapper: Any, set_mapper: Any,
                                                          snapshot: Any, viewer_registry: Any,
                                                          project_id: int, protocol_id: int,
                                                          viewer_id: str, action_id: str,
                                                          source_loader=None) -> Dict[str, Any]:
    """Correlate server declaration + registered-class AST + persisted output.

    The optional source_loader is for internal tests; never expose it via HTTP.
    An observed reference is NEVER scientific proof. No web action is enabled.
    """
    _check_identity(mapper=mapper, set_mapper=set_mapper, snapshot=snapshot,
                    viewer_registry=viewer_registry, project_id=project_id, protocol_id=protocol_id,
                    viewer_id=viewer_id, action_id=action_id, source_loader=source_loader)
    try:
        declaration = _validated_declaration(viewer_id, action_id)
    except ProtocolViewerActionBindingError as error:
        raise ProtocolViewerActionSourceConsistencyError(error.code) from None

    # Establish the persisted protocol and registered viewer BEFORE parsing
    # sources. Neither the action label nor the browser provides the output.
    discovered = resolvePersistedProtocolViewerCandidates(mapper=mapper, project_id=project_id,
                                                          protocol_id=protocol_id, snapshot=snapshot)
    _validated_discovery(discovered, project_id, protocol_id, viewer_id)
    try:
        source_evidence = describeProtocolViewerStaticResourceReferences(
            discovered, viewer_registry, **({} if source_loader is None else {"source_loader": source_loader}))
    except (ValueError, TypeError) as error:
        raise ProtocolViewerActionSourceConsistencyError("static_analysis_unavailable") from error
    reported = _checked_source_report(source_evidence, viewer_id, action_id)
    references = reported["candidateOutputNames"]
    expected_name = declaration["outputName"]
    if reported["status"] == "indeterminate":
        correlation = "indeterminate"
    elif not references:
        correlation = "no-direct-reference"
    elif len(references) != 1:
        correlation = "ambiguous-references"
    elif references[0] != expected_name:
        correlation = "declared-output-not-referenced"
    else:
        correlation = "single-reference-matches-declaration"

    # Only a single exact match merits the further, scoped PostgreSQL check.
    # All other outcomes are advisory and never query output data.
    persisted = False
    if correlation == "single-reference-matches-declaration":
        evidence = inspectDeclaredProtocolViewerActionBinding(
            mapper=mapper, set_mapper=set_mapper, snapshot=snapshot,
            project_id=project_id, protocol_id=protocol_id,
            viewer_id=viewer_id, action_id=action_id)
        _checked_binding_result(evidence, declaration, (project_id, protocol_id, viewer_id, action_id))
        persisted = True
    return {
        "status": "advisory-only", "source": "server-declaration+registered-static-ast+postgresql",
        "projectId": project_id, "protocolId": str(protocol_id),
        "viewerId": viewer_id, "actionId": action_id,
        "declaredOutputName": expected_name,
        "sourceCorrelation": correlation,
        "persistedOutputConfirmed": persisted,
        "bindingVerified": False, "scientificSemanticsVerified": False,
        "instanceVerified": False, "availability": "blocked",
        "blockers": ["action_semantics_not_verified", "runtime_instance_not_verified",
                     "action_adapter_not_integrated", "web_action_not_implemented"],
        "renderable": False, "executionAllowed": False,
    }
