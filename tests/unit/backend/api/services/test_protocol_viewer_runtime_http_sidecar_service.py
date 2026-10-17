"""RED 153: preserve validated inert conditional viewer rules at HTTP boundary.

Regression: GREEN 150 produces conditionalFields, but GREEN 136 HTTP serializer
silently dropped this sidecar. No viewer actions may be enabled by forwarding it.
"""
from __future__ import annotations

import copy
import importlib

import pytest


VIEWER = 'xmipp3.viewers.viewer_cl2d.XmippCL2DViewer'


def svc():
    return importlib.import_module(
        'app.backend.api.services.protocol_viewer_runtime_preview_http_service'
    )


def runtime_field(name='doShowLastLevel', control='select', **overrides):
    field = {
        'name': name, 'label': 'Level to visualize' if name == 'doShowLastLevel' else name,
        'control': control, 'hasCondition': False, 'visibility': 'visible',
        'visible': True, 'hidden': False, 'hiddenAttributeAvailable': True,
        'pending': False, 'readOnly': True, 'executionAllowed': False,
        'conditionState': 'none',
    }
    if control == 'select':
        field.update(default='0', choices=['last', 'selection'])
    elif control == 'text':
        field.update(default='')
    field.update(overrides)
    return field


def preview(*, with_sidecar=True):
    base = {
        'status': 'runtime-preview', 'source': 'isolated-worker',
        'projectId': 7, 'protocolId': '115', 'viewerId': VIEWER,
        'sections': [{
            'label': 'Visualization', 'fields': [runtime_field()], 'groups': [],
        }],
        'fieldsDiscovered': 1, 'omittedFields': 2,
        'instanceEligibility': 'not-evaluated',
        'webReady': False, 'renderable': False, 'executionAllowed': False,
    }
    if with_sidecar:
        base['conditionalFields'] = [{
            'section': 'Visualization', 'group': None,
            'field': runtime_field(
                'showSeveralLevels', 'text', label='Levels selection',
                visibility='conditional-hidden', visible=False, conditionState='unmet',
            ),
            'rule': {
                'op': 'eq',
                'left': {'op': 'field', 'name': 'doShowLastLevel'},
                'right': {'op': 'const', 'value': 1},
            },
        }]
    return base


def invoke(monkeypatch, payload, *, user=None, flags=True):
    if flags:
        monkeypatch.setenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_HTTP', '1')
        monkeypatch.setenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL', '1')
    user = user if user is not None else {'id': 8, 'role': 'admin'}
    hits = []

    def evaluator(**kwargs):
        hits.append(kwargs)
        return payload

    result = svc().requestProtocolViewerRuntimePreview(
        mapper=object(), current_user=user, project_id=7, protocol_id=115,
        viewer_id=VIEWER, snapshot={}, evaluator=evaluator,
    )
    assert len(hits) == 1
    return result


def invalid(monkeypatch, payload):
    with pytest.raises(svc().ProtocolViewerRuntimePreviewHttpError) as exc:
        invoke(monkeypatch, payload)
    assert exc.value.code == 'invalid_preview'


def test_cl2d_deferred_rule_survives_worker_to_http(monkeypatch):
    response = invoke(monkeypatch, preview())
    assert response['conditionalFields'][0]['field']['name'] == 'showSeveralLevels'
    assert response['conditionalFields'][0]['field']['visibility'] == 'conditional-hidden'
    assert response['conditionalFields'][0]['rule']['right']['value'] == 1
    assert response['sections'][0]['fields'][0]['name'] == 'doShowLastLevel'
    assert all(field['name'] != 'showSeveralLevels'
               for field in response['sections'][0]['fields'])
    assert response['renderable'] is False
    assert response['executionAllowed'] is False


def test_protocol_identity_and_counts_preserved(monkeypatch):
    response = invoke(monkeypatch, preview())
    assert response['projectId'] == 7
    assert response['protocolId'] == '115'
    assert response['viewerId'] == VIEWER
    assert response['fieldsDiscovered'] == 1
    assert response['omittedFields'] == 2
    assert response['webReady'] is False


def test_legacy_http_reply_stays_read_only_and_has_no_sidecar(monkeypatch):
    result = invoke(monkeypatch, preview(with_sidecar=False))
    assert 'conditionalFields' not in result
    assert result['renderable'] is False
    assert result['sections'][0]['fields'][0]['readOnly'] is True


