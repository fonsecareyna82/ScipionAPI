import os
import signal
import socket
import sys
import time
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from scipionapi_cli.shell import resolveRepoRoot
from scipionapi_cli.envfile import readEnvFile, exportEnvToOs


console = Console()


def _pidDir(repoRoot: Path) -> Path:
    # ensurePidDir
    runDir = repoRoot / ".run"
    runDir.mkdir(exist_ok=True)
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


def _readPidSafe(pidPath: Path) -> Optional[int]:
    # readPidFileSafe
    try:
        return _readPid(pidPath)
    except Exception:
        return None


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


def _readLastLines(filePath: Path, maxLines: int = 80, maxBytes: int = 65536) -> str:
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
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception:
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

    try:
        os.killpg(pid, signal.SIGKILL)
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            return


def _stopPid(pidPath: Path) -> Tuple[str, Optional[int]]:
    # stopProcessByPidFile
    if not pidPath.exists():
        return "missing", None

    pid = _readPidSafe(pidPath)
    if pid is None:
        _safeUnlink(pidPath)
        return "invalid", None

    aliveBefore = _isProcessAlive(pid)
    _terminateProcessGroup(pid)
    _safeUnlink(pidPath)

    if aliveBefore:
        return "stopped", pid

    return "stale", pid


def _ensureLogFile(logPath: Path) -> None:
    # ensureLogFileExists
    logPath.parent.mkdir(exist_ok=True, parents=True)
    if not logPath.exists():
        logPath.touch()


def _startDetachedProcess(
    args: List[str],
    cwd: Path,
    env: Dict[str, str],
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


def _resolveScipionHome(repoRoot: Path) -> Path:
    # resolveScipionHomeFromEnvOrDefault
    configured = (os.getenv("SCIPION_HOME") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (repoRoot / "scipion_home").resolve()


def _resolveEnvPath(repoRoot: Path) -> Path:
    # resolveEnvPath
    return _resolveScipionHome(repoRoot) / ".env"


def _loadEnv(repoRoot: Path) -> Dict[str, str]:
    # loadEnvFromScipionHome
    envPath = _resolveEnvPath(repoRoot)
    exportEnvToOs(envPath)
    return readEnvFile(envPath)


def _normalizeDisplayHost(host: str) -> str:
    # normalizeDisplayHost
    value = (host or "").strip()
    if value in ("", "0.0.0.0", "::"):
        return "127.0.0.1"
    return value


def _tcpReachable(host: str, port: str, timeoutSec: float = 1.0) -> bool:
    # tcpReachable
    try:
        targetHost = _normalizeDisplayHost(host)
        targetPort = int(str(port).strip())
        with socket.create_connection((targetHost, targetPort), timeout=timeoutSec):
            return True
    except Exception:
        return False


def _canBindTcpPort(host: str, port: str) -> bool:
    # Check whether the configured API address can be bound.
    try:
        bindHost = (host or "0.0.0.0").strip()
        bindPort = int(str(port).strip())

        family = (
            socket.AF_INET6
            if ":" in bindHost
            else socket.AF_INET
        )

        with socket.socket(
            family,
            socket.SOCK_STREAM,
        ) as sock:
            sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1,
            )
            sock.bind((bindHost, bindPort))

        return True

    except Exception:
        return False

def _httpCheck(url: str, timeoutSec: float = 2.0) -> Tuple[bool, str]:
    # httpCheck
    try:
        req = Request(url, headers={"User-Agent": "scipionapi-cli/1.0"})
        with urlopen(req, timeout=timeoutSec) as response:
            status = getattr(response, "status", None) or response.getcode()
            if 200 <= int(status) < 400:
                return True, f"HTTP {status}"
            return False, f"HTTP {status}"
    except HTTPError as e:
        return False, f"HTTP {e.code}"
    except URLError as e:
        reason = getattr(e, "reason", None)
        return False, f"{reason}" if reason else "URL error"
    except Exception as e:
        return False, str(e)


def _envFloat(env: Dict[str, str], key: str, default: float) -> float:
    # readFloatEnv
    try:
        return float(env.get(key, default))
    except Exception:
        return default


def _envInt(env: Dict[str, str], key: str, default: int) -> int:
    # readIntEnv
    try:
        return int(env.get(key, default))
    except Exception:
        return default


def _waitForTcp(host: str, port: str, timeoutSec: float, intervalSec: float = 0.5) -> bool:
    # waitForTcpEndpoint
    deadline = time.time() + max(0.1, timeoutSec)

    while time.time() < deadline:
        if _tcpReachable(host, port, timeoutSec=1.0):
            return True
        time.sleep(max(0.1, intervalSec))

    return False


def _waitForHttp(url: str, timeoutSec: float, intervalSec: float = 0.5) -> Tuple[bool, str]:
    # waitForHttpEndpoint
    deadline = time.time() + max(0.1, timeoutSec)
    lastDetail = "not checked"

    while time.time() < deadline:
        ok, detail = _httpCheck(url, timeoutSec=2.0)
        lastDetail = detail

        if ok:
            return True, detail

        time.sleep(max(0.1, intervalSec))

    return False, lastDetail


def _getProcessElapsedTime(pid: int) -> Optional[str]:
    # getProcessElapsedTime
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "etime="],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return None
        value = (proc.stdout or "").strip()
        return value or None
    except Exception:
        return None


