"""Viewer forms: params put on one line (e.g. a color scale) and their wizards."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.backend.api.services import protocol_viewer_dynamic_form_worker as worker
from app.backend.api.services import protocol_wizard_runtime_service as service


def colorScaleForm():
    from pyworkflow.protocol.params import BooleanParam, FloatParam, Form, IntParam, StringParam
    form = Form(SimpleNamespace())
    with worker.captureViewerHiddenDeclarations() as evidence:
        form.addSection(label='Visualization')
        group = form.addGroup('Colored resolution')
        group.addParam('doShowSlices', BooleanParam, default=True, label='Show slices')
        line = group.addLine('Color scale options:')
        line.addParam('highest', FloatParam, default=19.4, label='Highest')
        line.addParam('lowest', FloatParam, default=5.0, label='Lowest')
        line.addParam('intervals', IntParam, default=11, label='Intervals')
        line.addParam('colorMap', StringParam, default='jet', label='Color set')
    return form, evidence


def test_params_on_one_line_are_fields_of_their_group():
    form, evidence = colorScaleForm()
    schema = worker.serializeRuntimeViewerDefinition(form, hidden_declarations=evidence)
    [group] = schema['sections'][0]['groups']
    assert [field['name'] for field in group['fields']] == [
        'doShowSlices', 'highest', 'lowest', 'intervals', 'colorMap']
    assert [field['control'] for field in group['fields'][1:]] == ['number', 'number', 'integer', 'text']


def test_viewer_wizards_are_found_as_the_desktop_viewer_form_finds_them(monkeypatch):
    class Wizard:
        __module__ = 'plugin.wizards'

    class Domain:
        def findWizards(self, viewer, environment):
            assert environment == 'tkinter'
            return {'highest': Wizard, 'lowest': Wizard, 'bad name': Wizard}

    from pyworkflow import Config
    monkeypatch.setattr(Config, 'getDomain', staticmethod(lambda: Domain()))
    assert worker.viewerWizards(object()) == {'highest': 'plugin.wizards.Wizard', 'lowest': 'plugin.wizards.Wizard'}


class Mapper:
    def getProject(self, projectId, userId):
        return {'id': projectId}


def payload(**overrides):
    values = dict(viewerId='xmipp3.viewers.XmippMonoResViewer', values={'highest': 9.5},
                  paramName='highest', wizardId='xmipp3.wizards.ColorScaleWizard', answers=[], preview=None)
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def candidates(monkeypatch):
    import app.backend.api.services.protocol_viewer_persisted_resolution_service as resolution
    monkeypatch.setattr(resolution, 'resolvePersistedProtocolViewerCandidates', lambda **kwargs: {
        'protocolDbId': 812, 'viewers': [{'id': 'xmipp3.viewers.XmippMonoResViewer', 'viewerKind': 'protocol-form'}]})


def call(runner, **overrides):
    return service.runProtocolViewerWizard(mapper=Mapper(), currentUser={'id': 1}, projectId=7, protocolId=117,
                                          payload=payload(**overrides), snapshot={}, workerRunner=runner)


def test_a_viewer_wizard_runs_with_the_viewer_form_values(candidates):
    requests = []

    def runner(request, timeout):
        requests.append(request)
        return {'status': 'done', 'paramUpdates': {'lowest': 1.5, 'highest': 6.0}, 'messages': []}

    reply = call(runner)
    assert reply['paramUpdates'] == {'lowest': 1.5, 'highest': 6.0}
    assert requests[0]['protocolDbId'] == 812 and requests[0]['values'] == {'highest': 9.5}


def test_only_viewers_of_the_protocol_run_wizards(candidates):
    with pytest.raises(HTTPException) as error:
        call(lambda *args: pytest.fail('ran'), viewerId='other.viewers.Viewer')
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        call(lambda *args: pytest.fail('ran'), values={'x': {'nested': 1}})
    assert error.value.status_code == 422
