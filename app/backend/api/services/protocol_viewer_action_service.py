"""Run one ProtocolViewer action in a child process and validate its reply.

The worker runs the viewer's own visualize handler and translates the Views
it produces (see protocol_viewer_action_worker). This module authorizes the
request before any plugin code runs, and only forwards a validated subset of
the worker reply: no free-form plugin data reaches the web.
"""
from __future__ import annotations

import os
import re
from typing import Any, Mapping, Optional

from app.backend.api.services.protocol_viewer_dynamic_form_service import (
    DynamicProtocolViewerFormError, _run_worker,
)
from app.backend.api.services.protocol_viewer_settings_service import viewerEvaluationEnabled
from app.backend.api.services.protocol_viewer_file_token_service import (
    isSafeProjectRelativePath, signViewerFileToken,
)
from app.backend.api.services.protocol_viewer_persisted_resolution_service import (
    resolvePersistedProtocolViewerCandidates,
)

_WORKER_MODULE = 'app.backend.api.services.protocol_viewer_action_worker'
_REPLY_MARKER = b'__SCIPION_VIEWER_ACTION_JSON__:'
_MAX_REQUEST = 65536
_MAX_REPLY = 24 * 1024 * 1024
_DEFAULT_TIMEOUT = 120
_MAX_TIMEOUT = 1800
_MAX_ITEMS = 32
_MAX_MESSAGES = 32
_MAX_STRING = 2048
_VIEWER_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_.]{0,254}\Z')
_WORKER_ERRORS = frozenset({
    'invalid_values', 'validation_failed', 'action_failed', 'unknown_action',
})
_LEVELS = frozenset({'info', 'warning', 'error'})
_FORMATS = frozenset({'metadata', 'image', 'text', 'file'})


class ProtocolViewerActionError(RuntimeError):
    def __init__(self, code: str, messages=()):
        self.code = code
        self.messages = list(messages)
        super().__init__(code)


def _int_id(value) -> bool:
    return type(value) is int and 0 < value <= 2147483647


def actionTimeoutSeconds() -> int:
    raw = os.environ.get('SCIPION_PROTOCOL_VIEWER_ACTION_TIMEOUT', '')
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT
    return min(max(value, 5), _MAX_TIMEOUT)


def _valid_values(values) -> bool:
    if not isinstance(values, Mapping) or len(values) > 128:
        return False
    for name, value in values.items():
        if type(name) is not str or not name.isidentifier() or len(name) > 128:
            return False
        if not (value is None or type(value) in (bool, int, float)
                or (type(value) is str and len(value) <= _MAX_STRING)):
            return False
    return True


def _text(value, limit=_MAX_STRING) -> str:
    return value[:limit] if type(value) is str else ''


def _output_reference(value) -> Optional[dict]:
    if value is None:
        return None
    if (not isinstance(value, dict) or not _int_id(value.get('protocolId'))
            or type(value.get('outputName')) is not str
            or not value['outputName'].isidentifier()
            or type(value.get('className')) is not str):
        raise ProtocolViewerActionError('invalid_worker_reply')
    return {'protocolId': value['protocolId'], 'outputName': value['outputName'],
            'className': value['className'][:128]}


def _file_reference(project_id, path) -> Optional[dict]:
    if path is None:
        return None
    if not isSafeProjectRelativePath(path):
        raise ProtocolViewerActionError('invalid_worker_reply')
    return {'path': path, 'fileToken': signViewerFileToken(project_id, path)}


def _validated_item(project_id, item) -> dict:
    if not isinstance(item, dict):
        raise ProtocolViewerActionError('invalid_worker_reply')
    kind = item.get('kind')
    if kind == 'message':
        level = item.get('level')
        return {'kind': kind, 'level': level if level in _LEVELS else 'info',
                'title': _text(item.get('title'), 160), 'text': _text(item.get('text'))}
    if kind == 'plot':
        data = item.get('data')
        if type(data) is not str or not data or item.get('mediaType') != 'image/png':
            raise ProtocolViewerActionError('invalid_worker_reply')
        return {'kind': kind, 'title': _text(item.get('title'), 160),
                'mediaType': 'image/png', 'data': data}
    if kind == 'text':
        files = []
        for entry in item.get('files') or []:
            if not isinstance(entry, dict):
                raise ProtocolViewerActionError('invalid_worker_reply')
            reference = _file_reference(project_id, entry.get('path'))
            files.append({
                'name': _text(entry.get('name'), 255),
                'content': _text(entry.get('content'), 512 * 1024),
                'truncated': entry.get('truncated') is True,
                'missing': entry.get('missing') is True,
                **(reference or {'path': None, 'fileToken': None}),
            })
        return {'kind': kind, 'title': _text(item.get('title'), 160), 'files': files[:10]}
    if kind == 'image':
        reference = _file_reference(project_id, item.get('path'))
        if reference is None:
            raise ProtocolViewerActionError('invalid_worker_reply')
        return {'kind': kind, 'title': _text(item.get('title'), 160), **reference}
    if kind == 'table':
        header = item.get('header')
        rows = item.get('rows')
        if not isinstance(header, list) or not isinstance(rows, list):
            raise ProtocolViewerActionError('invalid_worker_reply')
        return {
            'kind': kind, 'title': _text(item.get('title'), 160),
            'message': _text(item.get('message')),
            'header': [_text(h, 160) for h in header[:64]],
            'rows': [[c if c is None or type(c) in (bool, int, float) else _text(c)
                      for c in (row if isinstance(row, list) else [])[:64]]
                     for row in rows[:5000]],
            'truncated': item.get('truncated') is True,
        }
    if kind == 'data':
        output = _output_reference(item.get('output'))
        reference = _file_reference(project_id, item.get('path'))
        if output is None and reference is None:
            raise ProtocolViewerActionError('invalid_worker_reply')
        view_params = item.get('viewParams') or {}
        index = item.get('index')
        table = item.get('table')
        return {
            'kind': kind,
            'viewClass': _text(item.get('viewClass'), 128),
            'title': _text(item.get('title'), 255),
            'format': item.get('format') if item.get('format') in _FORMATS else 'file',
            'table': table if type(table) is str and 0 < len(table) <= 128 else None,
            'index': index if _int_id(index) else None,
            'viewParams': {k: _text(v, 512) for k, v in view_params.items()
                           if type(k) is str and len(k) <= 32 and type(v) is str},
            'output': output,
            **(reference or {'path': None, 'fileToken': None}),
        }
    if kind == 'link':
        url = item.get('url')
        if (type(url) is not str or len(url) > _MAX_STRING
                or re.match(r'https?://[^\s]+\Z', url, re.I) is None):
            raise ProtocolViewerActionError('invalid_worker_reply')
        return {'kind': kind, 'url': url, 'title': _text(item.get('title'), 255)}
    if kind == 'unsupported':
        return {'kind': kind, 'viewClass': _text(item.get('viewClass'), 128),
                'reason': _text(item.get('reason'), 64),
                'detail': _text(item.get('detail'), 500)}
    raise ProtocolViewerActionError('invalid_worker_reply')


