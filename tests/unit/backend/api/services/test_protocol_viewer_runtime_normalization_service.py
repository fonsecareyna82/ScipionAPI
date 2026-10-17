"""RED 139: viewer-owned form fields and safe runtime condition normalization.

Uses inert Scipion-shaped fakes. Never opens projects or invokes plugin actions.
"""
import importlib
import inspect
from types import SimpleNamespace


def worker():
    return importlib.import_module('app.backend.api.services.protocol_viewer_dynamic_form_worker')


class Holder:
    def __init__(self, value): self.value = value
    def get(self): return self.value


class StringParam:
    def __init__(self, label, default='', condition=None, hidden=False):
        self.label = Holder(label)
        self.default = Holder(default)
        self.condition = Holder(condition)
        self.help = Holder('')
        self.hidden = hidden


class LabelParam(StringParam):
    pass


class EnumParam(StringParam):
    def __init__(self, label, choices=('last', 'selection'), default=0, **kwargs):
        super().__init__(label, default=default, **kwargs)
        self.choices = list(choices)


class Section:
    def __init__(self, label, entries):
        self.label = Holder(label)
        self.entries = list(entries)
    def iterParams(self): return iter(self.entries)


# The fake Group extends pyworkflow.protocol.params.Group to exercise the
# real worker's isinstance(param, Group) traversal.
def group(name, fields):
    from pyworkflow.protocol.params import Group
    class FakeGroup(Group):
        def __init__(self):
            self.label = Holder(name)
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


def schema(f, *, inherited=None, values=None):
    return worker().serializeRuntimeViewerDefinition(
        f, inherited_field_names=inherited,
        condition_values=values)


def visible_fields(result):
    output = []
    for s in result['sections']:
        output += s['fields']
        for g in s['groups']:
            output += g['fields']
    return output


def test_snapshot_records_builtins_before_plugin_additions():
    f = form(Section('General', [('runName', StringParam('Run name'))]))
    before = worker().capturePreViewerParameterNames(f)
    f._paramsDict['visualize'] = LabelParam('Visualize')
    assert before == frozenset({'runName'})


def test_snapshot_is_immutable_after_form_registry_mutates():
    f = form(Section('General', [('runMode', EnumParam('Run mode'))]))
    before = worker().capturePreViewerParameterNames(f)
    f._paramsDict.clear()
    assert before == {'runMode'}


def test_inherited_general_fields_are_excluded_without_counting_as_omitted():
    f = form(Section('General', [
        ('runName', StringParam('Run name')), ('runMode', EnumParam('Run mode'))]),
        Section('Visualization', [('visualize', LabelParam('Visualize'))]))
    result = schema(f, inherited={'runName', 'runMode'})
    assert [x['label'] for x in result['sections']] == ['Visualization']
    assert result['fieldsDiscovered'] == 1 and result['omittedFields'] == 0


def test_new_custom_field_in_general_section_is_preserved():
    f = form(Section('General', [
        ('runName', StringParam('Run name')), ('myAction', LabelParam('My action'))]))
    result = schema(f, inherited={'runName'})
    assert [f['name'] for f in visible_fields(result)] == ['myAction']
    assert result['sections'][0]['label'] == 'General'


def test_empty_scaffold_sections_are_pruned():
    f = form(Section('General', [('runName', StringParam('Run name'))]),
             Section('Other', [('base', StringParam('Base'))]))
    result = schema(f, inherited={'runName', 'base'})
    assert result['sections'] == [] and result['fieldsDiscovered'] == 0


def test_new_group_fields_are_kept_even_if_group_is_in_inherited_section():
    f = form(Section('General', [
        ('runName', StringParam('Run name')),
        ('views', group('Viewer controls', [('newChoice', EnumParam('Select a view'))]))]))
    result = schema(f, inherited={'runName'})
    assert result['sections'][0]['groups'][0]['fields'][0]['name'] == 'newChoice'


def test_empty_inherited_group_is_not_emitted():
    f = form(Section('General', [
        ('baseGroup', group('System group', [('base', StringParam('Base'))]))]),
        Section('Viewer', [('custom', LabelParam('Custom'))]))
    result = schema(f, inherited={'base'})
    assert [s['label'] for s in result['sections']] == ['Viewer']


