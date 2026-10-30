"""A protocol's summary (the desktop Summary tab), computed in a child process.

The request is authorized here, before any plugin code runs; the child loads the project and the
protocol, runs ``summary()`` and answers its lines and the objects they link to.
"""
from __future__ import annotations

from typing import Any, Mapping

from app.backend.api.services.protocol_viewer_dynamic_form_service import (
    DynamicProtocolViewerFormError, _run_worker,
)

_WORKER_MODULE = 'app.backend.api.services.protocol_summary_worker'
_REPLY_MARKER = b'__SCIPION_SUMMARY_JSON__:'
_MAX_REQUEST = 4096
_MAX_REPLY = 262144
_TIMEOUT = 60
_MAX_LINES = 400
_MAX_LINE = 4000


class ProtocolSummaryError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _int_id(value) -> bool:
    return type(value) is int and 0 < value <= 2147483647


def _objects(value) -> dict:
    """The linked objects of the reply, each with an int protocolId and a valid output name."""
    if not isinstance(value, dict):
        return {}
    objects = {}
    for objId, item in value.items():
        if not (isinstance(objId, str) and objId.isdigit() and isinstance(item, dict)):
            continue
        name = item.get('outputName')
        if not (_int_id(item.get('protocolId')) and isinstance(name, str) and name.isidentifier()):
            continue
        objects[objId] = {'protocolId': item['protocolId'], 'outputName': name,
                          'className': str(item.get('className') or ''), 'label': str(item.get('label') or name)}
    return objects


def getProtocolSummary(*, mapper: Any, current_user: Mapping[str, Any], project_id: int, protocol_id: int,
                       worker_runner=None) -> dict:
    """{lines, objects, hasWarnings} of the protocol, for a user who may see its project."""
    if not (_int_id(project_id) and _int_id(protocol_id)):
        raise ProtocolSummaryError('invalid_identity')
    if (not isinstance(current_user, Mapping) or not _int_id(current_user.get('id'))
            or mapper is None or not mapper.getProject(projectId=project_id, userId=current_user['id'])):
        raise ProtocolSummaryError('unauthorized')
    row = mapper.getProjectProtocolByProtocolId(projectId=project_id, protocolId=protocol_id)
    if not isinstance(row, dict):
        raise ProtocolSummaryError('not_found')
    request = {'projectId': project_id, 'protocolId': protocol_id, 'protocolDbId': int(row['id'])}
    try:
        if worker_runner is not None:
            reply = worker_runner(request, _TIMEOUT)
        else:
            reply = _run_worker(request, _TIMEOUT, module=_WORKER_MODULE, marker=_REPLY_MARKER,
                                max_request=_MAX_REQUEST, max_reply=_MAX_REPLY)
    except DynamicProtocolViewerFormError as exc:
        raise ProtocolSummaryError(exc.code) from exc
    lines = reply.get('lines') if isinstance(reply, dict) else None
    if not isinstance(lines, list):
        raise ProtocolSummaryError('invalid_reply')
    return {
        'lines': [str(line)[:_MAX_LINE] for line in lines][:_MAX_LINES],
        'objects': _objects(reply.get('objects')),
        'hasWarnings': bool(reply.get('hasWarnings')),
    }