def _describePidState(pidPath: Path) -> Tuple[str, Optional[int]]:
    # describePidState
    if not pidPath.exists():
        return "STOPPED", None

    pid = _readPidSafe(pidPath)
    if pid is None:
        return "INVALID PID FILE", None

    if _isProcessAlive(pid):
        return "RUNNING", pid

    return "STALE PID", pid


def _normalizeMountPath(value: str) -> str:
    # normalizeMountPath
    mountPath = (value or "/api").strip()
    if not mountPath:
        mountPath = "/api"
    if not mountPath.startswith("/"):
        mountPath = f"/{mountPath}"
    if mountPath != "/" and mountPath.endswith("/"):
        mountPath = mountPath.rstrip("/")
    return mountPath


def _docsUrl(env: Dict[str, str]) -> str:
    # buildDocsUrl
    apiHost = env.get("API_HOST", "0.0.0.0")
    apiPort = env.get("API_PORT", "8080")
    serveWeb = (env.get("SERVE_WEB") or "").strip() == "1"
    mountPath = _normalizeMountPath(env.get("API_MOUNT_PATH") or "/api")

    host = _normalizeDisplayHost(apiHost)
    if serveWeb:
        return f"http://{host}:{apiPort}{mountPath}/docs"
    return f"http://{host}:{apiPort}/docs"


def _webUrl(env: Dict[str, str]) -> Optional[str]:
    # buildWebUrl
    serveWeb = (env.get("SERVE_WEB") or "").strip() == "1"
    if not serveWeb:
        return None

    apiHost = env.get("API_HOST", "0.0.0.0")
    apiPort = env.get("API_PORT", "8080")
    host = _normalizeDisplayHost(apiHost)
    return f"http://{host}:{apiPort}/"


def _statusStyle(state: str) -> str:
    # statusStyle
    value = (state or "").upper()
    if "RUNNING" in value or value == "OK":
        return "bold green"
    if "FAILED" in value or "STOPPED" in value or "INVALID" in value:
        return "bold red"
    if "STALE" in value:
        return "bold yellow"
    return "bold cyan"


def _printPanel(title: str, body: str = "") -> None:
    # printPanel
    console.print(Panel.fit(body or "", title=title, border_style="cyan"))


def _printKeyValueTable(title: str, rows: List[Tuple[str, Any]]) -> None:
    # printKeyValueTable
    table = Table(title=title, show_header=True, header_style="bold magenta")
    table.add_column("Field", style="bold white", no_wrap=True)
    table.add_column("Value", style="white")

    for key, value in rows:
        table.add_row(str(key), str(value))

    console.print(table)


