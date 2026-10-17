"""Authorized read-only HTTP projection of a ProtocolViewer output inspection target.

This exposes metadata, not a scientific action, a browser-launch permission, a
file path or a native pointer. Project authorization MUST precede discovery,
static AST inspection and PostgreSQL Set reads. The web client supplies only
registered viewer/action identities; never an output selector or executable code.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Dict, Optional

from app.backend.api.services.protocol_viewer_output_inspection_target_service import (
    ProtocolViewerInspectionTargetError,
    _ACTION_ID, _OUTPUT_NAME, _VIEWER_ID, _OUTPUT_VIEWERS,
    prepareProtocolViewerOutputInspectionTarget,
)

_MAX_ID = 2147483647
_EXPECTED = frozenset((
    "status", "source", "projectId", "protocolId", "viewerId", "actionId",
    "sourceCorrelation", "target", "bindingVerified", "scientificSemanticsVerified",
    "inspectionAuthorized", "actionExecutionAllowed", "requiresCallerAuthorization",
))
_TARGET = frozenset((
    "projectId", "protocolId", "outputName", "outputClassName",
    "webViewerKind", "inspectionMode",
))
_CORRELATIONS = frozenset((
    "indeterminate", "no-direct-reference", "ambiguous-references",
    "declared-output-not-referenced", "single-reference-matches-declaration",
))
_SOURCE = "server-declaration+registered-static-ast+postgresql"


class ProtocolViewerInspectionHttpError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _identity(project_id: Any, protocol_id: Any, viewer_id: Any, action_id: Any) -> bool:
    return (
        type(project_id) is int and 0 < project_id <= _MAX_ID
        and type(protocol_id) is int and 0 < protocol_id <= _MAX_ID
        and type(viewer_id) is str and _VIEWER_ID.fullmatch(viewer_id) is not None
        and len(viewer_id) <= 255
        and type(action_id) is str and _ACTION_ID.fullmatch(action_id) is not None
    )


def _safe_projection(result: Any, project_id: int, protocol_id: int,
                     viewer_id: str, action_id: str) -> Dict[str, Any]:
    """Reject forged booleans, identities, targets and extra target fields."""
    if (not isinstance(result, dict) or not _EXPECTED.issubset(result)
            or result.get("status") not in ("inspection-target-pending", "inspection-target-described")
            or result.get("source") != _SOURCE
            or type(result.get("projectId")) is not int or result["projectId"] != project_id
            or result.get("protocolId") != str(protocol_id)
            or result.get("viewerId") != viewer_id or result.get("actionId") != action_id
            or result.get("sourceCorrelation") not in _CORRELATIONS
            or any(result.get(key) is not False for key in (
                "bindingVerified", "scientificSemanticsVerified",
                "inspectionAuthorized", "actionExecutionAllowed"))
            or result.get("requiresCallerAuthorization") is not True):
        raise ProtocolViewerInspectionHttpError("invalid_inspection_target")

    correlation = result["sourceCorrelation"]
    matched = correlation == "single-reference-matches-declaration"
    if (result["status"] == "inspection-target-described") != matched:
        raise ProtocolViewerInspectionHttpError("invalid_inspection_target")
    target = result["target"]
    if matched:
        if (not isinstance(target, dict) or set(target) != _TARGET
                or type(target.get("projectId")) is not int or target["projectId"] != project_id
                or target.get("protocolId") != str(protocol_id)
                or type(target.get("outputName")) is not str
                or _OUTPUT_NAME.fullmatch(target["outputName"]) is None
                or type(target.get("outputClassName")) is not str
                or type(target.get("webViewerKind")) is not str
                or target.get("inspectionMode") != "manual-persisted-output"
                or target["webViewerKind"] not in ("volume", "metadata")
                or _OUTPUT_VIEWERS.get(target["outputClassName"]) != target["webViewerKind"]):
            raise ProtocolViewerInspectionHttpError("invalid_inspection_target")
        target = {key: target[key] for key in (
            "projectId", "protocolId", "outputName", "outputClassName",
            "webViewerKind", "inspectionMode")}
    elif target is not None:
        raise ProtocolViewerInspectionHttpError("invalid_inspection_target")

    # Explicit allowlist: do not forward callbacks, URLs, paths, extra claims,
    # scientific data or other fields from underlying plugin metadata.
    return {
        "status": result["status"], "source": _SOURCE,
        "projectId": project_id, "protocolId": str(protocol_id),
        "viewerId": viewer_id, "actionId": action_id,
        "sourceCorrelation": correlation, "target": target,
        "projectAccessVerified": True,
        "bindingVerified": False, "scientificSemanticsVerified": False,
        "inspectionAuthorized": False, "browserLaunchAllowed": False,
        "actionExecutionAllowed": False,
    }


def requestProtocolViewerOutputInspectionHttp(*, mapper: Any, current_user: Any,
                                               project_service: Any, project_id: int,
                                               protocol_id: int, viewer_id: str,
                                               action_id: str, snapshot_provider: Callable,
                                               set_mapper_factory: Optional[Callable] = None,
                                               target_builder: Optional[Callable] = None) -> Dict[str, Any]:
    """Authorize the project before consulting viewer registry or output data.

    The two optional callables are server-internal dependency seams for tests;
    the HTTP payload cannot provide them. No global execution flags are set.
    """
    if not _identity(project_id, protocol_id, viewer_id, action_id):
        raise ProtocolViewerInspectionHttpError("invalid_identity")
    if (not isinstance(current_user, Mapping)
            or type(current_user.get("id")) is not int or current_user["id"] <= 0):
        raise ProtocolViewerInspectionHttpError("unauthenticated")
    if (mapper is None or project_service is None
            or not callable(getattr(project_service, "getProjectDbRow", None))
            or not callable(snapshot_provider)
            or (set_mapper_factory is not None and not callable(set_mapper_factory))
            or (target_builder is not None and not callable(target_builder))):
        raise ProtocolViewerInspectionHttpError("invalid_context")

    project = project_service.getProjectDbRow(mapper, project_id, current_user)
    if not project:
        raise ProtocolViewerInspectionHttpError("project_not_found")
    snapshot = snapshot_provider()
    if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("viewers"), Mapping):
        raise ProtocolViewerInspectionHttpError("invalid_context")

    if set_mapper_factory is None:
        from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
        set_mapper_factory = ScipionSetPostgresqlMapper
    set_mapper = set_mapper_factory(mapper)
    if set_mapper is None:
        raise ProtocolViewerInspectionHttpError("invalid_context")
    builder = prepareProtocolViewerOutputInspectionTarget if target_builder is None else target_builder
    try:
        result = builder(
            mapper=mapper, set_mapper=set_mapper, snapshot=snapshot,
            viewer_registry=snapshot["viewers"], project_id=project_id,
            protocol_id=protocol_id, viewer_id=viewer_id, action_id=action_id,
        )
    except ProtocolViewerInspectionTargetError as exc:
        # No traceback, source code, native object or filesystem path reaches HTTP.
        if exc.code in ("binding_not_declared", "viewer_not_found", "action_not_found"):
            raise ProtocolViewerInspectionHttpError("inspection_target_not_found") from None
        if exc.code in ("invalid_identity", "invalid_context"):
            raise ProtocolViewerInspectionHttpError("invalid_context") from None
        raise ProtocolViewerInspectionHttpError("inspection_target_unavailable") from None
    return _safe_projection(result, project_id, protocol_id, viewer_id, action_id)
