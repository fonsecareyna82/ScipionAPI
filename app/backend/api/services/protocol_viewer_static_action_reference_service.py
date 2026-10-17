"""Conservative, non-executing source evidence about ProtocolViewer action outputs.

A direct ``self.protocol.outputFoo`` AST read is a *hint*, never proof that
an action consumes that persisted output. No routes, imports of plugin paths,
callbacks, scientific data files, database queries or execution permissions are provided here.
"""
from __future__ import annotations

import ast
import copy
import inspect
import re
import textwrap
from collections.abc import Mapping
from typing import Any

from pyworkflow.viewer import ProtocolViewer
from app.backend.api.services.protocol_viewer_action_schema_service import _method_source
from app.backend.api.services.protocol_viewer_web_action_contract_service import _registered_viewers, _public_fields, _preview_actions
from app.backend.api.services.protocol_viewer_capabilities_service import CAPABILITY_KINDS

_MAX_SOURCE = 131072
_MAX_NODES = 8000
_MAX_ACTIONS = 96
_MAX_VIEWERS = 512
_OUTPUT = re.compile(r"output[A-Z0-9_][A-Za-z0-9_]{0,121}\Z")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_HANDLER = re.compile(r"_[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_DYNAMIC_NAMES = frozenset(("getattr", "setattr", "delattr", "eval", "exec", "compile", "vars", "globals", "locals", "__import__"))


class ProtocolViewerStaticReferenceError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _parse_function(source: Any, name: str) -> Any:
    if type(source) is not str or len(source) > _MAX_SOURCE:
        return None
    try:
        tree = ast.parse(textwrap.dedent(source))
        if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
            return None
    except (SyntaxError, ValueError, MemoryError, RecursionError, UnicodeError):
        return None
    definitions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if (len(definitions) != 1 or isinstance(definitions[0], ast.AsyncFunctionDef)
            or not definitions[0].args.args or definitions[0].args.args[0].arg != "self"):
        return None
    return definitions[0]


def _literal_handlers(source: Any) -> Any:
    """Recognize exact, unambiguous literal action -> self.method mappings."""
    fn = _parse_function(source, "_getVisualizeDict")
    if fn is None:
        return None
    assigned = {}
    returned = None
    for statement in fn.body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and type(statement.value.value) is str:
            continue
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name) and isinstance(statement.value, ast.Dict):
            if statement.targets[0].id in assigned:
                return None
            assigned[statement.targets[0].id] = statement.value
        elif isinstance(statement, ast.Return) and returned is None:
            returned = statement.value
        else:
            return None  # Mutation, branch, extra return or dynamic dictionary work.
    node = returned if isinstance(returned, ast.Dict) else assigned.get(returned.id) if isinstance(returned, ast.Name) else None
    if not isinstance(node, ast.Dict) or len(node.keys) > _MAX_ACTIONS:
        return None
    result = {}
    for key, value in zip(node.keys, node.values):
        if (not isinstance(key, ast.Constant) or type(key.value) is not str
                or not _ID.fullmatch(key.value) or key.value in result
                or not isinstance(value, ast.Attribute) or not isinstance(value.value, ast.Name)
                or value.value.id != "self" or not _HANDLER.fullmatch(value.attr)):
            return None
        result[key.value] = value.attr
    return result


def _output_references(source: Any, method_name: str) -> Any:
    fn = _parse_function(source, method_name)
    if fn is None:
        return None
    # Reject AST constructs that defeat this intentionally narrow direct-access
    # interpretation. This is *not* a general Python data-flow analyzer.
    for node in ast.walk(fn):
        if (node is not fn and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef))):
            return None
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.Delete)):
            return None
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _DYNAMIC_NAMES:
                return None
            if isinstance(node.func, ast.Attribute) and node.func.attr in ("__getattribute__", "__getattr__", "__dict__"):
                return None
    found = set()
    called_nodes = {id(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)}
    for node in ast.walk(fn):
        if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                and _OUTPUT.fullmatch(node.attr)
                and isinstance(node.value, ast.Attribute) and node.value.attr == "protocol"
                and isinstance(node.value.value, ast.Name) and node.value.value.id == "self"):
            # An output-named function call is not a Set reference.
            if id(node) in called_nodes:
                continue
            found.add(node.attr)
            if len(found) > _MAX_ACTIONS:
                return None
    return sorted(found)


def parseProtocolViewerActionResourceReferences(visualize_source: Any, handlers: Any, action_id: Any) -> dict:
    """Pure AST helper: ``handlers`` is a server-side method-name -> source map.

    Never reads paths or imports code. In production the wrapper supplies only
    methods already located on the registered viewer class.
    """
    result = {"status": "indeterminate", "source": "static-ast", "actionId": action_id if type(action_id) is str and _ID.fullmatch(action_id) else None,
              "candidateOutputNames": [], "scientificSemanticsVerified": False, "bindingVerified": False,
              "availability": "blocked", "renderable": False, "executionAllowed": False}
    if result["actionId"] is None or not isinstance(handlers, Mapping) or len(handlers) > _MAX_ACTIONS:
        return result
    mapping = _literal_handlers(visualize_source)
    if mapping is None or action_id not in mapping:
        return result
    method = mapping[action_id]
    refs = _output_references(handlers.get(method), method)
    if refs is None:
        return result
    result["candidateOutputNames"] = refs
    result["status"] = "source-reference-observed" if refs else "no-direct-reference-observed"
    return result


