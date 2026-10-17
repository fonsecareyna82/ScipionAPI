"""RED 149: inert, bounded conditional viewer definitions for browser-local inputs.

A conditionally hidden field remains absent from the initial visible sections;
its safe definition/rule is retained in a separate bounded sidecar. Explicit
hidden=True, inherited fields and executable/unsupported conditions never leak.
"""
from __future__ import annotations

import copy
import importlib
import inspect
import json
from types import SimpleNamespace

import pytest


def worker():
    return importlib.import_module('app.backend.api.services.protocol_viewer_dynamic_form_worker')


def parent():
    return importlib.import_module('app.backend.api.services.protocol_viewer_dynamic_form_service')


def rules():
    return importlib.import_module('app.backend.api.services.protocol_viewer_condition_contract_service')


class Holder:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class StringParam:
    def __init__(self, label='Field', default='', condition=None, hidden=None, help='', **kwargs):
        self.label, self.default = Holder(label), Holder(default)
        self.condition, self.help = Holder(condition), Holder(help)
        # Like real Scipion Param: intentionally discards hidden keyword.


class LabelParam(StringParam):
    pass


class EnumParam(StringParam):
    def __init__(self, choices=('last', 'selection'), **kwargs):
        super().__init__(**kwargs)
        self.choices = list(choices)


class ElementGroup:
    def __init__(self):
        self.entries = []

    def addParam(self, name, cls, **kwargs):
        result = cls(**kwargs)
        self.entries.append((name, result))
        return result

    def iterParams(self):
        return iter(self.entries)


class Group(ElementGroup):
    def __init__(self, label):
        super().__init__()
        self.label = Holder(label)


class Section(ElementGroup):
    def __init__(self, label):
        super().__init__()
        self.label = Holder(label)


@pytest.fixture(autouse=True)
def group_class(monkeypatch):
    # The serializer uses isinstance(param, pyworkflow.protocol.params.Group).
    # Override only this symbol during the test without initializing Scipion.
    import sys
    from types import ModuleType
    names = ['pyworkflow', 'pyworkflow.protocol', 'pyworkflow.protocol.params']
    for name in names:
        if name not in sys.modules:
            module = ModuleType(name)
            module.__path__ = []
            monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(sys.modules[names[-1]], 'Group', Group, raising=False)


def spec(name, cls=StringParam, **kwargs):
    return name, cls, {'label': name, **kwargs}


def fixture_form(*entries, section_name='Visualization', group_name=None):
    section = Section(section_name)
    target = section
    if group_name:
        target = Group(group_name)
        section.entries.append(('group', target))
    with worker().captureViewerHiddenDeclarations(ElementGroup) as provenance:
        for name, cls, kwargs in entries:
            target.addParam(name, cls, **kwargs)
    return SimpleNamespace(_sectionList=[section],
                           _paramsDict={name: param for name, param in target.entries}), provenance


def initial_fields(schema):
    return [field for section in schema['sections']
            for field in section['fields'] + [field for group in section['groups']
                                               for field in group['fields']]]


def build(*entries, group_name=None, values=None, inherited=None):
    form, provenance = fixture_form(*entries, group_name=group_name)
    return worker().serializeRuntimeViewerDefinition(
        form, hidden_declarations=provenance,
        inherited_field_names=inherited, condition_values=values)


MODE = spec('doShowLastLevel', EnumParam, default=0)
LEVELS = spec('showSeveralLevels', StringParam, default='', condition='doShowLastLevel == 1')
REQUEST = {'projectId': 7, 'protocolId': 12, 'viewerId': 'xmipp3.viewers.XmippCL2DViewer'}


def reply(schema):
    return {'ok': True, 'status': 'runtime-preview', 'source': 'isolated-worker',
            **REQUEST, 'protocolId': str(REQUEST['protocolId']),
            'webReady': False, 'renderable': False, 'executionAllowed': False,
            **schema}


def validate(schema):
    return parent()._validated_reply(reply(schema), REQUEST)


def reject(payload):
    with pytest.raises(parent().DynamicProtocolViewerFormError) as exc:
        parent()._validated_reply(payload, REQUEST)
    assert exc.value.code == 'invalid_worker_schema'


