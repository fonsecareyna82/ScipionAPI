"""RED 147: preserve truth of viewer hidden declarations across Scipion Param construction.

Also verify that local condition-value overrides can be interpreted without
executing plugin expressions. No project, DB, viewer actions or HTTP involved.
"""
import importlib
import inspect

import pytest


def worker():
    return importlib.import_module(
        'app.backend.api.services.protocol_viewer_dynamic_form_worker')


class Holder:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class StringParam:
    """Like Scipion Param, intentionally discards hidden= keyword."""
    def __init__(self, label='Value', default='', condition=None, hidden=None, **kwargs):
        self.label = Holder(label)
        self.default = Holder(default)
        self.condition = Holder(condition)
        self.help = Holder('')


class LabelParam(StringParam):
    pass


class EnumParam(StringParam):
    def __init__(self, choices=('last', 'selection'), **kwargs):
        super().__init__(**kwargs)
        self.choices = list(choices)


class ElementGroup:
    def __init__(self):
        self.entries = []

    def addParam(self, name, ParamClass, **kwargs):
        param = ParamClass(**kwargs)
        self.entries.append((name, param))
        return param


class Section:
    label = Holder('Visualization')

    def __init__(self, entries):
        self.entries = entries

    def iterParams(self):
        return iter(self.entries)


def form(group):
    from types import SimpleNamespace
    return SimpleNamespace(_sectionList=[Section(group.entries)],
                           _paramsDict=dict(group.entries))


def flat(result):
    return [field for section in result['sections'] for field in section['fields']]


def capture_and_serialize(*entries, values=None):
    group = ElementGroup()
    with worker().captureViewerHiddenDeclarations(ElementGroup) as evidence:
        for name, cls, kwargs in entries:
            group.addParam(name, cls, **kwargs)
    return worker().serializeRuntimeViewerDefinition(
        form(group), hidden_declarations=evidence, condition_values=values)


def entry(name, cls=StringParam, **kwargs):
    return name, cls, {'label': name, **kwargs}


def test_capture_original_hidden_true_despite_param_discarding_it():
    result = capture_and_serialize(entry('hierarchy', LabelParam, hidden=True))
    assert flat(result) == []
    assert result['omittedFields'] == 1


def test_capture_false_is_verified_even_without_param_attribute():
    result = capture_and_serialize(entry('hierarchy', LabelParam, hidden=False))
    field = flat(result)[0]
    assert field['hidden'] is False
    assert field['hiddenAttributeAvailable'] is True
    assert field['visibility'] == 'visible'
    assert field['executionAllowed'] is False


def test_observed_addparam_without_hidden_is_proof_no_hidden_keyword_was_sent():
    field = flat(capture_and_serialize(entry('mode', EnumParam, default=0)))[0]
    assert field['hiddenAttributeAvailable'] is True
    assert field['hidden'] is False
    assert field['readOnly'] is True


def test_true_hidden_does_not_leak_sensitive_values():
    result = capture_and_serialize(entry('secret', hidden=True, default='SENSITIVE'),
                                   entry('public', default='harmless'))
    assert [f['name'] for f in flat(result)] == ['public']
    assert 'SENSITIVE' not in repr(result)


def test_non_boolean_hidden_keyword_fails_closed():
    assert flat(capture_and_serialize(entry('unknown', hidden='False'))) == []
    assert flat(capture_and_serialize(entry('unknown', hidden=None))) == []


def test_dynamic_registration_without_observed_addparam_fails_closed():
    group = ElementGroup()
    param = group.addParam('injected', LabelParam, label='injected')
    result = worker().serializeRuntimeViewerDefinition(
        form(group), hidden_declarations={})
    assert flat(result) == []
    assert result['omittedFields'] == 1
    assert not hasattr(param, 'hidden')


def test_invalid_observation_record_fails_closed():
    group = ElementGroup()
    group.addParam('field', LabelParam, label='field')
    for bad in [(None, None), ('false', False), (True,), [], True]:
        result = worker().serializeRuntimeViewerDefinition(
            form(group), hidden_declarations={'field': bad})
        assert flat(result) == []


