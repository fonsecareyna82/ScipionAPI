"""RED 135: opt-in, admin-only HTTP admission for live viewer form preview."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]


def svc():
    return importlib.import_module(
        'app.backend.api.services.protocol_viewer_runtime_preview_http_service'
    )


def admin():
    return {'id': 8, 'role': 'admin'}


def preview():
    return {
        'status': 'runtime-preview', 'source': 'isolated-worker',
        'projectId': 4, 'protocolId': '19',
        'viewerId': 'xmipp3.viewers.XmippCL2DViewer',
        'sections': [{'label': 'Visualization', 'fields': [], 'groups': []}],
        'fieldsDiscovered': 0, 'omittedFields': 0,
        'webReady': False, 'renderable': False, 'executionAllowed': False,
    }


def enable(monkeypatch):
    monkeypatch.setenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_HTTP', '1')
    monkeypatch.setenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL', '1')


_UNSET = object()

def call(monkeypatch, user=_UNSET, viewer='xmipp3.viewers.XmippCL2DViewer', response=None, **options):
    enable(monkeypatch)
    hits = []

    def evaluator(**kwargs):
        hits.append(kwargs)
        return preview() if response is None else response

    config = dict(
        mapper=object(), current_user=admin() if user is _UNSET else user,
        project_id=4, protocol_id=19, viewer_id=viewer,
        snapshot={'viewers': {}}, evaluator=evaluator,
    )
    config.update(options)
    return config, hits


def test_feature_disabled_by_default_even_for_admin(monkeypatch):
    monkeypatch.delenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_HTTP', raising=False)
    monkeypatch.delenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL', raising=False)
    assert svc().isProtocolViewerRuntimePreviewAvailable(admin()) is False
    with pytest.raises(svc().ProtocolViewerRuntimePreviewHttpError) as exc:
        svc().requestProtocolViewerRuntimePreview(
            mapper=object(), current_user=admin(), project_id=4,
            protocol_id=19, viewer_id='xmipp3.viewers.XmippCL2DViewer',
            snapshot={}, evaluator=lambda **_: pytest.fail('ran'))
    assert exc.value.code == 'preview_disabled'


@pytest.mark.parametrize('missing', [
    'SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_HTTP',
    'SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL',
])
def test_requires_both_explicit_flags(monkeypatch, missing):
    enable(monkeypatch)
    monkeypatch.delenv(missing)
    assert svc().isProtocolViewerRuntimePreviewAvailable(admin()) is False


@pytest.mark.parametrize('user', [
    {'id': 8, 'role': 'user'}, {'id': 8, 'role': 'editor'},
    {'id': 8}, {'id': True, 'role': 'admin'}, None,
])
def test_non_admins_and_invalid_users_never_spawn(monkeypatch, user):
    request, hits = call(monkeypatch, user=user)
    assert svc().isProtocolViewerRuntimePreviewAvailable(user) is False
    with pytest.raises(svc().ProtocolViewerRuntimePreviewHttpError) as exc:
        svc().requestProtocolViewerRuntimePreview(**request)
    assert exc.value.code == 'admin_required'
    assert not hits


def test_admin_availability_requires_both_flags(monkeypatch):
    enable(monkeypatch)
    assert svc().isProtocolViewerRuntimePreviewAvailable(admin()) is True
    assert svc().isProtocolViewerRuntimePreviewAvailable({'id': 8, 'role': 'ADMIN'}) is True
    monkeypatch.setenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL', '0')
    assert svc().isProtocolViewerRuntimePreviewAvailable(admin()) is False


@pytest.mark.parametrize('bad', [
    {'project_id': True}, {'project_id': -1}, {'protocol_id': 0},
    {'viewer_id': '__import__("os")'}, {'viewer_id': ''},
])
def test_invalid_request_identity_rejected_without_worker(monkeypatch, bad):
    request, hits = call(monkeypatch)
    request.update(bad)
    with pytest.raises(svc().ProtocolViewerRuntimePreviewHttpError) as exc:
        svc().requestProtocolViewerRuntimePreview(**request)
    assert exc.value.code == 'invalid_identity'
    assert hits == []


def test_valid_request_delegates_unchanged_identity_without_action(monkeypatch):
    request, hits = call(monkeypatch)
    result = svc().requestProtocolViewerRuntimePreview(**request)
    assert len(hits) == 1
    assert hits[0] == {
        'mapper': request['mapper'], 'current_user': admin(),
        'project_id': 4, 'protocol_id': 19,
        'viewer_id': 'xmipp3.viewers.XmippCL2DViewer',
        'snapshot': request['snapshot'],
    }
    assert result['sections'][0]['label'] == 'Visualization'
    assert result['webReady'] is False
    assert result['renderable'] is False
    assert result['executionAllowed'] is False
    assert result['instanceEligibility'] == 'not-evaluated'


def test_blocks_worker_claiming_web_execution_rights(monkeypatch):
    for key in ('webReady', 'renderable', 'executionAllowed'):
        response = dict(preview(), **{key: True})
        request, hits = call(monkeypatch, response=response)
        with pytest.raises(svc().ProtocolViewerRuntimePreviewHttpError) as exc:
            svc().requestProtocolViewerRuntimePreview(**request)
        assert exc.value.code == 'invalid_preview'
        assert len(hits) == 1


def test_rejects_mismatched_worker_identity(monkeypatch):
    response = dict(preview(), protocolId='200')
    request, _ = call(monkeypatch, response=response)
    with pytest.raises(svc().ProtocolViewerRuntimePreviewHttpError) as exc:
        svc().requestProtocolViewerRuntimePreview(**request)
    assert exc.value.code == 'invalid_preview'


def test_worker_metadata_cannot_inject_commands_or_paths(monkeypatch):
    response = dict(preview(), executionCommand='rm -rf',
                    secrets={'password': 'not sent'})
    request, _ = call(monkeypatch, response=response)
    result = svc().requestProtocolViewerRuntimePreview(**request)
    assert 'executionCommand' not in result
    assert 'secrets' not in result
    assert 'actions' not in result


def test_actions_other_than_form_field_names_are_rejected(monkeypatch):
    response = dict(preview(), actions=[{'launch': True}])
    request, _ = call(monkeypatch, response=response)
    with pytest.raises(svc().ProtocolViewerRuntimePreviewHttpError) as error:
        svc().requestProtocolViewerRuntimePreview(**request)
    assert error.value.code == 'invalid_preview'


def test_route_uses_post_and_schema_not_get_or_free_form_path():
    source = _REPO_ROOT.joinpath('app/backend/api/routers/project_router.py').read_text()
    assert '@router.post(\n    "/{projectId}/protocols/{protocolId}/viewers/runtime-preview",' in source
    assert 'class ProtocolViewerRuntimePreviewRequest(BaseModel):' in source
    assert 'viewerId: StrictStr' in source
    assert 'response_model=Any' in source


def test_route_auth_and_project_access_before_snapshot_or_worker():
    source = _REPO_ROOT.joinpath('app/backend/api/routers/project_router.py').read_text()
    start = source.index('def inspectProtocolViewerRuntimeForm(')
    end = source.index('@router.post(\n    "/{projectId}/protocols/{protocolId}/viewer/resolve",', start)
    body = source[start:end]
    assert 'Depends(getCurrentUser)' in body
    assert 'Depends(getMapper)' in body
    assert 'isProtocolViewerRuntimePreviewAvailable(currentUser)' in body
    assert 'service.getProjectDbRow(mapper, projectId, currentUser)' in body
    assert 'getScipionViewerResolutionSnapshot()' in body
    assert 'requestProtocolViewerRuntimePreview(' in body
    assert body.index('getProjectDbRow(') < body.index('getScipionViewerResolutionSnapshot()')
    assert body.index('getScipionViewerResolutionSnapshot()') < body.index('requestProtocolViewerRuntimePreview(')
    assert 'loadPostgresqlRuntimeProjectForMutation' not in body


def test_errors_are_sanitized_not_worker_tracebacks():
    source = _REPO_ROOT.joinpath('app/backend/api/routers/project_router.py').read_text()
    start = source.index('def inspectProtocolViewerRuntimeForm(')
    end = source.index('@router.post(\n    "/{projectId}/protocols/{protocolId}/viewer/resolve",', start)
    body = source[start:end]
    assert 'except DynamicProtocolViewerFormError' in body
    assert 'except ProtocolViewerRuntimePreviewHttpError' in body
    assert 'detail=exc.code' in body
    assert 'traceback' not in body


def test_get_discovery_advertises_only_explicit_admin_preview():
    source = _REPO_ROOT.joinpath('app/backend/api/routers/project_router.py').read_text()
    start = source.index('def listPersistedProtocolViewers(')
    end = source.index('@router.post(', start)
    body = source[start:end]
    assert 'isProtocolViewerRuntimePreviewAvailable(currentUser)' in body
    assert 'runtimePreviewAvailable' in body
    assert 'requestProtocolViewerRuntimePreview(' not in body


def test_existing_dynamic_worker_remains_opt_in_not_action_executor():
    src = _REPO_ROOT.joinpath('app/backend/api/services/protocol_viewer_dynamic_form_service.py').read_text()
    assert "SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL" in src
    assert 'def evaluateProtocolViewerDynamicForm(' in src
    assert '_getVisualizeDict(' not in src
    assert 'visualize(' not in src
