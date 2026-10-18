"""Xmipp's supervised picking classifier, kept alive per picking session.

The classifier (C++ AutoParticlePicking2) is only reachable through Xmipp's
Java bindings, and its correction step needs the candidates of the previous
autopick, which exist only in memory. So, like the desktop picker, each
picking session keeps one classifier process alive: XmippPickerSession.java,
run without a GUI, answering one tab-separated command per line.
The trained model itself lives in the session folder (``model_*`` files), so
a new process continues from where an old one stopped.

While the protocol's interactive step waits for the web picker, the process
lives with that step, as the Java picker does on the desktop, and the API
reaches it through the step (``StepClassifier``). Otherwise (a picker opened on
a finished protocol) it lives in the API process.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

RUNNER_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "XmippPickerSession.java")
ANSWER_PREFIX = "@@picker "
IDLE_SECONDS = 15 * 60
COMMAND_TIMEOUT = 600


class ClassifierError(RuntimeError):
    pass


def javaCommand() -> Tuple[List[str], Dict[str, str]]:
    """Command and environment to run the runner, as Scipion runs Xmipp's Java."""
    from pwem.viewers.showj import getJavaBin, getJavaIJappArguments
    import xmipp3

    arguments = shlex.split(getJavaIJappArguments(None, "XmippPickerSession", ""))
    # getJavaIJappArguments ends with the application name; ours is a source file.
    arguments = [arg for arg in arguments if arg != "XmippPickerSession"]
    command = [getJavaBin(), "-Djava.awt.headless=true"] + arguments + [RUNNER_SOURCE]
    return command, dict(xmipp3.Plugin.getEnviron())


