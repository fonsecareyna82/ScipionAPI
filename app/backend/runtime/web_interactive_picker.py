"""Xmipp's interactive particle picker, run in the web instead of a Java window.

On the desktop, a picking protocol's interactive step opens the Java picker
and waits until it is closed; meanwhile the picker registers coordinates by
asking the protocol, over TCP, to run ``registerCoords``. Here the step opens
a web session instead and waits the same way. The web and this step talk
through files in the session folder (``<extra>/.scipionweb_picker``):

  session.json          written and refreshed by the step while it waits
  register-<id>.json    the web asks the protocol to register coordinates;
                        the step answers in register-<id>.result.json
  classifier-<id>.json  the web asks the supervised picking classifier (train,
                        autopick, correct); answered in classifier-<id>.result.json
  close                 the web closed the picker: the step finishes

The files live in the protocol folder, so this works with the protocol worker
on any node that shares the project folder with the API, and with any number
of API processes. Like the Java picker on the desktop, the classifier process
lives with the step: it starts on the first request and ends with the step.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
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
    return _requestStep(outputDir, "register", {"coordsDir": outputDir}, timeout)


def requestClassifier(outputDir: str, request: Dict[str, Any], timeout: float = 600.0) -> Dict[str, Any]:
    """Ask the waiting step's picking classifier to run one operation; returns its answer."""
    return _requestStep(outputDir, "classifier", request, timeout)


def _requestStep(outputDir: str, kind: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    folder = channelFolder(outputDir)
    requestId = uuid.uuid4().hex
    request = os.path.join(folder, "%s-%s.json" % (kind, requestId))
    result = os.path.join(folder, "%s-%s.result.json" % (kind, requestId))
    _writeJson(request, dict(payload, id=requestId))
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
        time.sleep(0.1)
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
        self.classifier = None

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
        handlers = {"register": self._registerCoordinates, "classifier": self._runClassifier}
        for name in sorted(os.listdir(self.folder)):
            kind = name.split("-", 1)[0]
            if kind not in handlers or not name.endswith(".json") or name.endswith(".result.json"):
                continue
            path = os.path.join(self.folder, name)
            request = _readJson(path) or {}
            try:
                os.remove(path)
            except OSError:
                continue
            answer: Dict[str, Any] = {"id": request.get("id")}
            try:
                answer.update(handlers[kind](request), ok=True)
            except Exception as error:
                traceback.print_exc()
                answer.update(ok=False, error=str(error) or type(error).__name__)
            _writeJson(os.path.join(self.folder, "%s.result.json" % name[:-len(".json")]), answer)

    def _registerCoordinates(self, request: Dict[str, Any]) -> Dict[str, Any]:
        before = set(name for name, _ in self.protocol.iterOutputAttributes())
        self.protocol.registerCoords(self.outputDir)
        created = [name for name, _ in self.protocol.iterOutputAttributes() if name not in before]
        outputName = created[-1] if created else None
        output = getattr(self.protocol, outputName, None) if outputName else None
        return {"outputName": outputName,
                "totalCoordinates": int(output.getSize()) if output is not None else 0}

    def _runClassifier(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """One operation of the supervised picking classifier, kept alive by this step."""
        from app.backend.runtime import xmipp_classifier_session as classifiers
        self.classifier = classifiers.classifierSession(
            self.outputDir, int(request["particleSize"]), list(request["micrographs"]), request["cwd"])
        operation = request["operation"]
        result: Any = None
        if operation == "train":
            self.classifier.train([tuple(row) for row in request["rows"]], tuple(request["rectangle"]))
        elif operation == "autopick":
            result = self.classifier.autopick(request["micrograph"], int(request["percent"]))
        elif operation == "correct":
            self.classifier.correct([tuple(point) for point in request["added"]],
                                    [tuple(row) for row in request["automatic"]])
        elif operation != "state":
            raise ValueError("Unknown classifier operation: %s" % operation)
        return {"result": result, "lastAutopicked": self.classifier.lastAutopicked}

    def _closeClassifier(self) -> None:
        if self.classifier is not None:
            from app.backend.runtime import xmipp_classifier_session as classifiers
            classifiers.closeClassifierSession(self.outputDir)
            self.classifier = None

    def _keepAlive(self, stop: threading.Event) -> None:
        # Separate from the requests: training may take longer than the web waits for a heartbeat.
        while not stop.is_set():
            self._heartbeat()
            stop.wait(HEARTBEAT_SECONDS)

    def wait(self) -> int:
        stop = threading.Event()
        heartbeat = threading.Thread(target=self._keepAlive, args=(stop,), daemon=True)
        heartbeat.start()
        try:
            while not os.path.exists(os.path.join(self.folder, CLOSE_FILE)):
                self._serveRequests()
                time.sleep(0.1)
            self._serveRequests()
        finally:
            stop.set()
            heartbeat.join(HEARTBEAT_SECONDS + 1)
            self._closeClassifier()
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
