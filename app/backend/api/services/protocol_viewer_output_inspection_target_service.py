"""Prepare a typed hand-off to existing ScipionWeb output viewers.

A matching server declaration, direct AST reference and PostgreSQL Set lookup
permit constructing an *inspection-only* target. They do not prove scientific
action semantics and NEVER authorize a ProtocolViewer callback or a browser
launch. There is no HTTP endpoint: a future caller must authorize the project,
then explicitly choose whether to offer manual output inspection.

Only server-authored (project, protocol, outputName, className) values leave
this boundary; no paths, plugin arguments, callback names, resource handles,
URLs, pointer values or Set members are returned.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Dict

from app.backend.api.services.protocol_viewer_action_binding_service import _validated_declaration
from app.backend.api.services.protocol_viewer_action_source_consistency_service import (
    inspectDeclaredProtocolViewerActionSourceConsistency,
)
from app.backend.api.services.protocol_viewer_persisted_resource_service import _OUTPUT_VIEWERS

_VIEWER_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z")
_ACTION_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_OUTPUT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_DECLARATION_FIELDS = frozenset(("outputName", "outputClassName", "adapterKind"))
_CONSISTENCY_FIELDS = frozenset((
    "status", "source", "projectId", "protocolId", "viewerId", "actionId",
    "declaredOutputName", "sourceCorrelation", "persistedOutputConfirmed",
    "bindingVerified", "scientificSemanticsVerified", "instanceVerified",
    "availability", "blockers", "renderable", "executionAllowed",
))
_CORRELATIONS = frozenset((
    "indeterminate", "no-direct-reference", "ambiguous-references",
    "declared-output-not-referenced", "single-reference-matches-declaration",
))
_BLOCKERS = [
    "action_semantics_not_verified", "runtime_instance_not_verified",
    "action_adapter_not_integrated", "web_action_not_implemented",
]
_KIND_TO_VIEWER = {"volume": "volume", "metadata-table": "metadata"}


class ProtocolViewerInspectionTargetError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _validate_report(report: Any, identity: tuple) -> str:
    project_id, protocol_id, viewer_id, action_id = identity
    if (not isinstance(report, dict) or set(report) != _CONSISTENCY_FIELDS
            or report.get("status") != "advisory-only"
            or report.get("source") != "server-declaration+registered-static-ast+postgresql"
            or type(report.get("projectId")) is not int or report["projectId"] != project_id
            or report.get("protocolId") != str(protocol_id)
            or report.get("viewerId") != viewer_id or report.get("actionId") != action_id
            or report.get("sourceCorrelation") not in _CORRELATIONS
            or type(report.get("declaredOutputName")) is not str
            or not _OUTPUT_NAME.fullmatch(report["declaredOutputName"])
            or type(report.get("persistedOutputConfirmed")) is not bool
            or report.get("bindingVerified") is not False
            or report.get("scientificSemanticsVerified") is not False
            or report.get("instanceVerified") is not False
            or report.get("availability") != "blocked"
            or report.get("blockers") != _BLOCKERS
            or report.get("renderable") is not False
            or report.get("executionAllowed") is not False):
        raise ProtocolViewerInspectionTargetError("invalid_consistency_evidence")
    match = report["sourceCorrelation"] == "single-reference-matches-declaration"
    if report["persistedOutputConfirmed"] != match:
        raise ProtocolViewerInspectionTargetError("invalid_consistency_evidence")
    return report["sourceCorrelation"]


def _validate_declaration(declaration: Any, output_name: str) -> tuple:
    if (not isinstance(declaration, Mapping) or set(declaration) != _DECLARATION_FIELDS
            or declaration.get("outputName") != output_name
            or type(declaration.get("outputClassName")) is not str
            or type(declaration.get("adapterKind")) is not str
            or not _OUTPUT_NAME.fullmatch(declaration["outputClassName"])
            or declaration["adapterKind"] not in _KIND_TO_VIEWER):
        raise ProtocolViewerInspectionTargetError("invalid_server_declaration")
    klass = declaration["outputClassName"]
    kind = _KIND_TO_VIEWER[declaration["adapterKind"]]
    if _OUTPUT_VIEWERS.get(klass) != kind:
        raise ProtocolViewerInspectionTargetError("incompatible_inspection_viewer")
    return klass, kind


def prepareProtocolViewerOutputInspectionTarget(*, mapper: Any, set_mapper: Any,
                                                 snapshot: Any, viewer_registry: Any,
                                                 project_id: int, protocol_id: int,
                                                 viewer_id: str, action_id: str,
                                                 source_loader=None) -> Dict[str, Any]:
    """Prepare a manual inspection target, never an action execution command.

    This internal helper does NOT authorize the caller. Future HTTP handlers
    must check project access *before* invoking it, even for blocked results.
    An observed AST reference is advisory evidence only.
    """
    if (type(project_id) is not int or project_id <= 0
            or type(protocol_id) is not int or protocol_id <= 0
            or type(viewer_id) is not str or not _VIEWER_ID.fullmatch(viewer_id)
            or type(action_id) is not str or not _ACTION_ID.fullmatch(action_id)):
        raise ProtocolViewerInspectionTargetError("invalid_identity")
    if (mapper is None or set_mapper is None or not isinstance(snapshot, Mapping)
            or not isinstance(viewer_registry, Mapping)
            or (source_loader is not None and not callable(source_loader))):
        raise ProtocolViewerInspectionTargetError("invalid_context")
    report = inspectDeclaredProtocolViewerActionSourceConsistency(
        mapper=mapper, set_mapper=set_mapper, snapshot=snapshot,
        viewer_registry=viewer_registry, project_id=project_id, protocol_id=protocol_id,
        viewer_id=viewer_id, action_id=action_id, source_loader=source_loader,
    )
    correlation = _validate_report(report, (project_id, protocol_id, viewer_id, action_id))
    result = {
        "status": "inspection-target-pending" if correlation != "single-reference-matches-declaration" else "inspection-target-described",
        "source": "server-declaration+registered-static-ast+postgresql",
        "projectId": project_id,
        "protocolId": str(protocol_id),
        "viewerId": viewer_id,
        "actionId": action_id,
        "sourceCorrelation": correlation,
        "target": None,
        "bindingVerified": False,
        "scientificSemanticsVerified": False,
        "inspectionAuthorized": False,
        "actionExecutionAllowed": False,
        "requiresCallerAuthorization": True,
    }
    if correlation != "single-reference-matches-declaration":
        return result
    declaration = _validated_declaration(viewer_id, action_id)
    klass, kind = _validate_declaration(declaration, report["declaredOutputName"])
    # These are the props the existing AnalyzeOutputDialog can consume.
    # No raw Set, native Pointer or arbitrary `outputRaw` from a client.
    result["target"] = {
        "projectId": project_id,
        "protocolId": str(protocol_id),
        "outputName": report["declaredOutputName"],
        "outputClassName": klass,
        "webViewerKind": kind,
        "inspectionMode": "manual-persisted-output",
    }
    return result