def _printServiceStatusTable(title: str, rows: List[Tuple[str, Any]]) -> None:
    # printServiceStatusTable
    table = Table(title=title, show_header=True, header_style="bold magenta")
    table.add_column("Field", style="bold white", no_wrap=True)
    table.add_column("Value", style="white")

    for key, value in rows:
        valueText = str(value)
        style = None

        if str(key).lower() in {"state", "tcp check", "http docs check", "http web check"}:
            style = _statusStyle(valueText)

        if style:
            table.add_row(str(key), Text(valueText, style=style))
        else:
            table.add_row(str(key), valueText)

    console.print(table)


def _printSummaryTable(rows: List[Tuple[str, Any]]) -> None:
    # printSummaryTable
    table = Table(title="Summary", show_header=True, header_style="bold magenta")
    table.add_column("Component", style="bold white", no_wrap=True)
    table.add_column("Status / Location", style="white")

    for key, value in rows:
        valueText = str(value)
        style = None
        if key in {"API", "Worker", "Plugin worker", "Protocol worker"}:
            style = _statusStyle(valueText)

        if style:
            table.add_row(str(key), Text(valueText, style=style))
        else:
            table.add_row(str(key), valueText)

    console.print(table)


def _printInfo(message: str) -> None:
    # printInfo
    console.print("[bold cyan]INFO[/bold cyan] " + message)


def _printSuccess(message: str) -> None:
    # printSuccess
    console.print("[bold green]SUCCESS[/bold green] " + message)


def _buildCeleryWorkerCommand(
    celeryApp: str,
    celeryLogLevel: str,
    queueName: str,
    concurrency: int,
    hostname: str,
) -> List[str]:
    return [
        sys.executable,
        "-m",
        "celery",
        "-A",
        celeryApp,
        "worker",
        "--loglevel",
        celeryLogLevel,
        "--hostname",
        hostname,
        "-Q",
        queueName,
        "--concurrency",
        str(concurrency),
        "--prefetch-multiplier",
        "1",
    ]


def _getWorkerPidPath(
    repoRoot: Path,
    workerKind: str,
) -> Path:
    kind = str(workerKind or "").strip().lower()

    if kind == "plugins":
        return _pidDir(repoRoot) / "worker.pid"

    if kind == "protocols":
        return _pidDir(repoRoot) / "protocol-worker.pid"

    raise ValueError(
        f"Unsupported worker kind: {workerKind}"
    )


def getWorkerProcessState(
    workerKind: str,
) -> Dict[str, Any]:
    repoRoot = resolveRepoRoot()
    pidPath = _getWorkerPidPath(
        repoRoot,
        workerKind,
    )

    rawState, pid = _describePidState(
        pidPath
    )

    stateMap = {
        "RUNNING": "running",
        "STOPPED": "stopped",
        "STALE PID": "stale",
        "INVALID PID FILE": "invalid",
    }

    return {
        "kind": str(workerKind).strip().lower(),
        "state": stateMap.get(
            rawState,
            rawState.lower(),
        ),
        "pid": pid,
        "pidPath": str(pidPath),
    }


def adoptWorkerProcess(
    workerKind: str,
    pid: int,
) -> Dict[str, Any]:
    repoRoot = resolveRepoRoot()
    pidPath = _getWorkerPidPath(
        repoRoot,
        workerKind,
    )

    pid = int(pid)

    if pid <= 0:
        raise ValueError(
            f"Invalid worker PID: {pid}"
        )

    if not _isProcessAlive(pid):
        raise RuntimeError(
            f"Worker process {pid} is not running."
        )

    _writePid(
        pidPath,
        pid,
    )

    return getWorkerProcessState(
        workerKind
    )


