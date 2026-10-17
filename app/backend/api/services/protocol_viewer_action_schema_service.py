"""Conservative AST-only preview of ProtocolViewer visualize actions.

A field-to-handler association in _getVisualizeDict is NOT a web operation.
The source may execute code or change the mapping at runtime; only a separate,
reviewed adapter and isolated protocol-instance evaluation may permit execution.
"""
from __future__ import annotations

import ast
import copy
import inspect
import re
import textwrap
from typing import Any, Dict, Mapping

from pyworkflow.viewer import ProtocolViewer, Viewer

from app.backend.api.services.protocol_viewer_inventory_service import _class_identity

MAX_SOURCE_LENGTH = 131072
MAX_NODES = 8000
MAX_ACTIONS = 96
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_HANDLER = re.compile(r"_[A-Za-z][A-Za-z0-9_]{0,127}\Z")


class ProtocolViewerActionsError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _empty(status: str = "unavailable") -> Dict[str, Any]:
    return {
        "status": status, "source": "static-ast", "actions": [],
        "actionsDiscovered": 0, "unmatchedActionsOmitted": 0,
        "dynamicEntriesSkipped": 0, "requiresRuntimeEvaluation": True,
        "executionAllowed": False, "renderable": False,
    }


def _public_fields(form_schema: Any) -> Dict[str, Dict[str, str]]:
    """Only names already reviewed by the static form scanner count as public."""
    if not isinstance(form_schema, dict) or form_schema.get("status") != "static-preview":
        return {}
    result = {}
    sections = form_schema.get("sections")
    if not isinstance(sections, list) or len(sections) > 100:
        return result
    for section in sections:
        if not isinstance(section, dict):
            continue
        groups = section.get("groups", [])
        if not isinstance(groups, list) or len(groups) > 100:
            continue
        sets = [section.get("fields", [])]
        sets.extend(group.get("fields", []) for group in groups if isinstance(group, dict))
        for fields in sets:
            if not isinstance(fields, list) or len(fields) > MAX_ACTIONS:
                continue
            for field in fields:
                if not isinstance(field, dict):
                    continue
                name, label, control = field.get("name"), field.get("label"), field.get("control")
                if (type(name) is str and _IDENTIFIER.fullmatch(name)
                        and type(label) is str and 0 < len(label) <= 160
                        and type(control) is str and 0 < len(control) <= 40):
                    result.setdefault(name, {"label": label, "control": control})
    return result


def _mapping_entries(node: ast.Dict, public: Mapping[str, Any]) -> Dict[str, Any]:
    found = []
    skipped = 0
    unmatched = 0
    seen = set()
    if len(node.keys) > MAX_ACTIONS:
        return {"actions": [], "skipped": len(node.keys), "unmatched": 0}
    for key_node, handler_node in zip(node.keys, node.values):
        # Only explicit, unique string-key -> self.method mappings qualify.
        if not isinstance(key_node, ast.Constant) or type(key_node.value) is not str:
            skipped += 1
            continue
        key = key_node.value
        if not _IDENTIFIER.fullmatch(key) or key in seen:
            skipped += 1
            continue
        seen.add(key)
        if not (isinstance(handler_node, ast.Attribute)
                and isinstance(handler_node.value, ast.Name)
                and handler_node.value.id == "self"
                and _HANDLER.fullmatch(handler_node.attr)):
            skipped += 1
            continue
        if key not in public:
            unmatched += 1  # Hidden or dynamically declared controls: no action exposure.
            continue
        field = public[key]
        found.append({
            "id": key,
            "fieldName": key,
            "label": field["label"],
            "control": field["control"],
            "kind": "visualize",
            "previewOnly": True,
            "requiresRuntimeEvaluation": True,
            "executionAllowed": False,
        })
    return {"actions": found, "skipped": skipped, "unmatched": unmatched}


