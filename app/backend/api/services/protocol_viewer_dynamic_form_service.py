"""Explicit, opt-in child-process boundary for trusted ProtocolViewer form definitions.

This is NOT a sandbox for untrusted plugin Python and is NOT an HTTP endpoint.
It neither runs visualize actions nor makes a viewer web-compatible.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import logging
import tempfile
from typing import Any, Mapping, Optional

from app.backend.api.services.protocol_viewer_condition_contract_service import (
    validViewerConditionRule, referencedViewerFields,
)

from app.backend.api.services.protocol_viewer_warm_pool import (
    WarmWorkerTimeout, prestartWarmWorker, runInWarmWorker,
)
from app.backend.api.services.protocol_viewer_settings_service import (
    DESKTOP_DISPLAY_PREFIX, serverDesktopDisplay, viewerEvaluationEnabled,
)
from app.backend.api.services.protocol_viewer_persisted_resolution_service import (
    resolvePersistedProtocolViewerCandidates,
)

logger = logging.getLogger(__name__)

_MAX_REPLY = 262144
_MAX_REQUEST = 4096
_MAX_SECONDS = 300
_DEFAULT_FORM_TIMEOUT = 60
_VIEWER_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,254}\Z")


class DynamicProtocolViewerFormError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def formTimeoutSeconds() -> int:
    """Loading the project and the viewer form can take a while on big projects."""
    try:
        value = int(os.environ.get('SCIPION_PROTOCOL_VIEWER_FORM_TIMEOUT', ''))
    except ValueError:
        return _DEFAULT_FORM_TIMEOUT
    return min(max(value, 1), _MAX_SECONDS)


def _int_id(value):
    return type(value) is int and 0 < value <= 2147483647



# The isolated worker's visibility contract extends the legacy
# field vocabulary.  Accept only the complete, non-executable extension;
# never relax the general field whitelist or allow arbitrary plugin metadata.
_LEGACY_FIELD_KEYS = frozenset({
    'name', 'label', 'control', 'hasCondition', 'help', 'default', 'choices',
})
_VISIBILITY_FIELD_KEYS = frozenset({
    'visibility', 'visible', 'hidden', 'hiddenAttributeAvailable',
    'pending', 'readOnly', 'executionAllowed', 'conditionState',
})
_ALLOWED_FIELD_KEYS = _LEGACY_FIELD_KEYS | _VISIBILITY_FIELD_KEYS


def _valid_visibility_metadata(field: dict, *, deferred=False) -> bool:
    present = _VISIBILITY_FIELD_KEYS.intersection(field)
    if not present:
        return True  # Pre-GREEN-142 schema; safe, read-only at HTTP/UI boundary.
    if present != _VISIBILITY_FIELD_KEYS:
        return False  # Reject partial/ambiguous metadata.
    if field['readOnly'] is not True or field['executionAllowed'] is not False:
        return False
    has_hidden = field['hiddenAttributeAvailable']
    if type(has_hidden) is not bool:
        return False
    if field['hidden'] is not (False if has_hidden else None):
        return False
    if (deferred and field['visibility'] == 'conditional-hidden'
            and field['visible'] is False and field['pending'] is False
            and field['conditionState'] == 'unmet'
            and field['hasCondition'] is False
            and has_hidden is True and field['hidden'] is False):
        return True
    if (field['visibility'] == 'visible' and field['visible'] is True
            and field['pending'] is False
            and field['conditionState'] in ('none', 'met')
            and field['hasCondition'] is False):
        return True
    if (field['visibility'] == 'pending' and field['visible'] is None
            and field['pending'] is True
            and field['conditionState'] == 'unresolved'
            and field['hasCondition'] is True):
        return True
    return False

def _validate_conditional_fields(payload, visible_fields):
    """Validate the inert local-rule sidecar, separate from initial UI fields."""
    if 'conditionalFields' not in payload:
        return None
    entries = payload['conditionalFields']
    if type(entries) is not list or not 1 <= len(entries) <= 96:
        raise DynamicProtocolViewerFormError('invalid_worker_schema')
    by_name = {field['name']: (section, group, field)
               for section, group, field in visible_fields}
    all_names = set(by_name)
    names = set()
    for entry in entries:
        if (type(entry) is not dict or set(entry) != {'section', 'group', 'field', 'rule'}
                or type(entry['section']) is not str
                or not 0 < len(entry['section']) <= 160
                or entry['group'] is not None and
                   (type(entry['group']) is not str or not 0 < len(entry['group']) <= 160)
                or type(entry['field']) is not dict
                or not validViewerConditionRule(entry['rule'])):
            raise DynamicProtocolViewerFormError('invalid_worker_schema')
        field = entry['field']
        name = field.get('name')
        if (type(name) is not str or not 0 < len(name) <= 128
                or not name.isidentifier() or name in names
                or set(field) - _ALLOWED_FIELD_KEYS
                or not _valid_visibility_metadata(field, deferred=True)
                or type(field.get('label')) is not str
                or not 0 < len(field['label']) <= 160
                or field.get('control') not in (
                    'text', 'multiline', 'integer', 'number', 'boolean',
                    'select', 'numeric-range', 'label')
                or 'help' in field and (type(field['help']) is not str or len(field['help']) > 2048)
                or 'default' in field and not (
                    field['default'] is None or type(field['default']) in (bool, int, float)
                    or type(field['default']) is str and len(field['default']) <= 2048)
                or field['control'] == 'select' and (
                    type(field.get('choices')) is not list or not 1 <= len(field['choices']) <= 100
                    or any(type(choice) not in (str, int, float) or
                           (type(choice) is str and len(choice) > 160)
                           for choice in field['choices']))
                or field['control'] != 'select' and 'choices' in field):
            raise DynamicProtocolViewerFormError('invalid_worker_schema')
        names.add(name)
        if name in by_name:
            section, group, existing = by_name[name]
            if (field != existing or entry['section'] != section or
                    entry['group'] != group):
                raise DynamicProtocolViewerFormError('invalid_worker_schema')
        elif field['visibility'] != 'conditional-hidden':
            raise DynamicProtocolViewerFormError('invalid_worker_schema')
        all_names.add(name)
    if len(all_names) > 96:
        raise DynamicProtocolViewerFormError('invalid_worker_schema')
    for entry in entries:
        refs = referencedViewerFields(entry['rule'])
        if not refs or not refs <= all_names:
            raise DynamicProtocolViewerFormError('invalid_worker_schema')
    return entries


def _validated_reply(payload: Any, request: dict) -> dict:
    if not isinstance(payload, dict) or payload.get('ok') is not True:
        raise DynamicProtocolViewerFormError('worker_failed')
    if (payload.get('projectId') != request['projectId'] or
            payload.get('protocolId') != str(request['protocolId']) or
            payload.get('viewerId') != request['viewerId']):
        raise DynamicProtocolViewerFormError('worker_identity_mismatch')
    if payload.get('status') != 'runtime-preview' or payload.get('source') != 'isolated-worker':
        raise DynamicProtocolViewerFormError('invalid_worker_result')
    if any(payload.get(k) is not False for k in ('webReady', 'renderable', 'executionAllowed')):
        raise DynamicProtocolViewerFormError('unsafe_worker_flags')
    sections = payload.get('sections')
    if not isinstance(sections, list) or len(sections) > 16:
        raise DynamicProtocolViewerFormError('invalid_worker_schema')
    count = 0
    visible_fields = []
    for section in sections:
        if (not isinstance(section, dict) or set(section) != {'label', 'fields', 'groups'}
                or not isinstance(section.get('label'), str) or not 0 < len(section['label']) <= 160):
            raise DynamicProtocolViewerFormError('invalid_worker_schema')
        buckets = [(None, section.get('fields'))]
        groups = section.get('groups')
        if not isinstance(groups, list) or len(groups) > 20:
            raise DynamicProtocolViewerFormError('invalid_worker_schema')
        for group in groups:
            if (not isinstance(group, dict) or set(group) != {'label', 'fields'}
                    or not isinstance(group.get('label'), str) or not 0 < len(group['label']) <= 160):
                raise DynamicProtocolViewerFormError('invalid_worker_schema')
            buckets.append((group['label'], group.get('fields')))
        for group_label, fields in buckets:
            if not isinstance(fields, list):
                raise DynamicProtocolViewerFormError('invalid_worker_schema')
            count += len(fields)
            if count > 96:
                raise DynamicProtocolViewerFormError('invalid_worker_schema')
            for field in fields:
                if not isinstance(field, dict) or not isinstance(field.get('name'), str):
                    raise DynamicProtocolViewerFormError('invalid_worker_schema')
                if (not 0 < len(field['name']) <= 128 or not field['name'].isidentifier()
                        or set(field) - _ALLOWED_FIELD_KEYS
                        or not isinstance(field.get('label'), str)
                        or not 0 < len(field['label']) <= 160
                        or type(field.get('hasCondition')) is not bool
                        or field.get('control') not in (
                        'text', 'multiline', 'integer', 'number', 'boolean', 'select', 'numeric-range', 'label'
                        )):
                    raise DynamicProtocolViewerFormError('invalid_worker_schema')
                visible_fields.append((section['label'], group_label, field))
                if not _valid_visibility_metadata(field):
                    raise DynamicProtocolViewerFormError('invalid_worker_schema')
                if 'help' in field and (type(field['help']) is not str or len(field['help']) > 2048):
                    raise DynamicProtocolViewerFormError('invalid_worker_schema')
                if 'default' in field and not (
                    field['default'] is None or type(field['default']) in (bool, int, float)
                    or (type(field['default']) is str and len(field['default']) <= 2048)
                ):
                    raise DynamicProtocolViewerFormError('invalid_worker_schema')
                if field['control'] == 'select':
                    choices = field.get('choices')
                    if (not isinstance(choices, list) or not 1 <= len(choices) <= 100 or any(
                        type(c) not in (str, int, float) or
                        (type(c) is str and len(c) > 160) for c in choices
                    )):
                        raise DynamicProtocolViewerFormError('invalid_worker_schema')
                elif 'choices' in field:
                    raise DynamicProtocolViewerFormError('invalid_worker_schema')
    conditional_fields = _validate_conditional_fields(payload, visible_fields)
    actions = _validate_actions(payload, visible_fields, conditional_fields)
    # Return only a constrained set of keys, never arbitrary worker metadata.
    result = {'status': 'runtime-preview', 'source': 'isolated-worker',
            'projectId': request['projectId'], 'protocolId': str(request['protocolId']),
            'viewerId': request['viewerId'], 'sections': sections,
            'fieldsDiscovered': count, 'omittedFields': payload.get('omittedFields', 0)
            if type(payload.get('omittedFields', 0)) is int and 0 <= payload.get('omittedFields', 0) <= 10000 else 0,
            'instanceEligibility': 'not-evaluated', 'webReady': False,
            'renderable': False, 'executionAllowed': False}
    if conditional_fields is not None:
        result['conditionalFields'] = conditional_fields
    if actions is not None:
        result['actions'] = actions
    return result


def _validate_actions(payload, visible_fields, conditional_fields):
    """Action names must be fields of the same form; None for older workers."""
    if 'actions' not in payload:
        return None
    actions = payload['actions']
    names = {field['name'] for _, _, field in visible_fields}
    names.update(entry['field']['name'] for entry in conditional_fields or ())
    if (type(actions) is not list or len(actions) > 96
            or any(type(name) is not str or name not in names for name in actions)
            or len(set(actions)) != len(actions)):
        raise DynamicProtocolViewerFormError('invalid_worker_schema')
    return list(actions)


def _log_worker_failure(module, returncode, stderrPath):
    """Plugin errors go to the server log, never to the HTTP reply."""
    try:
        with open(stderrPath, 'rb') as stderr:
            stderr.seek(0, 2)
            size = stderr.tell()
            stderr.seek(max(0, size - _STDERR_TAIL))
            tail = stderr.read().decode('utf-8', errors='replace')
    except Exception:
        tail = ''
    logger.warning('Viewer worker %s exited with %s:\n%s', module, returncode, tail)


_FORM_WORKER_MODULE = 'app.backend.api.services.protocol_viewer_dynamic_form_worker'
_FORM_REPLY_MARKER = b'__SCIPION_VIEWER_FORM_JSON__:'
_STDERR_TAIL = 4096


def _worker_environment() -> dict:
    """Environment of viewer workers: no display, the server's one handed over."""
    env = os.environ.copy()
    for name, value in serverDesktopDisplay().items():
        env[DESKTOP_DISPLAY_PREFIX + name] = value
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    env['MPLBACKEND'] = 'Agg'
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['SCIPION_VIEWER_FORM_CHILD'] = '1'
    return env