def _getWorkerRuntimeSpec(
    workerKind: str,
) -> Dict[str, Any]:
    kind = str(workerKind or "").strip().lower()

    if kind not in {
        "plugins",
        "protocols",
    }:
        raise ValueError(
            f"Unsupported worker kind: {workerKind}"
        )

    repoRoot = resolveRepoRoot()
    env = _loadEnv(repoRoot)

    logsDir = Path(
        env.get(
            "LOGS_PATH",
            str(
                _resolveScipionHome(repoRoot)
                / "logs"
            ),
        )
    )

    logsDir.mkdir(
        exist_ok=True,
        parents=True,
    )

    celeryApp = env.get(
        "CELERY_APP",
        "app.workers.task_queue",
    )

    celeryLogLevel = env.get(
        "CELERY_LOGLEVEL",
        "info",
    )

    startupWait = _envFloat(
        env,
        "WORKER_STARTUP_WAIT",
        2.0,
    )

    if kind == "plugins":
        queueName = "plugins"
        hostname = "plugins@%h"
        concurrency = 1
        logPath = logsDir / "celery.log"

    else:
        queueName = "protocols"
        hostname = "protocols@%h"
        concurrency = max(
            1,
            _envInt(
                env,
                "PROTOCOL_WORKER_CONCURRENCY",
                4,
            ),
        )
        logPath = (
            logsDir
            / "celery-protocols.log"
        )

    return {
        "kind": kind,
        "repoRoot": repoRoot,
        "pidPath": _getWorkerPidPath(
            repoRoot,
            kind,
        ),
        "logPath": logPath,
        "celeryApp": celeryApp,
        "celeryLogLevel": celeryLogLevel,
        "queueName": queueName,
        "hostname": hostname,
        "concurrency": concurrency,
        "startupWait": startupWait,
    }


def _recoverInterruptedPluginTasks() -> int:
    try:
        from app.backend.api.services.plugin_task_log import (
            appendPluginTaskLog,
        )
        from app.backend.api.services.system_task_service import (
            SystemTaskService,
        )

        service = SystemTaskService()

        tasks = service.listTasks(
            taskType="plugin",
            includeAcknowledged=True,
            limit=500,
        )

        interruptedStatuses = {
            "STARTED",
            "PROGRESS",
            "RETRY",
        }

        recovered = 0

        for task in tasks:
            backend = str(
                task.get("backend")
                or ""
            ).strip().lower()

            status = str(
                task.get("status")
                or ""
            ).strip().upper()

            if (
                backend != "celery"
                or status not in interruptedStatuses
            ):
                continue

            taskId = str(
                task.get("taskId")
                or ""
            ).strip()

            if not taskId:
                continue

            message = (
                "Plugin task was interrupted because "
                "the plugin worker restarted before "
                "completion. The operation may have "
                "been partially applied; verify the "
                "plugin state and retry if needed."
            )

            service.updateTask(
                taskId=taskId,
                status="FAILURE",
                step="Interrupted",
                error=message,
            )

            try:
                appendPluginTaskLog(
                    taskId,
                    f"[recovery] {message}",
                )
            except Exception:
                pass

            recovered += 1

        return recovered

    except Exception:
        return 0


def startWorkerProcess(
    workerKind: str,
) -> Dict[str, Any]:
    spec = _getWorkerRuntimeSpec(
        workerKind
    )

    state = getWorkerProcessState(
        workerKind
    )

    if state["state"] == "running":
        return state

    if state["state"] in {
        "stale",
        "invalid",
    }:
        _safeUnlink(
            spec["pidPath"]
        )

    if spec["kind"] == "plugins":
        _recoverInterruptedPluginTasks()

    workerEnv = os.environ.copy()
    workerEnv["PYTHONPATH"] = str(
        spec["repoRoot"]
    )
    workerEnv["PYTHONUNBUFFERED"] = "1"

    command = _buildCeleryWorkerCommand(
        celeryApp=spec["celeryApp"],
        celeryLogLevel=spec[
            "celeryLogLevel"
        ],
        queueName=spec["queueName"],
        concurrency=spec["concurrency"],
        hostname=spec["hostname"],
    )

    pid = _startDetachedProcess(
        command,
        cwd=spec["repoRoot"],
        env=workerEnv,
        logPath=spec["logPath"],
        sanityWaitSec=spec[
            "startupWait"
        ],
    )

    _writePid(
        spec["pidPath"],
        pid,
    )

    return getWorkerProcessState(
        workerKind
    )