def parseProtocolViewerStaticActionsSource(source: str, form_schema: Any) -> Dict[str, Any]:
    """Read literal AST metadata; never call a method, compile or eval source."""
    answer = _empty()
    if type(source) is not str or len(source) > MAX_SOURCE_LENGTH:
        return answer
    try:
        tree = ast.parse(textwrap.dedent(source))
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return answer
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        return answer
    defs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "_getVisualizeDict"]
    if len(defs) != 1 or isinstance(defs[0], ast.AsyncFunctionDef):
        return answer
    fn = defs[0]
    if not fn.args.args or fn.args.args[0].arg != "self":
        return answer
    public = _public_fields(form_schema)
    if not public:
        return answer

    # Recognize direct literal return, or a single dict assigned to a local
    # name and explicitly returned. Do NOT follow aliases or merge/update calls.
    assigned = {}
    returned = None
    dynamic = 0
    for statement in fn.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            name = statement.targets[0].id
            if isinstance(statement.value, ast.Dict):
                assigned[name] = statement.value
            else:
                assigned.pop(name, None)
                dynamic += 1
        elif isinstance(statement, ast.Return):
            if returned is not None:
                return answer
            returned = statement.value
        elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and type(statement.value.value) is str:
            continue  # docstring
        else:
            dynamic += 1
    if isinstance(returned, ast.Dict):
        mapping = returned
    elif isinstance(returned, ast.Name):
        mapping = assigned.get(returned.id)
    else:
        mapping = None
    if mapping is None:
        return answer
    parsed = _mapping_entries(mapping, public)
    if not parsed["actions"]:
        answer["unmatchedActionsOmitted"] = parsed["unmatched"]
        answer["dynamicEntriesSkipped"] = dynamic + parsed["skipped"]
        return answer
    return {
        "status": "static-preview", "source": "static-ast",
        "actions": parsed["actions"],
        "actionsDiscovered": len(parsed["actions"]),
        "unmatchedActionsOmitted": parsed["unmatched"],
        "dynamicEntriesSkipped": dynamic + parsed["skipped"],
        "requiresRuntimeEvaluation": True,
        "executionAllowed": False, "renderable": False,
    }


def _method_source(viewer_class: type):
    # Inherited plugin implementations are common. Stop before the Scipion
    # ProtocolViewer base; never getattr() a plugin-supplied descriptor.
    for base in viewer_class.__mro__:
        if base in (ProtocolViewer, Viewer, object):
            break
        method = vars(base).get("_getVisualizeDict")
        if method is not None:
            return method if inspect.isfunction(method) else None
    return None


def describeProtocolViewerStaticActions(
    candidates: Dict[str, Any], viewer_registry: Mapping[str, Any], *, source_loader=None,
) -> Dict[str, Any]:
    """Attach advisory action previews to registered, form-bearing viewers."""
    if not isinstance(candidates, dict) or not isinstance(candidates.get("viewers"), list):
        raise ProtocolViewerActionsError("invalid_candidates", "Invalid viewer candidates")
    if not isinstance(viewer_registry, Mapping):
        raise ProtocolViewerActionsError("invalid_registry", "Invalid viewer registry")
    registered = {
        _class_identity(value): value for value in viewer_registry.values()
        if isinstance(value, type) and issubclass(value, Viewer)
    }
    # Full validation before producing a result; reject stale or fabricated IDs.
    for candidate in candidates["viewers"]:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str):
            raise ProtocolViewerActionsError("invalid_candidates", "Invalid viewer descriptor")
        if candidate["id"] not in registered:
            raise ProtocolViewerActionsError("unregistered_viewer", "Viewer is not registered")

    result = copy.deepcopy(candidates)
    loader = inspect.getsource if source_loader is None else source_loader
    n_protocol = 0
    n_static = 0
    actions = 0
    for candidate in result["viewers"]:
        viewer_class = registered[candidate["id"]]
        if not issubclass(viewer_class, ProtocolViewer):
            candidate["actionSchema"] = None
            continue
        n_protocol += 1
        preview = _empty()
        method = _method_source(viewer_class)
        if method is not None:
            try:
                source = loader(method)
            except (OSError, TypeError, IOError, ValueError, RuntimeError, UnicodeError):
                source = None
            if type(source) is str:
                preview = parseProtocolViewerStaticActionsSource(source, candidate.get("formSchema"))
        candidate["actionSchema"] = preview
        if preview["status"] == "static-preview":
            n_static += 1
            actions += preview["actionsDiscovered"]
    result["actionSchemaSummary"] = {
        "protocolViewerCount": n_protocol,
        "staticPreviewCount": n_static,
        "actionsDiscovered": actions,
        "executableActionCount": 0,
    }
    result["autoLaunchAllowed"] = False
    result["selectedViewerId"] = None
    return result