class ClassifierSession:
    """One live classifier for one picking folder."""

    def __init__(self, folder: str, particleSize: int, micrographs: Sequence[str], cwd: str):
        self.folder = folder
        self.particleSize = particleSize
        self.micrographs = tuple(micrographs)
        self.lastAutopicked: Optional[str] = None
        # (micrograph id, rectangle) of the last training, as the Java picker keeps it.
        self.trainedOn: Optional[Tuple[str, Tuple[int, int, int, int]]] = None
        self.lastUsed = time.time()
        self._lock = threading.Lock()
        command, env = javaCommand()
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=cwd, env=env, text=True, bufsize=1, start_new_session=True)
        micsFile = os.path.join(folder, ".web_classifier_mics.txt")
        with open(micsFile, "w", encoding="utf-8") as handle:
            handle.write("\n".join(self.micrographs) + "\n")
        self.call("create", particleSize, os.path.join(folder, "model"), micsFile)

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def call(self, *args, timeout: float = COMMAND_TIMEOUT) -> List[str]:
        """Send one command; returns the answer fields after 'ok'."""
        with self._lock:
            self.lastUsed = time.time()
            if not self.alive:
                raise ClassifierError("The picking classifier stopped")
            self.process.stdin.write("\t".join(str(arg) for arg in args) + "\n")
            self.process.stdin.flush()
            deadline = time.time() + timeout
            log: List[str] = []
            while time.time() < deadline:
                line = self.process.stdout.readline()
                if not line:
                    raise ClassifierError("The picking classifier stopped: %s" % " ".join(log[-5:]))
                if not line.startswith(ANSWER_PREFIX):
                    log.append(line.strip())  # Xmipp's own output.
                    continue
                fields = line[len(ANSWER_PREFIX):].rstrip("\n").split("\t")
                if fields[0] == "error":
                    raise ClassifierError(fields[1] if len(fields) > 1 else "Classifier error")
                return fields[1:]
            self.close()
            raise ClassifierError("The picking classifier did not answer in time")

    def train(self, trainRows: Sequence[Tuple[str, str]], rectangle: Tuple[int, int, int, int]) -> None:
        trainFile = os.path.join(self.folder, ".web_classifier_train.txt")
        with open(trainFile, "w", encoding="utf-8") as handle:
            handle.write("".join("%s\t%s\n" % row for row in trainRows))
        self.call("train", trainFile, *rectangle)

    def autopick(self, micrograph: str, percent: int) -> List[Tuple[int, int, float]]:
        outFile = os.path.join(self.folder, ".web_classifier_auto.txt")
        self.call("autopick", micrograph, int(percent), outFile)
        self.lastAutopicked = micrograph
        particles = []
        with open(outFile, "r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 3:
                    particles.append((int(parts[0]), int(parts[1]), float(parts[2])))
        return particles

    def correct(self, added: Sequence[Tuple[int, int]],
                automatic: Sequence[Tuple[int, int, float, int]]) -> None:
        manualFile = os.path.join(self.folder, ".web_classifier_manual.txt")
        autoFile = os.path.join(self.folder, ".web_classifier_auto_rows.txt")
        with open(manualFile, "w", encoding="utf-8") as handle:
            handle.write("".join("%d %d\n" % point for point in added))
        with open(autoFile, "w", encoding="utf-8") as handle:
            handle.write("".join("%d %d %r %d\n" % row for row in automatic))
        self.call("correct", manualFile, autoFile)

    def close(self) -> None:
        try:
            if self.alive:
                self.process.stdin.write("quit\n")
                self.process.stdin.flush()
                self.process.wait(timeout=10)
        except Exception:
            pass
        if self.alive:
            self.process.kill()


_sessions: Dict[str, ClassifierSession] = {}
_sessionsLock = threading.Lock()


def classifierSession(folder: str, particleSize: int, micrographs: Sequence[str],
                      cwd: str) -> ClassifierSession:
    """The live classifier of a picking folder, started if needed."""
    with _sessionsLock:
        _closeIdle()
        session = _sessions.get(folder)
        if (session is not None and session.alive and session.particleSize == particleSize
                and session.micrographs == tuple(micrographs)):
            return session
        if session is not None:
            session.close()
        session = ClassifierSession(folder, particleSize, micrographs, cwd)
        _sessions[folder] = session
        return session


def _closeIdle() -> None:
    now = time.time()
    for folder, session in list(_sessions.items()):
        if not session.alive or now - session.lastUsed > IDLE_SECONDS:
            session.close()
            del _sessions[folder]


def closeClassifierSession(folder: str) -> None:
    with _sessionsLock:
        session = _sessions.pop(folder, None)
    if session is not None:
        session.close()


class StepClassifier:
    """The classifier kept alive by the protocol's waiting step, as seen from the API.

    Same operations as ClassifierSession; each one is a request to the step.
    """

    def __init__(self, folder: str, particleSize: int, micrographs: Sequence[str], cwd: str):
        self.folder = folder
        self.particleSize = particleSize
        self.micrographs = tuple(micrographs)
        self.cwd = cwd
        # Kept on disk by the caller: the step's process may outlive this object.
        self.trainedOn: Optional[Tuple[str, Tuple[int, int, int, int]]] = None
        self._lastAutopicked: Optional[str] = None
        self._stateKnown = False

    def _request(self, operation: str, **arguments):
        from app.backend.runtime import web_interactive_picker as interactive
        answer = interactive.requestClassifier(self.folder, dict(
            arguments, operation=operation, particleSize=self.particleSize,
            micrographs=list(self.micrographs), cwd=self.cwd), timeout=COMMAND_TIMEOUT)
        if not answer.get("ok"):
            raise ClassifierError(answer.get("error") or "The picking protocol did not answer")
        self._lastAutopicked = answer.get("lastAutopicked")
        self._stateKnown = True
        return answer.get("result")

    @property
    def lastAutopicked(self) -> Optional[str]:
        if not self._stateKnown:
            self._request("state")
        return self._lastAutopicked

    def train(self, trainRows: Sequence[Tuple[str, str]], rectangle: Tuple[int, int, int, int]) -> None:
        self._request("train", rows=[list(row) for row in trainRows], rectangle=list(rectangle))

    def autopick(self, micrograph: str, percent: int) -> List[Tuple[int, int, float]]:
        found = self._request("autopick", micrograph=micrograph, percent=int(percent)) or []
        return [(int(x), int(y), float(cost)) for x, y, cost in found]

    def correct(self, added: Sequence[Tuple[int, int]],
                automatic: Sequence[Tuple[int, int, float, int]]) -> None:
        self._request("correct", added=[list(point) for point in added],
                      automatic=[list(row) for row in automatic])
