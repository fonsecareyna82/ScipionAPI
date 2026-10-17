"""Xmipp's interactive particle picker, run in the web instead of a Java window.

On the desktop, a picking protocol's interactive step opens the Java picker
and waits until it is closed; meanwhile the picker registers coordinates by
asking the protocol, over TCP, to run ``registerCoords``. Here the step opens
a web session instead and waits the same way. The web and this step talk
through files in the session folder (``<extra>/.scipionweb_picker``):

  session.json          written and refreshed by the step while it waits
  register-<id>.json    the web asks the protocol to register coordinates;
                        the step answers in register-<id>.result.json
  close                 the web closed the picker: the step finishes

The files live in the protocol folder, so this works with the protocol worker
on any node that shares the project folder with the API.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Optional

CHANNEL_FOLDER = ".scipionweb_picker"
SESSION_FILE = "session.json"
CLOSE_FILE = "close"
HEARTBEAT_SECONDS = 2.0
# The web considers a session open while its heartbeat is this recent.
SESSION_TIMEOUT_SECONDS = 20.0
SWITCH = "SCIPION_WEB_INTERACTIVE_PICKER"


def channelFolder(outputDir: str) -> str:
    return os.path.join(outputDir, CHANNEL_FOLDER)


def _writeJson(path: str, value: Dict[str, Any]) -> None:
    temporary = "%s.%s.tmp" % (path, uuid.uuid4().hex)
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(value, handle)
    os.replace(temporary, path)


def _readJson(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def readSession(outputDir: str) -> Optional[Dict[str, Any]]:
    """The open session of a picking folder, if its step is still waiting."""
    path = os.path.join(channelFolder(outputDir), SESSION_FILE)
    try:
        age = time.time() - os.stat(path).st_mtime
    except OSError:
        return None
    if age > SESSION_TIMEOUT_SECONDS:
        return None
    return _readJson(path)


def requestClose(outputDir: str) -> bool:
    folder = channelFolder(outputDir)
    if readSession(outputDir) is None:
        return False
    with open(os.path.join(folder, CLOSE_FILE), "w", encoding="utf-8") as handle:
        handle.write(str(time.time()))
    return True


def requestRegisterCoordinates(outputDir: str, timeout: float = 600.0) -> Dict[str, Any]:
    """Ask the waiting step to run registerCoords; returns its answer."""
    folder = channelFolder(outputDir)
    requestId = uuid.uuid4().hex
    request = os.path.join(folder, "register-%s.json" % requestId)
    result = os.path.join(folder, "register-%s.result.json" % requestId)
    _writeJson(request, {"id": requestId, "coordsDir": outputDir})
    deadline = time.time() + timeout
    while time.time() < deadline:
        answer = _readJson(result)
        if answer is not None:
            try:
                os.remove(result)
            except OSError:
                pass
            return answer
        if readSession(outputDir) is None:
            break
        time.sleep(0.2)
    try:
        os.remove(request)
    except OSError:
        pass
    return {"ok": False, "error": "The picking protocol did not answer"}


class WebPickerProcess:
    """Stands in for the Java picker process: wait() returns when the web closes."""

    def __init__(self, protocol, outputDir: str, mode: Optional[str] = None):
        self.protocol = protocol
        self.outputDir = outputDir
        self.mode = mode
        self.folder = channelFolder(outputDir)
        self.returncode = None
        # Identifies this launch's session; a relaunch is a new session.
        self.sessionId = "%d-%s" % (os.getpid(), uuid.uuid4().hex[:12])

    def start(self) -> "WebPickerProcess":
        os.makedirs(self.folder, exist_ok=True)
        for name in os.listdir(self.folder):
            os.remove(os.path.join(self.folder, name))
        self._heartbeat()
        return self

    def _heartbeat(self) -> None:
        _writeJson(os.path.join(self.folder, SESSION_FILE), {
            "protocolId": self.protocol.getObjId(), "pid": os.getpid(),
            "sessionId": self.sessionId, "mode": self.mode or "", "updatedAt": time.time(),
        })

    def _serveRequests(self) -> None:
        for name in sorted(os.listdir(self.folder)):
            if not (name.startswith("register-") and name.endswith(".json")) or name.endswith(".result.json"):
                continue
            path = os.path.join(self.folder, name)
            request = _readJson(path) or {}
            try:
                os.remove(path)
            except OSError:
                continue
            answer: Dict[str, Any] = {"id": request.get("id")}
            try:
                before = set(name for name, _ in self.protocol.iterOutputAttributes())
                self.protocol.registerCoords(self.outputDir)
                created = [name for name, _ in self.protocol.iterOutputAttributes() if name not in before]
                outputName = created[-1] if created else None
                output = getattr(self.protocol, outputName, None) if outputName else None
                answer.update(ok=True, outputName=outputName,
                              totalCoordinates=int(output.getSize()) if output is not None else 0)
            except Exception as error:
                import traceback
                traceback.print_exc()
                answer.update(ok=False, error=str(error) or type(error).__name__)
            _writeJson(os.path.join(self.folder, "%s.result.json" % name[:-len(".json")]), answer)

    def wait(self) -> int:
        nextHeartbeat = 0.0
        try:
            while not os.path.exists(os.path.join(self.folder, CLOSE_FILE)):
                now = time.time()
                if now >= nextHeartbeat:
                    self._heartbeat()
                    nextHeartbeat = now + HEARTBEAT_SECONDS
                self._serveRequests()
                time.sleep(0.25)
            self._serveRequests()
        finally:
            for name in (SESSION_FILE, CLOSE_FILE):
                try:
                    os.remove(os.path.join(self.folder, name))
                except OSError:
                    pass
        self.returncode = 0
        return 0

    def poll(self):
        return self.returncode


def launchWebSupervisedPicker(micsFn, outputDir, protocol, mode=None, memory=None,
                              pickerProps=None, inTmpFolder=False):
    """Replacement of pwem's launchSupervisedPickerGUI for protocol steps."""
    return WebPickerProcess(protocol, outputDir, mode).start()


def webPickerEnabled() -> bool:
    return os.environ.get(SWITCH, "1").strip().lower() not in ("0", "false", "no", "off")


@contextmanager
def webInteractivePickers():
    """While a protocol runs, its interactive picker opens in the web.

    The launcher is replaced everywhere it was imported by name (e.g.
    ``from pwem.viewers import launchSupervisedPickerGUI``) and restored after.
    """
    if not webPickerEnabled():
        yield
        return
    try:
        from pwem.viewers import showj
    except ImportError:
        yield
        return
    original = showj.launchSupervisedPickerGUI
    patched = []
    for module in list(sys.modules.values()):
        if getattr(module, "launchSupervisedPickerGUI", None) is original:
            patched.append(module)
            setattr(module, "launchSupervisedPickerGUI", launchWebSupervisedPicker)
    try:
        yield
    finally:
        for module in patched:
            setattr(module, "launchSupervisedPickerGUI", original)