def prestartViewerWorkers() -> None:
    """Have a warm viewer worker ready before the first viewer action."""
    prestartWarmWorker(_worker_environment())


def _run_cold_worker(module: str, paths: dict, env: dict, timeout_seconds: int) -> int:
    """A one-shot worker process, killed with its process group on timeout."""
    with open(paths['stdin'], 'rb') as stdin, open(paths['stdout'], 'wb') as stdout, \
            open(paths['stderr'], 'wb') as stderr:
        try:
            process = subprocess.Popen([sys.executable, '-m', module], stdin=stdin,
                                       stdout=stdout, stderr=stderr,
                                       env=env, start_new_session=True)
        except OSError as exc:
            raise DynamicProtocolViewerFormError('worker_unavailable') from exc
        try:
            return process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
            process.wait()
            raise DynamicProtocolViewerFormError('worker_timeout') from exc


def _run_worker(request: dict, timeout_seconds: int, *,
                module: str = _FORM_WORKER_MODULE,
                marker: bytes = _FORM_REPLY_MARKER,
                max_request: int = _MAX_REQUEST,
                max_reply: int = _MAX_REPLY) -> dict:
    """Fixed child module, disk-backed streams, process-group timeout.

    The child is forked from the warm worker when possible (most of a cold
    start is importing Scipion and the plugins), else started from scratch.
    """
    env = _worker_environment()
    data = json.dumps(request, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(data) > max_request:
        raise DynamicProtocolViewerFormError('request_too_large')
    with tempfile.TemporaryDirectory(prefix='scipion-viewer-') as folder:
        paths = {name: os.path.join(folder, name) for name in ('stdin', 'stdout', 'stderr')}
        with open(paths['stdin'], 'wb') as stdin:
            stdin.write(data)
        for name in ('stdout', 'stderr'):
            open(paths[name], 'wb').close()
        try:
            returncode = runInWarmWorker(module, paths, env, timeout_seconds)
        except WarmWorkerTimeout as exc:
            raise DynamicProtocolViewerFormError('worker_timeout') from exc
        if returncode is None:
            returncode = _run_cold_worker(module, paths, env, timeout_seconds)
        if returncode != 0:
            _log_worker_failure(module, returncode, paths['stderr'])
            raise DynamicProtocolViewerFormError(
                'reply_too_large' if returncode == 3 else 'worker_failed')
        with open(paths['stdout'], 'rb') as stdout:
            stdout.seek(0, 2)
            size = stdout.tell()
            stdout.seek(0)
            # Plugin print() output may precede the reply; keep the last bytes.
            if size > max_reply:
                stdout.seek(size - max_reply - 1)
            output = stdout.read(max_reply + 1)
    # Plugin print() output is never trusted as a wire-format response.
    records = [line for line in output.splitlines() if line.startswith(marker)]
    if len(records) != 1:
        raise DynamicProtocolViewerFormError('invalid_worker_reply')
    try:
        value = json.loads(records[0][len(marker):].decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise DynamicProtocolViewerFormError('invalid_worker_reply') from exc
    return value


def evaluateProtocolViewerDynamicForm(
    *, mapper: Any, current_user: Mapping[str, Any], project_id: int,
    protocol_id: int, viewer_id: str, snapshot: Mapping[str, Any],
    timeout_seconds: Optional[int] = None, worker_runner=None,
) -> dict:
    """Opt-in trusted-plugin preview; authorization BEFORE starting a subprocess.

    Use only from an explicitly authenticated caller. No HTTP route is added.
    """
    if not viewerEvaluationEnabled():
        raise DynamicProtocolViewerFormError('evaluation_disabled')
    if not (_int_id(project_id) and _int_id(protocol_id) and
            type(viewer_id) is str and _VIEWER_ID.fullmatch(viewer_id)):
        raise DynamicProtocolViewerFormError('invalid_identity')
    if timeout_seconds is None:
        timeout_seconds = formTimeoutSeconds()
    if (type(timeout_seconds) is not int or not 1 <= timeout_seconds <= _MAX_SECONDS):
        raise DynamicProtocolViewerFormError('invalid_timeout')
    if (not isinstance(current_user, Mapping) or not _int_id(current_user.get('id')) or
            mapper is None or not callable(getattr(mapper, 'getProject', None))):
        raise DynamicProtocolViewerFormError('unauthorized')
    if not mapper.getProject(projectId=project_id, userId=current_user['id']):
        raise DynamicProtocolViewerFormError('unauthorized')
    candidates = resolvePersistedProtocolViewerCandidates(
        mapper=mapper, project_id=project_id, protocol_id=protocol_id,
        snapshot=snapshot)
    choices = [item for item in candidates['viewers']
               if item.get('id') == viewer_id and item.get('viewerKind') == 'protocol-form']
    if len(choices) != 1:
        raise DynamicProtocolViewerFormError('viewer_not_applicable')
    request = {'projectId': project_id, 'protocolId': protocol_id,
               'viewerId': viewer_id, 'protocolDbId': candidates['protocolDbId']}
    runner = _run_worker if worker_runner is None else worker_runner
    return _validated_reply(runner(request, timeout_seconds), request)
