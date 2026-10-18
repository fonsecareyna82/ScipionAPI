"""Worker process that runs one wizard of a protocol viewer's form.

Viewer forms have wizards too (e.g. the color scale of local resolution
viewers): the desktop opens them with the viewer as the form's "protocol".
The viewer is loaded as for its actions, with the web form values applied,
and the wizard runs as in protocol_wizard_runtime.
"""
from __future__ import annotations

import json
import os
import sys

from app.backend.api.services.protocol_viewer_settings_service import viewerEvaluationEnabled
from app.backend.api.services.protocol_wizard_runtime_worker import (
    MAX_ANSWERS, desktopWizards, wizardIdentity)

REPLY_MARKER = b'__SCIPION_VIEWER_WIZARD_JSON__:'
MAX_REQUEST = 1024 * 1024
MAX_REPLY = 24 * 1024 * 1024
MAX_VIEWS = 16


def _run(request):
    from pyworkflow import Config
    from app.backend.api.services.protocol_viewer_action_worker import (
        OutputIndex, PathResolver, ViewerActionError, applyViewerValues, translateView)
    from app.backend.api.services.protocol_viewer_dynamic_form_worker import loadRuntimeViewer
    from app.backend.api.services.protocol_viewer_settings_service import workerDesktopDisplay
    from app.backend.api.services.protocol_wizard_runtime import runWizard

    with loadRuntimeViewer(request) as context:
        try:
            applyViewerValues(context, request['values'])
        except ViewerActionError as exc:
            return {'status': 'invalid', 'errors': [str(message)[:500] for message in exc.messages[:20]]
                    or ['Invalid viewer values']}
        wizardClass = desktopWizards(Config.getDomain(), context.viewer).get(request['paramName'])
        if wizardClass is None or wizardIdentity(wizardClass) != request['wizardId']:
            return {'status': 'failed', 'error': 'wizard_not_found'}
        reply = runWizard(wizardClass, context.viewer, request['paramName'],
                          answers=request['answers'], preview=request['preview'])
        views = reply.pop('views', None) or []
        if views:
            resolver = PathResolver(context.project.getPath())
            outputs = OutputIndex(context.project, context.protocol, request['projectId'])
            items = []
            for view in views[:MAX_VIEWS]:
                try:
                    items.append(translateView(view, resolver, outputs, workerDesktopDisplay()))
                except Exception as exc:
                    items.append({'kind': 'unsupported', 'viewClass': type(view).__name__,
                                  'reason': 'translation_failed', 'detail': str(exc)[:500]})
            reply['items'] = items
        return reply


def validRequest(request) -> bool:
    return (
        isinstance(request, dict)
        and set(request) == {'projectId', 'protocolId', 'protocolDbId', 'viewerId', 'values',
                             'paramName', 'wizardId', 'answers', 'preview'}
        and all(type(request[key]) is int and request[key] > 0
                for key in ('projectId', 'protocolId', 'protocolDbId'))
        and type(request['viewerId']) is str and 0 < len(request['viewerId']) <= 255
        and isinstance(request['values'], dict) and len(request['values']) <= 128
        and type(request['paramName']) is str and request['paramName'].isidentifier()
        and len(request['paramName']) <= 128
        and type(request['wizardId']) is str and 0 < len(request['wizardId']) <= 512
        and isinstance(request['answers'], list) and len(request['answers']) <= MAX_ANSWERS
        and all(isinstance(answer, dict) for answer in request['answers'])
        and (request['preview'] is None or isinstance(request['preview'], dict))
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
        if not validRequest(request):
            return 2
        result = _run(request)
        wire = json.dumps(result, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False, default=str).encode('utf-8')
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