def _validated_reply(payload, request) -> dict:
    if not isinstance(payload, dict):
        raise ProtocolViewerActionError('invalid_worker_reply')
    if (payload.get('projectId') != request['projectId']
            or payload.get('protocolId') != str(request['protocolId'])
            or payload.get('viewerId') != request['viewerId']
            or payload.get('action') != request['action']):
        raise ProtocolViewerActionError('worker_identity_mismatch')
    messages = payload.get('messages') or []
    if not isinstance(messages, list):
        raise ProtocolViewerActionError('invalid_worker_reply')
    if payload.get('ok') is not True:
        code = payload.get('error')
        if code not in _WORKER_ERRORS:
            raise ProtocolViewerActionError('invalid_worker_reply')
        raise ProtocolViewerActionError(
            code, [_text(m) for m in messages[:_MAX_MESSAGES] if type(m) is str])
    items = payload.get('items')
    if payload.get('status') != 'viewer-action' or not isinstance(items, list):
        raise ProtocolViewerActionError('invalid_worker_reply')
    project_id = request['projectId']
    validated_messages = []
    for message in messages[:_MAX_MESSAGES]:
        if not isinstance(message, dict):
            raise ProtocolViewerActionError('invalid_worker_reply')
        level = message.get('level')
        validated_messages.append({
            'level': level if level in _LEVELS else 'info',
            'title': _text(message.get('title'), 160),
            'text': _text(message.get('text')),
        })
    omitted = payload.get('omittedItems', 0)
    return {
        'status': 'viewer-action',
        'projectId': project_id,
        'protocolId': str(request['protocolId']),
        'viewerId': request['viewerId'],
        'action': request['action'],
        'items': [_validated_item(project_id, item) for item in items[:_MAX_ITEMS]],
        'messages': validated_messages,
        'omittedItems': omitted if type(omitted) is int and 0 <= omitted <= 10000 else 0,
    }


def runProtocolViewerAction(
    *, mapper: Any, current_user: Mapping[str, Any], project_id: int,
    protocol_id: int, viewer_id: str, action: str, values: Mapping[str, Any],
    snapshot: Mapping[str, Any], timeout_seconds: Optional[int] = None,
    worker_runner=None,
) -> dict:
    """Authorize, then run the viewer handler for ``action`` in a child process."""
    if not viewerEvaluationEnabled():
        raise ProtocolViewerActionError('evaluation_disabled')
    if not (_int_id(project_id) and _int_id(protocol_id)
            and type(viewer_id) is str and _VIEWER_ID.fullmatch(viewer_id)
            and type(action) is str and action.isidentifier() and len(action) <= 128):
        raise ProtocolViewerActionError('invalid_identity')
    if not _valid_values(values):
        raise ProtocolViewerActionError('invalid_values')
    if (not isinstance(current_user, Mapping) or not _int_id(current_user.get('id'))
            or mapper is None or not callable(getattr(mapper, 'getProject', None))):
        raise ProtocolViewerActionError('unauthorized')
    if not mapper.getProject(projectId=project_id, userId=current_user['id']):
        raise ProtocolViewerActionError('unauthorized')
    candidates = resolvePersistedProtocolViewerCandidates(
        mapper=mapper, project_id=project_id, protocol_id=protocol_id,
        snapshot=snapshot)
    choices = [item for item in candidates['viewers']
               if item.get('id') == viewer_id and item.get('viewerKind') == 'protocol-form']
    if len(choices) != 1:
        raise ProtocolViewerActionError('viewer_not_applicable')
    request = {'projectId': project_id, 'protocolId': protocol_id,
               'protocolDbId': candidates['protocolDbId'], 'viewerId': viewer_id,
               'action': action, 'values': dict(values)}
    timeout = actionTimeoutSeconds() if timeout_seconds is None else timeout_seconds
    try:
        if worker_runner is None:
            reply = _run_worker(request, timeout, module=_WORKER_MODULE,
                                marker=_REPLY_MARKER, max_request=_MAX_REQUEST,
                                max_reply=_MAX_REPLY)
        else:
            reply = worker_runner(request, timeout)
    except DynamicProtocolViewerFormError as exc:
        raise ProtocolViewerActionError(exc.code) from exc
    return _validated_reply(reply, request)
