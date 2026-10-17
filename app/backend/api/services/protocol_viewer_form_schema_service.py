"""Conservative, non-executing preview of Scipion ProtocolViewer forms.

Scipion's real _defineParams may depend on protocol state or execute arbitrary
plugin code. This scanner only recognizes a bounded subset of literal AST calls
and *never* offers an executable form or handler. Complex definitions require a
later, reviewed instance-aware adapter. No protocol is reconstructed.
"""
from __future__ import annotations

import ast
import copy
import inspect
import textwrap
from typing import Any, Dict, Mapping, Optional

from pyworkflow.viewer import ProtocolViewer, Viewer

from app.backend.api.services.protocol_viewer_inventory_service import _class_identity


MAX_SOURCE_LENGTH = 131072
MAX_NODES = 8000
MAX_FIELDS = 96
PARAM_CONTROLS = {
    "StringParam": "text", "TextParam": "multiline", "PathParam": "text",
    "IntParam": "integer", "FloatParam": "number", "BooleanParam": "boolean",
    "EnumParam": "select", "NumericRangeParam": "numeric-range",
    "LabelParam": "label",  # May map to a visualizer; NOT an executable action.
}


class ProtocolViewerFormSchemaError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _literal(node: ast.AST, max_length: int = 2048) -> Any:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError, OverflowError):
        return _MISSING
    if value is None or type(value) in (bool, int, float):
        return value
    if type(value) is str and len(value) <= max_length:
        return value
    return _MISSING


_MISSING = object()


def _kw(call: ast.Call, name: str) -> Any:
    for keyword in call.keywords:
        if keyword.arg == name:
            return _literal(keyword.value)
    return _MISSING


def _text(value: Any, max_length: int = 160) -> Optional[str]:
    if type(value) is str and 0 < len(value) <= max_length:
        return value
    return None


def _call_on(node: Any) -> Any:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if not isinstance(node.func.value, ast.Name):
        return None
    return node.func.value.id, node.func.attr


def _form_call_in(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        target = _call_on(node)
        if target and target[1] in ("addSection", "addGroup", "addParam", "addHidden", "addLine", "addBooleanParam"):
            return True
    return False


def _empty_preview(status: str) -> Dict[str, Any]:
    return {
        "status": status, "source": "static-ast", "sections": [],
        "fieldsDiscovered": 0, "hiddenFields": 0, "dynamicDefinitionsSkipped": 0,
        "requiresRuntimeEvaluation": True, "renderable": False,
        "actionExecutionAllowed": False,
    }


def parseProtocolViewerStaticFormSource(source: str) -> Dict[str, Any]:
    """Best-effort literal syntax preview. No eval/exec or Scipion form creation."""
    answer = _empty_preview("unavailable")
    if not isinstance(source, str) or len(source) > MAX_SOURCE_LENGTH:
        return answer
    try:
        tree = ast.parse(textwrap.dedent(source))
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return answer
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        return answer
    definitions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == "_defineParams"]
    if len(definitions) != 1 or isinstance(definitions[0], ast.AsyncFunctionDef):
        return answer
    definition = definitions[0]
    if len(definition.args.args) < 2:
        return answer
    form_arg = definition.args.args[1].arg
    sections = []
    current = None
    group_vars = {}
    seen_fields = set()
    skipped = 0
    hidden = 0
    count = 0
    for statement in definition.body:
        assigned_to = None
        call = None
        if isinstance(statement, ast.Expr):
            call = statement.value
        elif isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            assigned_to = statement.targets[0].id
            call = statement.value
        target = _call_on(call)
        if not target:
            # Unknown plugin code or control flow is never executed or expanded.
            # Count conditional definitions as skipped rather than presenting
            # their fields as unconditional controls.
            if _form_call_in(statement):
                skipped += 1
            if assigned_to:
                group_vars.pop(assigned_to, None)
            continue
        receiver, method = target
        if receiver == form_arg and method == "addSection":
            label = _text(_kw(call, "label"))
            if label is None and call.args:
                label = _text(_literal(call.args[0]))
            if label is None:
                skipped += 1
                current = None
                continue
            current = {"label": label, "fields": [], "groups": []}
            sections.append(current)
            group_vars = {}
            continue
        if receiver == form_arg and method == "addGroup":
            label = _text(_literal(call.args[0])) if call.args else _text(_kw(call, "label"))
            if current is None or label is None:
                skipped += 1
                continue
            group = {"label": label, "fields": []}
            current["groups"].append(group)
            if assigned_to:
                group_vars[assigned_to] = group
            continue
        if method == "addHidden" and (receiver == form_arg or receiver in group_vars):
            hidden += 1
            continue
        if method != "addParam" or (receiver != form_arg and receiver not in group_vars):
            if method in ("addLine", "addBooleanParam", "addParam", "addHidden") or receiver == "self":
                skipped += 1
            continue
        if current is None or len(call.args) < 2 or call.keywords and any(x.arg is None for x in call.keywords):
            skipped += 1
            continue
        name = _text(_literal(call.args[0]), 128)
        param_type = call.args[1]
        if isinstance(param_type, ast.Name):
            type_name = param_type.id
        elif isinstance(param_type, ast.Attribute) and isinstance(param_type.value, ast.Name):
            type_name = param_type.attr
        else:
            type_name = None
        control = PARAM_CONTROLS.get(type_name)
        label = _text(_kw(call, "label"))
        if name is None or control is None or label is None or name in seen_fields:
            skipped += 1
            continue
        field = {"name": name, "label": label, "control": control,
                 "hasCondition": any(k.arg == "condition" for k in call.keywords)}
        help_value = _kw(call, "help")
        if isinstance(help_value, str) and len(help_value) <= 2048:
            field["help"] = help_value
        default = _kw(call, "default")
        if default is not _MISSING:
            field["default"] = default
        elif any(k.arg == "default" for k in call.keywords):
            field["unresolvedDefault"] = True
        if control == "select":
            choices_node = next((k.value for k in call.keywords if k.arg == "choices"), None)
            if choices_node is None:
                skipped += 1
                continue
            try:
                choices = ast.literal_eval(choices_node)
            except (TypeError, ValueError, SyntaxError, MemoryError, RecursionError, OverflowError):
                skipped += 1
                continue
            if (not isinstance(choices, (list, tuple)) or not 1 <= len(choices) <= 100
                    or any(type(v) not in (str, int, float) or
                           (type(v) is str and len(v) > 160) for v in choices)):
                skipped += 1
                continue
            field["choices"] = list(choices)
        seen_fields.add(name)
        target_fields = current["fields"] if receiver == form_arg else group_vars[receiver]["fields"]
        target_fields.append(field)
        count += 1
        if count > MAX_FIELDS:
            return _empty_preview("unavailable")
    if not sections or not count:
        answer["dynamicDefinitionsSkipped"] = skipped
        answer["hiddenFields"] = hidden
        return answer
    return {
        "status": "static-preview", "source": "static-ast", "sections": sections,
        "fieldsDiscovered": count, "hiddenFields": hidden,
        "dynamicDefinitionsSkipped": skipped,
        "requiresRuntimeEvaluation": True, "renderable": False,
        "actionExecutionAllowed": False,
    }