def stopWorkerProcess(
    workerKind: str,
) -> Dict[str, Any]:
    repoRoot = resolveRepoRoot()

    _stopPid(
        _getWorkerPidPath(
            repoRoot,
            workerKind,
        )
    )

    return getWorkerProcessState(
        workerKind
    )


def restartWorkerProcess(
    workerKind: str,
) -> Dict[str, Any]:
    stopWorkerProcess(
        workerKind
    )

    time.sleep(0.5)

    return startWorkerProcess(
        workerKind
    )


def startCommand() -> None:
    # startApiAndWorkers
    repoRoot = resolveRepoRoot()
    env = _loadEnv(repoRoot)
    envPath = _resolveEnvPath(repoRoot)

    runDir = _pidDir(repoRoot)
    apiPidPath = runDir / "api.pid"
    workerPidPath = runDir / "worker.pid"
    protocolWorkerPidPath = runDir / "protocol-worker.pid"

    logsDir = Path(env.get("LOGS_PATH", str(_resolveScipionHome(repoRoot) / "logs")))
    logsDir.mkdir(exist_ok=True, parents=True)
    apiLogPath = logsDir / "app.log"
    workerLogPath = logsDir / "celery.log"
    protocolWorkerLogPath = logsDir / "celery-protocols.log"

    apiHost = env.get("API_HOST", "0.0.0.0")
    apiPort = env.get("API_PORT", "8080")
    celeryApp = env.get("CELERY_APP", "app.workers.task_queue")
    celeryLogLevel = env.get("CELERY_LOGLEVEL", "info")
    protocolWorkerConcurrency = max(1, _envInt(env, "PROTOCOL_WORKER_CONCURRENCY", 4))

    apiStartupTimeout = _envFloat(env, "API_STARTUP_TIMEOUT", 20.0)
    workerStartupWait = _envFloat(env, "WORKER_STARTUP_WAIT", 2.0)

    _printPanel("Starting Scipion API services")
    _printKeyValueTable(
        "Environment",
        [
            ("Repo root", repoRoot),
            ("SCIPION_HOME", _resolveScipionHome(repoRoot)),
            ("Env file", envPath),
            ("PID directory", runDir),
            ("Logs directory", logsDir),
        ],
    )

    apiState, apiPid = _describePidState(apiPidPath)
    if apiState in {"STALE PID", "INVALID PID FILE"}:
        _safeUnlink(apiPidPath)

    _printServiceStatusTable(
        "API service",
        [
            ("State", apiState),
            ("PID", apiPid if apiPid is not None else "-"),
            ("Host", apiHost),
            ("Port", apiPort),
            ("PID file", apiPidPath),
            ("Log file", apiLogPath),
        ],
    )

    if not apiPidPath.exists():
        if not _canBindTcpPort(apiHost, apiPort):
            raise RuntimeError(
                f"API port {apiPort} is already in use "
                f"on host {apiHost}. "
                "Run install/provision with --api-port <port> "
                f"or update API_PORT in {envPath}."
            )

        _printInfo("Launching uvicorn")
        apiEnv = os.environ.copy()
        apiEnv["PYTHONPATH"] = str(repoRoot)
        apiEnv["PYTHONUNBUFFERED"] = "1"

        apiPid = _startDetachedProcess(
            [sys.executable, "-m", "uvicorn", "app.backend.main:app", "--host", apiHost, "--port", str(apiPort)],
            cwd=repoRoot,
            env=apiEnv,
            logPath=apiLogPath,
            sanityWaitSec=1.0,
        )
        _writePid(apiPidPath, apiPid)
        _printSuccess(f"API started (pid={apiPid})")

    docsUrl = _docsUrl(env)

    if apiPidPath.exists():
        apiTcpOk = _waitForTcp(apiHost, apiPort, timeoutSec=apiStartupTimeout)
        docsHttpOk, docsHttpDetail = _waitForHttp(docsUrl, timeoutSec=apiStartupTimeout)
    else:
        apiTcpOk = False
        docsHttpOk, docsHttpDetail = False, "API PID file not found"

    _printServiceStatusTable(
        "API checks",
        [
            ("TCP check", "OK" if apiTcpOk else "FAILED"),
            ("Docs URL", docsUrl),
            ("HTTP docs check", f"OK ({docsHttpDetail})" if docsHttpOk else f"FAILED ({docsHttpDetail})"),
        ],
    )

    workerState, workerPid = _describePidState(workerPidPath)
    if workerState in {"STALE PID", "INVALID PID FILE"}:
        _safeUnlink(workerPidPath)

    _printServiceStatusTable(
        "Plugin worker service",
        [
            ("State", workerState),
            ("PID", workerPid if workerPid is not None else "-"),
            ("Celery app", celeryApp),
            ("Log level", celeryLogLevel),
            ("Concurrency", 1),
            ("Queue", "plugins"),
            ("PID file", workerPidPath),
            ("Log file", workerLogPath),
        ],
    )

    if not workerPidPath.exists():
        _recoverInterruptedPluginTasks()

        _printInfo("Launching plugin Celery worker")
        workerEnv = os.environ.copy()
        workerEnv["PYTHONPATH"] = str(repoRoot)
        workerEnv["PYTHONUNBUFFERED"] = "1"

        workerCommand = _buildCeleryWorkerCommand(
            celeryApp=celeryApp,
            celeryLogLevel=celeryLogLevel,
            queueName="plugins",
            concurrency=1,
            hostname="plugins@%h",
        )

        workerPid = _startDetachedProcess(
            workerCommand,
            cwd=repoRoot,
            env=workerEnv,
            logPath=workerLogPath,
            sanityWaitSec=workerStartupWait,
        )
        _writePid(workerPidPath, workerPid)
        _printSuccess(f"Plugin worker started (pid={workerPid})")

    protocolWorkerState, protocolWorkerPid = _describePidState(protocolWorkerPidPath)
    if protocolWorkerState in {"STALE PID", "INVALID PID FILE"}:
        _safeUnlink(protocolWorkerPidPath)

    _printServiceStatusTable(
        "Protocol worker service",
        [
            ("State", protocolWorkerState),
            ("PID", protocolWorkerPid if protocolWorkerPid is not None else "-"),
            ("Celery app", celeryApp),
            ("Log level", celeryLogLevel),
            ("Concurrency", protocolWorkerConcurrency),
            ("Queue", "protocols"),
            ("PID file", protocolWorkerPidPath),
            ("Log file", protocolWorkerLogPath),
        ],
    )

    if not protocolWorkerPidPath.exists():
        _printInfo("Launching protocol Celery worker")
        protocolWorkerEnv = os.environ.copy()
        protocolWorkerEnv["PYTHONPATH"] = str(repoRoot)
        protocolWorkerEnv["PYTHONUNBUFFERED"] = "1"

        protocolWorkerCommand = _buildCeleryWorkerCommand(
            celeryApp=celeryApp,
            celeryLogLevel=celeryLogLevel,
            queueName="protocols",
            concurrency=protocolWorkerConcurrency,
            hostname="protocols@%h",
        )

        protocolWorkerPid = _startDetachedProcess(
            protocolWorkerCommand,
            cwd=repoRoot,
            env=protocolWorkerEnv,
            logPath=protocolWorkerLogPath,
            sanityWaitSec=workerStartupWait,
        )
        _writePid(protocolWorkerPidPath, protocolWorkerPid)
        _printSuccess(f"Protocol worker started (pid={protocolWorkerPid})")

    finalApiState, finalApiPid = _describePidState(apiPidPath)
    finalWorkerState, finalWorkerPid = _describePidState(workerPidPath)
    finalProtocolWorkerState, finalProtocolWorkerPid = _describePidState(protocolWorkerPidPath)

    summaryRows = [
        ("API", finalApiState if finalApiPid is None else f"{finalApiState} (pid={finalApiPid})"),
        ("Plugin worker", finalWorkerState if finalWorkerPid is None else f"{finalWorkerState} (pid={finalWorkerPid})"),
        ("Protocol worker", finalProtocolWorkerState if finalProtocolWorkerPid is None else f"{finalProtocolWorkerState} (pid={finalProtocolWorkerPid})"),
        ("Docs", docsUrl),
    ]

    webUrl = _webUrl(env)
    if webUrl:
        webHttpOk, webHttpDetail = _httpCheck(webUrl)
        summaryRows.append(("Web", f"{webUrl} [{'OK' if webHttpOk else 'FAILED'}: {webHttpDetail}]"))

    _printSummaryTable(summaryRows)


