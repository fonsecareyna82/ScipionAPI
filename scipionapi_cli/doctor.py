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
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
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
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from scipionapi_cli.envfile import exportEnvToOs, readEnvFile
from scipionapi_cli.shell import resolveRepoRoot, runCmd


try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _HAS_RICH = True
    _console = Console()
except Exception:
    _HAS_RICH = False
    _console = None


StatusRow = Tuple[str, str, str]


def _printPanel(title: str, body: str = "") -> None:
    # Print a panel with optional fallback.
    if _HAS_RICH:
        _console.print(Panel.fit(body or "", title=title, border_style="cyan"))
    else:
        print(f"\n== {title} ==", flush=True)
        if body:
            print(body, flush=True)


def _statusStyle(status: str) -> str:
    # Return rich style for a doctor status value.
    value = (status or "").upper()
    if value == "OK":
        return "bold green"
    if value == "WARN":
        return "bold yellow"
    if value == "FAIL":
        return "bold red"
    return "bold cyan"


def _printRows(rows: List[StatusRow]) -> None:
    # Print doctor check rows.
    if _HAS_RICH:
        table = Table(title="Doctor checks", show_header=True, header_style="bold magenta")
        table.add_column("Check", style="bold white", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Details", style="white")

        for name, status, detail in rows:
            table.add_row(name, Text(status, style=_statusStyle(status)), detail)

        _console.print(table)
        return

    print("\nDoctor checks:", flush=True)
    for name, status, detail in rows:
        print(f"  [{status}] {name}: {detail}", flush=True)


def _ok(name: str, detail: str) -> StatusRow:
    return name, "OK", detail


def _warn(name: str, detail: str) -> StatusRow:
    return name, "WARN", detail


def _fail(name: str, detail: str) -> StatusRow:
    return name, "FAIL", detail


def _pathExists(path: Path, label: str, required: bool = True) -> StatusRow:
    # Check whether a path exists.
    if path.exists():
        return _ok(label, str(path))

    if required:
        return _fail(label, f"Missing: {path}")

    return _warn(label, f"Not found: {path}")


def _commandExists(command: str) -> bool:
    # Check whether a command exists in PATH.
    for item in os.environ.get("PATH", "").split(os.pathsep):
        if not item:
            continue
        candidate = Path(item) / command
        if candidate.exists() and os.access(str(candidate), os.X_OK):
            return True
    return False


def _checkCommand(command: str, label: Optional[str] = None, required: bool = True) -> StatusRow:
    # Check command availability.
    displayName = label or command
    if _commandExists(command):
        return _ok(displayName, f"Command found: {command}")

    if required:
        return _fail(displayName, f"Command not found: {command}")

    return _warn(displayName, f"Command not found: {command}")


def _resolveScipionHome(repoRoot: Path, defaultEnv: Dict[str, str]) -> Path:
    # Resolve SCIPION_HOME like install/provision.
    configured = os.environ.get("SCIPION_HOME") or defaultEnv.get("SCIPION_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (repoRoot / "scipion_home").resolve()


def _loadDoctorEnv(repoRoot: Path) -> Tuple[Path, Path, Dict[str, str]]:
    # Resolve env file and load it into os.environ.
    defaultHome = (repoRoot / "scipion_home").resolve()
    defaultEnvPath = defaultHome / ".env"
    defaultEnv = readEnvFile(defaultEnvPath)

    scipionHome = _resolveScipionHome(repoRoot, defaultEnv)
    envPath = scipionHome / ".env"

    if envPath.exists():
        exportEnvToOs(envPath)
        env = readEnvFile(envPath)
    else:
        env = {}

    return scipionHome, envPath, env


def _checkPythonVersion() -> StatusRow:
    # Check Python version used by the CLI.
    versionText = ".".join(str(part) for part in sys.version_info[:3])

    if sys.version_info[:2] == (3, 8):
        return _ok("Python", f"Python {versionText}")

    if sys.version_info[:2] > (3, 8):
        return _warn("Python", f"Python {versionText}; project target is Python 3.8")

    return _fail("Python", f"Python {versionText}; Python 3.8 is required")

def _resolveCondaExe(env: Dict[str, str]) -> str:
    # Resolve conda executable from env or PATH.
    candidates = [
        (os.environ.get("SCIPIONAPI_CONDA_EXE") or "").strip(),
        (os.environ.get("CONDA_EXE") or "").strip(),
        (env.get("CONDA_EXE") or "").strip(),
        "conda",
    ]

    for candidate in candidates:
        if not candidate:
            continue

        try:
            proc = runCmd([candidate, "--version"], capture=True, timeout=5)
        except Exception:
            continue

        if proc.returncode == 0:
            return candidate

    return ""


def _checkConda(env: Dict[str, str]) -> List[StatusRow]:
    # Check conda executable and target environment.
    rows: List[StatusRow] = []

    condaExe = _resolveCondaExe(env)
    if not condaExe:
        rows.append(_fail("Conda", "conda executable not found"))
        return rows

    rows.append(_ok("Conda", f"Executable OK: {condaExe}"))

    envName = (
        os.environ.get("SCIPIONAPI_CONDA_ENV")
        or os.environ.get("SCIPIONAPI_ENV_NAME")
        or "scipion4Web"
    )

    proc = runCmd([condaExe, "env", "list"], capture=True, timeout=10)
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")

    if proc.returncode != 0:
        rows.append(_warn("Conda env list", output.strip() or "Failed to list conda envs"))
        return rows

    found = False
    for line in output.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        if parts[0] == envName:
            found = True
            break

    if found:
        rows.append(_ok("Conda env", f"Found target env: {envName}"))
    else:
        rows.append(_warn("Conda env", f"Target env not found in conda list: {envName}"))

    activeEnv = os.environ.get("CONDA_DEFAULT_ENV") or ""
    if activeEnv:
        if activeEnv == envName:
            rows.append(_ok("Active conda env", activeEnv))
        else:
            rows.append(_warn("Active conda env", f"{activeEnv}; expected {envName}"))
    else:
        rows.append(_warn("Active conda env", "CONDA_DEFAULT_ENV is not set"))

    return rows

def _checkImport(moduleName: str, label: Optional[str] = None, required: bool = True) -> StatusRow:
    # Check whether a Python module can be imported.
    displayName = label or f"Import {moduleName}"

    try:
        __import__(moduleName)
        return _ok(displayName, f"Imported {moduleName}")
    except Exception as exc:
        if required:
            return _fail(displayName, str(exc))
        return _warn(displayName, str(exc))


def _tcpReachable(host: str, port: str, timeoutSec: float = 2.0) -> bool:
    # Check TCP connectivity.
    try:
        targetHost = (host or "").strip()
        if targetHost in ("", "0.0.0.0", "::"):
            targetHost = "127.0.0.1"

        targetPort = int(str(port).strip())

        with socket.create_connection((targetHost, targetPort), timeout=timeoutSec):
            return True
    except Exception:
        return False


def _checkTcp(host: str, port: str, label: str, required: bool = False) -> StatusRow:
    # Check whether a TCP endpoint is reachable.
    if _tcpReachable(host, port):
        return _ok(label, f"Reachable at {host}:{port}")

    detail = f"Not reachable at {host}:{port}"
    if required:
        return _fail(label, detail)
    return _warn(label, detail)


def _checkRequiredEnv(env: Dict[str, str], keys: List[str]) -> List[StatusRow]:
    # Check required .env keys.
    rows: List[StatusRow] = []

    for key in keys:
        value = (env.get(key) or "").strip()
        if value:
            rows.append(_ok(f"Env {key}", "Configured"))
        else:
            rows.append(_fail(f"Env {key}", "Missing or empty"))

    return rows


def _checkOptionalEnv(env: Dict[str, str], keys: List[str]) -> List[StatusRow]:
    # Check optional .env keys.
    rows: List[StatusRow] = []

    for key in keys:
        value = (env.get(key) or "").strip()
        if value:
            rows.append(_ok(f"Env {key}", "Configured"))
        else:
            rows.append(_warn(f"Env {key}", "Not configured"))

    return rows


def _checkPostgres(env: Dict[str, str]) -> StatusRow:
    # Check database connectivity through psycopg2.
    databaseUrl = (env.get("DATABASE_URL") or "").strip()
    if not databaseUrl:
        return _fail("PostgreSQL", "DATABASE_URL is missing")

    try:
        import psycopg2
    except Exception as exc:
        return _fail("PostgreSQL", f"psycopg2 import failed: {exc}")

    try:
        conn = psycopg2.connect(databaseUrl, connect_timeout=3)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
        finally:
            conn.close()

        return _ok("PostgreSQL", "Connection OK")
    except Exception as exc:
        return _fail("PostgreSQL", str(exc))


def _checkRedis(env: Dict[str, str]) -> StatusRow:
    # Check Redis broker TCP connectivity.
    brokerUrl = (env.get("BROKER_URL") or "").strip()
    if not brokerUrl:
        return _warn("Redis", "BROKER_URL is missing")

    parsed = urlparse(brokerUrl)
    if parsed.scheme not in ("redis", "rediss"):
        return _warn("Redis", f"Unsupported broker scheme for TCP check: {parsed.scheme}")

    host = parsed.hostname or "localhost"
    port = str(parsed.port or 6379)

    if _tcpReachable(host, port):
        return _ok("Redis", f"Reachable at {host}:{port}")

    return _fail("Redis", f"Not reachable at {host}:{port}")


def _checkAlembic(repoRoot: Path) -> StatusRow:
    # Check Alembic current revision.
    try:
        proc = runCmd(
            ["alembic", "current"],
            cwd=repoRoot,
            capture=True,
            timeout=10,
        )
    except Exception as exc:
        return _fail("Alembic", str(exc))

    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()

    if proc.returncode == 0:
        return _ok("Alembic", output or "current revision available")

    return _fail("Alembic", output or "alembic current failed")


def _readPidSafe(path: Path) -> Optional[int]:
    # Read PID file safely.
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _isProcessAlive(pid: int) -> bool:
    # Check process existence.
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _checkPidFile(path: Path, label: str) -> StatusRow:
    # Check runtime PID file.
    if not path.exists():
        return _warn(label, f"PID file not found: {path}")

    pid = _readPidSafe(path)
    if pid is None:
        return _fail(label, f"Invalid PID file: {path}")

    if _isProcessAlive(pid):
        return _ok(label, f"Running with pid={pid}")

    return _warn(label, f"Stale PID file: {path} pid={pid}")


def _checkWebDist(env: Dict[str, str]) -> StatusRow:
    # Check integrated web dist when enabled.
    serveWeb = (env.get("SERVE_WEB") or "").strip() == "1"
    if not serveWeb:
        return _warn("Web dist", "SERVE_WEB is disabled")

    webDist = (env.get("WEB_DIST_PATH") or "").strip()
    if not webDist:
        return _fail("Web dist", "SERVE_WEB=1 but WEB_DIST_PATH is missing")

    path = Path(webDist).expanduser()
    if not path.exists():
        return _fail("Web dist", f"WEB_DIST_PATH does not exist: {path}")

    if not (path / "index.html").exists():
        return _fail("Web dist", f"index.html not found in {path}")

    return _ok("Web dist", str(path))


def _checkScipionConfig(scipionHome: Path) -> List[StatusRow]:
    # Check Scipion config files.
    configDir = scipionHome / "config"
    return [
        _pathExists(configDir / "scipion.conf", "scipion.conf", required=True),
        _pathExists(configDir / "hosts.conf", "hosts.conf", required=True),
    ]


def _checkFilesystem(env: Dict[str, str], scipionHome: Path) -> List[StatusRow]:
    # Check core filesystem paths.
    logsPath = Path(env.get("LOGS_PATH") or (scipionHome / "logs")).expanduser()
    projectsPath = Path(env.get("PROJECTS_PATH") or (scipionHome / "projects")).expanduser()

    return [
        _pathExists(scipionHome, "SCIPION_HOME", required=True),
        _pathExists(logsPath, "Logs directory", required=False),
        _pathExists(projectsPath, "Projects directory", required=False),
    ]


def _summary(rows: List[StatusRow]) -> Tuple[int, int, int]:
    # Count status rows.
    okCount = sum(1 for _, status, _ in rows if status == "OK")
    warnCount = sum(1 for _, status, _ in rows if status == "WARN")
    failCount = sum(1 for _, status, _ in rows if status == "FAIL")
    return okCount, warnCount, failCount


def doctorCommand(strict: bool = False, full: bool = True) -> None:
    # Run read-only environment diagnostics.
    repoRoot = resolveRepoRoot()
    scipionHome, envPath, env = _loadDoctorEnv(repoRoot)

    rows: List[StatusRow] = []

    _printPanel(
        "ScipionAPI doctor",
        "Read-only checks for repository, Python environment, configuration, database, broker, and runtime.",
    )

    rows.append(_pathExists(repoRoot / "pyproject.toml", "Repository pyproject.toml", required=True))
    rows.append(_pathExists(repoRoot / "alembic.ini", "Repository alembic.ini", required=True))
    rows.append(_pathExists(repoRoot / "app", "Repository app package", required=True))
    rows.append(_checkPythonVersion())
    rows.extend(_checkConda(env))
    envExists = envPath.exists()
    rows.append(_pathExists(envPath, ".env file", required=False))

    rows.extend(_checkFilesystem(env, scipionHome))
    rows.extend(_checkScipionConfig(scipionHome))

    if envExists:
        rows.extend(
            _checkRequiredEnv(
                env,
                [
                    "SCIPION_HOME",
                    "DATABASE_URL",
                    "DATABASE_NAME",
                    "DATABASE_USER",
                    "DATABASE_PASS",
                    "SECRET_KEY",
                    "BROKER_URL",
                    "API_HOST",
                    "API_PORT",
                ],
            )
        )
    else:
        rows.append(
            _warn(
                "Environment configuration",
                "Install has not been run yet. Run `scipionapi install` or `scipionapi provision`.",
            )
        )

    rows.extend(
        _checkOptionalEnv(
            env,
            [
                "CONDA_EXE",
                "CONDA_ACTIVATION_CMD",
                "SERVE_WEB",
                "WEB_DIST_PATH",
                "WEB_API_BASE_URL",
                "CELERY_APP",
                "CELERY_LOGLEVEL",
            ],
        )
    )

    rows.append(_checkCommand("alembic", required=True))
    rows.append(_checkCommand("psql", required=False))
    rows.append(_checkCommand("redis-server", required=False))

    rows.append(_checkImport("fastapi", "Import fastapi", required=True))
    rows.append(_checkImport("uvicorn", "Import uvicorn", required=True))
    rows.append(_checkImport("celery", "Import celery", required=True))
    rows.append(_checkImport("sqlalchemy", "Import sqlalchemy", required=True))
    rows.append(_checkImport("psycopg2", "Import psycopg2", required=True))
    rows.append(_checkImport("pyworkflow", "Import pyworkflow", required=False))

    if envExists:
        rows.append(_checkPostgres(env))
        rows.append(_checkRedis(env))
    else:
        rows.append(_warn("PostgreSQL", "Skipped because .env file is missing"))
        rows.append(_warn("Redis", "Skipped because .env file is missing"))

    apiHost = env.get("API_HOST") or "0.0.0.0"
    apiPort = env.get("API_PORT") or "8080"
    rows.append(_checkTcp(apiHost, apiPort, "API TCP", required=False))

    runDir = repoRoot / ".run"
    rows.append(_checkPidFile(runDir / "api.pid", "API PID"))
    rows.append(_checkPidFile(runDir / "worker.pid", "Worker PID"))

    if envExists:
        rows.append(_checkWebDist(env))
    else:
        rows.append(_warn("Web dist", "Skipped because .env file is missing"))

    if full:
        rows.append(_checkImport("app.backend.main", "Import app.backend.main", required=True))
        rows.append(_checkAlembic(repoRoot))

    _printRows(rows)

    okCount, warnCount, failCount = _summary(rows)
    summaryText = f"OK={okCount}  WARN={warnCount}  FAIL={failCount}"

    if failCount:
        _printPanel("Doctor completed with failures", summaryText)
    elif warnCount:
        _printPanel("Doctor completed with warnings", summaryText)
    else:
        _printPanel("Doctor completed successfully", summaryText)

    if strict and failCount:
        raise SystemExit(1)