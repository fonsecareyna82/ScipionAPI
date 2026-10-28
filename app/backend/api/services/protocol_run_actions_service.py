"""The actions a protocol offers while it runs (``getActions``), listed and run in a child process.

The desktop shows them in the context menu of a running protocol: STOP STREAMING of a streaming import
(it closes its output and finishes, and the protocols after it finish in turn), APPROVE CHECKPOINT of a
checkpoint. Each one leaves a file in the run folder that the running protocol looks for. This module
authorizes the request before any plugin code runs, and starts the child only for a running protocol:
the others offer none.
"""
from __future__ import annotations

from typing import Any, Callable, List, Mapping, Optional

from app.backend.api.services.protocol_viewer_dynamic_form_service import (
    DynamicProtocolViewerFormError, _run_worker,
)

_WORKER_MODULE = 'app.backend.api.services.protocol_run_actions_worker'
_REPLY_MARKER = b'__SCIPION_RUN_ACTIONS_JSON__:'
_MAX_REQUEST = 4096
_MAX_REPLY = 65536
_TIMEOUT = 60
_MAX_ACTIONS = 16
_MAX_LABEL = 128
# pyworkflow's STATUS_RUNNING: getActions offers its actions only then
_RUNNING = 'running'


class ProtocolRunActionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _int_id(value) -> bool:
    return type(value) is int and 0 < value <= 2147483647


def _label(value) -> bool:
    return type(value) is str and 0 < len(value) <= _MAX_LABEL


def _runningProtocol(mapper: Any, current_user: Mapping[str, Any], project_id: int,
                     protocol_id: int) -> Optional[dict]:
    """The protocol's row when the user may see the project and it runs; None when it does not run."""
    if not (_int_id(project_id) and _int_id(protocol_id)):
        raise ProtocolRunActionError('invalid_identity')
    if (not isinstance(current_user, Mapping) or not _int_id(current_user.get('id'))
            or mapper is None or not mapper.getProject(projectId=project_id, userId=current_user['id'])):
        raise ProtocolRunActionError('unauthorized')
    row = mapper.getProjectProtocolByProtocolId(projectId=project_id, protocolId=protocol_id)
    if not isinstance(row, dict):
        raise ProtocolRunActionError('not_found')
    return row if str(row.get('status') or '').lower() == _RUNNING else None


def _ask(row: dict, project_id: int, protocol_id: int, action: Optional[str],
         worker_runner: Optional[Callable[[dict, int], dict]]) -> dict:
    request = {'projectId': project_id, 'protocolId': protocol_id, 'protocolDbId': int(row['id']),
               'action': action}
    try:
        if worker_runner is not None:
            return worker_runner(request, _TIMEOUT)
        return _run_worker(request, _TIMEOUT, module=_WORKER_MODULE, marker=_REPLY_MARKER,
                           max_request=_MAX_REQUEST, max_reply=_MAX_REPLY)
    except DynamicProtocolViewerFormError as exc:
        raise ProtocolRunActionError(exc.code) from exc


def listProtocolRunActions(*, mapper: Any, current_user: Mapping[str, Any], project_id: int,
                           protocol_id: int, worker_runner=None) -> List[str]:
    """The labels of the actions the protocol offers now (none unless it runs)."""
    row = _runningProtocol(mapper, current_user, project_id, protocol_id)
    if row is None:
        return []
    reply = _ask(row, project_id, protocol_id, None, worker_runner)
    actions = reply.get('actions') if isinstance(reply, dict) else None
    if not isinstance(actions, list):
        raise ProtocolRunActionError('invalid_reply')
    return [label for label in actions if _label(label)][:_MAX_ACTIONS]


def runProtocolRunAction(*, mapper: Any, current_user: Mapping[str, Any], project_id: int, protocol_id: int,
                         action: str, worker_runner=None) -> dict:
    """Run one action the protocol offers now; a protocol that no longer runs offers none."""
    if not _label(action):
        raise ProtocolRunActionError('invalid_action')
    row = _runningProtocol(mapper, current_user, project_id, protocol_id)
    if row is None:
        raise ProtocolRunActionError('not_running')
    reply = _ask(row, project_id, protocol_id, action, worker_runner)
    if not isinstance(reply, dict):
        raise ProtocolRunActionError('invalid_reply')
    if reply.get('error') == 'unknown_action':
        raise ProtocolRunActionError('unknown_action')
    if reply.get('ran') != action:
        raise ProtocolRunActionError('invalid_reply')
    return {'ran': action}
