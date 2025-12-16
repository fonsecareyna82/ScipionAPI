# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# * Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from scipionapi_cli.shell import resolveRepoRoot
from scipionapi_cli.envfile import readEnvFile, exportEnvToOs


def _resolveScipionHome(repoRoot: Path) -> Path:
    # resolveScipionHome
    configured = (os.getenv("SCIPION_HOME") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (repoRoot / "scipion_home").resolve()


def _envPathForScipionHome(scipionHome: Path) -> Path:
    # envPathForScipionHome
    return scipionHome / ".env"


def _pidDir(scipionHome: Path) -> Path:
    # ensurePidDir
    runDir = scipionHome / ".run"
    runDir.mkdir(exist_ok=True, parents=True)
    return runDir


def _isProcessAlive(pid: int) -> bool:
    # isProcessAliveCheck
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True


def _readPid(pidPath: Path) -> int:
    # readPidFile
    return int(pidPath.read_text(encoding="utf-8").strip())


def _writePid(pidPath: Path, pid: int) -> None:
    # writePidFile
    pidPath.write_text(str(pid), encoding="utf-8")


def _safeUnlink(path: Path) -> None:
    # safeUnlink
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception:
        return


def _ensureLogFile(logPath: Path) -> None:
    # ensureLogFileExists
    logPath.parent.mkdir(exist_ok=True, parents=True)
    if not logPath.exists():
        logPath.touch()


def _readLastLines(filePath: Path, maxLines: int = 120, maxBytes: int = 65536) -> str:
    # readLastLinesForDiagnostics
    try:
        if not filePath.exists():
            return f"(log file not found: {filePath})"
        with open(filePath, "rb") as f:
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - maxBytes), os.SEEK_SET)
            except Exception:
                f.seek(0, os.SEEK_SET)
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()[-maxLines:]
        return "\n".join(lines).strip()
    except Exception as e:
        return f"(failed to read log tail: {e})"


def _terminateProcessGroup(pid: int, timeoutSec: float = 5.0) -> None:
    # terminateProcessGroup
    if not _isProcessAlive(pid):
        return

    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            return

    deadline = time.time() + timeoutSec
    while time.time() < deadline:
        if not _isProcessAlive(pid):
            return
        time.sleep(0.2)

    # forceKillFallback
    try:
        os.killpg(pid, signal.SIGKILL)
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            return


def _stopPid(pidPath: Path) -> None:
    # stopProcessByPidFile
    if not pidPath.exists():
        return

    try:
        pid = _readPid(pidPath)
    except Exception:
        _safeUnlink(pidPath)
        return

    _terminateProcessGroup(pid)
    _safeUnlink(pidPath)


