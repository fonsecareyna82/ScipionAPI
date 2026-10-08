from unittest.mock import Mock


def test_LogWindowReturns404ForMissingProject(projectClient, fakeProjectService):
    fakeProjectService.projectDbRowResult = None
    response = projectClient.get("/projects/1/protocols/2/logs/window?channel=stdout")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_LogWindowDelegatesParametersAndReturnsWindow(projectClient, fakeProjectService):
    expected = {
        "channel": "stdout",
        "content": "last lines\n",
        "startOffset": 900,
        "endOffset": 911,
        "sizeBytes": 1000,
    }
    fakeProjectService.readProtocolLogWindowService = Mock(return_value=expected)
    response = projectClient.get(
        "/projects/1/protocols/2/logs/window?channel=stdout&endOffset=911&maxBytes=4096"
    )
    assert response.status_code == 200
    assert response.json() == expected
    kwargs = fakeProjectService.readProtocolLogWindowService.call_args.kwargs
    assert kwargs["projectId"] == 1
    assert kwargs["protocolId"] == 2
    assert kwargs["channel"] == "stdout"
    assert kwargs["endOffset"] == 911
    assert kwargs["maxBytes"] == 4096
    assert kwargs["protocolIdIsScipionId"] is True
    assert kwargs["mapper"] is not None


def test_LogWindowRejectsUnknownChannel(projectClient):
    response = projectClient.get("/projects/1/protocols/2/logs/window?channel=unknown")
    assert response.status_code == 422
