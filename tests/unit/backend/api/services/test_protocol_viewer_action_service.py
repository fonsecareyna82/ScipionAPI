import pytest

from app.backend.api.services import protocol_viewer_action_service as service
from app.backend.api.services.protocol_viewer_dynamic_form_service import (
    DynamicProtocolViewerFormError,
)
from app.backend.api.services.protocol_viewer_file_token_service import readViewerFileToken

VIEWER = 'xmipp3.viewers.viewer_cl2d.XmippCL2DViewer'


class Mapper:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def getProject(self, projectId, userId):
        return {'id': projectId} if self.allowed else None


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL', '1')
    monkeypatch.setattr(service, 'resolvePersistedProtocolViewerCandidates', lambda **kw: {
        'protocolDbId': 9253,
        'viewers': [{'id': VIEWER, 'viewerKind': 'protocol-form'},
                    {'id': 'pwem.viewers.DataViewer', 'viewerKind': 'simple'}],
    })


def reply(**changes):
    payload = {'ok': True, 'status': 'viewer-action', 'projectId': 7,
               'protocolId': '115', 'viewerId': VIEWER, 'action': 'showConvergence',
               'items': [], 'messages': [], 'omittedItems': 0}
    payload.update(changes)
    return payload


def run(worker_reply=None, worker_error=None, mapper=None, **changes):
    calls = []

    def runner(request, timeout):
        calls.append((request, timeout))
        if worker_error:
            raise DynamicProtocolViewerFormError(worker_error)
        return worker_reply if worker_reply is not None else reply()

    kwargs = dict(mapper=mapper or Mapper(), current_user={'id': 1}, project_id=7,
                  protocol_id=115, viewer_id=VIEWER, action='showConvergence',
                  values={'doShowLastLevel': 1}, snapshot={}, worker_runner=runner)
    kwargs.update(changes)
    return service.runProtocolViewerAction(**kwargs), calls


def code_of(**kwargs):
    with pytest.raises(service.ProtocolViewerActionError) as error:
        run(**kwargs)
    return error.value.code


def test_worker_receives_the_authorized_request_and_configured_timeout(monkeypatch):
    monkeypatch.setenv('SCIPION_PROTOCOL_VIEWER_ACTION_TIMEOUT', '300')
    result, calls = run()
    assert calls == [({'projectId': 7, 'protocolId': 115, 'protocolDbId': 9253,
                       'viewerId': VIEWER, 'action': 'showConvergence',
                       'values': {'doShowLastLevel': 1}}, 300)]
    assert result['status'] == 'viewer-action' and result['items'] == []


def test_nothing_runs_without_flag_access_or_an_applicable_viewer(monkeypatch):
    assert code_of(mapper=Mapper(allowed=False)) == 'unauthorized'
    assert code_of(viewer_id='pwem.viewers.DataViewer') == 'viewer_not_applicable'
    assert code_of(action='not valid') == 'invalid_identity'
    assert code_of(values={'x': [1]}) == 'invalid_values'
    monkeypatch.delenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL')
    assert code_of() == 'evaluation_disabled'


def test_files_are_returned_with_signed_tokens_and_outputs_as_references():
    items = [
        {'kind': 'data', 'viewClass': 'DataView', 'title': 'level_classes.xmd',
         'format': 'metadata', 'path': 'Runs/000115/extra/level_classes.xmd',
         'table': 'info', 'index': None, 'viewParams': {'mode': 'table'}, 'output': None},
        {'kind': 'data', 'viewClass': 'ObjectView', 'title': 'x', 'format': 'metadata',
         'path': None, 'table': None, 'index': None, 'viewParams': {},
         'output': {'protocolId': 22, 'outputName': 'outputParticles',
                    'className': 'SetOfParticles'}},
        {'kind': 'image', 'title': 'avg', 'path': 'Runs/000115/extra/avg.mrc'},
    ]
    result, _ = run(worker_reply=reply(items=items, injected='never'))
    data, output, image = result['items']
    assert readViewerFileToken(data['fileToken'], 7) == 'Runs/000115/extra/level_classes.xmd'
    assert data['table'] == 'info' and data['viewParams'] == {'mode': 'table'}
    assert output['fileToken'] is None and output['output']['outputName'] == 'outputParticles'
    assert readViewerFileToken(image['fileToken'], 7) == 'Runs/000115/extra/avg.mrc'
    assert 'injected' not in result


@pytest.mark.parametrize('item', [
    {'kind': 'image', 'title': 'x', 'path': '/etc/passwd'},
    {'kind': 'data', 'path': '../x.xmd', 'output': None},
    {'kind': 'data', 'path': None, 'output': None},
    {'kind': 'plot', 'mediaType': 'text/html', 'data': '<script>'},
    {'kind': 'launch', 'command': 'rm'},
])
def test_unsafe_or_unknown_items_reject_the_reply(item):
    assert code_of(worker_reply=reply(items=[item])) == 'invalid_worker_reply'


def test_worker_errors_keep_their_code_and_messages():
    with pytest.raises(service.ProtocolViewerActionError) as error:
        run(worker_reply=reply(ok=False, error='validation_failed',
                               messages=['Select a level']))
    assert (error.value.code, error.value.messages) == ('validation_failed', ['Select a level'])
    assert code_of(worker_reply=reply(ok=False, error='anything')) == 'invalid_worker_reply'
    assert code_of(worker_reply=reply(action='other')) == 'worker_identity_mismatch'
    assert code_of(worker_error='worker_timeout') == 'worker_timeout'


def test_timeout_setting_is_bounded(monkeypatch):
    for raw, expected in (('', 120), ('x', 120), ('1', 5), ('99999', 1800), ('600', 600)):
        monkeypatch.setenv('SCIPION_PROTOCOL_VIEWER_ACTION_TIMEOUT', raw)
        assert service.actionTimeoutSeconds() == expected