def describeProtocolViewerStaticForms(
    candidates: Dict[str, Any],
    viewer_registry: Mapping[str, Any],
    *,
    source_loader=None,
) -> Dict[str, Any]:
    """Attach advisory AST previews to *registered* ProtocolViewer classes."""
    if not isinstance(candidates, dict) or not isinstance(candidates.get("viewers"), list):
        raise ProtocolViewerFormSchemaError("invalid_candidates", "Invalid viewer candidates")
    if not isinstance(viewer_registry, Mapping):
        raise ProtocolViewerFormSchemaError("invalid_registry", "Invalid viewer registry")
    registered = {
        _class_identity(value): value for value in viewer_registry.values()
        if isinstance(value, type) and issubclass(value, Viewer)
    }
    loader = inspect.getsource if source_loader is None else source_loader
    result = copy.deepcopy(candidates)
    scanned = 0
    previews = 0
    for candidate in result["viewers"]:
        viewer_id = candidate.get("id") if isinstance(candidate, dict) else None
        if not isinstance(viewer_id, str) or viewer_id not in registered:
            raise ProtocolViewerFormSchemaError("unregistered_viewer", "Viewer is not registered")
        viewer_class = registered[viewer_id]
        if not issubclass(viewer_class, ProtocolViewer):
            candidate["formSchema"] = None
            continue
        scanned += 1
        # Read only the concrete class's own function, never an accessor,
        # inherited method, or plugin constructor. Scipion can delegate to
        # helpers, which remain an *unavailable* preview until reviewed.
        method = vars(viewer_class).get("_defineParams")
        preview = _empty_preview("unavailable")
        if inspect.isfunction(method):
            try:
                source = loader(method)
            except (OSError, TypeError, IOError, ValueError, RuntimeError, UnicodeError):
                source = None
            if isinstance(source, str):
                preview = parseProtocolViewerStaticFormSource(source)
        candidate["formSchema"] = preview
        if preview["status"] == "static-preview":
            previews += 1
    result["formSchemaSummary"] = {
        "protocolViewerCount": scanned, "staticPreviewCount": previews,
        "executableFormCount": 0,
    }
    result["autoLaunchAllowed"] = False
    result["selectedViewerId"] = None
    return result