def _safe_contract_actions(candidate: Mapping) -> list:
    schema, contracts = candidate.get("actionSchema"), candidate.get("webActionContracts")
    if (not isinstance(schema, dict) or schema.get("status") != "static-preview" or schema.get("source") != "static-ast"
            or schema.get("renderable") is not False or schema.get("executionAllowed") is not False
            or not isinstance(contracts, dict) or contracts.get("status") != "advisory-only"
            or contracts.get("source") != "static-ast" or contracts.get("readyCount") != 0
            or contracts.get("renderable") is not False or contracts.get("executionAllowed") is not False):
        return []
    static = schema.get("actions")
    published = contracts.get("actions")
    if not isinstance(static, list) or not isinstance(published, list) or len(static) > _MAX_ACTIONS or len(published) > _MAX_ACTIONS:
        return []
    if contracts.get("actionCount") != len(published):
        return []
    public = _public_fields(candidate.get("formSchema"))
    vetted = _preview_actions(schema, public)
    if len(vetted) != len(static):
        return []
    static_ids = {}
    for action in static:
        if (not isinstance(action, dict) or type(action.get("id")) is not str or not _ID.fullmatch(action["id"])
                or action["id"] in static_ids or action.get("fieldName") != action["id"]
                or action.get("kind") != "visualize" or action.get("previewOnly") is not True
                or action.get("executionAllowed") is not False or action.get("requiresRuntimeEvaluation") is not True):
            return []
        static_ids[action["id"]] = action
    accepted, seen = [], set()
    for action in published:
        if not isinstance(action, dict):
            return []
        ident = action.get("id")
        original = static_ids.get(ident) if type(ident) is str else None
        if (original is None or ident in seen or action.get("fieldName") != ident
                or (action.get("label"), action.get("control")) != (original.get("label"), original.get("control"))
                or action.get("intent") != "visualize" or action.get("source") != "static-ast"
                or action.get("availability") != "blocked" or action.get("renderable") is not False
                or action.get("executionAllowed") is not False or action.get("requiresRuntimeVerification") is not True
                or action.get("adapterStatus") not in ("missing", "declared-not-integrated")
                or not isinstance(action.get("blockers"), list)
                or "web_action_not_implemented" not in action["blockers"]):
            return []
        if action["adapterStatus"] == "missing":
            if action.get("adapter") is not None or action["blockers"] != ["action_adapter_missing", "runtime_instance_not_verified", "web_action_not_implemented"]:
                return []
        else:
            adapter = action.get("adapter")
            if (not isinstance(adapter, dict) or set(adapter) != {"id", "kind", "effect", "surface", "status"}
                    or type(adapter["id"]) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,127}", adapter["id"])
                    or type(adapter["kind"]) is not str or adapter["kind"] not in CAPABILITY_KINDS
                    or adapter["effect"] not in ("read-only", "derived-read")
                    or adapter["surface"] not in ("react", "external")
                    or adapter["status"] != "declared-not-integrated"
                    or action["blockers"] != ["action_adapter_not_integrated", "runtime_instance_not_verified", "web_action_not_implemented"]):
                return []
        seen.add(ident)
        accepted.append(ident)
    return accepted


def describeProtocolViewerStaticResourceReferences(candidates: Any, viewer_registry: Any, *, source_loader=None) -> dict:
    """Annotate already-discovered registered viewers with advisory AST hints.

    Caller must complete permission checks before exposing discovery responses.
    No Scipion runtime protocol is reconstructed and no scientific data file is opened.
    """
    if (not isinstance(candidates, dict) or not isinstance(candidates.get("viewers"), list)
            or len(candidates["viewers"]) > _MAX_VIEWERS):
        raise ProtocolViewerStaticReferenceError("invalid_candidates")
    try:
        registry = _registered_viewers(viewer_registry)
    except (TypeError, ValueError):
        raise ProtocolViewerStaticReferenceError("invalid_registry") from None
    for candidate in candidates["viewers"]:
        if (not isinstance(candidate, dict) or type(candidate.get("id")) is not str
                or candidate["id"] not in registry):
            raise ProtocolViewerStaticReferenceError("unregistered_viewer")
    loader = inspect.getsource if source_loader is None else source_loader
    if not callable(loader):
        raise ProtocolViewerStaticReferenceError("invalid_source_loader")
    result = copy.deepcopy(candidates)
    for item in result["viewers"]:
        viewer_class = registry[item["id"]]
        actions = _safe_contract_actions(item) if issubclass(viewer_class, ProtocolViewer) else []
        method = _method_source(viewer_class) if actions else None
        mapping = None
        try:
            source = loader(method) if method is not None else None
            mapping = _literal_handlers(source)
        except (OSError, TypeError, IOError, ValueError, RuntimeError, UnicodeError):
            mapping = None
        reports = []
        for ident in actions:
            hints = None
            if mapping is not None and ident in mapping:
                handler_name = mapping[ident]
                # vars() inspects class dictionaries; getattr() would execute descriptors.
                for base in viewer_class.__mro__:
                    if base in (ProtocolViewer, object):
                        break
                    candidate_method = vars(base).get(handler_name)
                    if candidate_method is not None:
                        if inspect.isfunction(candidate_method):
                            try:
                                hints = _output_references(loader(candidate_method), handler_name)
                            except (OSError, TypeError, IOError, ValueError, RuntimeError, UnicodeError):
                                pass
                        break
            status = "indeterminate" if hints is None else "source-reference-observed" if hints else "no-direct-reference-observed"
            reports.append({"actionId": ident, "status": status, "source": "static-ast",
                            "candidateOutputNames": hints if hints is not None else [],
                            "scientificSemanticsVerified": False, "bindingVerified": False,
                            "availability": "blocked", "renderable": False, "executionAllowed": False})
        item["staticResourceReferences"] = {"status": "advisory-only", "source": "static-ast", "actions": reports,
                                             "actionCount": len(reports), "verifiedBindings": 0,
                                             "renderable": False, "executionAllowed": False}
    result["autoLaunchAllowed"] = False
    return result