def test_repeated_parameter_name_becomes_ambiguous_and_is_omitted():
    group = ElementGroup()
    with worker().captureViewerHiddenDeclarations(ElementGroup) as evidence:
        group.addParam('reused', StringParam, label='reused', hidden=False)
        group.addParam('reused', StringParam, label='reused', hidden=True)
    assert evidence['reused'] == (None, None)
    assert flat(worker().serializeRuntimeViewerDefinition(
        form(group), hidden_declarations=evidence)) == []


def test_capture_restores_original_method_after_normal_completion():
    original = ElementGroup.addParam
    with worker().captureViewerHiddenDeclarations(ElementGroup):
        assert ElementGroup.addParam is not original
    assert ElementGroup.addParam is original


def test_capture_restores_original_method_after_plugin_exception():
    original = ElementGroup.addParam
    with pytest.raises(RuntimeError, match='plugin failed'):
        with worker().captureViewerHiddenDeclarations(ElementGroup):
            raise RuntimeError('plugin failed')
    assert ElementGroup.addParam is original


def test_capture_does_not_record_failed_addparam_calls():
    group = ElementGroup()
    with worker().captureViewerHiddenDeclarations(ElementGroup) as evidence:
        with pytest.raises(TypeError):
            group.addParam('bad', object, hidden=True)
    assert evidence == {}


def test_runtime_object_hidden_true_cannot_be_overridden_by_false_keyword():
    class ExplicitHiddenParam(StringParam):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.hidden = True
    assert flat(capture_and_serialize(
        entry('protected', ExplicitHiddenParam, hidden=False))) == []


def test_runtime_object_hidden_false_disagreement_with_true_keyword_fails_closed():
    class ExplicitVisibleParam(StringParam):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.hidden = False
    assert flat(capture_and_serialize(
        entry('protected', ExplicitVisibleParam, hidden=True))) == []


def test_existing_direct_serializer_behavior_remains_backward_compatible():
    group = ElementGroup()
    group.addParam('mode', EnumParam, label='mode', default=0)
    field = flat(worker().serializeRuntimeViewerDefinition(form(group)))[0]
    assert field['visibility'] == 'visible'
    assert field['hiddenAttributeAvailable'] is False
    assert field['hidden'] is None


def test_local_enum_change_can_recompute_supported_condition_without_eval():
    entries = (entry('mode', EnumParam, default=0),
               entry('levels', StringParam, condition='mode == 1'))
    initial = capture_and_serialize(*entries, values={'mode': 0})
    changed = capture_and_serialize(*entries, values={'mode': 1})
    assert [f['name'] for f in flat(initial)] == ['mode']
    assert [f['name'] for f in flat(changed)] == ['mode', 'levels']
    assert flat(changed)[1]['conditionState'] == 'met'


def test_local_override_with_unsupported_expression_stays_pending():
    result = capture_and_serialize(
        entry('levels', condition='__import__("os").system("id")'), values={'mode': 1})
    field = flat(result)[0]
    assert field['visibility'] == 'pending'
    assert field['executionAllowed'] is False


def test_conditional_hidden_true_stays_omitted_even_if_condition_true():
    result = capture_and_serialize(entry('mode', EnumParam, default=1),
                                   entry('secret', hidden=True, condition='mode == 1'),
                                   values={'mode': 1})
    assert [f['name'] for f in flat(result)] == ['mode']


def test_group_aware_serializer_retains_limit_and_no_action_fields():
    result = capture_and_serialize(entry('safe', hidden=False))
    assert set(result) == {'sections', 'fieldsDiscovered', 'omittedFields'}
    assert all(field['readOnly'] is True and field['executionAllowed'] is False
               for field in flat(result))


def test_worker_entrypoint_wires_capture_to_setprotocol_and_serializer():
    source = inspect.getsource(worker()._evaluate)
    assert 'with captureViewerHiddenDeclarations() as hidden_declarations:' in source
    assert 'hidden_declarations=hidden_declarations' in source
    assert source.index('with captureViewerHiddenDeclarations()') < source.index('viewer.setProtocol(protocol)')
