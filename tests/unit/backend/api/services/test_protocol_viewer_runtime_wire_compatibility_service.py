"""RED 145: preserve the complete, inert GREEN 142 visibility contract across the worker boundary.

Regression: GREEN 142's child sends visibility metadata, but the parent worker
validator still accepts only the pre-142 field whitelist, raising invalid_worker_schema.
"""
from __future__ import annotations

import copy
import importlib

import pytest


def service():
    return importlib.import_module('app.backend.api.services.protocol_viewer_dynamic_form_service')


def http_service():
    return importlib.import_module('app.backend.api.services.protocol_viewer_runtime_preview_http_service')


REQUEST = {'projectId': 4, 'protocolId': 19, 'viewerId': 'xmipp3.viewers.XmippCL2DViewer'}


def field(name='show', **overrides):
    item = {'name': name, 'label': name, 'control': 'text', 'hasCondition': False}
    item.update(overrides)
    return item


def explicit(name='show', **overrides):
    item = field(name, visibility='visible', visible=True, hidden=None,
                 hiddenAttributeAvailable=False, pending=False,
                 readOnly=True, executionAllowed=False, conditionState='none')
    item.update(overrides)
    return item


def reply(fields=None, groups=None):
    result = {'ok': True, 'status': 'runtime-preview', 'source': 'isolated-worker',
              **REQUEST, 'protocolId': str(REQUEST['protocolId']),
              'webReady': False, 'renderable': False,
              'executionAllowed': False,
              'sections': [{'label': 'Visualization', 'fields': fields or [],
                            'groups': groups or []}], 'omittedFields': 0}
    return result


def checked(fields=None, groups=None):
    return service()._validated_reply(reply(fields, groups), REQUEST)


def reject(one, *, grouped=False):
    obj = reply([] if grouped else [one],
                [{'label': 'Extras', 'fields': [one]}] if grouped else [])
    with pytest.raises(service().DynamicProtocolViewerFormError) as error:
        service()._validated_reply(obj, REQUEST)
    assert error.value.code == 'invalid_worker_schema'


# Current GREEN 142 fields must survive the parent and HTTP boundaries.
def test_visible_runtime_field_accepted_without_losing_metadata():
    result = checked([explicit('level', control='select', choices=['last', 'selection'], default=0)])
    assert result['fieldsDiscovered'] == 1
    assert result['sections'][0]['fields'][0] == explicit(
        'level', control='select', choices=['last', 'selection'], default=0)


def test_condition_met_is_preserved():
    result = checked([explicit('levels', conditionState='met', default='0-3')])
    assert result['sections'][0]['fields'][0]['conditionState'] == 'met'


def test_unresolved_condition_is_preserved_as_pending():
    item = explicit('levels', visibility='pending', visible=None, pending=True,
                    conditionState='unresolved', hasCondition=True)
    assert checked([item])['sections'][0]['fields'][0] == item


def test_known_hidden_false_is_distinct_from_missing_hidden_attribute():
    known = explicit('known', hidden=False, hiddenAttributeAvailable=True)
    absent = explicit('unknown', hidden=None, hiddenAttributeAvailable=False)
    result = checked([known, absent])
    assert result['sections'][0]['fields'][0]['hidden'] is False
    assert result['sections'][0]['fields'][1]['hidden'] is None


def test_grouped_visibility_fields_are_preserved():
    item = explicit('grouped', visibility='pending', visible=None, pending=True,
                    hasCondition=True, conditionState='unresolved')
    result = checked([], [{'label': 'Settings', 'fields': [item]}])
    assert result['sections'][0]['groups'][0]['fields'] == [item]


def test_mixed_legacy_and_explicit_fields_remain_supported():
    legacy = field('legacy')
    modern = explicit('modern')
    result = checked([legacy, modern])
    assert result['sections'][0]['fields'] == [legacy, modern]