def test_valid_existing_conditional_rule_kept_by_http(monkeypatch):
    payload = preview()
    conditional = payload['conditionalFields'][0]
    conditional['field']['visibility'] = 'visible'
    conditional['field']['visible'] = True
    conditional['field']['conditionState'] = 'met'
    payload['sections'][0]['fields'].append(copy.deepcopy(conditional['field']))
    payload['fieldsDiscovered'] = 2
    out = invoke(monkeypatch, payload)
    assert out['conditionalFields'][0]['field'] == out['sections'][0]['fields'][1]


def test_http_keeps_group_placement_without_exposing_raw_payload(monkeypatch):
    payload = preview()
    payload['sections'][0]['groups'] = [{'label': 'Group A', 'fields': []}]
    payload['conditionalFields'][0]['group'] = 'Group A'
    payload.update(command='run', secrets={'token': 'SECRET'})
    result = invoke(monkeypatch, payload)
    assert result['conditionalFields'][0]['group'] == 'Group A'
    assert 'actions' not in result
    assert 'command' not in result
    assert 'secrets' not in result


@pytest.mark.parametrize('mutation', [
    'invalid_operator',
    'unknown_reference',
    'field_extra_action',
    'field_executable',
    'field_editable',
    'field_hidden_true',
    'field_hidden_unverified',
    'malformed_location',
    'unexpected_entry_key',
    'duplicate_sidecar',
    'not_array',
    'empty_array',
    'invalid_rule_constant',
    'forged_initial_visible',
    'invalid_field_control',
    'too_long_field',
])
def test_http_rejects_malformed_or_executable_sidecars(monkeypatch, mutation):
    payload = preview()
    entry = payload['conditionalFields'][0]
    field = entry['field']
    if mutation == 'invalid_operator':
        entry['rule']['op'] = 'execute'
    elif mutation == 'unknown_reference':
        entry['rule']['left']['name'] = 'secret'
    elif mutation == 'field_extra_action':
        field['launch'] = 'rm -rf /'
    elif mutation == 'field_executable':
        field['executionAllowed'] = True
    elif mutation == 'field_editable':
        field['readOnly'] = False
    elif mutation == 'field_hidden_true':
        field['hidden'] = True
    elif mutation == 'field_hidden_unverified':
        field['hiddenAttributeAvailable'] = False
        field['hidden'] = None
    elif mutation == 'malformed_location':
        entry['section'] = ''
    elif mutation == 'unexpected_entry_key':
        entry['callbacks'] = ['run']
    elif mutation == 'duplicate_sidecar':
        payload['conditionalFields'].append(copy.deepcopy(entry))
    elif mutation == 'not_array':
        payload['conditionalFields'] = {'field': field}
    elif mutation == 'empty_array':
        payload['conditionalFields'] = []
    elif mutation == 'invalid_rule_constant':
        entry['rule']['right']['value'] = {'__class__': 'danger'}
    elif mutation == 'forged_initial_visible':
        payload['sections'][0]['fields'].append(copy.deepcopy(field))
    elif mutation == 'invalid_field_control':
        field['control'] = 'action'
    elif mutation == 'too_long_field':
        field['label'] = 'X' * 200
    invalid(monkeypatch, payload)


@pytest.mark.parametrize('key', ['webReady', 'renderable', 'executionAllowed'])
def test_http_still_rejects_top_level_execution_claims(monkeypatch, key):
    payload = preview()
    payload[key] = True
    invalid(monkeypatch, payload)


def test_no_child_launch_when_http_disabled(monkeypatch):
    monkeypatch.setenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_HTTP', '0')
    monkeypatch.setenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL', '1')
    hits = []
    with pytest.raises(svc().ProtocolViewerRuntimePreviewHttpError) as exc:
        svc().requestProtocolViewerRuntimePreview(
            mapper=object(), current_user={'id': 8, 'role': 'admin'},
            project_id=7, protocol_id=115, viewer_id=VIEWER,
            snapshot={}, evaluator=lambda **_: hits.append(True),
        )
    assert exc.value.code == 'preview_disabled'
    assert hits == []
