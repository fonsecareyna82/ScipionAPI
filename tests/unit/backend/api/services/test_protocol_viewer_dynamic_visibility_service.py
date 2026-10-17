"""RED 133: CL2D-inspired generic safe constants and explicit visibility tests.

All plugin-like snippets are inert input strings; no viewer actions are executed.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

# Representative inert module constants used by real Xmipp CL2D.
LEVEL_LAST = 0
LEVEL_SEL = 1
LEVEL_CHOICES = ["last", "selection"]


def forms():
    return importlib.import_module('app.backend.api.services.protocol_viewer_form_schema_service')


def worker():
    return importlib.import_module('app.backend.api.services.protocol_viewer_dynamic_form_worker')


SOURCE = '''def _defineParams(self, form):
    form.addSection(label="Visualization")
    form.addParam("doShowLastLevel", EnumParam, choices=LEVEL_CHOICES,
                  default=LEVEL_LAST, label="Level to visualize")
    form.addParam("showSeveralLevels", StringParam, default="",
                  label="Levels selection", condition="doShowLastLevel==%d" % LEVEL_SEL)
'''
CONSTANTS = {'LEVEL_LAST': 0, 'LEVEL_SEL': 1, 'LEVEL_CHOICES': ['last', 'selection']}


def preview(source=SOURCE, constants=None):
    return forms().parseProtocolViewerStaticFormSource(
        source, safe_constants=CONSTANTS if constants is None else constants)


def fields(value):
    return [field for section in value['sections'] for field in section['fields']]


def test_cl2d_levels_constant_choices_become_advisory_enum():
    result = preview()
    enum = fields(result)[0]
    assert (enum['name'], enum['control'], enum['choices']) == (
        'doShowLastLevel', 'select', ['last', 'selection'])


def test_cl2d_level_default_is_resolved_from_module_constant():
    result = preview()
    enum = fields(result)[0]
    assert enum['name'] == 'doShowLastLevel' and enum['default'] == 0


def test_cl2d_condition_still_requires_evaluation():
    result = preview()
    assert result['fieldsDiscovered'] == 2
    assert fields(result)[1]['hasCondition'] is True
    assert result['requiresRuntimeEvaluation'] is True
    assert result['actionExecutionAllowed'] is False


def test_module_tuple_choices_are_supported_without_running_plugin():
    source = '''def _defineParams(self, form):
    form.addSection(label="Options")
    form.addParam("option", EnumParam, label="Choice", choices=CHOICES)
'''
    result = preview(source, {'CHOICES': ('a', 'b')})
    assert fields(result)[0]['choices'] == ['a', 'b']


def test_unknown_dynamic_choices_cannot_be_guessed_from_local_list():
    source = '''def _defineParams(self, form):
    form.addSection(label="Visualization")
    local_choices = ["classes"]
    if self.protocol.doCore:
        local_choices.append("cores")
    form.addParam("classesToShow", EnumParam, choices=local_choices, label="What to show")
    form.addParam("regular", StringParam, label="Regular")
'''
    result = preview(source)
    assert [f['name'] for f in fields(result)] == ['regular']
    assert result['dynamicDefinitionsSkipped'] >= 1
    assert result['requiresRuntimeEvaluation'] is True


def test_hidden_true_omits_control_and_does_not_leak_default():
    source = '''def _defineParams(self, form):
    form.addSection(label="Visualization")
    form.addParam("secret", StringParam, label="Secret", hidden=True, default="API_TOKEN")
    form.addParam("normal", StringParam, label="Normal")
'''
    result = preview(source)
    assert [f['name'] for f in fields(result)] == ['normal']
    assert result['hiddenFields'] == 1
    assert 'API_TOKEN' not in str(result)


def test_hidden_constant_true_is_omitted():
    source = '''def _defineParams(self, form):
    form.addSection(label="Visualization")
    form.addParam("secret", StringParam, label="Secret", hidden=HIDE_SECRET, default="TOP_SECRET")
    form.addParam("regular", StringParam, label="Regular")
'''
    result = preview(source, {'HIDE_SECRET': True})
    assert [f['name'] for f in fields(result)] == ['regular']
    assert result['hiddenFields'] == 1
    assert 'TOP_SECRET' not in str(result)


def test_cl2d_dynamic_hidden_is_not_presented_as_unconditional_field():
    source = '''def _defineParams(self, form):
    form.addSection(label="Visualization")
    form.addParam("showConvergence", LabelParam, label="Visualize convergence")
    form.addParam("showClassHierarchy", LabelParam, label="Visualize class hierarchy.",
                  hidden=not self.protocol.computeHierarchy)
'''
    result = preview(source)
    assert [f['name'] for f in fields(result)] == ['showConvergence']
    assert result['dynamicDefinitionsSkipped'] >= 1
    assert result['actionExecutionAllowed'] is False


def test_unrecognized_hidden_symbol_is_fail_closed():
    source = '''def _defineParams(self, form):
    form.addSection(label="Visualization")
    form.addParam("maybeHidden", StringParam, label="Hidden?", hidden=UNKNOWN)
    form.addParam("known", StringParam, label="Known")
'''
    result = preview(source)
    assert [f['name'] for f in fields(result)] == ['known']
    assert result['dynamicDefinitionsSkipped'] >= 1


def test_non_literal_constant_object_is_never_iterated_or_called():
    class Trap:
        def __iter__(self):
            raise AssertionError('must not iterate plugin object')
        def __bool__(self):
            raise AssertionError('must not inspect plugin object')
    result = preview(SOURCE, {**CONSTANTS, 'LEVEL_CHOICES': Trap()})
    assert [f['name'] for f in fields(result)] == ['showSeveralLevels']
    assert result['dynamicDefinitionsSkipped'] >= 1
    assert result['actionExecutionAllowed'] is False


def test_module_constants_are_copied_into_inert_preview():
    choices = ['last', 'selection']
    result = preview(SOURCE, {**CONSTANTS, 'LEVEL_CHOICES': choices})
    choices.append('mutated later')
    assert fields(result)[0]['choices'] == ['last', 'selection']


def test_class_registry_reads_own_function_globals_without_instantiating():
    from pyworkflow.viewer import ProtocolViewer
    from app.backend.api.services.protocol_viewer_inventory_service import _class_identity
    class LocalViewer(ProtocolViewer):
        def __init__(self, *args, **kwargs):
            raise AssertionError('viewer instantiated on API server')
        def _defineParams(self, form):
            raise AssertionError('plugin _defineParams executed')
    # Form parser is allowed to inspect function.__globals__ but never calls it.
    result = forms().describeProtocolViewerStaticForms(
        {'viewers': [{'id': _class_identity(LocalViewer)}]},
        {'local': LocalViewer}, source_loader=lambda method: SOURCE)
    found = result['viewers'][0]['formSchema']
    assert [f['name'] for f in fields(found)] == ['doShowLastLevel', 'showSeveralLevels']
    assert found['renderable'] is False


class Holder:
    def __init__(self, value):
        self.value = value
    def get(self):
        return self.value


class EnumParam:
    def __init__(self, choices, hidden=False):
        self.label = Holder('What to show')
        self.condition = Holder(None)
        self.help = Holder(None)
        self.default = Holder(0)
        self.choices = choices
        self.hidden = hidden


class StringParam:
    def __init__(self, *, hidden=False, default=''):
        self.label = Holder('Private')
        self.condition = Holder(None)
        self.help = Holder(None)
        self.default = Holder(default)
        self.hidden = hidden


class Section:
    label = Holder('Visualization')
    def __init__(self, params):
        self.params = params
    def iterParams(self):
        return iter(self.params)


def run_worker(params):
    return worker().serializeRuntimeViewerDefinition(SimpleNamespace(
        _sectionList=[Section(params)]))


def test_runtime_computed_choices_from_protocol_state_are_serialized():
    result = run_worker([('classesToShow', EnumParam(['classes', 'cores', 'stable cores']))])
    assert result['fieldsDiscovered'] == 1
    assert result['sections'][0]['fields'][0]['choices'] == ['classes', 'cores', 'stable cores']
    # No handlers, actions or execution grants are serialized.
    assert 'action' not in str(result)


def test_runtime_explicit_hidden_true_is_omitted():
    result = run_worker([('secret', StringParam(hidden=True, default='TOP_SECRET')),
                         ('classesToShow', EnumParam(['classes']))])
    assert result['fieldsDiscovered'] == 1
    assert result['omittedFields'] == 1
    assert 'TOP_SECRET' not in str(result)


def test_runtime_unknown_hidden_marker_is_fail_closed():
    result = run_worker([('secret', StringParam(hidden='True', default='TOP_SECRET')),
                         ('classesToShow', EnumParam(['classes']))])
    assert result['fieldsDiscovered'] == 1
    assert result['omittedFields'] == 1
    assert 'TOP_SECRET' not in str(result)


def test_runtime_hidden_marker_rejects_numeric_truthiness():
    result = run_worker([('secret', StringParam(hidden=1, default='TOP_SECRET')),
                         ('classesToShow', EnumParam(['classes']))])
    assert result['fieldsDiscovered'] == 1
    assert result['omittedFields'] == 1
    assert 'TOP_SECRET' not in str(result)
