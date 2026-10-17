"""RED 127: trusted subprocess boundary for dynamic Scipion ProtocolViewer forms."""
from __future__ import annotations

import importlib
import json
import subprocess
from types import SimpleNamespace

import pytest


def lib():
    return importlib.import_module(
        'app.backend.api.services.protocol_viewer_dynamic_form_service')


def worker():
    return importlib.import_module(
        'app.backend.api.services.protocol_viewer_dynamic_form_worker')


def context():
    from pyworkflow.protocol import Protocol
    from pyworkflow.viewer import ProtocolViewer, Viewer
    from app.backend.api.services.protocol_viewer_inventory_service import _class_identity

    class ProtDemo(Protocol):
        pass

    class DemoViewer(ProtocolViewer):
        _targets = [ProtDemo]
        def __init__(self, *args, **kwargs):
            raise AssertionError('viewer construction in API process')
        @classmethod
        def can_handle_this_instance(cls, instance):
            raise AssertionError('plugin condition executed in API process')

    class PlainViewer(Viewer):
        _targets = [ProtDemo]

    ProtDemo.__module__ = 'demo_plugin.protocols'
    ProtDemo.__qualname__ = 'ProtDemo'
    DemoViewer.__qualname__ = 'DemoViewer'
    PlainViewer.__qualname__ = 'PlainViewer'
    DemoViewer.__module__ = 'demo_plugin.viewers'
    PlainViewer.__module__ = 'demo_plugin.viewers'

    class Mapper:
        calls = []
        allow = True
        found = True
        def getProject(self, projectId, userId):
            self.calls.append(('project', projectId, userId))
            return {'id': projectId} if self.allow else None
        def getProjectProtocolByProtocolId(self, projectId, protocolId):
            self.calls.append(('protocol', projectId, protocolId))
            if not self.found:
                return None
            return {'id': 71, 'projectId': projectId, 'protocolId': str(protocolId),
                    'protocolClassName': 'ProtDemo', 'status': 'finished',
                    'params': {'secret': 'never send'}}

    mapper = Mapper()
    snap = {'protocols': {'ProtDemo': ProtDemo},
            'viewers': {'DemoViewer': DemoViewer, 'PlainViewer': PlainViewer},
            'preferredViewers': {}}
    return mapper, snap, _class_identity(DemoViewer), _class_identity(PlainViewer)


def call(monkeypatch, *, override=None, runner=None):
    monkeypatch.setenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL', '1')
    mapper, snap, viewer_id, _ = context()
    config = {'mapper': mapper, 'current_user': {'id': 8},
              'project_id': 4, 'protocol_id': 19, 'viewer_id': viewer_id,
              'snapshot': snap, 'worker_runner': runner or preview_runner}
    if override:
        config.update(override)
    return lib().evaluateProtocolViewerDynamicForm(**config)


def preview_runner(request, timeout):
    return {'ok': True, 'status': 'runtime-preview', 'source': 'isolated-worker',
            'projectId': request['projectId'], 'protocolId': str(request['protocolId']),
            'viewerId': request['viewerId'], 'sections': [], 'omittedFields': 0,
            'webReady': False, 'renderable': False, 'executionAllowed': False}


def test_disabled_by_default_even_with_matching_viewer(monkeypatch):
    monkeypatch.delenv('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL', raising=False)
    mapper, snap, viewer_id, _ = context()
    with pytest.raises(lib().DynamicProtocolViewerFormError) as exc:
        lib().evaluateProtocolViewerDynamicForm(mapper=mapper, current_user={'id': 8},
           project_id=4, protocol_id=19, viewer_id=viewer_id, snapshot=snap)
    assert exc.value.code == 'evaluation_disabled'
    assert mapper.calls == []


@pytest.mark.parametrize('bad', [{'project_id': True}, {'protocol_id': -1},
                                 {'viewer_id': '__import__("os").system("x")'},
                                 {'timeout_seconds': 11}])