def cl2d():
    return build(MODE, LEVELS,
                 spec('classesToShow', EnumParam, default=0,
                      choices=['classes', 'cores', 'stable cores']),
                 spec('showConvergence', LabelParam),
                 spec('showClassHierarchy', LabelParam, hidden=True))


def test_initial_visible_form_unchanged_and_deferred_levels_available():
    schema = cl2d()
    assert [field['name'] for field in initial_fields(schema)] == [
        'doShowLastLevel', 'classesToShow', 'showConvergence']
    assert schema['fieldsDiscovered'] == 3
    assert len(schema['conditionalFields']) == 1
    deferred = schema['conditionalFields'][0]
    assert deferred['field']['name'] == 'showSeveralLevels'
    assert deferred['field']['visibility'] == 'conditional-hidden'
    assert deferred['field']['visible'] is False
    assert deferred['field']['readOnly'] is True
    assert deferred['field']['executionAllowed'] is False
    assert deferred['rule'] == {
        'op': 'eq', 'left': {'op': 'field', 'name': 'doShowLastLevel'},
        'right': {'op': 'const', 'value': 1}}
    assert 'showClassHierarchy' not in json.dumps(schema)


def test_wire_parent_preserves_deferred_rule_without_promoting_into_visible_fields():
    out = validate(cl2d())
    assert out['conditionalFields'][0]['field']['visible'] is False
    assert out['fieldsDiscovered'] == 3
    assert len(initial_fields(out)) == 3
    assert out['executionAllowed'] is False


def test_local_values_support_conditional_reveal_without_worker_reexecution():
    initial = build(MODE, LEVELS, values={'doShowLastLevel': 0})
    changed = build(MODE, LEVELS, values={'doShowLastLevel': 1})
    assert [f['name'] for f in initial_fields(initial)] == ['doShowLastLevel']
    assert [f['name'] for f in initial_fields(changed)] == ['doShowLastLevel', 'showSeveralLevels']
    assert changed['conditionalFields'][0]['field']['conditionState'] == 'met'


def test_visible_conditional_has_identical_rule_sidecar_field():
    schema = build(MODE, LEVELS, values={'doShowLastLevel': 1})
    descriptor = schema['conditionalFields'][0]
    assert descriptor['field'] == initial_fields(schema)[1]
    assert descriptor['field']['visibility'] == 'visible'
    assert validate(schema)['conditionalFields'][0]['field']['name'] == 'showSeveralLevels'


def test_group_path_is_retained_for_dynamic_insertion():
    schema = build(MODE, LEVELS, group_name='Analysis')
    deferred = schema['conditionalFields'][0]
    assert deferred['section'] == 'Visualization'
    assert deferred['group'] == 'Analysis'
    validate(schema)


def test_conditional_only_section_survives_in_sidecar():
    schema = build(LEVELS, values={'doShowLastLevel': 0})
    assert schema['sections'] == []
    # The referenced selector is not part of the viewer; do not leak it.
    assert 'conditionalFields' not in schema




def test_unverified_hidden_provenance_is_not_advertised_as_reactive():
    form, _ = fixture_form(MODE, LEVELS)
    schema = worker().serializeRuntimeViewerDefinition(form)
    assert 'conditionalFields' not in schema
    assert [item['name'] for item in initial_fields(schema)] == ['doShowLastLevel']

def test_hidden_true_precedes_condition_and_is_not_in_sidecar():
    schema = build(MODE, spec('private', default='SENSITIVE', hidden=True,
                              condition='doShowLastLevel == 1'))
    assert 'private' not in json.dumps(schema)
    assert 'SENSITIVE' not in json.dumps(schema)
    assert 'conditionalFields' not in schema


def test_inherited_condition_dependency_is_not_exported():
    schema = build(spec('runMode', EnumParam, default=0),
                   spec('extra', condition='runMode == 1'), inherited={'runMode'})
    assert 'conditionalFields' not in schema


def test_unsupported_python_condition_has_no_local_rule_or_actions():
    expression = '__import__("os").system("echo BAD")'
    schema = build(spec('thing', condition=expression))
    assert schema['sections'][0]['fields'][0]['visibility'] == 'pending'
    assert expression not in json.dumps(schema)
    assert 'conditionalFields' not in schema


