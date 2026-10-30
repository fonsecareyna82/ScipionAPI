"""One-shot trusted worker that gives a protocol's summary, as the desktop Summary tab shows it.

``protocol.summary()`` runs the plugin's ``_summary()`` (most read the outputs or ``summaryVar``) and adds
the protocol's comment, error and warnings. The lines keep Scipion's markup (``*bold*``, ``_italic_``,
links); the web draws it. Objects linked with ``[[sci-open:ID][name]]`` are told by their id: the
protocol and output they are, so the web opens them in the viewer of that output.

Like the viewer workers, this child keeps plugin code out of the API process; it is not a sandbox for
the installed plugins.
"""
from __future__ import annotations

import json
import os
import sys

from app.backend.api.services.protocol_viewer_dynamic_form_worker import (
    attachStoredOutputs, loadRuntimeProtocol, restoreProtocolInputs,
)

REPLY_MARKER = b'__SCIPION_SUMMARY_JSON__:'
MAX_REQUEST = 4096
MAX_REPLY = 262144
MAX_LINES = 400
MAX_LINE = 4000
MAX_OBJECTS = 200


def _outputName(name) -> str:
    """The output an attribute name or a pointer's extension names (``outputCoordinates.12`` is an item)."""
    name = str(name or '')
    return name if name.isidentifier() else ''


def _linkedObjects(protocol) -> dict:
    """{object id: {protocolId, outputName, className, label}} of the protocol's outputs and inputs."""
    objects = {}

    def add(obj, protocolId, outputName):
        objId = obj.getObjId() if obj is not None else None
        if objId is None or not outputName or len(objects) >= MAX_OBJECTS:
            return
        objects[str(objId)] = {'protocolId': int(protocolId), 'outputName': outputName,
                               'className': obj.getClassName(), 'label': obj.getObjLabel() or outputName}

    for name, output in protocol.iterOutputAttributes():
        add(output, protocol.getObjId(), _outputName(name))
    for _key, pointer in protocol.iterInputAttributes():
        try:
            producer = pointer.getObjValue()
            if producer is None or not hasattr(producer, 'getObjId') or not pointer.hasExtended():
                continue
            add(pointer.get(), producer.getObjId(), _outputName(pointer.getExtended()))
        except Exception:
            continue
    return objects


def _run(request: dict) -> dict:
    with loadRuntimeProtocol(request) as (mapper, project, protocol):
        # Most summaries read the inputs and the outputs, as the desktop project load gives them
        try:
            restoreProtocolInputs(mapper, project, protocol, request['projectId'], request['protocolId'])
        except Exception:
            import traceback
            traceback.print_exc(file=sys.stderr)
        attachStoredOutputs(project, protocol, request['projectId'], request['protocolDbId'])
        try:
            protocol.checkSummaryWarnings()
        except Exception:
            pass
        # summary() catches the plugin's errors and shows them as its lines
        lines = [str(line)[:MAX_LINE] for line in (protocol.summary() or [])][:MAX_LINES]
        try:
            objects = _linkedObjects(protocol)
        except Exception:
            objects = {}
        return {'lines': lines, 'objects': objects, 'hasWarnings': bool(protocol.hasSummaryWarnings())}


def _valid_request(request) -> bool:
    return (isinstance(request, dict) and set(request) == {'projectId', 'protocolId', 'protocolDbId'}
            and all(type(request[key]) is int and request[key] > 0 for key in request))


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
