"""RED 141: explicit visibility provenance for trusted runtime viewer previews.

No project loading, plugin action execution, environment changes or network.
"""
from types import SimpleNamespace
import importlib
import inspect


def worker():
    return importlib.import_module(
        'app.backend.api.services.protocol_viewer_dynamic_form_worker')


class Holder:
    def __init__(self, value):
        self.value = value
    def get(self):
        return self.value


_NO_HIDDEN = object()


class StringParam:
    def __init__(self, label, default='', condition=None, hidden=_NO_HIDDEN, help_text=''):
        self.label = Holder(label)
        self.default = Holder(default)
        self.condition = Holder(condition)
        self.help = Holder(help_text)
        if hidden is not _NO_HIDDEN:
            self.hidden = hidden


class EnumParam(StringParam):
    def __init__(self, label, default=0, choices=('last', 'selection'), **kwargs):
        super().__init__(label, default, **kwargs)
        self.choices = list(choices)


class LabelParam(StringParam):
    pass


class Section:
    def __init__(self, label, entries):
        self.label = Holder(label)
        self.entries = list(entries)
    def iterParams(self):
        return iter(self.entries)


def group(label, fields):
    from pyworkflow.protocol.params import Group
    class FakeGroup(Group):
        def __init__(self):
            self.label = Holder(label)
        def iterParams(self):
            return iter(fields)
    return FakeGroup()


def form(*sections):
    registry = {}
    for section in sections:
        for name, param in section.entries:
            registry[name] = param
            if hasattr(param, 'iterParams'):
                for child_name, child in param.iterParams():
                    registry[child_name] = child
    return SimpleNamespace(_sectionList=list(sections), _paramsDict=registry)


def describe(*entries, inherited=None, values=None):
    f = form(Section('Visualization', entries))
    return worker().serializeRuntimeViewerDefinition(
        f, inherited_field_names=inherited, condition_values=values)


def fields(result):
    all_fields = []
    for section in result['sections']:
        all_fields.extend(section['fields'])
        for g in section['groups']:
            all_fields.extend(g['fields'])
    return all_fields


def one(name='mode', param=None):
    result = describe((name, param or EnumParam('Mode')))
    return fields(result)[0]


def test_no_condition_yields_resolved_visible_read_only():
    field = one()
    assert field['visibility'] == 'visible'
    assert field['visible'] is True
    assert field['pending'] is False
    assert field['readOnly'] is True
    assert field['executionAllowed'] is False


def test_unconditional_field_never_fabricates_hidden_attribute():
    field = one(param=StringParam('Plain'))
    assert field['hiddenAttributeAvailable'] is False
    assert field['hidden'] is None


def test_explicit_false_hidden_is_verifiably_false():
    field = one(param=StringParam('Visible', hidden=False))
    assert field['hiddenAttributeAvailable'] is True
    assert field['hidden'] is False
    assert field['visibility'] == 'visible'


def test_known_true_condition_is_marked_met_not_pending():
    result = describe(('mode', EnumParam('Mode', default=1)),
                      ('levels', StringParam('Levels', condition='mode==1')))
    field = fields(result)[1]
    assert field['conditionState'] == 'met'
    assert field['visibility'] == 'visible'
    assert field['visible'] is True
    assert field['pending'] is False
    assert field['hasCondition'] is False


def test_default_false_condition_is_not_exposed():
    result = describe(('mode', EnumParam('Mode', default=0)),
                      ('levels', StringParam('Levels', condition='mode==1')))
    assert [field['name'] for field in fields(result)] == ['mode']
    assert result['omittedFields'] == 1


def test_unknown_field_condition_marks_visibility_pending():
    result = describe(('levels', StringParam('Levels', condition='outside==1')))
    field = fields(result)[0]
    assert field['conditionState'] == 'unresolved'
    assert field['visibility'] == 'pending'
    assert field['visible'] is None
    assert field['pending'] is True
    assert field['hasCondition'] is True


def test_unsupported_python_condition_is_pending_without_execution():
    field = one(param=StringParam('Unknown', condition='dangerous()'))
    assert field['visibility'] == 'pending'
    assert field['conditionState'] == 'unresolved'
    assert field['executionAllowed'] is False


