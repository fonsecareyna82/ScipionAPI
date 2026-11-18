"""Desktop programs opened on the server and shown in the browser.

A program (a 3D viewer, a tomogram viewer...) runs on the machine that holds the data, on a display of its own
made by Xpra. The browser gets only the picture of its window, through ScipionAPI: Xpra listens on 127.0.0.1 with a
password of its own, and the web reaches it at /remote-displays/<session id>/, where the session id is the key.

Each session is a file in SCIPION_HOME/remote-displays (so every API process sees it) with its display, port,
password, owner and Xpra's pid. Xpra ends with the program (exit-with-children) or when nobody has looked at it for
IDLE_SECONDS (server-idle-timeout); a session whose Xpra is gone is forgotten when next read.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

IDLE_SECONDS = 15 * 60
MAX_SESSIONS_PER_USER = 3
# Lowest picture quality (1-100) while the picture changes; Xpra lowers it to save network, which blurs
MIN_QUALITY = 80
_DISPLAYS = range(300, 400)
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
_START_TIMEOUT = 20.0


class RemoteDisplayError(RuntimeError):
    """code: unavailable (no Xpra or no program), too_many, not_found, start_failed."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def xpraExecutable() -> Optional[str]:
    return shutil.which("xpra")


def _stateDir() -> Path:
    home = os.environ.get("SCIPION_HOME") or os.getcwd()
    path = Path(home) / "remote-displays"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _readSession(path: Path) -> Optional[Dict[str, Any]]:
    try:
        session = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(session, dict) or not _alive(session.get("pid")):
        path.unlink(missing_ok=True)
        return None
    return session


def listSessions(userId: Optional[int] = None) -> List[Dict[str, Any]]:
    sessions = []
    for path in sorted(_stateDir().glob("*.json")):
        session = _readSession(path)
        if session and (userId is None or session.get("userId") == userId):
            sessions.append(session)
    return sessions


def getSession(sessionId: str) -> Optional[Dict[str, Any]]:
    if not isinstance(sessionId, str) or not _SESSION_ID.match(sessionId):
        return None
    return _readSession(_stateDir() / f"{sessionId}.json")


def _freeDisplay(taken: Sequence[int]) -> int:
    for number in _DISPLAYS:
        if number in taken or os.path.exists(f"/tmp/.X11-unix/X{number}") or os.path.exists(f"/tmp/.X{number}-lock"):
            continue
        return number
    raise RemoteDisplayError("too_many", "No display is free on this machine")


def _freePort() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def programCommand(program: str, args: Sequence[str]) -> List[str]:
    """The command that runs a program file: a script without its first #! line (some installers write them) runs
    through sh, as a terminal would."""
    command = [program]
    try:
        with open(program, "rb") as handle:
            head = handle.read(4)
        if head != b"\x7fELF" and not head.startswith(b"#!"):
            command = ["/bin/sh", program]
    except OSError:
        pass
    return command + [str(arg) for arg in args]


def _waitUntilServing(port: int, pid: int) -> bool:
    deadline = time.monotonic() + _START_TIMEOUT
    while time.monotonic() < deadline:
        if not _alive(pid):
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def startSession(*, userId: int, projectId: int, title: str, command: Sequence[str],
                 cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Open `command` on a new display and return its session (id, password...)."""
    xpra = xpraExecutable()
    if not xpra:
        raise RemoteDisplayError("unavailable", "Showing programs in the browser is not installed on this server")
    sessions = listSessions()
    if sum(1 for s in sessions if s.get("userId") == userId) >= MAX_SESSIONS_PER_USER:
        raise RemoteDisplayError("too_many", f"You already have {MAX_SESSIONS_PER_USER} windows open; close one first")

    sessionId = secrets.token_urlsafe(32)
    password = secrets.token_urlsafe(24)
    display = _freeDisplay([int(s.get("display", -1)) for s in sessions])
    port = _freePort()
    stateDir = _stateDir()
    logPath = stateDir / f"{sessionId}.log"
    args = [
        xpra, "start", f":{display}",
        f"--bind-tcp=127.0.0.1:{port},auth=password:value={password}",
        "--html=on", "--daemon=no",
        "--exit-with-children=yes", f"--start-child={shlex.join(command)}",
        f"--server-idle-timeout={IDLE_SECONDS}",
        # Nobody opens other programs, files or devices from the page
        "--start-new-commands=no", "--file-transfer=no", "--open-files=no", "--open-url=no",
        "--printing=no", "--webcam=no", "--pulseaudio=no", "--speaker=no", "--microphone=no",
        "--notifications=no", "--mdns=no", "--splash=no",
        # Sharp picture: never too compressed while it changes, and never sent as a video (shrunk and blurred
        # where the picture changes a lot, until the exact one comes)
        f"--min-quality={MIN_QUALITY}", "--video-encoders=none", "--video-scaling=0",
    ]
    with open(logPath, "ab") as log:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   cwd=cwd or None, env={**os.environ, **(env or {})}, start_new_session=True)
    if not _waitUntilServing(port, process.pid):
        _terminate(process.pid)
        raise RemoteDisplayError("start_failed", "The program could not be opened; see " + str(logPath))

    session = {
        "id": sessionId, "userId": userId, "projectId": projectId, "title": title,
        "display": display, "port": port, "password": password, "pid": process.pid,
        "createdAt": time.time(),
    }
    statePath = stateDir / f"{sessionId}.json"
    statePath.write_text(json.dumps(session))
    os.chmod(statePath, 0o600)
    return session


def _terminate(pid: int) -> None:
    try:
        os.killpg(int(pid), signal.SIGTERM)
    except (OSError, ValueError):
        pass


def stopSession(sessionId: str, userId: int) -> None:
    session = getSession(sessionId)
    if not session or session.get("userId") != userId:
        raise RemoteDisplayError("not_found")
    _terminate(session["pid"])
    (_stateDir() / f"{sessionId}.json").unlink(missing_ok=True)


def publicView(session: Dict[str, Any]) -> Dict[str, Any]:
    """What the web gets: where to open it, never the port or the pid."""
    return {
        "id": session["id"], "title": session.get("title", ""), "projectId": session.get("projectId"),
        "createdAt": session.get("createdAt"),
        "path": f"remote-displays/{session['id']}/index.html?password={session['password']}"
                "&sharing=no&floating_menu=yes&title=" + _quote(session.get("title", "")),
    }


def _quote(text: str) -> str:
    from urllib.parse import quote
    return quote(text, safe="")
