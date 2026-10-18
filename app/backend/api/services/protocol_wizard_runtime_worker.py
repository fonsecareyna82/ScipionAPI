"""Worker process that runs one protocol form wizard (see protocol_wizard_runtime).

It loads the project, builds the protocol with the values of the web form,
runs the wizard the desktop would open for the param, and prints one reply.
Plugin code only runs here, never in the API process.
"""
from __future__ import annotations

import json
import os
import sys

from app.backend.api.services.protocol_viewer_settings_service import viewerEvaluationEnabled

REPLY_MARKER = b'__SCIPION_WIZARD_JSON__:'
MAX_REQUEST = 1024 * 1024
MAX_REPLY = 24 * 1024 * 1024
MAX_ANSWERS = 32
MAX_VIEWS = 16


def wizardIdentity(wizardClass) -> str:
    return "%s.%s" % (wizardClass.__module__, wizardClass.__name__)


def desktopWizards(domain, protocol) -> dict:
    """{param: wizard class}, exactly as the desktop form finds them."""
    from pyworkflow.wizard import DESKTOP_TKINTER
    return domain.findWizards(protocol, DESKTOP_TKINTER)


def _translateViews(views, project, protocol, projectId):
    from app.backend.api.services.protocol_viewer_action_worker import (
        OutputIndex, PathResolver, translateView)
    from app.backend.api.services.protocol_viewer_settings_service import workerDesktopDisplay

    resolver = PathResolver(project.getPath())
    try:
        outputs = OutputIndex(project, protocol, projectId)
    except Exception:
        outputs = None
    items = []
    for view in views[:MAX_VIEWS]:
        try:
            items.append(translateView(view, resolver, outputs, workerDesktopDisplay()))
        except Exception as exc:
            items.append({'kind': 'unsupported', 'viewClass': type(view).__name__,
                          'reason': 'translation_failed', 'detail': str(exc)[:500]})
    return items


def buildProtocol(wizardService, service, project, mapper, projectId, request):
    """The protocol as the form shows it: the stored one (with its inputs) or a
    new one, with the form's current values on top."""
    from fastapi import HTTPException, status

    protocolId = request['protocolId']
    if protocolId:
        protocol = service._getScipionProtocolByScipionId(
            protocolId, mapper=mapper, projectId=projectId)
        if protocol is None or protocol.getClassName() != request['protocolClassName']:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Protocol not found')
        try:
            from app.backend.api.services.protocol_viewer_dynamic_form_worker import restoreProtocolInputs
            restoreProtocolInputs(mapper, project, protocol, projectId, protocolId)
        except Exception:
            import traceback
            traceback.print_exc(file=sys.stderr)
        # Its pointers are the restored inputs; reconfiguring them through the
        # runs graph would drop them.
        values = wizardService._sanitizeWizardFormValues(request['formValues'])
        errors = wizardService._applyFormValuesToProtocolInstance(
            protocol, values, mapper=mapper, projectId=projectId)
        if errors:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors)
        return protocol
    return wizardService._buildWizardReadyProtocol(
        protocolId=None, protocolClassName=request['protocolClassName'],
        formValues=request['formValues'], mapper=mapper, projectId=projectId)


def _run(request):
    from fastapi import HTTPException
    from pyworkflow import Config
    from app.backend.api.services.project_service import ProjectService
    from app.backend.api.services.protocol_wizard_runtime import runWizard
    from app.backend.api.services.protocol_wizard_service import ProtocolWizardService
    from app.backend.database import getMapper
    from app.backend.runtime.project_runtime_repository import ProjectRuntimeRepository

    if Config.getDomain() is None:
        Config.setDomain("pwem")
    projectId = request['projectId']
    mapper = getMapper()
    try:
        projectPath = ProjectRuntimeRepository().getProjectNameById(mapper, projectId)
        if not projectPath:
            return {'status': 'failed', 'error': 'missing_project'}
        service = ProjectService()
        project = service._loadPostgresqlRuntimeProject(
            mapper=mapper, projectId=projectId, projectPath=projectPath)
        service.currentProject = project
        wizardService = ProtocolWizardService(currentProject=project, projectService=service)
        try:
            protocol = buildProtocol(wizardService, service, project, mapper, projectId, request)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, list) else [str(exc.detail)]
            return {'status': 'invalid', 'errors': [str(item)[:500] for item in detail[:20]]}
        wizardClass = desktopWizards(project.getDomain(), protocol).get(request['paramName'])
        if wizardClass is None or wizardIdentity(wizardClass) != request['wizardId']:
            return {'status': 'failed', 'error': 'wizard_not_found'}
        reply = runWizard(wizardClass, protocol, request['paramName'],
                          answers=request['answers'], preview=request['preview'])
        views = reply.pop('views', None) or []
        if views:
            reply['items'] = _translateViews(views, project, protocol, projectId)
        return reply
    finally:
        try:
            mapper.db.close()
        except Exception:
            pass


def validRequest(request) -> bool:
    return (
        isinstance(request, dict)
        and set(request) == {'projectId', 'protocolId', 'protocolClassName', 'formValues',
                             'paramName', 'wizardId', 'answers', 'preview'}
        and type(request['projectId']) is int and request['projectId'] > 0
        and (request['protocolId'] is None
             or (type(request['protocolId']) is int and request['protocolId'] > 0))
        and type(request['protocolClassName']) is str and 0 < len(request['protocolClassName']) <= 255
        and isinstance(request['formValues'], dict)
        and type(request['paramName']) is str and 0 < len(request['paramName']) <= 255
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
