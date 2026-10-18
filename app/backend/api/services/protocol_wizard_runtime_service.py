"""Runs protocol form wizards in a worker process (protocol_wizard_runtime_worker).

The API process authorizes the request and validates the reply; the wizard's
plugin code only runs in the worker, forked from the warm viewer worker when
there is one, like the protocol viewers.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Mapping

from fastapi import HTTPException, status

from app.backend.api.services.protocol_viewer_dynamic_form_service import (
    DynamicProtocolViewerFormError, _run_worker)
from app.backend.api.services.protocol_viewer_settings_service import viewerEvaluationEnabled
from app.backend.api.services.protocol_wizard_runtime_worker import (
    MAX_REPLY, MAX_REQUEST, REPLY_MARKER, validRequest)

logger = logging.getLogger(__name__)

WORKER_MODULE = 'app.backend.api.services.protocol_wizard_runtime_worker'
TIMEOUT_SWITCH = 'SCIPION_PROTOCOL_WIZARD_TIMEOUT'
DEFAULT_TIMEOUT = 180
REPLY_STATUSES = frozenset({'done', 'dialog', 'preview', 'cancelled', 'failed', 'invalid', 'unsupported'})

_WORKER_ERRORS = {
    'worker_timeout': (status.HTTP_504_GATEWAY_TIMEOUT, 'The wizard took too long'),
    'request_too_large': (status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, 'The wizard request is too large'),
    'reply_too_large': (status.HTTP_502_BAD_GATEWAY, 'The wizard reply is too large'),
}


def wizardTimeoutSeconds() -> int:
    try:
        value = int(os.environ.get(TIMEOUT_SWITCH, DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT
    return min(max(value, 5), 3600)


def runProtocolWizard(*, mapper: Any, currentUser: Mapping[str, Any], projectId: int,
                      payload, workerRunner=None) -> Dict[str, Any]:
    if not viewerEvaluationEnabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail='Running plugin code is disabled on this server')
    userId = currentUser.get('id') if isinstance(currentUser, Mapping) else None
    if not userId or not mapper.getProject(projectId=projectId, userId=userId):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Project not found')
    request = {
        'projectId': int(projectId),
        'protocolId': payload.protocolId or None,
        'protocolClassName': str(payload.protocolClassName or '').strip(),
        'formValues': dict(payload.formValues or {}),
        'paramName': str(payload.paramName or '').strip(),
        'wizardId': str(payload.wizardId or '').strip(),
        'answers': list(payload.answers or []),
        'preview': payload.preview,
    }
    if not validRequest(request):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail='Invalid wizard request')
    runner = workerRunner or (lambda value, timeout: _run_worker(
        value, timeout, module=WORKER_MODULE, marker=REPLY_MARKER,
        max_request=MAX_REQUEST, max_reply=MAX_REPLY))
    try:
        reply = runner(request, wizardTimeoutSeconds())
    except DynamicProtocolViewerFormError as exc:
        code, detail = _WORKER_ERRORS.get(exc.code, (status.HTTP_502_BAD_GATEWAY, 'The wizard failed'))
        raise HTTPException(status_code=code, detail=detail)
    if not isinstance(reply, dict) or reply.get('status') not in REPLY_STATUSES:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='Invalid wizard reply')
    reply['wizardId'] = request['wizardId']
    reply['paramName'] = request['paramName']
    return reply
