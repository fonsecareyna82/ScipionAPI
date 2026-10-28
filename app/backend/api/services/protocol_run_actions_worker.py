"""One-shot trusted worker that lists or runs the actions a protocol offers while it runs.

The desktop shows them in the context menu of a run: ``protocol.getActions()`` gives ``(label, callback)``
pairs, such as STOP STREAMING of a streaming import or APPROVE CHECKPOINT of a checkpoint. The protocol
runs in another process, so the callbacks only leave a file in its run folder that it looks for (e.g.
``extra/STOP_STREAMING.TXT``): the import then closes its output and finishes on its own.

The project is loaded with its folder as the working directory, so the callbacks write where the running
protocol looks. Like the viewer workers, this child keeps plugin code out of the API process; it is not a
sandbox for the installed plugins.
"""
from __future__ import annotations

import inspect
import json
import os
import sys

from app.backend.api.services.protocol_viewer_dynamic_form_worker import loadRuntimeProtocol

REPLY_MARKER = b'__SCIPION_RUN_ACTIONS_JSON__:'
MAX_REQUEST = 4096
MAX_REPLY = 65536
MAX_LABEL = 128


def _actions(protocol):
    """The (label, callback) pairs the protocol offers now; a plugin failing here offers none."""
    try:
        actions = protocol.getActions() or []
    except Exception:
        import traceback
        traceback.print_exc(file=sys.stderr)
        return []
    return [(label, callback) for label, callback in actions
            if type(label) is str and 0 < len(label) <= MAX_LABEL and callable(callback)]


def _call(callback):
    """Desktop callbacks get the menu event or nothing (``stopImport(self, e)``, ``stopWait(self)``)."""
    try:
        required = [parameter for parameter in inspect.signature(callback).parameters.values()
                    if parameter.default is inspect.Parameter.empty
                    and parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)]
    except (TypeError, ValueError):
        required = []
    return callback(*([None] * len(required)))


def _run(request: dict) -> dict:
    with loadRuntimeProtocol(request) as (_mapper, _project, protocol):
        actions = _actions(protocol)
        wanted = request.get('action')
        if wanted is None:
            return {'actions': [label for label, _ in actions]}
        callback = next((callback for label, callback in actions if label == wanted), None)
        if callback is None:
            return {'error': 'unknown_action'}
        _call(callback)
        return {'ran': wanted}


def _valid_request(request) -> bool:
    if not isinstance(request, dict) or set(request) != {'projectId', 'protocolId', 'protocolDbId', 'action'}:
        return False
    if any(type(request[key]) is not int or request[key] <= 0 for key in ('projectId', 'protocolId', 'protocolDbId')):
        return False
    action = request['action']
    return action is None or (type(action) is str and 0 < len(action) <= MAX_LABEL)


def main() -> int:
    if os.environ.get('SCIPION_VIEWER_FORM_CHILD') != '1':
        return 2
    raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
    if len(raw) > MAX_REQUEST:
        return 2
    try:
        request = json.loads(raw)
        if not _valid_request(request):
            return 2
        wire = json.dumps(_run(request), separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
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