def _startDetachedProcess(
    args: list,
    cwd: Path,
    env: dict,
    logPath: Path,
    sanityWaitSec: float = 1.0,
) -> int:
    # startDetachedProcessWithSanityCheck
    _ensureLogFile(logPath)

    with open(logPath, "a", encoding="utf-8") as logFile:
        proc = subprocess.Popen(
            args,
            cwd=str(cwd),
            env=env,
            stdout=logFile,
            stderr=logFile,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    # quickSanityCheck
    time.sleep(max(0.1, sanityWaitSec))
    if proc.poll() is not None:
        tail = _readLastLines(logPath, maxLines=120)
        raise RuntimeError(
            "Process exited immediately.\n"
            f"Command: {' '.join(str(x) for x in args)}\n"
            f"Exit code: {proc.returncode}\n"
            f"Log tail ({logPath}):\n{tail}\n"
        )

    return proc.pid


def startCommand() -> None:
    # startApiAndWorker
    repoRoot = resolveRepoRoot()
    scipionHome = _resolveScipionHome(repoRoot)
    envPath = _envPathForScipionHome(scipionHome)

    exportEnvToOs(envPath)
    env = readEnvFile(envPath)

    runDir = _pidDir(scipionHome)
    apiPidPath = runDir / "api.pid"
    workerPidPath = runDir / "worker.pid"

    logsDir = Path(env.get("LOGS_PATH", str(scipionHome / "logs"))).resolve()
    logsDir.mkdir(exist_ok=True, parents=True)
    apiLogPath = logsDir / "app.log"
    workerLogPath = logsDir / "celery.log"

    apiHost = env.get("API_HOST", "0.0.0.0")
    apiPort = env.get("API_PORT", "8080")

    celeryApp = env.get("CELERY_APP", "app.workers.task_queue")
    celeryLogLevel = env.get("CELERY_LOGLEVEL", "info")

    # startApiIfNotRunning
    if apiPidPath.exists():
        pid = _readPid(apiPidPath)
        if _isProcessAlive(pid):
            print(f"API already running (pid={pid})")
        else:
            _safeUnlink(apiPidPath)

    if not apiPidPath.exists():
        apiEnv = os.environ.copy()
        apiEnv["PYTHONPATH"] = str(repoRoot)
        apiEnv["PYTHONUNBUFFERED"] = "1"
        apiEnv["SCIPION_HOME"] = str(scipionHome)

        pid = _startDetachedProcess(
            [sys.executable, "-m", "uvicorn", "app.backend.main:app", "--host", apiHost, "--port", str(apiPort)],
            cwd=repoRoot,
            env=apiEnv,
            logPath=apiLogPath,
            sanityWaitSec=1.0,
        )
        _writePid(apiPidPath, pid)
        print(f"API started (pid={pid})")

    # startWorkerIfNotRunning
    if workerPidPath.exists():
        pid = _readPid(workerPidPath)
        if _isProcessAlive(pid):
            print(f"Worker already running (pid={pid})")
        else:
            _safeUnlink(workerPidPath)

    if not workerPidPath.exists():
        workerEnv = os.environ.copy()
        workerEnv["PYTHONPATH"] = str(repoRoot)
        workerEnv["PYTHONUNBUFFERED"] = "1"
        workerEnv["SCIPION_HOME"] = str(scipionHome)

        pid = _startDetachedProcess(
            [sys.executable, "-m", "celery", "-A", celeryApp, "worker", "--loglevel", celeryLogLevel],
            cwd=repoRoot,
            env=workerEnv,
            logPath=workerLogPath,
            sanityWaitSec=1.0,
        )
        _writePid(workerPidPath, pid)
        print(f"Worker started (pid={pid})")


def stopCommand() -> None:
    # stopApiAndWorker
    repoRoot = resolveRepoRoot()
    scipionHome = _resolveScipionHome(repoRoot)
    runDir = _pidDir(scipionHome)

    _stopPid(runDir / "api.pid")
    _stopPid(runDir / "worker.pid")
    print("Stopped.")


def restartCommand() -> None:
    # restartApiAndWorker
    stopCommand()
    time.sleep(0.5)
    startCommand()


def statusCommand() -> None:
    # statusApiAndWorker
    repoRoot = resolveRepoRoot()
    scipionHome = _resolveScipionHome(repoRoot)
    runDir = _pidDir(scipionHome)

    apiPidPath = runDir / "api.pid"
    workerPidPath = runDir / "worker.pid"

    if apiPidPath.exists():
        pid = _readPid(apiPidPath)
        print(f"API: RUNNING (pid={pid})" if _isProcessAlive(pid) else "API: STALE PID")
    else:
        print("API: STOPPED")

    if workerPidPath.exists():
        pid = _readPid(workerPidPath)
        print(f"Worker: RUNNING (pid={pid})" if _isProcessAlive(pid) else "Worker: STALE PID")
    else:
        print("Worker: STOPPED")


def logsCommand() -> None:
    # tailLogs
    repoRoot = resolveRepoRoot()
    scipionHome = _resolveScipionHome(repoRoot)
    envPath = _envPathForScipionHome(scipionHome)

    exportEnvToOs(envPath)
    env = readEnvFile(envPath)

    logsDir = Path(env.get("LOGS_PATH", str(scipionHome / "logs"))).resolve()
    appLog = logsDir / "app.log"
    celeryLog = logsDir / "celery.log"

    _ensureLogFile(appLog)
    _ensureLogFile(celeryLog)

    subprocess.run(["tail", "-n", "200", "-f", str(appLog), str(celeryLog)])