def test_constant_false_hidden_does_not_get_deferred_descriptor():
    schema = build(spec('private', default='PRIVATE', condition='False'))
    assert not initial_fields(schema)
    assert 'conditionalFields' not in schema
    assert 'PRIVATE' not in json.dumps(schema)


def test_rule_parser_supports_boolean_not_and_order_without_execution():
    rule = rules().compileViewerConditionRule('not (mode == 0 or score < 2) and enabled == True')
    assert rule['op'] == 'and'
    assert rules().validViewerConditionRule(rule)
    assert rules().referencedViewerFields(rule) == frozenset({'mode', 'score', 'enabled'})


@pytest.mark.parametrize('expression', [
    'danger()', 'protocol.secret', 'items[0]', '[v for v in x]',
    '(lambda:1)()', 'a + 1', 'a ** 2', 'f"{secret}"',
    'a == b == c', '1 is 1', 'x := 1',
])
def test_rule_parser_rejects_unsafe_or_unsupported_syntax(expression):
    assert rules().compileViewerConditionRule(expression) is None


def test_rule_limits_bound_literals_and_nodes():
    assert rules().compileViewerConditionRule('"' + 'X' * 257 + '"') is None
    assert rules().compileViewerConditionRule('a == 1 ' + ' and a == 1' * 40) is None


@pytest.mark.parametrize('rule', [
    {'op':'field','name':'danger','execute':True},
    {'op':'import','name':'os'},
    {'op':'and','args':[]},
    {'op':'eq','left':{'op':'const','value':1}},
    {'op':'field','name':'some[0]'},
    {'op':'const','value':[1,2]},
    {'op':'const','value':float('nan')},
])
def test_rule_wire_validator_is_strict(rule):
    assert not rules().validViewerConditionRule(rule)


def test_parent_rejects_sidecar_with_extra_execution_property():
    payload = reply(cl2d())
    payload['conditionalFields'][0]['field']['launch'] = 'bad'
    reject(payload)


def test_parent_rejects_sidecar_with_changed_identity_and_location():
    payload = reply(build(MODE, LEVELS, values={'doShowLastLevel': 1}))
    payload['conditionalFields'][0]['section'] = 'Other'
    reject(payload)


def test_parent_rejects_hidden_field_if_declared_executable():
    payload = reply(cl2d())
    payload['conditionalFields'][0]['field']['executionAllowed'] = True
    reject(payload)


def test_parent_rejects_forged_hidden_field_in_initial_visible_sections():
    payload = reply(cl2d())
    payload['sections'][0]['fields'].append(payload['conditionalFields'][0]['field'])
    reject(payload)


def test_parent_rejects_bogus_duplicate_sidecars():
    payload = reply(cl2d())
    payload['conditionalFields'].append(copy.deepcopy(payload['conditionalFields'][0]))
    reject(payload)


def test_parent_rejects_rules_with_unknown_references():
    payload = reply(cl2d())
    payload['conditionalFields'][0]['rule']['left']['name'] = 'secretField'
    reject(payload)


def test_parent_rejects_unbounded_sidecar_and_empty_sidecar():
    payload = reply(cl2d())
    payload['conditionalFields'] = []
    reject(payload)
    payload['conditionalFields'] = [copy.deepcopy(cl2d()['conditionalFields'][0]) for _ in range(97)]
    reject(payload)


def test_parent_rejects_legacy_field_disguised_as_deferred_hidden():
    payload = reply(cl2d())
    field = payload['conditionalFields'][0]['field']
    for key in ('visibility', 'visible', 'hiddenAttributeAvailable', 'conditionState'):
        field.pop(key)
    reject(payload)


def test_parent_legacy_reply_without_conditional_sidecar_stays_compatible():
    schema = build(MODE)
    assert 'conditionalFields' not in validate(schema)


def test_no_plugin_action_calls_or_python_eval_in_rule_module():
    code = inspect.getsource(rules())
    assert 'eval(' not in code
    assert 'exec(' not in code
    assert 'getVisualizeDict' not in code
