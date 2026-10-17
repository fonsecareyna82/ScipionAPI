import pytest
from fastapi import HTTPException

from app.backend.api.services import protocol_viewer_action_service as action_service


class Service:
    def __init__(self, project=True):
        self.project = project
        self.calls = []

    def getProjectDbRow(self, mapper, projectId, currentUser):
        self.calls.append(projectId)
        return {"id": projectId} if self.project else None


def call(project_router, monkeypatch, *, available=True, project=True, outcome=None):
    monkeypatch.setattr(project_router, "isProtocolViewerRuntimePreviewAvailable", lambda user: available)
    monkeypatch.setattr(project_router, "getScipionViewerResolutionSnapshot", lambda: {})
    received = []

    def run(**kwargs):
        received.append(kwargs)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome or {"status": "viewer-action"}

    monkeypatch.setattr(action_service, "runProtocolViewerAction", run)
    service = Service(project)
    payload = project_router.ProtocolViewerActionRequest(
        viewerId="xmipp3.viewers.viewer_cl2d.XmippCL2DViewer", action="showConvergence",
        values={"doShowLastLevel": 1})
    result = project_router.runProtocolViewerActionRoute(
        7, 115, payload, currentUser={"id": 1, "role": "admin"}, mapper=object(), service=service)
    return result, received, service


def test_action_route_runs_the_viewer_for_an_authorized_project(projectRouterModule, monkeypatch):
    result, received, service = call(projectRouterModule, monkeypatch)
    assert result == {"status": "viewer-action"}
    assert service.calls == [7]
    assert received[0]["action"] == "showConvergence"
    assert received[0]["values"] == {"doShowLastLevel": 1}


def test_action_route_checks_availability_and_project_before_running(projectRouterModule, monkeypatch):
    for kwargs in ({"available": False}, {"project": False}):
        with pytest.raises(HTTPException) as error:
            call(projectRouterModule, monkeypatch, **kwargs)
        assert error.value.status_code == 404


@pytest.mark.parametrize("code, status", [
    ("validation_failed", 422), ("unknown_action", 404), ("worker_timeout", 504),
    ("invalid_worker_reply", 502),
])
def test_action_errors_keep_their_code_and_messages(projectRouterModule, monkeypatch, code, status):
    with pytest.raises(HTTPException) as error:
        call(projectRouterModule, monkeypatch, outcome=action_service.ProtocolViewerActionError(code, ["Select a level"]))
    assert error.value.status_code == status
    assert error.value.detail == {"code": code, "messages": ["Select a level"]}


def test_action_request_accepts_only_scalar_values(projectRouterModule):
    request = projectRouterModule.ProtocolViewerActionRequest
    with pytest.raises(Exception):
        request(viewerId="v.V", action="a", values={"x": [1]})
    with pytest.raises(Exception):
        request(viewerId="v.V", action="a", path="/etc")
