"""Capture and translation of the Views produced by ProtocolViewer actions."""
import base64

import pytest

from app.backend.api.services import protocol_viewer_action_worker as worker


class FakeProject:
    port = None

    def __init__(self, path):
        self._path = str(path)

    def getPath(self):
        return self._path


class FakeOutputs:
    def __init__(self, known=None):
        self.known = known or {}

    def find(self, object_id):
        return self.known.get(str(object_id))


@pytest.fixture
def project(tmp_path):
    (tmp_path / 'Runs' / '000115_CL2D' / 'extra').mkdir(parents=True)
    (tmp_path / 'Runs' / '000115_CL2D' / 'extra' / 'level_classes.xmd').write_text('data_info\n')
    (tmp_path / 'Runs' / '000115_CL2D' / 'extra' / 'hierarchy.txt').write_text('class 1 -> 2\n')
    (tmp_path / 'Runs' / '000115_CL2D' / 'extra' / 'avg.mrc').write_bytes(b'\0' * 16)
    return tmp_path


def translate(view, project, outputs=None):
    return worker.translateView(view, worker.PathResolver(str(project)),
                                outputs or FakeOutputs())


def test_data_view_block_becomes_a_project_file_with_table(project):
    from pwem.viewers.views import DataView
    item = translate(DataView('info@Runs/000115_CL2D/extra/level_classes.xmd'), project)
    assert item['kind'] == 'data'
    assert item['format'] == 'metadata'
    assert item['table'] == 'info'
    assert item['path'] == 'Runs/000115_CL2D/extra/level_classes.xmd'
    assert item['output'] is None


def test_indexed_image_path_keeps_the_index(project):
    from pwem.viewers.views import DataView
    item = translate(DataView('3@Runs/000115_CL2D/extra/avg.mrc'), project)
    assert (item['format'], item['index'], item['path']) == (
        'image', 3, 'Runs/000115_CL2D/extra/avg.mrc')


def test_object_view_of_a_stored_output_points_to_the_output(project):
    from pwem.viewers.views import ObjectView
    output = {'protocolId': 22, 'outputName': 'outputParticles', 'className': 'SetOfParticles'}
    view = ObjectView(FakeProject(project), '1003860', '/tmp/elsewhere/particles.sqlite',
                      viewParams={'mode': 'gallery', 'unknown': 'dropped'})
    item = translate(view, project, FakeOutputs({'1003860': output}))
    assert item['output'] == output
    assert item['path'] is None
    assert item['viewParams'] == {'mode': 'gallery'}


def test_files_outside_the_project_are_not_exposed(project, tmp_path_factory):
    from pwem.viewers.views import DataView, ImageView
    outside = tmp_path_factory.mktemp('outside') / 'x.xmd'
    outside.write_text('data_x\n')
    assert translate(DataView(str(outside)), project)['reason'] == 'file_outside_project'
    assert translate(ImageView(str(outside)), project)['kind'] == 'unsupported'


def test_text_message_and_command_views(project):
    from pyworkflow.viewer import CommandView, MessageView, TextView, MSG_WARN
    text = translate(TextView([str(project / 'Runs/000115_CL2D/extra/hierarchy.txt'),
                               'Runs/missing.txt']), project)
    assert text['files'][0]['content'] == 'class 1 -> 2\n'
    assert text['files'][1]['missing'] is True
    message = translate(MessageView('No classes', 'Info', MSG_WARN), project)
    assert (message['kind'], message['level'], message['text']) == ('message', 'warning', 'No classes')
    command = translate(CommandView('chimera x.cxc'), project)
    assert (command['kind'], command['reason']) == ('unsupported', 'desktop_command')
    assert 'chimera' not in str(command)


def test_unknown_views_are_reported_by_class_name(project):
    from pyworkflow.viewer import View

    class PluginOnlyView(View):
        pass

    item = translate(PluginOnlyView(), project)
    assert item == {'kind': 'unsupported', 'viewClass': 'PluginOnlyView',
                    'reason': 'unknown_view'}


def test_shown_plotters_tables_and_pyplot_figures_are_captured_and_restored(project):
    from pyworkflow.gui.plotter import Plotter
    from pyworkflow.viewer import TextView
    import pwem.viewers.views as views
    import matplotlib.pyplot as plt

    original_show = TextView.show
    original_table_init = views.TableView.__init__
    collector = worker.ViewCollector()
    with worker.captureShownViews(collector):
        plotter = Plotter(mainTitle='Convergence')
        plotter.createSubPlot('Similarity', 'iteration', 'value').plot([1, 2], [3, 4])
        plotter.show()
        views.TableView(['class', 'size'], [(1, 10), (2, 20)], title='Sizes')
        figure = plt.figure()
        figure.add_subplot(111).plot([0, 1])
        plt.show()
    assert TextView.show is original_show
    assert views.TableView.__init__ is original_table_init

    items = [translate(view, project) for view in collector.views]
    plot = items[0]
    assert plot['kind'] == 'plot' and plot['title'] == 'Convergence'
    assert base64.b64decode(plot['data'])[:8] == b'\x89PNG\r\n\x1a\n'
    assert items[1] == {'kind': 'table', 'title': 'Sizes', 'message': '',
                        'header': ['class', 'size'], 'rows': [[1, 10], [2, 20]],
                        'truncated': False}
    assert [item['kind'] for item in items[2:]] == ['plot'] * (len(items) - 2)
    plt.close('all')