def test_selection_condition_eq_false_excludes_levels_by_default():
    f = form(Section('Visualization', [
        ('doShowLastLevel', EnumParam('Level to visualize', default=0)),
        ('showSeveralLevels', StringParam('Levels selection',
                                         condition='doShowLastLevel==1'))]))
    result = schema(f)
    assert [field['name'] for field in visible_fields(result)] == ['doShowLastLevel']
    assert result['omittedFields'] == 1


def test_selection_condition_eq_true_restores_levels_when_selected():
    f = form(Section('Visualization', [
        ('doShowLastLevel', EnumParam('Level to visualize', default=1)),
        ('showSeveralLevels', StringParam('Levels selection',
                                         condition='doShowLastLevel==1'))]))
    result = schema(f)
    assert [field['name'] for field in visible_fields(result)] == [
        'doShowLastLevel', 'showSeveralLevels']
    assert visible_fields(result)[1]['hasCondition'] is False


def test_safe_equality_rejects_boolean_integer_coercion():
    assert worker()._safe_condition('flag == 1', {'flag': True}) is False
    assert worker()._safe_condition('flag != 1', {'flag': True}) is True


def test_safe_inequality_and_order_conditions():
    assert worker()._safe_condition('n >= 2', {'n': 3}) is True
    assert worker()._safe_condition('n < 2', {'n': 3}) is False


def test_safe_literal_true_and_false():
    assert worker()._safe_condition('True', {}) is True
    assert worker()._safe_condition('False', {}) is False


def test_safe_none_checks():
    assert worker()._safe_condition('item is None', {'item': None}) is True
    assert worker()._safe_condition('item is not None', {'item': None}) is False


def test_boolean_and_not_are_three_state_conservative():
    safe = worker()._safe_condition
    assert safe('a and not b', {'a': True, 'b': False}) is True
    assert safe('a and not b', {'a': True, 'b': True}) is False
    assert safe('a and missing', {'a': True}) is None
    assert safe('a and missing', {'a': False}) is False
    assert safe('a or missing', {'a': True}) is True


def test_unknown_conditions_are_retained_but_not_marked_evaluated():
    f = form(Section('Visualization', [
        ('mystery', StringParam('Mystery', condition='unknownField == 1'))]))
    result = schema(f)
    assert [x['name'] for x in visible_fields(result)] == ['mystery']
    assert visible_fields(result)[0]['hasCondition'] is True


def test_ast_rejects_calls_attributes_and_indexing():
    safe = worker()._safe_condition
    assert safe('doDangerous()', {}) is None
    assert safe('self.protocol.computeHierarchy', {}) is None
    assert safe('values[0] == 1', {'values': [1]}) is None
    assert safe('__import__("os").system("touch /tmp/unsafe")', {}) is None


def test_unknown_condition_does_not_leak_default_of_explicit_hidden():
    f = form(Section('Visualization', [
        ('private', StringParam('Private', default='SECRET', hidden=True,
                                condition='unknownField == 1')),
        ('known', LabelParam('Known'))]))
    result = schema(f)
    assert [x['name'] for x in visible_fields(result)] == ['known']
    assert 'SECRET' not in str(result)


def test_runtime_fields_remain_inert_and_never_web_executable():
    f = form(Section('Visualization', [('view', EnumParam('View'))]))
    result = schema(f)
    assert 'action' not in str(result).lower()
    assert set(result) == {'sections', 'fieldsDiscovered', 'omittedFields'}


def test_oversized_or_malformed_conditions_fail_closed_without_crashing():
    safe = worker()._safe_condition
    assert safe('(' * 50, {}) is None
    assert safe('a' * 400 + ' == 1', {'a': 1}) is None
    assert safe('[x for x in range(100)]', {}) is None


def test_runtime_capture_occurs_before_set_protocol_in_worker():
    source = inspect.getsource(worker().loadRuntimeViewer)
    assert source.index('baseline = capturePreViewerParameterNames(') < source.index('viewer.setProtocol(protocol)')
    assert 'inherited_field_names=context.baseline' in inspect.getsource(worker()._evaluate)
