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
import tempfile
from typing import Any, Mapping

from app.backend.api.services.protocol_viewer_condition_contract_service import (
    validViewerConditionRule, referencedViewerFields,
)

from app.backend.api.services.protocol_viewer_persisted_resolution_service import (
    resolvePersistedProtocolViewerCandidates,
)

_MAX_REPLY = 262144
_MAX_REQUEST = 4096
_MAX_SECONDS = 10
_VIEWER_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,254}\Z")


class DynamicProtocolViewerFormError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _int_id(value):
    return type(value) is int and 0 < value <= 2147483647



# The isolated worker's GREEN 142 visibility contract extends the legacy
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
    return result


def _run_worker(request: dict, timeout_seconds: int) -> dict:
    """Fixed child module, bounded disk-backed pipes, process-group timeout."""
    env = os.environ.copy()
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    env['MPLBACKEND'] = 'Agg'
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['SCIPION_VIEWER_FORM_CHILD'] = '1'
    command = [sys.executable, '-m',
               'app.backend.api.services.protocol_viewer_dynamic_form_worker']
    data = json.dumps(request, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(data) > _MAX_REQUEST:
        raise DynamicProtocolViewerFormError('request_too_large')
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                       stdout=stdout, stderr=stderr,
                                       env=env, start_new_session=True)
        except OSError as exc:
            raise DynamicProtocolViewerFormError('worker_unavailable') from exc
        try:
            process.communicate(input=data, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
            process.communicate()
            raise DynamicProtocolViewerFormError('worker_timeout') from exc
        if process.returncode != 0:
            raise DynamicProtocolViewerFormError('worker_failed')
        stdout.seek(0, 2)
        size = stdout.tell()
        if size > _MAX_REPLY:
            raise DynamicProtocolViewerFormError('reply_too_large')
        stdout.seek(0)
        output = stdout.read(_MAX_REPLY + 1)
    # Plugin print() output is never trusted as a wire-format response.
    marker = b'__SCIPION_VIEWER_FORM_JSON__:'
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
    timeout_seconds: int = 5, worker_runner=None,
) -> dict:
    """Opt-in trusted-plugin preview; authorization BEFORE starting a subprocess.

    Use only from an explicitly authenticated caller. No HTTP route is added.
    """
    if os.environ.get('SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL') != '1':
        raise DynamicProtocolViewerFormError('evaluation_disabled')
    if not (_int_id(project_id) and _int_id(protocol_id) and
            type(viewer_id) is str and _VIEWER_ID.fullmatch(viewer_id)):
        raise DynamicProtocolViewerFormError('invalid_identity')
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