def test_malformed_input_fails_before_worker(monkeypatch, bad):
    with pytest.raises(lib().DynamicProtocolViewerFormError) as exc:
        call(monkeypatch, override=bad, runner=lambda *_: pytest.fail('worker ran'))
    assert exc.value.code in ('invalid_identity', 'invalid_timeout')


def test_no_project_access_does_not_read_protocol(monkeypatch):
    mapper, snap, viewer_id, _ = context()
    mapper.allow = False
    with pytest.raises(lib().DynamicProtocolViewerFormError) as exc:
        call(monkeypatch, override={'mapper': mapper, 'snapshot': snap, 'viewer_id': viewer_id},
             runner=lambda *_: pytest.fail('worker ran'))
    assert exc.value.code == 'unauthorized'
    assert [c[0] for c in mapper.calls] == ['project']


def test_missing_runtime_row_never_starts_worker(monkeypatch):
    mapper, snap, viewer_id, _ = context()
    mapper.found = False
    with pytest.raises(Exception):
        call(monkeypatch, override={'mapper': mapper, 'snapshot': snap, 'viewer_id': viewer_id},
             runner=lambda *_: pytest.fail('worker ran'))
    assert [c[0] for c in mapper.calls] == ['project', 'protocol']


def test_non_protocol_viewer_is_not_accepted(monkeypatch):
    mapper, snap, _, plain_id = context()
    with pytest.raises(lib().DynamicProtocolViewerFormError) as exc:
        call(monkeypatch, override={'mapper': mapper, 'snapshot': snap, 'viewer_id': plain_id},
             runner=lambda *_: pytest.fail('worker ran'))
    assert exc.value.code == 'viewer_not_applicable'


def test_valid_request_passes_only_strict_ids_to_worker(monkeypatch):
    requests = []
    def runner(request, timeout):
        requests.append((request, timeout))
        return preview_runner(request, timeout)
    result = call(monkeypatch, runner=runner)
    assert requests[0][0] == {'projectId': 4, 'protocolId': 19,
                              'protocolDbId': 71, 'viewerId': result['viewerId']}
    assert requests[0][1] == 5
    assert result['executionAllowed'] is False and result['webReady'] is False
    assert 'secret' not in str(result)


def test_spoofed_worker_identity_is_rejected(monkeypatch):
    def runner(req, timeout):
        result = preview_runner(req, timeout)
        result['projectId'] = 100
        return result
    with pytest.raises(lib().DynamicProtocolViewerFormError) as exc:
        call(monkeypatch, runner=runner)
    assert exc.value.code == 'worker_identity_mismatch'


def test_spoofed_executable_flag_is_rejected(monkeypatch):
    def runner(req, timeout):
        result = preview_runner(req, timeout)
        result['executionAllowed'] = True
        return result
    with pytest.raises(lib().DynamicProtocolViewerFormError) as exc:
        call(monkeypatch, runner=runner)
    assert exc.value.code == 'unsafe_worker_flags'


def test_worker_cannot_return_arbitrary_schema(monkeypatch):
    def runner(req, timeout):
        result = preview_runner(req, timeout)
        result['sections'] = [{'label': 'X', 'fields': [{'name': 'foo', 'control': 'custom-exec'}], 'groups': []}]
        return result
    with pytest.raises(lib().DynamicProtocolViewerFormError) as exc:
        call(monkeypatch, runner=runner)
    assert exc.value.code == 'invalid_worker_schema'


def test_worker_rejects_unexpected_fields_even_if_inert(monkeypatch):
    def runner(req, timeout):
        result = preview_runner(req, timeout)
        result['sections'] = [{'label': 'Visualization', 'groups': [], 'fields': [
            {'name': 'threshold', 'label': 'Threshold', 'control': 'number',
             'hasCondition': False, 'leakedData': 'SECRET'}]}]
        return result
    with pytest.raises(lib().DynamicProtocolViewerFormError) as exc:
        call(monkeypatch, runner=runner)
    assert exc.value.code == 'invalid_worker_schema'