def stopCommand() -> None:
    # stopApiAndWorkers
    repoRoot = resolveRepoRoot()
    env = _loadEnv(repoRoot)
    runDir = _pidDir(repoRoot)
    logsDir = Path(env.get("LOGS_PATH", str(_resolveScipionHome(repoRoot) / "logs")))

    _printPanel("Stopping Scipion API services")
    _printKeyValueTable(
        "Environment",
        [
            ("Repo root", repoRoot),
            ("PID directory", runDir),
            ("Logs directory", logsDir),
        ],
    )

    apiStatus, apiPid = _stopPid(runDir / "api.pid")
    workerStatus, workerPid = _stopPid(runDir / "worker.pid")
    protocolWorkerStatus, protocolWorkerPid = _stopPid(runDir / "protocol-worker.pid")

    _printServiceStatusTable(
        "Stop results",
        [
            (
                "API",
                f"Stopped pid={apiPid}" if apiStatus == "stopped"
                else f"Removed stale pid={apiPid}" if apiStatus == "stale"
                else "Removed invalid PID file" if apiStatus == "invalid"
                else "Already stopped",
            ),
            (
                "Plugin worker",
                f"Stopped pid={workerPid}" if workerStatus == "stopped"
                else f"Removed stale pid={workerPid}" if workerStatus == "stale"
                else "Removed invalid PID file" if workerStatus == "invalid"
                else "Already stopped",
            ),
            (
                "Protocol worker",
                f"Stopped pid={protocolWorkerPid}" if protocolWorkerStatus == "stopped"
                else f"Removed stale pid={protocolWorkerPid}" if protocolWorkerStatus == "stale"
                else "Removed invalid PID file" if protocolWorkerStatus == "invalid"
                else "Already stopped",
            ),
        ],
    )

    _printSuccess("Stop completed.")


