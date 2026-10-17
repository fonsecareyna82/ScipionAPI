"""One-shot trusted worker that runs one ProtocolViewer action for the web.

The desktop calls ``viewer._getVisualizeDict()[param](param)`` and then
``show()`` on every returned View. Here the same handler runs with every
``show()`` intercepted, and each View is translated into a JSON descriptor
that ScipionWeb renders with its own viewers.

Like the form worker, this child protects the API from crashes and timeouts;
it is not a sandbox for the installed plugins' code.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
from contextlib import contextmanager

from app.backend.api.services.protocol_viewer_settings_service import viewerEvaluationEnabled
from app.backend.api.services.protocol_viewer_dynamic_form_worker import (
    _CONTROL_TYPES, loadRuntimeViewer, serializeRuntimeViewerDefinition,
)

REPLY_MARKER = b'__SCIPION_VIEWER_ACTION_JSON__:'
MAX_REQUEST = 65536
MAX_REPLY = 24 * 1024 * 1024
MAX_ITEMS = 32
MAX_MESSAGES = 32
MAX_TEXT_FILES = 10
MAX_TEXT_BYTES = 512 * 1024
MAX_PLOT_BYTES = 6 * 1024 * 1024
MAX_TABLE_ROWS = 5000
MAX_TABLE_COLUMNS = 64
MAX_STRING = 2048

METADATA_EXTENSIONS = frozenset({'sqlite', 'db', 'star', 'xmd'})
IMAGE_EXTENSIONS = frozenset({
    'mrc', 'mrcs', 'map', 'st', 'ali', 'rec', 'em', 'stk', 'spi', 'xmp',
    'vol', 'tif', 'tiff', 'png', 'jpg', 'jpeg', 'hdf', 'dm4',
})
TEXT_EXTENSIONS = frozenset({'txt', 'log', 'json', 'csv', 'out', 'err', 'tsv'})
VIEW_PARAM_KEYS = frozenset({
    'mode', 'visible', 'order', 'render', 'zoom', 'sortby', 'labels',
})
_INDEXED_PATH = re.compile(r'(\d+)@(.+)\Z', re.S)


class ViewerActionError(Exception):
    """An expected failure reported to the web with a stable code."""

    def __init__(self, code, messages=()):
        super().__init__(code)
        self.code = code
        self.messages = [str(m)[:MAX_STRING] for m in messages][:MAX_MESSAGES]


# ------------------------------------------------------------------------------
# Capture of shown Views
# ------------------------------------------------------------------------------

def _all_subclasses(cls):
    seen, pending = set(), [cls]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(current.__subclasses__())
    return seen


class CapturedTable:
    """Data of a TableView, whose constructor would open a Tk window."""

    def __init__(self, headerList, dataList, mesg=None, title=None, **kwargs):
        self.headerList = headerList
        self.dataList = dataList
        self.mesg = mesg
        self.title = title


class ViewCollector:
    """Ordered, de-duplicated Views and messages produced by one action."""

    def __init__(self):
        self.views = []
        self.messages = []
        self._seen = set()

    def addView(self, view):
        if view is None or id(view) in self._seen:
            return
        self._seen.add(id(view))
        self.views.append(view)

    def addMessage(self, level, text, title=''):
        if len(self.messages) < MAX_MESSAGES:
            self.messages.append({
                'level': level,
                'title': str(title or '')[:160],
                'text': str(text or '')[:MAX_STRING],
            })


@contextmanager
def captureShownViews(collector, view_base=None):
    """Replace show() on every loaded View class (and pyplot.show) by capture.

    Viewers may call show() themselves or return the Views; both end up in the
    collector. Originals are restored on exit.
    """
    import matplotlib
    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt

    if view_base is None:
        from pyworkflow.viewer import View as view_base
    try:
        import pwem.viewers.views as pwem_views
    except ImportError:
        pwem_views = None

    patched = []

    def capture(view, *args, **kwargs):
        collector.addView(view)

    for cls in _all_subclasses(view_base):
        if 'show' in cls.__dict__:
            patched.append((cls, 'show', cls.__dict__['show']))
            cls.show = capture

    table_cls = getattr(pwem_views, 'TableView', None)
    if table_cls is not None:
        original_init = table_cls.__dict__['__init__']

        def table_init(view, headerList, dataList, mesg=None, title=None,
                       *args, **kwargs):
            collector.addView(CapturedTable(headerList, dataList, mesg, title))

        patched.append((table_cls, '__init__', original_init))
        table_cls.__init__ = table_init

    original_plt_show = plt.show

    def plt_show(*args, **kwargs):
        for number in plt.get_fignums():
            collector.addView(plt.figure(number))

    plt.show = plt_show
    try:
        yield collector
    finally:
        plt.show = original_plt_show
        for cls, name, original in reversed(patched):
            setattr(cls, name, original)


def _install_message_hooks(viewer, collector):
    """Desktop viewers report problems through showError/showInfo dialogs."""
    def window_hook(level):
        # FormWindow.showError(msg, header=...) as assigned by visualize().
        def show(msg='', header='', *args, **kwargs):
            collector.addMessage(level, msg, header or kwargs.get('title', ''))
        return show

    def dialog_hook(level):
        # pyworkflow.gui.dialog.showError(title, msg, parent).
        def show(title='', msg='', *args, **kwargs):
            collector.addMessage(level, msg, title)
        return show

    levels = (('showError', 'error'), ('showInfo', 'info'),
              ('showWarning', 'warning'))
    for name, level in levels:
        try:
            setattr(viewer, name, window_hook(level))
        except Exception:
            pass
    try:
        import pyworkflow.gui.dialog as dialog
        for name, level in levels:
            setattr(dialog, name, dialog_hook(level))
    except Exception:
        pass


# ------------------------------------------------------------------------------
# Form values
# ------------------------------------------------------------------------------

def editableViewerFields(context):
    """Fields the web form shows for this viewer: name -> serialized field."""
    schema = serializeRuntimeViewerDefinition(
        context.viewer._definition, inherited_field_names=context.baseline,
        hidden_declarations=context.hidden_declarations)
    fields = {}
    for section in schema['sections']:
        for field in section['fields']:
            fields[field['name']] = field
        for group in section['groups']:
            for field in group['fields']:
                fields[field['name']] = field
    for entry in schema.get('conditionalFields', ()):
        fields.setdefault(entry['field']['name'], entry['field'])
    return fields


def _coerce_value(field, value):
    control = field['control']
    if control == 'boolean':
        if type(value) is bool:
            return value
        if value in ('true', 'false'):
            return value == 'true'
    elif control == 'integer':
        if type(value) is int:
            return value
        if type(value) is str and re.fullmatch(r'-?\d{1,18}', value.strip()):
            return int(value)
    elif control == 'number':
        if type(value) in (int, float):
            return float(value)
        if type(value) is str:
            try:
                return float(value)
            except ValueError:
                pass
    elif control == 'select':
        choices = field.get('choices') or []
        if type(value) is int and 0 <= value < len(choices):
            return value
        if type(value) is str:
            if value.isdigit() and int(value) < len(choices):
                return int(value)
            if value in choices:
                return choices.index(value)
    elif control in ('text', 'multiline', 'numeric-range'):
        if type(value) in (str, int, float) and type(value) is not bool:
            text = str(value)
            if len(text) <= MAX_STRING:
                return text
    raise ViewerActionError('invalid_values',
                            ["Invalid value for '%s'" % field['label']])


def applyViewerValues(context, values):
    """Set the web form values on the viewer attributes the form defines."""
    if not isinstance(values, dict):
        raise ViewerActionError('invalid_values')
    fields = editableViewerFields(context)
    for name, value in values.items():
        field = fields.get(name)
        if field is None or field['control'] == 'label':
            continue  # Unknown or display-only names are ignored.
        if value is None:
            continue
        attribute = getattr(context.viewer, name, None)
        if attribute is None or not callable(getattr(attribute, 'set', None)):
            continue
        attribute.set(_coerce_value(field, value))


# ------------------------------------------------------------------------------
# Translation of Views into web descriptors
# ------------------------------------------------------------------------------

class PathResolver:
    """Map plugin paths to paths relative to the project folder."""

    def __init__(self, project_path):
        self.root = os.path.realpath(project_path)

    def relative(self, path):
        if type(path) is not str or not path or '\x00' in path:
            return None
        absolute = path if os.path.isabs(path) else os.path.join(self.root, path)
        real = os.path.realpath(absolute)
        try:
            if os.path.commonpath([real, self.root]) != self.root:
                return None
        except ValueError:
            return None
        if not os.path.exists(real):
            return None
        relative = os.path.relpath(real, self.root)
        return None if relative == '.' else relative


class OutputIndex:
    """Find which stored protocol output a Scipion object id refers to."""

    def __init__(self, project, protocol, project_id=None):
        self._project = project
        self._protocol = protocol
        self._project_id = project_id
        self._own = None
        self._stored = {}

    @staticmethod
    def _collect(protocol, target):
        try:
            for name, output in protocol.iterOutputAttributes():
                object_id = output.getObjId()
                if object_id is not None:
                    target.setdefault(int(object_id), {
                        'protocolId': int(protocol.getObjId()),
                        'outputName': name,
                        'className': output.getClassName(),
                    })
        except Exception:
            pass

    def find(self, object_id):
        try:
            object_id = int(object_id)
        except (TypeError, ValueError):
            return None
        if self._own is None:
            self._own = {}
            self._collect(self._protocol, self._own)
        if object_id in self._own:
            return self._own[object_id]
        if object_id not in self._stored:
            self._stored[object_id] = self._find_stored(object_id)
        return self._stored[object_id]

    def _find_stored(self, object_id):
        """Outputs of other protocols (e.g. a viewer showing the inputs)."""
        db = getattr(getattr(self._project, 'mapper', None), 'db', None)
        if db is None or self._project_id is None:
            return None
        try:
            rows = db.fetchAll(
                """
                SELECT COALESCE(NULLIF(o.path, ''), o.name) AS "outputName",
                       o."className", p."protocolId"
                  FROM scipion_objects o
                  JOIN protocols p ON p.id = o."protocolDbId"
                 WHERE o."projectId" = %s
                   AND o."scipionObjId" = %s
                   AND o."parentObjectId" IS NULL
                """,
                (self._project_id, object_id),
            ) or []
        except Exception:
            return None
        if len(rows) != 1:
            return None
        row = rows[0]
        name = str(row.get('outputName') or '')
        try:
            protocol_id = int(row.get('protocolId'))
        except (TypeError, ValueError):
            return None
        if not name.isidentifier():
            return None
        return {'protocolId': protocol_id, 'outputName': name,
                'className': str(row.get('className') or '')}


def _extension(path):
    base = os.path.basename(path or '')
    return base.rsplit('.', 1)[-1].lower() if '.' in base else ''


def _file_format(path):
    extension = _extension(path)
    if extension in METADATA_EXTENSIONS:
        return 'metadata'
    if extension in IMAGE_EXTENSIONS:
        return 'image'
    if extension in TEXT_EXTENSIONS:
        return 'text'
    return 'file'


def _unsupported(view, reason):
    return {
        'kind': 'unsupported',
        'viewClass': type(view).__name__,
        'reason': reason,
    }


def _scalar_cell(value):
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float('inf') else None
    try:
        import numpy as np
        if isinstance(value, np.generic):
            return _scalar_cell(value.item())
    except ImportError:
        pass
    return str(value)[:MAX_STRING]


def _figure_png(figure):
    buffer = io.BytesIO()
    figure.savefig(buffer, format='png', dpi=min(int(figure.dpi or 100), 150),
                   bbox_inches='tight')
    data = buffer.getvalue()
    if len(data) > MAX_PLOT_BYTES:
        return None
    return base64.b64encode(data).decode('ascii')


def _figure_title(figure, default=''):
    try:
        suptitle = figure._suptitle.get_text() if figure._suptitle else ''
    except Exception:
        suptitle = ''
    if suptitle:
        return suptitle[:160]
    try:
        for axes in figure.get_axes():
            title = axes.get_title()
            if title:
                return title[:160]
    except Exception:
        pass
    return default


def _translate_plot(view, figure):
    try:
        try:
            if getattr(view, 'tightLayoutOn', False):
                figure.tight_layout()
        except Exception:
            pass
        png = _figure_png(figure)
    except Exception as exc:
        return {'kind': 'unsupported', 'viewClass': type(view).__name__,
                'reason': 'plot_render_failed', 'detail': str(exc)[:500]}
    if png is None:
        return _unsupported(view, 'plot_too_large')
    return {'kind': 'plot', 'title': _figure_title(figure, 'Plot'),
            'mediaType': 'image/png', 'data': png}


def _translate_text(view, resolver):
    files = []
    for path in list(view.getFileList() or [])[:MAX_TEXT_FILES]:
        relative = resolver.relative(path)
        if relative is None or not os.path.isfile(os.path.join(resolver.root, relative)):
            files.append({'path': None, 'name': os.path.basename(str(path)),
                          'content': '', 'missing': True})
            continue
        with open(os.path.join(resolver.root, relative), 'rb') as handle:
            raw = handle.read(MAX_TEXT_BYTES + 1)
        files.append({
            'path': relative, 'name': os.path.basename(relative),
            'content': raw[:MAX_TEXT_BYTES].decode('utf-8', errors='replace'),
            'truncated': len(raw) > MAX_TEXT_BYTES,
        })
    return {'kind': 'text', 'title': str(getattr(view, '_title', '') or '')[:160],
            'files': files}


def _translate_data(view, resolver, outputs):
    raw_path = view.getPath() if callable(getattr(view, 'getPath', None)) else None
    table = view.getTableName() if callable(getattr(view, 'getTableName', None)) else None
    index = None
    if type(raw_path) is str:
        match = _INDEXED_PATH.match(raw_path)
        if match:
            index, raw_path = int(match.group(1)), match.group(2)
    view_params = {}
    try:
        for key, value in dict(view.getViewParams() or {}).items():
            if key in VIEW_PARAM_KEYS and type(value) in (str, int, float):
                view_params[key] = str(value)[:512]
    except Exception:
        pass

    output = None
    input_id = getattr(view, 'inputid', None)
    if input_id is not None:
        output = outputs.find(input_id)
    relative = resolver.relative(raw_path)
    if output is None and relative is None:
        unsupported = _unsupported(view, 'file_outside_project')
        unsupported['detail'] = 'object %s, file %s' % (
            input_id, os.path.basename(str(raw_path or '')))
        return unsupported
    descriptor = {
        'kind': 'data',
        'viewClass': type(view).__name__,
        'title': os.path.basename(raw_path or '') or type(view).__name__,
        'format': _file_format(raw_path),
        'path': relative,
        'table': table if type(table) is str and table else None,
        'index': index,
        'viewParams': view_params,
        'output': output,
    }
    return descriptor


def _translate_md_view(view, resolver, outputs):
    em_set = getattr(view, '_emSet', None)
    output = outputs.find(getattr(em_set, 'getObjId', lambda: None)())
    if output is None:
        return _unsupported(view, 'set_not_stored')
    return {'kind': 'data', 'viewClass': type(view).__name__,
            'title': output['outputName'], 'format': 'metadata', 'path': None,
            'table': None, 'index': None, 'viewParams': {}, 'output': output}


def translateView(view, resolver, outputs):
    """Return one JSON-safe descriptor for a captured View."""
    from matplotlib.figure import Figure

    if isinstance(view, CapturedTable):
        header = [str(h)[:160] for h in list(view.headerList or [])[:MAX_TABLE_COLUMNS]]
        rows = []
        for row in list(view.dataList or [])[:MAX_TABLE_ROWS]:
            rows.append([_scalar_cell(c) for c in list(row)[:MAX_TABLE_COLUMNS]])
        return {'kind': 'table', 'title': str(view.title or '')[:160],
                'message': str(view.mesg or '')[:MAX_STRING],
                'header': header, 'rows': rows,
                'truncated': len(view.dataList or []) > MAX_TABLE_ROWS}
    if isinstance(view, Figure):
        return _translate_plot(view, view)

    names = {cls.__name__ for cls in type(view).__mro__}
    figure = getattr(view, 'figure', None)
    if 'Plotter' in names and isinstance(figure, Figure):
        return _translate_plot(view, figure)
    if 'MessageView' in names:
        level = {0: 'info', 1: 'warning', 2: 'error'}.get(
            getattr(view, '_msgType', 0), 'info')
        return {'kind': 'message', 'level': level,
                'title': str(getattr(view, '_title', '') or '')[:160],
                'text': str(getattr(view, '_msg', '') or '')[:MAX_STRING]}
    if 'TextView' in names:
        return _translate_text(view, resolver)
    if 'CommandView' in names:
        return _unsupported(view, 'desktop_command')
    if 'CoordinatesObjectView' in names:
        return _unsupported(view, 'desktop_picker')
    if 'ImageView' in names:
        relative = resolver.relative(getattr(view, '_imagePath', None))
        if relative is None:
            return _unsupported(view, 'file_outside_project')
        return {'kind': 'image', 'title': os.path.basename(relative),
                'path': relative}
    if 'MDView' in names:
        return _translate_md_view(view, resolver, outputs)
    if 'DataView' in names:
        return _translate_data(view, resolver, outputs)
    return _unsupported(view, 'unknown_view')


# ------------------------------------------------------------------------------
# Action execution
# ------------------------------------------------------------------------------

def _flatten(views):
    if views is None:
        return []
    if not isinstance(views, (list, tuple)):
        return [views]
    flat = []
    for view in views:
        flat.extend(_flatten(view))
    return flat


def runViewerAction(context, action, values, project_id=None):
    viewer = context.viewer
    try:
        visualize = viewer._getVisualizeDict()
    except Exception as exc:
        raise ViewerActionError('action_failed', [str(exc)]) from exc
    if type(action) is not str or action not in visualize:
        raise ViewerActionError('unknown_action')
    applyViewerValues(context, values)

    collector = ViewCollector()
    _install_message_hooks(viewer, collector)
    errors = viewer.validate()
    if errors:
        raise ViewerActionError('validation_failed', errors)

    with captureShownViews(collector):
        try:
            returned = visualize[action](action)
        except ViewerActionError:
            raise
        except Exception as exc:
            import traceback
            traceback.print_exc(file=sys.stderr)
            raise ViewerActionError('action_failed', [str(exc) or type(exc).__name__]) from exc
        for view in _flatten(returned):
            collector.addView(view)

    resolver = PathResolver(context.project.getPath())
    outputs = OutputIndex(context.project, context.protocol, project_id)
    items = []
    for view in collector.views[:MAX_ITEMS]:
        try:
            items.append(translateView(view, resolver, outputs))
        except Exception as exc:
            items.append({'kind': 'unsupported', 'viewClass': type(view).__name__,
                          'reason': 'translation_failed', 'detail': str(exc)[:500]})
    return {'items': items, 'messages': collector.messages,
            'omittedItems': max(0, len(collector.views) - MAX_ITEMS)}


def _run(request):
    identity = {
        'projectId': request['projectId'],
        'protocolId': str(request['protocolId']),
        'viewerId': request['viewerId'],
        'action': request['action'],
    }
    try:
        with loadRuntimeViewer(request) as context:
            result = runViewerAction(context, request['action'], request['values'],
                                     request['projectId'])
    except ViewerActionError as exc:
        return {'ok': False, 'error': exc.code, 'messages': exc.messages, **identity}
    return {'ok': True, 'status': 'viewer-action', **identity, **result}


def _valid_request(request):
    return (
        isinstance(request, dict)
        and set(request) == {'projectId', 'protocolId', 'protocolDbId',
                             'viewerId', 'action', 'values'}
        and all(type(request[k]) is int and request[k] > 0
                for k in ('projectId', 'protocolId', 'protocolDbId'))
        and type(request['viewerId']) is str and len(request['viewerId']) <= 255
        and type(request['action']) is str and request['action'].isidentifier()
        and len(request['action']) <= 128
        and isinstance(request['values'], dict) and len(request['values']) <= 128
    )


def main() -> int:
    if (os.environ.get('SCIPION_VIEWER_FORM_CHILD') != '1' or
            not viewerEvaluationEnabled()):
        return 2
    raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
    if len(raw) > MAX_REQUEST:
        return 2
    try:
        request = json.loads(raw)
        if not _valid_request(request):
            return 2
        result = _run(request)
        wire = json.dumps(result, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
        if len(wire) > MAX_REPLY:
            return 3
        sys.stdout.buffer.write(REPLY_MARKER + wire + b'\n')
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
