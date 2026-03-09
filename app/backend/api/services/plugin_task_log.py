import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Tuple


_PLUGIN_TASK_LOG_DIR = Path(
    os.environ.get("SCIPION_PLUGIN_TASK_LOG_DIR", "/tmp/scipion-plugin-task-logs")
)


def _timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _sanitizeTaskId(taskId: str) -> str:
    return "".join(ch for ch in str(taskId) if ch.isalnum() or ch in ("-", "_"))


def ensurePluginTaskLogDir() -> Path:
    _PLUGIN_TASK_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _PLUGIN_TASK_LOG_DIR


def getPluginTaskLogPath(taskId: str) -> Path:
    safeTaskId = _sanitizeTaskId(taskId)
    return ensurePluginTaskLogDir() / f"{safeTaskId}.log"


def initializePluginTaskLog(taskId: str, pluginName: str, operation: str) -> Path:
    path = getPluginTaskLogPath(taskId)
    with open(path, "w", encoding="utf-8", errors="replace") as fh:
        fh.write(f"[{_timestamp()}] taskId={taskId}\n")
        fh.write(f"[{_timestamp()}] operation={operation}\n")
        fh.write(f"[{_timestamp()}] plugin={pluginName}\n")
        fh.write(f"[{_timestamp()}] log-start\n\n")
    return path


def appendPluginTaskLog(taskId: str, text: str) -> None:
    path = getPluginTaskLogPath(taskId)
    with open(path, "a", encoding="utf-8", errors="replace") as fh:
        fh.write(text)
        if text and not text.endswith("\n"):
            fh.write("\n")


def writePluginTaskStep(taskId: str, step: str) -> None:
    appendPluginTaskLog(taskId, f"[{_timestamp()}] {step}")


def readPluginTaskLog(taskId: str, offset: int = 0, limit: int = 65536) -> Tuple[str, int]:
    path = getPluginTaskLogPath(taskId)
    if not path.exists():
        return "", max(0, int(offset))

    safeOffset = max(0, int(offset))
    safeLimit = max(1, int(limit))

    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        fileSize = fh.tell()
        safeOffset = min(safeOffset, fileSize)
        fh.seek(safeOffset)
        data = fh.read(safeLimit)
        nextOffset = safeOffset + len(data)

    return data.decode("utf-8", errors="replace"), nextOffset


@contextmanager
def pluginTaskLogCapture(taskId: str) -> Iterator[Path]:
    path = getPluginTaskLogPath(taskId)
    ensurePluginTaskLogDir()

    logFile = open(path, "a", encoding="utf-8", buffering=1, errors="replace")

    rootLogger = logging.getLogger()
    fileHandler = logging.StreamHandler(logFile)
    fileHandler.setLevel(logging.DEBUG)
    fileHandler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    )

    oldStdoutFd = os.dup(1)
    oldStderrFd = os.dup(2)
    oldStdout = sys.stdout
    oldStderr = sys.stderr

    redirectedStdout = None
    redirectedStderr = None

    try:
        for stream in (sys.stdout, sys.stderr, getattr(sys, "__stdout__", None), getattr(sys, "__stderr__", None)):
            try:
                if stream is not None:
                    stream.flush()
            except Exception:
                pass

        os.dup2(logFile.fileno(), 1)
        os.dup2(logFile.fileno(), 2)

        redirectedStdout = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8", errors="replace")
        redirectedStderr = os.fdopen(os.dup(2), "w", buffering=1, encoding="utf-8", errors="replace")

        sys.stdout = redirectedStdout
        sys.stderr = redirectedStderr

        rootLogger.addHandler(fileHandler)
        yield path
    finally:
        try:
            if redirectedStdout is not None:
                redirectedStdout.flush()
        except Exception:
            pass

        try:
            if redirectedStderr is not None:
                redirectedStderr.flush()
        except Exception:
            pass

        try:
            rootLogger.removeHandler(fileHandler)
        except Exception:
            pass

        try:
            fileHandler.flush()
        except Exception:
            pass

        os.dup2(oldStdoutFd, 1)
        os.dup2(oldStderrFd, 2)

        os.close(oldStdoutFd)
        os.close(oldStderrFd)

        sys.stdout = oldStdout
        sys.stderr = oldStderr

        try:
            if redirectedStdout is not None:
                redirectedStdout.close()
        except Exception:
            pass

        try:
            if redirectedStderr is not None:
                redirectedStderr.close()
        except Exception:
            pass

        try:
            fileHandler.close()
        except Exception:
            pass

        try:
            logFile.close()
        except Exception:
            pass