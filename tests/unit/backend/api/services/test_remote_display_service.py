"""Programs opened on the server and shown in the browser: their sessions, and the page and connection that pass
through the API (the last ones with a real Xpra, when it is installed)."""
import os
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.api.services import remote_display_service as displays


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIPION_HOME", str(tmp_path))
    return tmp_path


def test_AScriptWithoutItsFirstLineRunsThroughSh(tmp_path):
    script = tmp_path / "Viewer"
    script.write_text("flatpak run some.viewer $*\n")
    assert displays.programCommand(str(script), ["a.mrc"]) == ["/bin/sh", str(script), "a.mrc"]
    script.write_text("#!/bin/bash\necho\n")
    assert displays.programCommand(str(script), ["a.mrc"]) == [str(script), "a.mrc"]


def test_NothingOpensWithoutXpra(home, monkeypatch):
    monkeypatch.setattr(displays, "xpraExecutable", lambda: None)
    with pytest.raises(displays.RemoteDisplayError) as error:
        displays.startSession(userId=1, projectId=1, title="t", command=["true"])
    assert error.value.code == "unavailable"


def test_TheWebNeverGetsThePortOrThePid(home):
    session = {"id": "x" * 40, "title": "Map (#3)", "projectId": 7, "createdAt": 1.0,
               "port": 14500, "pid": 123, "password": "secret", "display": 300, "userId": 1}
    view = displays.publicView(session)
    assert "port" not in view and "pid" not in view and "display" not in view
    assert view["path"].startswith("remote-displays/" + "x" * 40 + "/index.html?password=secret")


def test_ASessionWhoseXpraIsGoneIsForgotten(home):
    (displays._stateDir() / ("a" * 40 + ".json")).write_text('{"id": "%s", "pid": 999999999}' % ("a" * 40))
    assert displays.getSession("a" * 40) is None
    assert not list(displays._stateDir().glob("*.json"))


def test_OnlyItsOwnerClosesASession(home, monkeypatch):
    monkeypatch.setattr(displays, "_terminate", lambda pid: None)
    sessionId = "b" * 40
    (displays._stateDir() / f"{sessionId}.json").write_text('{"id": "%s", "pid": %d, "userId": 1}' % (sessionId, os.getpid()))
    with pytest.raises(displays.RemoteDisplayError):
        displays.stopSession(sessionId, 2)
    displays.stopSession(sessionId, 1)
    assert displays.getSession(sessionId) is None


def test_AnotherIdIsNeverReadAsAFile(home):
    assert displays.getSession("../../etc/passwd") is None
    assert displays.getSession("short") is None


@pytest.mark.skipif(not (shutil.which("xpra") and shutil.which("xterm")), reason="needs xpra and xterm")
def test_ThePageAndTheConnectionPassThroughTheApi(authTestEnv):
    from app.backend.api.routers import remote_display_router

    app = FastAPI()
    app.include_router(remote_display_router.router)
    session = displays.startSession(userId=1, projectId=1, title="Terminal", command=["xterm"])
    try:
        client = TestClient(app)
        page = client.get(f"/remote-displays/{session['id']}/index.html")
        assert page.status_code == 200 and "<html" in page.text.lower()
        assert client.get("/remote-displays/" + "z" * 40 + "/index.html").status_code == 404
        with client.websocket_connect(f"/remote-displays/{session['id']}/", subprotocols=["binary"]) as ws:
            assert ws.accepted_subprotocol == "binary"
    finally:
        displays.stopSession(session["id"], 1)


def test_ABrowserOnTheMachineOfTheApiOpensProgramsOnItsScreen(monkeypatch):
    from types import SimpleNamespace
    from app.backend.api.routers import remote_display_router as router

    def request(host, forwarded=None):
        headers = {"x-forwarded-for": forwarded} if forwarded else {}
        return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers)

    monkeypatch.setattr(router, "_thisMachineAddresses", lambda: {"10.0.0.5"})
    monkeypatch.setattr(router, "_connectionOwner", lambda clientPort, serverPort: None)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert router._browserIsOnThisMachine(request("127.0.0.1"))
    assert router._browserIsOnThisMachine(request("10.0.0.5"))
    assert not router._browserIsOnThisMachine(request("10.0.0.9"))
    # Behind a proxy on this machine, the browser is the one it forwards
    assert not router._browserIsOnThisMachine(request("127.0.0.1", forwarded="10.0.0.9"))

    monkeypatch.delenv("DISPLAY")
    assert not router._browserIsOnThisMachine(request("127.0.0.1"))  # no screen here

    # Started from an ssh -X login: that screen is another machine's
    monkeypatch.setenv("DISPLAY", "localhost:10.0")
    assert not router._browserIsOnThisMachine(request("127.0.0.1"))


def test_AnotherAccountOnTheMachineOfTheApiSeesProgramsInTheBrowser(monkeypatch):
    import os
    from types import SimpleNamespace
    from app.backend.api.routers import remote_display_router as router

    def request(forwarded=None):
        headers = {"x-forwarded-for": forwarded} if forwarded else {}
        return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1", port=51000), headers=headers,
                               scope={"server": ("127.0.0.1", 8080)})

    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(router, "_connectionOwner", lambda clientPort, serverPort: os.getuid())
    assert router._browserIsOnThisMachine(request())
    monkeypatch.setattr(router, "_connectionOwner", lambda clientPort, serverPort: os.getuid() + 1)
    assert not router._browserIsOnThisMachine(request())
    monkeypatch.setattr(router, "_connectionOwner", lambda clientPort, serverPort: None)
    assert router._browserIsOnThisMachine(request())  # cannot tell: as before


def test_TheOwnerOfAConnectionIsReadFromTheKernel():
    import os
    import socket
    from app.backend.api.routers import remote_display_router as router

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.create_connection(server.getsockname())
    try:
        clientPort, serverPort = client.getsockname()[1], server.getsockname()[1]
        assert router._connectionOwner(clientPort, serverPort) == os.getuid()
        assert router._connectionOwner(None, serverPort) is None
    finally:
        client.close()
        server.close()
