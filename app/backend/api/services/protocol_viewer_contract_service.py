"""Fail-closed consistency check for advisory Scipion ProtocolViewer previews.

The RED 121/123 scanners inspect AST; they cannot certify that a runtime
ProtocolViewer form/action map is complete, or that a React action exists.
This service reconciles their *metadata* without importing plugin code,
instantiating viewers/protocols, or authorising UI/runtime execution.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, Mapping

from pyworkflow.viewer import ProtocolViewer, Viewer

from app.backend.api.services.protocol_viewer_inventory_service import _class_identity
from app.backend.api.services.protocol_viewer_form_schema_service import PARAM_CONTROLS

_MAX_VIEWERS = 512
_MAX_FIELDS = 96
_MAX_ACTIONS = 96
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_CONTROLS = frozenset(PARAM_CONTROLS.values())


class ProtocolViewerContractError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _nonnegative(value: Any) -> bool:
    return type(value) is int and value >= 0


def _clean_text(value: Any, bound: int) -> bool:
    return type(value) is str and 0 < len(value) <= bound


def _add_issue(issues: list, code: str) -> None:
    if code not in issues:
        issues.append(code)


def _public_form_fields(schema: Any, issues: list) -> Dict[str, Dict[str, Any]]:
    if not isinstance(schema, dict) or schema.get("status") != "static-preview":
        _add_issue(issues, "form_schema_unavailable")
        return {}
    sections = schema.get("sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= _MAX_FIELDS:
        _add_issue(issues, "invalid_form_schema")
        return {}
    public = {}
    encountered = 0
    for section in sections:
        if not isinstance(section, dict) or not _clean_text(section.get("label"), 160):
            _add_issue(issues, "invalid_form_schema")
            continue
        groups = section.get("groups", [])
        if not isinstance(groups, list) or len(groups) > _MAX_FIELDS:
            _add_issue(issues, "invalid_form_schema")
            continue
        buckets = [section.get("fields", [])]
        for group in groups:
            if not isinstance(group, dict) or not _clean_text(group.get("label"), 160):
                _add_issue(issues, "invalid_form_schema")
                continue
            buckets.append(group.get("fields", []))
        for bucket in buckets:
            if not isinstance(bucket, list) or len(bucket) > _MAX_FIELDS:
                _add_issue(issues, "invalid_form_schema")
                continue
            for field in bucket:
                encountered += 1
                if encountered > _MAX_FIELDS:
                    _add_issue(issues, "invalid_form_schema")
                    return public
                if not isinstance(field, dict):
                    _add_issue(issues, "invalid_form_field")
                    continue
                name = field.get("name")
                if not (_clean_text(name, 128) and _NAME.fullmatch(name)
                        and _clean_text(field.get("label"), 160)
                        and type(field.get("control")) is str and field["control"] in _CONTROLS):
                    _add_issue(issues, "invalid_form_field")
                    continue
                if name in public:
                    _add_issue(issues, "duplicate_form_field")
                    continue
                if field.get("hasCondition") is True:
                    _add_issue(issues, "unresolved_form_condition")
                if field.get("unresolvedDefault") is True:
                    _add_issue(issues, "unresolved_form_default")
                if field["control"] == "select":
                    choices = field.get("choices")
                    if (not isinstance(choices, list) or not 1 <= len(choices) <= 100
                            or any(type(choice) not in (str, int, float)
                                   or (type(choice) is str and len(choice) > 160)
                                   for choice in choices)):
                        _add_issue(issues, "invalid_form_field")
                public[name] = field
    if not _nonnegative(schema.get("fieldsDiscovered")) or schema["fieldsDiscovered"] != encountered:
        _add_issue(issues, "inconsistent_form_count")
    if not _nonnegative(schema.get("dynamicDefinitionsSkipped")):
        _add_issue(issues, "invalid_form_schema")
    elif schema["dynamicDefinitionsSkipped"]:
        _add_issue(issues, "dynamic_form_definition")
    if not _nonnegative(schema.get("hiddenFields")):
        _add_issue(issues, "invalid_form_schema")
    if schema.get("renderable") is not False or schema.get("actionExecutionAllowed") is not False:
        _add_issue(issues, "unsafe_form_preview_flags")
    return public


def _check_actions(schema: Any, fields: Mapping[str, Any], issues: list) -> int:
    if not isinstance(schema, dict) or schema.get("status") != "static-preview":
        _add_issue(issues, "action_schema_unavailable")
        return 0
    entries = schema.get("actions")
    if not isinstance(entries, list) or len(entries) > _MAX_ACTIONS:
        _add_issue(issues, "invalid_action_schema")
        return 0
    if not _nonnegative(schema.get("actionsDiscovered")) or schema["actionsDiscovered"] != len(entries):
        _add_issue(issues, "inconsistent_action_count")
    if not _nonnegative(schema.get("dynamicEntriesSkipped")):
        _add_issue(issues, "invalid_action_schema")
    elif schema["dynamicEntriesSkipped"]:
        _add_issue(issues, "dynamic_action_definition")
    if not _nonnegative(schema.get("unmatchedActionsOmitted")):
        _add_issue(issues, "invalid_action_schema")
    elif schema["unmatchedActionsOmitted"]:
        _add_issue(issues, "unmatched_action_omitted")
    if schema.get("renderable") is not False or schema.get("executionAllowed") is not False:
        _add_issue(issues, "unsafe_action_preview_flags")
    names = set()
    for entry in entries:
        if not isinstance(entry, dict):
            _add_issue(issues, "invalid_action_entry")
            continue
        action_id = entry.get("id")
        field_name = entry.get("fieldName")
        if (not _clean_text(action_id, 128) or not _NAME.fullmatch(action_id)
                or field_name != action_id or entry.get("kind") != "visualize"
                or not _clean_text(entry.get("label"), 160)
                or type(entry.get("control")) is not str or entry["control"] not in _CONTROLS):
            _add_issue(issues, "invalid_action_entry")
            continue
        if action_id in names:
            _add_issue(issues, "duplicate_action")
        names.add(action_id)
        original = fields.get(action_id)
        if original is None:
            _add_issue(issues, "unknown_action_field")
        elif entry["label"] != original["label"] or entry["control"] != original["control"]:
            _add_issue(issues, "action_field_mismatch")
        if (entry.get("previewOnly") is not True
                or entry.get("executionAllowed") is not False
                or entry.get("requiresRuntimeEvaluation") is not True):
            _add_issue(issues, "unsafe_action_entry_flags")
    return len(entries)


def validateProtocolViewerContracts(
    candidates: Dict[str, Any], viewer_registry: Mapping[str, Any],
) -> Dict[str, Any]:
    """Provide advisory status; never promote declarations to runnable web UI."""
    if (not isinstance(candidates, dict)
            or not isinstance(candidates.get("viewers"), list)
            or len(candidates["viewers"]) > _MAX_VIEWERS):
        raise ProtocolViewerContractError("invalid_candidates", "Invalid viewer candidate list")
    if not isinstance(viewer_registry, Mapping):
        raise ProtocolViewerContractError("invalid_registry", "Invalid viewer class registry")
    registered = {
        _class_identity(cls): cls for cls in viewer_registry.values()
        if isinstance(cls, type) and issubclass(cls, Viewer)
    }
    # Reject stale/forged ids *before* reading any preview metadata.
    for candidate in candidates["viewers"]:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str):
            raise ProtocolViewerContractError("invalid_candidates", "Invalid viewer descriptor")
        if candidate["id"] not in registered:
            raise ProtocolViewerContractError("unregistered_viewer", "Viewer is not registered")

    result = copy.deepcopy(candidates)
    counts = {"described": 0, "pending": 0, "discovered": 0}
    n_protocol = 0
    for item in result["viewers"]:
        cls = registered[item["id"]]
        issues = []
        if issubclass(cls, ProtocolViewer):
            n_protocol += 1
            form = item.get("formSchema")
            action = item.get("actionSchema")
            fields = _public_form_fields(form, issues)
            action_count = _check_actions(action, fields, issues)
            has_preview = (isinstance(form, dict) and form.get("status") == "static-preview") or (
                isinstance(action, dict) and action.get("status") == "static-preview"
            )
            status = "described" if not issues else ("pending" if has_preview else "discovered")
        else:
            # A plain Viewer is not a ProtocolViewer form. Other viewer types
            # can be adapted later, but must not accidentally inherit form actions.
            fields, action_count, status = {}, 0, "discovered"
            if item.get("formSchema") is not None or item.get("actionSchema") is not None:
                _add_issue(issues, "unexpected_protocol_form")
        counts[status] += 1
        # An AST parse is not an execution permit even if perfectly consistent.
        has_adapter = isinstance(item.get("webAdapter"), dict)
        blockers = list(issues)
        blockers.extend(("runtime_instance_not_verified",
                         "web_adapter_not_integrated" if has_adapter else "web_adapter_missing"))
        item["contractValidation"] = {
            "status": status,
            "staticConsistency": "advisory-consistent" if status == "described" else
                                 ("incomplete" if status == "pending" else "unavailable"),
            "issues": issues,
            "blockers": blockers,
            "publicFieldCount": len(fields),
            "previewActionCount": action_count,
            "formComplete": False, "actionsComplete": False,
            "instanceVerified": False, "webAdapterIntegrated": False,
            "webReady": False, "renderable": False, "executionAllowed": False,
        }
        item["webSupport"] = "unassessed"
        item["runtimeEligibility"] = "unverified"
        item["webReady"] = False
        item["webLaunchAllowed"] = False
        item["renderable"] = False
        item["executionAllowed"] = False
        # Adapter metadata remains declarative, even when a caller inserted
        # a forged ready/integrated status in the incoming descriptor.
        if isinstance(item.get("webAdapter"), dict):
            item["webAdapter"]["status"] = "declared-not-integrated"
        if isinstance(item.get("eligibilityAssessment"), dict):
            item["eligibilityAssessment"]["webLaunchAllowed"] = False
        if isinstance(item.get("formSchema"), dict):
            item["formSchema"]["renderable"] = False
            item["formSchema"]["actionExecutionAllowed"] = False
        if isinstance(item.get("actionSchema"), dict):
            item["actionSchema"]["renderable"] = False
            item["actionSchema"]["executionAllowed"] = False
            if isinstance(item["actionSchema"].get("actions"), list):
                for action in item["actionSchema"]["actions"]:
                    if isinstance(action, dict):
                        action["executionAllowed"] = False
                        action["previewOnly"] = True
    result["contractValidationSummary"] = {
        "candidateCount": len(result["viewers"]),
        "protocolViewerCount": n_protocol,
        "describedCount": counts["described"],
        "pendingCount": counts["pending"],
        "discoveredCount": counts["discovered"],
        "webReadyCount": 0,
    }
    result["autoLaunchAllowed"] = False
    result["selectedViewerId"] = None
    return result
