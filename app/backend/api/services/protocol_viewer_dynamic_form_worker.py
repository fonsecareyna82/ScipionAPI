"""One-shot trusted Scipion viewer form worker. Never started by inventory reads.

Subprocess separation protects the API event loop from crashes/timeouts, not
against malicious plugin code with the server's filesystem/database privileges.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager

from app.backend.api.services.protocol_viewer_condition_contract_service import (
    compileViewerConditionRule, referencedViewerFields,
)
import json
import os
import sys

_MAX_REQUEST = 4096
_MAX_REPLY = 200000
_CONTROL_TYPES = {
    'StringParam': 'text', 'TextParam': 'multiline', 'PathParam': 'text',
    'IntParam': 'integer', 'FloatParam': 'number', 'BooleanParam': 'boolean',
    'EnumParam': 'select', 'NumericRangeParam': 'numeric-range',
    'LabelParam': 'label',
}


def _value(holder):
    if holder is None:
        return None
    value = holder.get() if callable(getattr(holder, 'get', None)) else holder
    if value is None or type(value) in (bool, int, float):
        return value
    return value if type(value) is str and len(value) <= 2048 else None



# Only scalar defaults belonging to the form may participate in visibility
# predicates. Never evaluate Python from a plugin string.
_UNKNOWN_CONDITION = object()


def _safe_condition(expression, values):
    """Three-state, bounded AST interpretation: True, False or None (unknown).

    Accepted: scalar literals, known scalar field names, boolean conjunctions,
    'not', and scalar equality/order comparisons. No eval, calls, attributes,
    subscripts, arithmetic, comprehension, or imported names.
    """
    if type(expression) is not str or not 0 < len(expression) <= 256:
        return None
    if not isinstance(values, dict) or len(values) > 128:
        return None
    try:
        root = ast.parse(expression, mode='eval')
    except (SyntaxError, ValueError, RecursionError):
        return None
    if len(list(ast.walk(root))) > 40:
        return None

    def read(node, depth=0):
        if depth > 12:
            return _UNKNOWN_CONDITION
        if isinstance(node, ast.Constant):
            if node.value is None or type(node.value) in (str, bool, int, float):
                return node.value if type(node.value) is not str or len(node.value) <= 256 else _UNKNOWN_CONDITION
            return _UNKNOWN_CONDITION
        if isinstance(node, ast.Name):
            value = values.get(node.id, _UNKNOWN_CONDITION)
            return value if value is None or type(value) in (str, bool, int, float) else _UNKNOWN_CONDITION
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            item = read(node.operand, depth + 1)
            return not item if type(item) is bool else _UNKNOWN_CONDITION
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            parts = [read(v, depth + 1) for v in node.values]
            if isinstance(node.op, ast.And):
                if False in [v for v in parts if type(v) is bool]:
                    return False
                return True if parts and all(v is True for v in parts) else _UNKNOWN_CONDITION
            if True in [v for v in parts if type(v) is bool]:
                return True
            return False if parts and all(v is False for v in parts) else _UNKNOWN_CONDITION
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            op = node.ops[0]
            left = read(node.left, depth + 1)
            right = read(node.comparators[0], depth + 1)
            if left is _UNKNOWN_CONDITION or right is _UNKNOWN_CONDITION:
                return _UNKNOWN_CONDITION
            if isinstance(op, (ast.Eq, ast.NotEq)):
                equal = type(left) is type(right) and left == right
                return equal if isinstance(op, ast.Eq) else not equal
            if isinstance(op, (ast.Is, ast.IsNot)):
                if left is None or right is None:
                    same = left is right
                    return same if isinstance(op, ast.Is) else not same
                return _UNKNOWN_CONDITION
            if (type(left) not in (int, float, str) or type(right) not in (int, float, str)
                    or (type(left) is str) != (type(right) is str)):
                return _UNKNOWN_CONDITION
            if isinstance(op, ast.Lt): return left < right
            if isinstance(op, ast.LtE): return left <= right
            if isinstance(op, ast.Gt): return left > right
            if isinstance(op, ast.GtE): return left >= right
        return _UNKNOWN_CONDITION

    result = read(root.body)
    return result if type(result) is bool else None


def capturePreViewerParameterNames(form):
    """Snapshot pre-existing Scipion fields before viewer.setProtocol().

    The actual Form keeps its globally registered parameters in _paramsDict.
    Capturing names rather than filtering section labels preserves any actual
    viewer additions to a section named 'General'.
    """
    params = getattr(form, '_paramsDict', None)
    if not isinstance(params, dict):
        raise ValueError('viewer_form_registry_unavailable')
    return frozenset(name for name in params if type(name) is str)


def _form_condition_values(form):
    """Scalars from the initial definition only; never execute plugin handlers."""
    params = getattr(form, '_paramsDict', None)
    if not isinstance(params, dict):
        return {}
    result = {}
    for name, param in list(params.items())[:128]:
        if type(name) is str and name.isidentifier() and len(name) <= 128:
            default = _value(getattr(param, 'default', None))
            if default is None or type(default) in (str, bool, int, float):
                result[name] = default
    return result



@contextmanager
def captureViewerHiddenDeclarations(element_group_cls=None):
    """Observe original addParam(hidden=...) before Scipion discards kwargs.

    Scoped to the trusted, one-shot child process; the original method is
    restored even if a viewer's setProtocol fails. A missing declaration is
    NEVER proof that hidden=False (plugins may bypass ElementGroup.addParam).
    """
    if element_group_cls is None:
        from pyworkflow.protocol.params import ElementGroup
        element_group_cls = ElementGroup
    original = element_group_cls.addParam
    declarations = {}

    def tracked(group, param_name, ParamClass, **kwargs):
        # Preserve Scipion's original insertion semantics and exception behavior.
        result = original(group, param_name, ParamClass, **kwargs)
        if type(param_name) is str and param_name.isidentifier() and len(param_name) <= 128:
            # A repeated name is ambiguous: do not trust either declaration.
            if param_name in declarations:
                declarations[param_name] = (None, None)
            else:
                declarations[param_name] = (
                    'hidden' in kwargs, kwargs.get('hidden')
                )
        return result

    element_group_cls.addParam = tracked
    try:
        yield declarations
    finally:
        element_group_cls.addParam = original



def serializeRuntimeViewerDefinition(
        form, *, inherited_field_names=None, condition_values=None,
        hidden_declarations=None) -> dict:
    """Capture a bounded, inert subset of Scipion Form; never call handlers."""
    sections = []
    count = omitted = total = 0
    conditional_fields = []
    # None means backwards-compatible serialization for isolated callers.
    inherited = frozenset() if inherited_field_names is None else frozenset(inherited_field_names)
    values = _form_condition_values(form) if condition_values is None else condition_values
    hidden_missing = object()

    def fields(element, section_label, group_label=None):
        nonlocal count, omitted, total
        output = []
        for name, param in element.iterParams():
            # Scipion boilerplate existed before setProtocol; don't even read
            # its default/help/label, and don't count it as an omitted field.
            if type(name) is str and name in inherited:
                continue
            if type(name) is not str or not name.isidentifier() or len(name) > 128:
                omitted += 1
                continue
            control = _CONTROL_TYPES.get(type(param).__name__)
            if control is None or len(output) >= 96 or total >= 96:
                omitted += 1
                continue
            label = _value(getattr(param, 'label', None))
            if not isinstance(label, str) or not label or len(label) > 160:
                omitted += 1
                continue
            condition = _value(getattr(param, 'condition', None))
            # A real Scipion Form can contain explicit hidden/condition flags.
            # Unknown hidden flags fail closed; no hidden default is serialized.
            # Some Scipion Param implementations discard plugin-provided
            # `hidden=...` kwargs.  Missing does not mean verified False.
            # Report provenance so a frontend never claims it inspected a
            # hidden attribute which is not present on the runtime object.
            hidden_marker = getattr(param, 'hidden', hidden_missing)
            hidden_available = hidden_marker is not hidden_missing
            if hidden_declarations is not None:
                # Dynamic worker path: a field is safe to show only if its
                # actual addParam call was observed. Direct registry injection
                # and custom uninstrumented constructors fail closed.
                if (not isinstance(hidden_declarations, dict) or
                        name not in hidden_declarations):
                    omitted += 1
                    continue
                declaration = hidden_declarations[name]
                if (not isinstance(declaration, tuple) or len(declaration) != 2 or
                        type(declaration[0]) is not bool):
                    omitted += 1
                    continue
                had_hidden, declared_hidden = declaration
                if had_hidden and type(declared_hidden) is not bool:
                    omitted += 1
                    continue
                # Prefer the witnessed constructor argument over an absent
                # Param.hidden attribute. If the object has its own marker,
                # disagreement is not safe; never override explicit hiding.
                if hidden_available and (type(hidden_marker) is not bool or
                                         hidden_marker is True or
                                         (had_hidden and hidden_marker != declared_hidden)):
                    omitted += 1
                    continue
                hidden_marker = declared_hidden if had_hidden else False
                # This means hidden *provenance* is verified, through the
                # observed call, not necessarily through Param.__dict__.
                hidden_available = True
            if hidden_available and (type(hidden_marker) is not bool or hidden_marker):
                omitted += 1
                continue
            if condition == 'False' or not isinstance(condition, (str, type(None))):
                omitted += 1
                continue
            decision = _safe_condition(condition, values) if condition else True
            # A false *declarative* condition may become true in the browser;
            # a real hidden=True declaration is filtered ABOVE this point.
            # Never publish a literal False field or arbitrary Python syntax.
            rule = compileViewerConditionRule(condition) if condition else None
            refs = referencedViewerFields(rule) if rule is not None else None
            locally_reactive = bool(refs) and hidden_available and decision in (True, False, None)
            if decision is False and not locally_reactive:
                omitted += 1
                continue
            # Visibility is an initial snapshot, not a promise that the
            # condition can be re-evaluated in React. `visible=None` is an
            # explicit unresolved state and never authorizes any action.
            pending = decision is None
            field = {
                'name': name, 'label': label, 'control': control,
                'hasCondition': bool(condition) and pending,
                'visibility': ('conditional-hidden' if decision is False else
                               'pending' if pending else 'visible'),
                'visible': False if decision is False else None if pending else True,
                'hidden': False if hidden_available else None,
                'hiddenAttributeAvailable': hidden_available,
                'pending': pending,
                'readOnly': True,
                'executionAllowed': False,
                'conditionState': (
                    'unmet' if decision is False else
                    'unresolved' if pending else
                    'met' if condition else 'none'
                ),
            }
            help_text = _value(getattr(param, 'help', None))
            if type(help_text) is str:
                field['help'] = help_text
            default = _value(getattr(param, 'default', None))
            if default is not None:
                field['default'] = default
            if control == 'select':
                choices = getattr(param, 'choices', ())
                if not isinstance(choices, (list, tuple)) or not 1 <= len(choices) <= 100:
                    omitted += 1
                    continue
                if any(type(v) not in (str, int, float) or
                       (type(v) is str and len(v) > 160) for v in choices):
                    omitted += 1
                    continue
                field['choices'] = list(choices)
            total += 1
            if locally_reactive:
                conditional_fields.append({
                    'section': section_label, 'group': group_label,
                    'field': field, 'rule': rule,
                })
            if decision is False:
                # Retained ONLY in the sidecar, never in the initial UI fields.
                omitted += 1
                continue
            output.append(field)
            count += 1
        return output

    for section in getattr(form, '_sectionList', ()):
        if len(sections) >= 16:
            omitted += 1
            break
        section_label = _value(getattr(section, 'label', None))
        if type(section_label) is not str or not section_label or len(section_label) > 160:
            omitted += 1
            continue
        result = {'label': section_label, 'fields': [], 'groups': []}
        from pyworkflow.protocol.params import Group
        # Build in the actual section order; Group appears in iterParams.
        for name, param in section.iterParams():
            if isinstance(param, Group):
                label = _value(getattr(param, 'label', None))
                if len(result['groups']) >= 20 or not isinstance(label, str) or not label or len(label) > 160:
                    omitted += 1
                    continue
                group_fields = fields(param, section_label, label)
                if group_fields:
                    result['groups'].append({'label': label, 'fields': group_fields})
            else:
                # Single param wrapper; use the same strict serializer.
                class _One:
                    def iterParams(self):
                        yield name, param
                result['fields'].extend(fields(_One(), section_label))
        if result['fields'] or result['groups']:
            sections.append(result)
    result = {'sections': sections, 'fieldsDiscovered': count, 'omittedFields': omitted}
    if conditional_fields:
        # Only conditions referencing a field which was itself safely
        # serialized may be passed to React. Do not expose expressions about
        # inherited, explicitly hidden, or omitted plugin parameters.
        available = {field['name'] for section in sections for field in
                     (section['fields'] + [f for group in section['groups']
                                          for f in group['fields']])}
        deferred = {item['field']['name'] for item in conditional_fields}
        while True:
            permitted = available | deferred
            removed = {item['field']['name'] for item in conditional_fields
                       if not referencedViewerFields(item['rule']) <= permitted}
            if not removed:
                break
            deferred -= removed
            conditional_fields = [item for item in conditional_fields
                                  if item['field']['name'] not in removed]
        if conditional_fields:
            result['conditionalFields'] = conditional_fields
    return result


def _evaluate(request: dict) -> dict:
    from pyworkflow import Config
    from pyworkflow.viewer import ProtocolViewer
    from app.backend.api.services.protocol_viewer_inventory_service import _class_identity
    from app.backend.api.services.project_service import ProjectService
    from app.backend.database import getMapper
    from app.backend.runtime.project_runtime_repository import ProjectRuntimeRepository

    project_id, protocol_id = request['projectId'], request['protocolId']
    viewer_id = request['viewerId']
    mapper = getMapper()
    try:
        row = mapper.getProjectProtocolByProtocolId(projectId=project_id, protocolId=protocol_id)
        if (not isinstance(row, dict) or int(row['id']) != request['protocolDbId']
                or int(row['projectId']) != project_id or int(row['protocolId']) != protocol_id):
            raise ValueError('stale_protocol_identity')
        project_path = ProjectRuntimeRepository().getProjectNameById(mapper, project_id)
        if not project_path:
            raise ValueError('missing_project')
        service = ProjectService()
        project = service._loadPostgresqlRuntimeProject(
            mapper=mapper, projectId=project_id, projectPath=project_path)
        protocol = service._getScipionProtocolByScipionId(protocol_id)
        if protocol is None or protocol.getClassName() != row['protocolClassName']:
            raise ValueError('protocol_class_changed')
        registry = Config.getDomain().getViewers()
        matches = [cls for cls in registry.values()
                   if isinstance(cls, type) and issubclass(cls, ProtocolViewer)
                   and _class_identity(cls) == viewer_id]
        if len(set(matches)) != 1:
            raise ValueError('viewer_not_registered')
        viewer_cls = matches[0]
        if not any(isinstance(t, type) and isinstance(protocol, t)
                   for t in getattr(viewer_cls, '_targets', ())):
            raise ValueError('viewer_target_mismatch')
        # Trusted installed plugin code runs ONLY in this short-lived child.
        viewer = viewer_cls(project=project, protocol=protocol)
        # Capture BEFORE setProtocol: the Form already contains Scipion's
        # generic Run name / Run mode fields, unrelated to the plugin viewer.
        baseline = capturePreViewerParameterNames(viewer._definition)
        # Observe the original hidden keyword before Scipion's FormElement
        # silently drops it.  No plugin code is run in the API parent.
        with captureViewerHiddenDeclarations() as hidden_declarations:
            viewer.setProtocol(protocol)  # calls dynamic _defineParams
        schema = serializeRuntimeViewerDefinition(
            viewer._definition, inherited_field_names=baseline,
            hidden_declarations=hidden_declarations)
        return {'ok': True, 'status': 'runtime-preview', 'source': 'isolated-worker',
                'projectId': project_id, 'protocolId': str(protocol_id), 'viewerId': viewer_id,
                'webReady': False, 'renderable': False, 'executionAllowed': False,
                **schema}
    finally:
        try:
            mapper.db.close()
        except Exception:
            pass


def main() -> int:
    if (os.environ.get('SCIPION_VIEWER_FORM_CHILD') != '1' or
            os.environ.get('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL') != '1'):
        return 2
    # Limit plugin log/file output; this is not a sandbox or a filesystem jail.
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
    except (ImportError, OSError, ValueError):
        pass
    # Worker uses a fixed module, never eval()s request strings.
    raw = sys.stdin.buffer.read(_MAX_REQUEST + 1)
    if len(raw) > _MAX_REQUEST:
        return 2
    try:
        request = json.loads(raw)
        if not isinstance(request, dict) or set(request) != {
            'projectId', 'protocolId', 'protocolDbId', 'viewerId'
        }:
            return 2
        if (any(type(request[k]) is not int or request[k] <= 0 for k in
                ('projectId', 'protocolId', 'protocolDbId'))
                or type(request['viewerId']) is not str or
                len(request['viewerId']) > 255):
            return 2
        result = _evaluate(request)
        wire = json.dumps(result, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
        if len(wire) > _MAX_REPLY:
            return 2
        sys.stdout.buffer.write(b'__SCIPION_VIEWER_FORM_JSON__:' + wire + b'\n')
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        return 1


if __name__ == '__main__':
    sys.exit(main())
