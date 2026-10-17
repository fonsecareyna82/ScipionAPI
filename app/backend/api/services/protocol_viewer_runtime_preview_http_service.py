"""Explicit HTTP admission policy for experimental ProtocolViewer runtime previews.

This is an opt-in *trusted plugin* diagnostics pathway, not a sandbox or an
execution permission. Callers must authenticate and have access to the
project before any child process can be launched. The same admission
gates the viewer actions (protocol_viewer_action_service).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Callable, Optional

from app.backend.api.services.protocol_viewer_dynamic_form_service import (
    evaluateProtocolViewerDynamicForm,
)
from app.backend.api.services.protocol_viewer_settings_service import viewersOnWebEnabled

_MAX_ID = 2147483647
_VIEWER_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_.]{0,254}\Z')


class ProtocolViewerRuntimePreviewHttpError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _valid_id(value: Any) -> bool:
    return type(value) is int and 0 < value <= _MAX_ID


def _flags_enabled() -> bool:
    return viewersOnWebEnabled()


def isProtocolViewerRuntimePreviewAvailable(current_user: Any) -> bool:
    """For UI discovery only. Server repeats all checks on every POST."""
    return (
        _flags_enabled()
        and isinstance(current_user, Mapping)
        and _valid_id(current_user.get('id'))
    )


def requestProtocolViewerRuntimePreview(
    *, mapper: Any, current_user: Any, project_id: int,
    protocol_id: int, viewer_id: str, snapshot: Mapping[str, Any],
    evaluator: Optional[Callable[..., dict]] = None,
) -> dict:
    """Gate trusted runtime evaluation; always return a non-executable preview.

    Project-specific authorization is enforced by the API route through
    getProjectDbRow(), then again by the existing dynamic form service.
    """
    if not _flags_enabled():
        raise ProtocolViewerRuntimePreviewHttpError('preview_disabled')
    if not isProtocolViewerRuntimePreviewAvailable(current_user):
        raise ProtocolViewerRuntimePreviewHttpError('unauthenticated')
    if (
        not _valid_id(project_id)
        or not _valid_id(protocol_id)
        or type(viewer_id) is not str
        or _VIEWER_ID.fullmatch(viewer_id) is None
    ):
        raise ProtocolViewerRuntimePreviewHttpError('invalid_identity')
    if mapper is None or not isinstance(snapshot, Mapping):
        raise ProtocolViewerRuntimePreviewHttpError('invalid_context')

    runner = evaluateProtocolViewerDynamicForm if evaluator is None else evaluator
    preview = runner(
        mapper=mapper,
        current_user=current_user,
        project_id=project_id,
        protocol_id=protocol_id,
        viewer_id=viewer_id,
        snapshot=snapshot,
    )
    # The child-service validates its own wire schema. Fail closed again at the
    # HTTP boundary; do not accept caller-injected web execution permissions.
    if (
        not isinstance(preview, dict)
        or preview.get('status') != 'runtime-preview'
        or preview.get('source') != 'isolated-worker'
        or any(preview.get(key) is not False for key in (
            'webReady', 'renderable', 'executionAllowed'
        ))
        or preview.get('projectId') != project_id
        or preview.get('protocolId') != str(protocol_id)
        or preview.get('viewerId') != viewer_id
        or not isinstance(preview.get('sections'), list)
    ):
        raise ProtocolViewerRuntimePreviewHttpError('invalid_preview')
    # Conditional fields are revalidated here too (also for alternate
    # evaluators); raw rules are never forwarded.
    conditional_fields = None
    if 'conditionalFields' in preview:
        from app.backend.api.services.protocol_viewer_dynamic_form_service import (
            _validated_reply, DynamicProtocolViewerFormError,
        )
        identity = {
            'projectId': project_id,
            'protocolId': protocol_id,
            'viewerId': viewer_id,
        }
        try:
            validated = _validated_reply({'ok': True, **preview}, identity)
        except DynamicProtocolViewerFormError as exc:
            raise ProtocolViewerRuntimePreviewHttpError('invalid_preview') from exc
        conditional_fields = validated.get('conditionalFields')
        if conditional_fields is None:
            raise ProtocolViewerRuntimePreviewHttpError('invalid_preview')

    # Explicit HTTP projection: preserve only validated, non-executable data.
    result = {
        'status': 'runtime-preview',
        'source': 'isolated-worker',
        'projectId': project_id,
        'protocolId': str(protocol_id),
        'viewerId': viewer_id,
        'sections': preview['sections'],
        'fieldsDiscovered': preview.get('fieldsDiscovered', 0),
        'omittedFields': preview.get('omittedFields', 0),
        'instanceEligibility': 'not-evaluated',
        'webReady': False,
        'renderable': False,
        'executionAllowed': False,
    }
    if conditional_fields is not None:
        result['conditionalFields'] = conditional_fields
    actions = preview.get('actions')
    if actions is not None:
        names = {field.get('name') for section in preview['sections']
                 for field in (section.get('fields', []) + [
                     f for group in section.get('groups', []) for f in group.get('fields', [])])}
        names.update(entry['field']['name'] for entry in conditional_fields or ())
        if (type(actions) is not list
                or any(type(name) is not str or name not in names for name in actions)):
            raise ProtocolViewerRuntimePreviewHttpError('invalid_preview')
        result['actions'] = list(actions)
    return result