def restartCommand() -> None:
    # restartApiAndWorker
    _printPanel("Restarting Scipion API services")
    _printInfo("Stopping running processes")
    stopCommand()
    time.sleep(0.5)
    _printInfo("Starting services again")
    startCommand()
    _printSuccess("Restart completed.")


def statusCommand() -> None:
    # statusApiAndWorkers
    repoRoot = resolveRepoRoot()
    env = _loadEnv(repoRoot)
    envPath = _resolveEnvPath(repoRoot)
    runDir = _pidDir(repoRoot)

    apiPidPath = runDir / "api.pid"
    workerPidPath = runDir / "worker.pid"
    protocolWorkerPidPath = runDir / "protocol-worker.pid"

    logsDir = Path(env.get("LOGS_PATH", str(_resolveScipionHome(repoRoot) / "logs")))
    appLogPath = logsDir / "app.log"
    celeryLogPath = logsDir / "celery.log"
    protocolCeleryLogPath = logsDir / "celery-protocols.log"

    apiHost = env.get("API_HOST", "0.0.0.0")
    apiPort = env.get("API_PORT", "8080")
    celeryApp = env.get("CELERY_APP", "app.workers.task_queue")
    celeryLogLevel = env.get("CELERY_LOGLEVEL", "info")
    protocolWorkerConcurrency = max(1, _envInt(env, "PROTOCOL_WORKER_CONCURRENCY", 4))

    docsUrl = _docsUrl(env)
    webUrl = _webUrl(env)

    apiState, apiPid = _describePidState(apiPidPath)
    workerState, workerPid = _describePidState(workerPidPath)
    protocolWorkerState, protocolWorkerPid = _describePidState(protocolWorkerPidPath)

    apiUptime = _getProcessElapsedTime(apiPid) if apiPid is not None and apiState == "RUNNING" else None
    workerUptime = _getProcessElapsedTime(workerPid) if workerPid is not None and workerState == "RUNNING" else None
    protocolWorkerUptime = _getProcessElapsedTime(protocolWorkerPid) if protocolWorkerPid is not None and protocolWorkerState == "RUNNING" else None

    apiTcpOk = _tcpReachable(apiHost, apiPort)
    docsHttpOk, docsHttpDetail = _httpCheck(docsUrl)

    _printPanel("Scipion API service status")
    _printKeyValueTable(
        "Environment",
        [
            ("Repo root", repoRoot),
            ("SCIPION_HOME", _resolveScipionHome(repoRoot)),
            ("Env file", envPath),
            ("PID directory", runDir),
            ("Logs directory", logsDir),
        ],
    )

    _printServiceStatusTable(
        "API service",
        [
            ("State", apiState),
            ("PID", apiPid if apiPid is not None else "-"),
            ("Uptime", apiUptime or "-"),
            ("Host", apiHost),
            ("Port", apiPort),
            ("PID file", apiPidPath),
            ("Log file", appLogPath),
            ("TCP check", "OK" if apiTcpOk else "FAILED"),
            ("Docs URL", docsUrl),
            ("HTTP docs check", f"OK ({docsHttpDetail})" if docsHttpOk else f"FAILED ({docsHttpDetail})"),
        ],
    )

    _printServiceStatusTable(
        "Plugin worker service",
        [
            ("State", workerState),
            ("PID", workerPid if workerPid is not None else "-"),
            ("Uptime", workerUptime or "-"),
            ("Celery app", celeryApp),
            ("Log level", celeryLogLevel),
            ("Concurrency", 1),
            ("Queue", "plugins"),
            ("PID file", workerPidPath),
            ("Log file", celeryLogPath),
        ],
    )

    _printServiceStatusTable(
        "Protocol worker service",
        [
            ("State", protocolWorkerState),
            ("PID", protocolWorkerPid if protocolWorkerPid is not None else "-"),
            ("Uptime", protocolWorkerUptime or "-"),
            ("Celery app", celeryApp),
            ("Log level", celeryLogLevel),
            ("Concurrency", protocolWorkerConcurrency),
            ("Queue", "protocols"),
            ("PID file", protocolWorkerPidPath),
            ("Log file", protocolCeleryLogPath),
        ],
    )

    summaryRows = [
        ("API", apiState if apiPid is None else f"{apiState} (pid={apiPid})"),
        ("Plugin worker", workerState if workerPid is None else f"{workerState} (pid={workerPid})"),
        ("Protocol worker", protocolWorkerState if protocolWorkerPid is None else f"{protocolWorkerState} (pid={protocolWorkerPid})"),
        ("Docs", docsUrl),
    ]

    if webUrl:
        webHttpOk, webHttpDetail = _httpCheck(webUrl)
        summaryRows.append(("Web", f"{webUrl} [{'OK' if webHttpOk else 'FAILED'}: {webHttpDetail}]"))

    _printSummaryTable(summaryRows)


def logsCommand() -> None:
    # tailLogs
    repoRoot = resolveRepoRoot()
    env = _loadEnv(repoRoot)

    logsDir = Path(env.get("LOGS_PATH", str(_resolveScipionHome(repoRoot) / "logs")))
    appLog = logsDir / "app.log"
    celeryLog = logsDir / "celery.log"
    protocolCeleryLog = logsDir / "celery-protocols.log"

    _ensureLogFile(appLog)
    _ensureLogFile(celeryLog)
    _ensureLogFile(protocolCeleryLog)

    _printPanel("Following logs")
    _printKeyValueTable(
        "Log files",
        [
            ("App log", appLog),
            ("Plugin Celery log", celeryLog),
            ("Protocol Celery log", protocolCeleryLog),
        ],
    )
    console.print("Press Ctrl+C to stop.\n")

    subprocess.run(["tail", "-n", "200", "-f", str(appLog), str(celeryLog), str(protocolCeleryLog)])