@pytest.mark.parametrize('field, value, expected', [
    ({'control': 'select', 'choices': ['last', 'selection']}, 1, 1),
    ({'control': 'select', 'choices': ['last', 'selection']}, 'selection', 1),
    ({'control': 'select', 'choices': ['last', 'selection']}, '0', 0),
    ({'control': 'boolean'}, 'true', True),
    ({'control': 'integer'}, ' 12 ', 12),
    ({'control': 'number'}, '0.5', 0.5),
    ({'control': 'numeric-range'}, '1-3,5', '1-3,5'),
])
def test_form_values_are_coerced_to_the_param_type(field, value, expected):
    assert worker._coerce_value(dict(field, label='Field'), value) == expected


@pytest.mark.parametrize('field, value', [
    ({'control': 'select', 'choices': ['last']}, 3),
    ({'control': 'boolean'}, 1),
    ({'control': 'integer'}, '1.5'),
    ({'control': 'number'}, 'nan?'),
    ({'control': 'text'}, True),
])
def test_invalid_form_values_are_rejected(field, value):
    with pytest.raises(worker.ViewerActionError) as error:
        worker._coerce_value(dict(field, label='Field'), value)
    assert error.value.code == 'invalid_values'


class FakeAttribute:
    def __init__(self, value=None):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeViewer:
    def __init__(self, handlers, errors=()):
        self.handlers = handlers
        self.errors = list(errors)
        self.level = FakeAttribute(0)

    def _getVisualizeDict(self):
        return self.handlers

    def validate(self):
        return self.errors


class FakeContext:
    def __init__(self, viewer, project):
        self.viewer = viewer
        self.project = FakeProject(project)
        self.protocol = None


@pytest.fixture
def fields(monkeypatch):
    monkeypatch.setattr(worker, 'editableViewerFields', lambda context: {
        'level': {'name': 'level', 'label': 'Level', 'control': 'select',
                  'choices': ['last', 'selection']},
    })
    monkeypatch.setattr(worker, 'OutputIndex', lambda *args: FakeOutputs())


def test_action_applies_values_and_collects_shown_and_returned_views(project, fields):
    from pyworkflow.viewer import MessageView
    from pwem.viewers.views import DataView

    def handler(name):
        assert viewer.level.get() == 1
        MessageView('shown by the handler').show()
        viewer.showError('Nothing selected')
        return [DataView('info@Runs/000115_CL2D/extra/level_classes.xmd')]

    viewer = FakeViewer({'showConvergence': handler})
    result = worker.runViewerAction(FakeContext(viewer, project), 'showConvergence',
                                    {'level': 'selection', 'unknown': 5})
    assert [item['kind'] for item in result['items']] == ['message', 'data']
    assert result['messages'] == [{'level': 'error', 'title': '', 'text': 'Nothing selected'}]


def test_unknown_action_validation_errors_and_handler_failures(project, fields):
    def broken(name):
        raise RuntimeError('missing level file')

    viewer = FakeViewer({'show': broken})
    with pytest.raises(worker.ViewerActionError) as error:
        worker.runViewerAction(FakeContext(viewer, project), 'other', {})
    assert error.value.code == 'unknown_action'
    with pytest.raises(worker.ViewerActionError) as error:
        worker.runViewerAction(FakeContext(viewer, project), 'show', {})
    assert (error.value.code, error.value.messages) == ('action_failed', ['missing level file'])
    viewer.errors = ['Select at least one level']
    with pytest.raises(worker.ViewerActionError) as error:
        worker.runViewerAction(FakeContext(viewer, project), 'show', {})
    assert (error.value.code, error.value.messages) == (
        'validation_failed', ['Select at least one level'])


def test_worker_request_shape_is_strict():
    request = {'projectId': 7, 'protocolId': 115, 'protocolDbId': 9253,
               'viewerId': 'xmipp3.viewers.viewer_cl2d.XmippCL2DViewer',
               'action': 'classesToShow', 'values': {}}
    assert worker._valid_request(request)
    for change in ({'action': 'not an action'}, {'values': []}, {'projectId': 0},
                   {'extra': 1}):
        assert not worker._valid_request(dict(request, **change))