def test_missing_condition_remains_unconditional():
    field = one(param=StringParam('Plain', condition=None))
    assert field['conditionState'] == 'none'
    assert field['hasCondition'] is False
    assert field['visibility'] == 'visible'


def test_literal_true_condition_is_marked_met():
    field = one(param=StringParam('Enabled', condition='True'))
    assert field['conditionState'] == 'met'
    assert field['visibility'] == 'visible'


def test_literal_false_condition_is_omitted():
    result = describe(('hidden', StringParam('Hidden', condition='False')))
    assert fields(result) == []
    assert result['omittedFields'] == 1


def test_explicit_true_hidden_remains_omitted_and_never_leaks_secret():
    result = describe(('private', StringParam('Private', default='SECRET', hidden=True)),
                      ('safe', LabelParam('Safe')))
    assert [x['name'] for x in fields(result)] == ['safe']
    assert 'SECRET' not in repr(result)


def test_invalid_hidden_marker_is_omitted_conservatively():
    result = describe(('private', StringParam('Private', hidden='unknown')),
                      ('public', StringParam('Public')))
    assert [x['name'] for x in fields(result)] == ['public']
    assert result['omittedFields'] == 1


def test_boolean_holders_on_explicit_hidden_do_not_allow_implicit_execution():
    result = describe(('private', StringParam('Private', hidden=Holder(False))))
    assert fields(result) == []
    assert result['omittedFields'] == 1


def test_unpreserved_plugin_kwarg_is_not_misreported_as_verified_hidden():
    # pyworkflow Param may discard hidden=not protocol.flag entirely.
    param = LabelParam('Class hierarchy')
    assert 'hidden' not in vars(param)
    field = one(param=param)
    assert field['hiddenAttributeAvailable'] is False
    assert field['hidden'] is None
    assert field['readOnly'] is True


def test_group_field_has_the_same_visibility_metadata():
    result = describe(('analysis', group('Analysis', [
        ('opt', EnumParam('Option', default=0)),
        ('unknown', StringParam('Conditional', condition='missing==3')),
    ])))
    assert [x['visibility'] for x in fields(result)] == ['visible', 'pending']
    assert all(x['readOnly'] is True for x in fields(result))


def test_explicit_inputs_can_resolve_a_pending_condition():
    result = describe(('mode', EnumParam('Mode', default=0)),
                      ('levels', StringParam('Levels', condition='mode==1')),
                      values={'mode': 1})
    assert [x['name'] for x in fields(result)] == ['mode', 'levels']
    assert fields(result)[1]['conditionState'] == 'met'


def test_inherited_fields_are_not_exposed_or_counted():
    result = describe(('runName', StringParam('Run name')),
                      ('view', LabelParam('View')),
                      inherited={'runName'})
    assert [x['name'] for x in fields(result)] == ['view']
    assert result['fieldsDiscovered'] == 1
    assert result['omittedFields'] == 0


def test_top_level_wire_contract_remains_backward_compatible():
    result = describe(('x', StringParam('X')))
    assert set(result) == {'sections', 'fieldsDiscovered', 'omittedFields'}


def test_all_controls_are_inert_even_when_eligible_for_presentation():
    result = describe(('sel', EnumParam('Select')),
                      ('text', StringParam('Text')),
                      ('act', LabelParam('Action')))
    assert len(fields(result)) == 3
    assert all(f['readOnly'] is True and f['executionAllowed'] is False for f in fields(result))
    assert all(f['visibility'] == 'visible' for f in fields(result))


def test_ast_interpreter_is_still_the_only_condition_evaluator():
    source = inspect.getsource(worker().serializeRuntimeViewerDefinition)
    assert '_safe_condition(condition, values)' in source
    assert 'eval(' not in source
    assert 'exec(' not in source


def test_condition_metadata_does_not_leak_its_expression_or_plugin_code():
    result = describe(('x', StringParam('X', condition='dangerous()')))
    assert 'dangerous()' not in repr(result)
    assert fields(result)[0]['conditionState'] == 'unresolved'


def test_runtime_schema_carries_no_launch_permissions():
    result = describe(('show', LabelParam('Show')))
    assert fields(result)[0]['executionAllowed'] is False
    assert fields(result)[0]['readOnly'] is True
    assert 'actionSchema' not in result
