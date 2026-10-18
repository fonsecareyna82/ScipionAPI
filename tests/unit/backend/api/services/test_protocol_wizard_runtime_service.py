"""The API process authorizes wizard runs and hands them to the worker."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.backend.api.services import protocol_wizard_runtime_service as service
from app.backend.api.services.protocol_viewer_dynamic_form_service import DynamicProtocolViewerFormError


class Mapper:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def getProject(self, projectId, userId):
        return {"id": projectId} if self.allowed else None


def payload(**overrides):
    values = dict(protocolId=22, protocolClassName="XmippProtExtractParticles", paramName="boxSize",
                  wizardId="xmipp3.wizards.XmippBoxSizeWizard", formValues={"downFactor": 2},
                  answers=[], preview=None)
    values.update(overrides)
    return SimpleNamespace(**values)


def call(mapper=None, runner=None, **overrides):
    return service.runProtocolWizard(mapper=mapper or Mapper(), currentUser={"id": 1}, projectId=7,
                                     payload=payload(**overrides), workerRunner=runner)


def test_the_worker_gets_the_form_and_its_reply_comes_back():
    requests = []

    def runner(request, timeout):
        requests.append(request)
        return {"status": "done", "paramUpdates": {"boxSize": 280}, "messages": []}

    reply = call(runner=runner)
    assert reply["paramUpdates"] == {"boxSize": 280} and reply["paramName"] == "boxSize"
    assert requests[0]["formValues"] == {"downFactor": 2} and requests[0]["protocolId"] == 22


def test_only_the_project_owner_runs_wizards():
    with pytest.raises(HTTPException) as error:
        call(mapper=Mapper(allowed=False), runner=lambda *args: pytest.fail("ran"))
    assert error.value.status_code == 404


def test_invalid_requests_never_reach_the_worker():
    with pytest.raises(HTTPException) as error:
        call(paramName="", runner=lambda *args: pytest.fail("ran"))
    assert error.value.status_code == 422


def test_worker_failures_are_http_errors():
    def slow(request, timeout):
        raise DynamicProtocolViewerFormError("worker_timeout")

    with pytest.raises(HTTPException) as error:
        call(runner=slow)
    assert error.value.status_code == 504
    with pytest.raises(HTTPException) as error:
        call(runner=lambda *args: {"status": "whatever"})
    assert error.value.status_code == 502


def test_no_plugin_code_runs_when_the_server_disables_it(monkeypatch):
    monkeypatch.setenv("SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL", "0")
    with pytest.raises(HTTPException) as error:
        call(runner=lambda *args: pytest.fail("ran"))
    assert error.value.status_code == 503


def test_the_web_finds_the_wizard_the_desktop_form_would_open():
    from app.backend.api.services.protocol_wizard_service import ProtocolWizardService

    class Base:
        pass

    class Protocol(Base):
        pass

    class First:
        __module__ = "plugin.wizards"
        _targets = [(Base, ["radius", "inner"])]
        _environments = ["tkinter"]

    class Domain:
        def findWizards(self, protocol, environment):
            assert environment == "tkinter"
            return {"radius": First, "inner": First}

    project = SimpleNamespace(getDomain=lambda: Domain())
    wizards = ProtocolWizardService(currentProject=project).findWizardsWeb(Protocol())
    assert set(wizards) == {"radius", "inner"}
    descriptor = wizards["radius"][0]
    assert descriptor["id"] == "plugin.wizards.First" and descriptor["runtime"] is True
    assert descriptor["targetParams"] == ["radius", "inner"] and descriptor["webSupported"] is True
