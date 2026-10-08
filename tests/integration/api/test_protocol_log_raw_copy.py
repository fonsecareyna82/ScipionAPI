from unittest.mock import Mock
import pytest


URL = "/projects/1/protocols/2/logs/raw"


def test_RawLogCopyStreamsAllBytesIncludingUnicodeAndMultipleBlocks(
        projectClient, fakeProjectService, tmp_path, monkeypatch):
    log = tmp_path / "stdout.log"
    payload = (b"start\n" + b"A" * (262144 - 8)
               + "ñ😀".encode("utf-8") + b"\nlast line\n")
    log.write_bytes(payload)
    get_path = Mock(return_value=str(log))
    monkeypatch.setattr(fakeProjectService, "getProtocolLogPathService", get_path, raising=False)

    response = projectClient.get(URL, params={"channel": "stdout"})

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["cache-control"] == "no-store"
    kwargs = get_path.call_args.kwargs
    assert kwargs["projectId"] == 1
    assert kwargs["protocolId"] == 2
    assert kwargs["channel"] == "stdout"
    assert kwargs["protocolIdIsScipionId"] is True
    assert kwargs["mapper"] is not None


@pytest.mark.parametrize("channel", ["stdout", "stderr", "schedule"])
def test_RawLogCopySupportsEachChannel(
        projectClient, fakeProjectService, tmp_path, monkeypatch, channel):
    log = tmp_path / (channel + ".log")
    log.write_text(channel + " entire log\n", encoding="utf-8")
    monkeypatch.setattr(fakeProjectService, "getProtocolLogPathService",
                        Mock(return_value=str(log)), raising=False)
    response = projectClient.get(URL, params={"channel": channel})
    assert response.status_code == 200
    assert response.text == channel + " entire log\n"


def test_RawLogCopyRequiresProjectAccess(projectClient, fakeProjectService):
    fakeProjectService.projectDbRowResult = None
    response = projectClient.get(URL, params={"channel": "stdout"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_RawLogCopyMissingLogIs404(projectClient, fakeProjectService, monkeypatch):
    monkeypatch.setattr(fakeProjectService, "getProtocolLogPathService",
                        Mock(return_value=None), raising=False)
    response = projectClient.get(URL, params={"channel": "stdout"})
    assert response.status_code == 404


def test_RawLogCopyRejectsUnlistedChannel(projectClient):
    response = projectClient.get(URL, params={"channel": "secrets"})
    assert response.status_code == 422