def test_runtime_form_with_real_cl2d_shape_survives():
    schema = [
        explicit('doShowLastLevel', label='Level to visualize', control='select',
                 choices=['last', 'selection'], default=0),
        explicit('classesToShow', label='What to show', control='select',
                 choices=['classes', 'cores', 'stable cores'], default=0),
        explicit('showConvergence', label='Visualize convergence', control='label'),
        explicit('showClassHierarchy', label='Visualize class hierarchy.', control='label'),
    ]
    assert checked(schema)['fieldsDiscovered'] == 4


def test_http_boundary_relay_preserves_safe_visibility_metadata(monkeypatch):
    monkeypatch.setenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_HTTP', '1')
    monkeypatch.setenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL', '1')
    child = reply([explicit('classesToShow', control='select',
                            choices=['classes', 'cores'], default=0)])

    def evaluator(**kwargs):
        assert kwargs['viewer_id'] == REQUEST['viewerId']
        return service()._validated_reply(child, REQUEST)

    result = http_service().requestProtocolViewerRuntimePreview(
        mapper=object(), current_user={'id': 8, 'role': 'admin'},
        project_id=4, protocol_id=19, viewer_id=REQUEST['viewerId'],
        snapshot={}, evaluator=evaluator)
    assert result['sections'][0]['fields'][0]['visibility'] == 'visible'
    assert result['sections'][0]['fields'][0]['readOnly'] is True
    assert result['executionAllowed'] is False


def test_legacy_worker_reply_remains_valid():
    result = checked([field('old', default=3)])
    assert result['sections'][0]['fields'][0] == field('old', default=3)


def test_worker_top_level_extra_keys_still_never_reach_http():
    payload = reply([field('old')])
    payload.update(secret='NEVER RETURN')
    result = service()._validated_reply(payload, REQUEST)
    assert 'secret' not in result and 'actions' not in result


def test_actions_are_names_of_fields_in_the_same_form():
    payload = reply([field('old')])
    payload.update(actions=['old'])
    assert service()._validated_reply(payload, REQUEST)['actions'] == ['old']
    for actions in ([{'launch': 'unsafe'}], ['missing'], ['old', 'old'], 'old'):
        payload.update(actions=actions)
        with pytest.raises(service().DynamicProtocolViewerFormError):
            service()._validated_reply(payload, REQUEST)


def test_rejects_arbitrary_field_property():
    reject(explicit('safe', injectedCommand='danger'))


def test_rejects_partial_visibility_contract():
    reject(field('partial', visibility='visible'))


def test_rejects_boolean_execution_permission():
    reject(explicit('unsafe', executionAllowed=True))


def test_rejects_false_read_only_claim():
    reject(explicit('unsafe', readOnly=False))


def test_rejects_hidden_field_from_worker():
    reject(explicit('secret', hidden=True, hiddenAttributeAvailable=True))


def test_rejects_hidden_provenance_mismatch():
    reject(explicit('mismatch', hidden=False, hiddenAttributeAvailable=False))


def test_rejects_visible_and_pending_conflict():
    reject(explicit('contradiction', visibility='visible', pending=True))


def test_rejects_pending_with_true_visibility():
    reject(explicit('contradiction', visibility='pending', visible=True,
                    pending=True, hasCondition=True, conditionState='unresolved'))


def test_rejects_invalid_condition_state():
    reject(explicit('condition', conditionState='call_python'))


def test_rejects_pending_without_condition_marker():
    reject(explicit('condition', visibility='pending', visible=None,
                    pending=True, conditionState='unresolved', hasCondition=False))


def test_rejects_non_boolean_flags():
    reject(explicit('unsafe', readOnly=1))


def test_rejects_unknown_metadata_inside_group():
    reject(explicit('grouped', callback='run'), grouped=True)


def test_rejects_unexpected_worker_identity_and_permissions():
    for change in ({'viewerId': 'evil.Viewer'}, {'executionAllowed': True}):
        payload = reply([field('legacy')])
        payload.update(change)
        with pytest.raises(service().DynamicProtocolViewerFormError):
            service()._validated_reply(payload, REQUEST)