def test_runtime_serializer_handles_conditional_fields_and_groups():
    module = worker()
    class Holder:
        def __init__(self, value): self.value = value
        def get(self): return self.value
    class EnumParam:
        choices = ['last', 'selected']
        label = Holder('Iteration')
        condition = Holder('is3d')
        help = Holder('Choose iteration')
        default = Holder(0)
    class FloatParam:
        label = Holder('Threshold')
        condition = Holder(None)
        help = Holder(None)
        default = Holder(0.143)
    class FakeGroup:
        label = Holder('Plot')
        def iterParams(self): return iter([('threshold', FloatParam())])
    class FakeSection:
        label = Holder('Visualization')
        def iterParams(self):
            return iter([('iteration', EnumParam()), ('plot', FakeGroup())])
    # The real Group class is imported from pyworkflow.protocol.params.
    import pyworkflow.protocol.params as params
    saved = params.Group
    params.Group = FakeGroup
    try:
        result = module.serializeRuntimeViewerDefinition(SimpleNamespace(_sectionList=[FakeSection()]))
    finally:
        params.Group = saved
    assert result['fieldsDiscovered'] == 2
    assert result['sections'][0]['fields'][0]['choices'] == ['last', 'selected']
    assert result['sections'][0]['fields'][0]['hasCondition'] is True
    assert result['sections'][0]['groups'][0]['fields'][0]['default'] == 0.143


def test_runtime_serializer_never_exposes_hidden_defaults():
    module = worker()
    class Holder:
        def __init__(self, v): self.v = v
        def get(self): return self.v
    class StringParam:
        label = Holder('Secret')
        condition = Holder('False')
        default = Holder('token-goes-here')
    class Section:
        label = Holder('Visualization')
        def iterParams(self): return iter([('secret', StringParam())])
    result = module.serializeRuntimeViewerDefinition(SimpleNamespace(_sectionList=[Section()]))
    assert result['fieldsDiscovered'] == 0
    assert result['omittedFields'] == 1
    assert 'token-goes-here' not in str(result)


def test_worker_timeout_kills_process_group(monkeypatch):
    runner = lib()
    called = []
    class FakeProcess:
        pid = 987
        returncode = None
        n = 0
        def communicate(self, input=None, timeout=None):
            self.n += 1
            if self.n == 1:
                raise subprocess.TimeoutExpired(['fake'], timeout)
            self.returncode = -9
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(runner.os, 'killpg', lambda pid, sig: called.append((pid, sig)))
    with pytest.raises(runner.DynamicProtocolViewerFormError) as exc:
        runner._run_worker({'projectId': 4, 'protocolId': 19, 'protocolDbId': 71,
                            'viewerId': 'demo_plugin.viewers.DemoViewer'}, 1)
    assert exc.value.code == 'worker_timeout'
    assert called and called[0][0] == 987


def test_child_command_is_fixed_and_does_not_use_shell(monkeypatch):
    runner = lib()
    launched = []
    class FakeProcess:
        returncode = 0
        def communicate(self, input=None, timeout=None):
            return None
    def start(command, **kw):
        launched.append((command, kw))
        return FakeProcess()
    monkeypatch.setattr(runner.subprocess, 'Popen', start)
    with pytest.raises(runner.DynamicProtocolViewerFormError):
        runner._run_worker({'projectId': 4, 'protocolId': 19, 'protocolDbId': 71,
                            'viewerId': 'demo_plugin.viewers.DemoViewer'}, 1)
    assert launched[0][0][-1] == 'app.backend.api.services.protocol_viewer_dynamic_form_worker'
    assert launched[0][1]['start_new_session'] is True
    assert 'shell' not in launched[0][1]
