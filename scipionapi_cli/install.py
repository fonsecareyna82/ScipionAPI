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
import re
import sys
from pathlib import Path
import os
import secrets
from shutil import which
from typing import Dict, Optional, List, Any, Tuple
from urllib.parse import quote_plus

from app.utils.scipion_helper import getFreePort
from scipionapi_cli.shell import resolveRepoRoot
from scipionapi_cli.envfile import readEnvFile, writeEnvFile, exportEnvToOs
from scipionapi_cli.db import ensureDatabaseAndRole, runAlembicUpgrade
from scipionapi_cli.admin import ensureAdminUser


try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    _HAS_RICH = True
    _console = Console()
except Exception:
    _HAS_RICH = False
    _console = None


def _resolveScipionHome(repoRoot: Path, existing: Dict[str, str]) -> Path:
    # resolveScipionHome
    configured = os.getenv("SCIPION_HOME") or existing.get("SCIPION_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (repoRoot / "scipion_home").resolve()


def _resolveCondaExe(existing: Dict[str, str]) -> Optional[Path]:
    # resolveCondaExePath
    candidates = [
        existing.get("CONDA_EXE"),
        os.getenv("CONDA_EXE"),
        which("conda"),
        str((Path.home() / "miniconda3" / "bin" / "conda").resolve()),
        str((Path.home() / "anaconda3" / "bin" / "conda").resolve()),
    ]

    for candidate in candidates:
        if not candidate:
            continue
        p = Path(candidate).expanduser()
        if p.exists():
            return p.resolve()

    return None


def _buildCondaActivationCmd(condaExe: str) -> str:
    # buildCondaActivationCmd
    return f'eval "$({condaExe} shell.bash hook)"'


def _buildDatabaseUrl(
    dbUser: str,
    dbPass: str,
    dbHost: str,
    dbPort: str,
    dbName: str,
) -> str:
    # Build a PostgreSQL URL with escaped credentials.
    safeUser = quote_plus(dbUser)
    safePass = quote_plus(dbPass)
    safeHost = dbHost.strip()
    safePort = str(dbPort).strip()
    safeName = quote_plus(dbName)

    return f"postgresql://{safeUser}:{safePass}@{safeHost}:{safePort}/{safeName}"


def _maskSecret(value: str, visible: int = 4) -> str:
    # Mask sensitive values for console output.
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= visible:
        return "*" * len(text)
    return f"{text[:visible]}{'*' * 8}"


def _normalizePort(value: Any, label: str) -> str:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        raise RuntimeError(
            f"Invalid {label}: {value}"
        )

    if port < 1 or port > 65535:
        raise RuntimeError(
            f"Invalid {label}: {port}. "
            "Expected a value between 1 and 65535."
        )

    return str(port)


def _findFreePort(
    excludedPorts: Optional[List[str]] = None,
) -> str:
    excluded = {
        str(port).strip()
        for port in (excludedPorts or [])
        if str(port).strip()
    }

    for _ in range(20):
        port = getFreePort()

        if not port:
            continue

        portValue = str(port)

        if portValue not in excluded:
            return portValue

    raise RuntimeError(
        "Could not find a free TCP port."
    )


def _resolveApiPort(
    existing: Dict[str, str],
    requestedApiPort: Optional[int] = None,
) -> str:
    if requestedApiPort is not None:
        return _normalizePort(
            requestedApiPort,
            "API port",
        )

    existingApiPort = existing.get("API_PORT")

    if existingApiPort:
        return _normalizePort(
            existingApiPort,
            "API_PORT",
        )

    return _findFreePort()


def _writeFileIfMissingOrEmpty(path: Path, content: str) -> Path:
    # writeFileIfMissingOrEmpty
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            if path.read_text(encoding="utf-8").strip():
                return path
        except Exception:
            pass

    path.write_text(content, encoding="utf-8")
    return path


_scipionJavaHomePattern = re.compile(
    r"(?mi)^\s*SCIPION_JAVA_HOME\s*=\s*(.*?)\s*$"
)


def _isValidJavaHome(value: str) -> bool:
    # isValidJavaHome
    if not value:
        return False

    expanded = os.path.expandvars(
        os.path.expanduser(value.strip())
    )

    javaBin = Path(expanded) / "bin" / "java"
    return javaBin.is_file() and os.access(javaBin, os.X_OK)


def _resolveManagedJavaHome() -> Optional[Path]:
    # resolveManagedJavaHome
    javaHome = Path(sys.prefix).resolve()
    javaBin = javaHome / "bin" / "java"

    if javaBin.is_file() and os.access(javaBin, os.X_OK):
        return javaHome

    return None


def _ensureScipionJavaHome(
    scipionConfPath: Path,
    javaHome: Path,
) -> bool:
    # ensureScipionJavaHome
    text = scipionConfPath.read_text(encoding="utf-8")
    match = _scipionJavaHomePattern.search(text)

    if match and _isValidJavaHome(match.group(1)):
        return False

    javaLine = f"SCIPION_JAVA_HOME = {javaHome}"

    if match:
        updated = (
            text[:match.start()]
            + javaLine
            + text[match.end():]
        )
    else:
        sectionMatch = re.search(
            r"(?mi)^\s*\[PYWORKFLOW\]\s*$",
            text,
        )

        if sectionMatch:
            updated = (
                text[:sectionMatch.end()]
                + "\n"
                + javaLine
                + text[sectionMatch.end():]
            )
        else:
            separator = "" if text.endswith("\n") else "\n"
            updated = (
                text
                + separator
                + "[PYWORKFLOW]\n"
                + javaLine
                + "\n"
            )

    scipionConfPath.write_text(updated, encoding="utf-8")
    return True


def _writeDefaultScipionConf(configDir: Path, condaActivationCmd: str) -> Path:
    # writeDefaultScipionConf
    content = (
        "# Generated by ScipionAPI installer\n"
        "[PYWORKFLOW]\n"
        "SCIPION_DOMAIN = pwem\n"
        f"CONDA_ACTIVATION_CMD = {condaActivationCmd}\n"
    )
    _printStep("Ensuring Scipion config files")
    return _writeFileIfMissingOrEmpty(configDir / "scipion.conf", content)


def _writeDefaultHostsConf(configDir: Path) -> Path:
    # writeDefaultHostsConf
    content = """; This is a comment line
[localhost]
PARALLEL_COMMAND = mpirun -np %_(JOB_NODES)d %_(COMMAND)s
NAME = PBS/TORQUE
MANDATORY = False
SUBMIT_COMMAND = qsub %_(JOB_SCRIPT)s
SUBMIT_TEMPLATE = #!/bin/bash
    ### Inherit all current environment variables
    #PBS -V
    ### Job name
    #PBS -N %_(JOB_NAME)s
    ### Queue name
    ###PBS -q %_(JOB_QUEUE)s
    ### Standard output and standard error messages
    #PBS -k eo
    ### Specify the number of nodes and thread (ppn) for your job.
    #PBS -l nodes=%_(JOB_NODES)d:ppn=%_(JOB_THREADS)d
    ### Tell PBS the anticipated run-time for your job, where walltime=HH:MM:SS
    #PBS -l walltime=%_(JOB_HOURS)d:00:00
    # Use as working dir the path where qsub was launched
    WORKDIR=$PBS_O_WORKDIR
    #################################
    ### Set environment variable to know running mode is non interactive
    export XMIPP_IN_QUEUE=1
    ### Switch to the working directory;
    cd $WORKDIR
    # Make a copy of PBS_NODEFILE
    cp $PBS_NODEFILE %_(JOB_NODEFILE)s
    # Calculate the number of processors allocated to this run.
    NPROCS=`wc -l < $PBS_NODEFILE`
    # Calculate the number of nodes allocated.
    NNODES=`uniq $PBS_NODEFILE | wc -l`
    ### Display the job context
    echo Running on host `hostname`
    echo Time is `date`
    echo Working directory is `pwd`
    echo Using ${NPROCS} processors across ${NNODES} nodes
    echo PBS_NODEFILE:
    cat $PBS_NODEFILE
    #################################
    %_(JOB_COMMAND)s
CANCEL_COMMAND = canceljob %_(JOB_ID)s
CHECK_COMMAND = qstat %_(JOB_ID)s
; Next variable is used to provide a regex to check if a job is finished on a queue system
JOB_DONE_REGEX = ""
QUEUES = { "default": {} }
"""
    return _writeFileIfMissingOrEmpty(configDir / "hosts.conf", content)


def _ensureScipionConfigFiles(
    configDir: Path,
    condaActivationCmd: str,
) -> Tuple[Path, Path]:
    # ensureRequiredScipionConfigFiles
    scipionConf = _writeDefaultScipionConf(configDir, condaActivationCmd)
    hostsConf = _writeDefaultHostsConf(configDir)
    return scipionConf, hostsConf


def _printLine(message: str = "") -> None:
    # printLine
    if _HAS_RICH:
        _console.print(message)
    else:
        print(message, flush=True)


def _printPanel(title: str, body: str = "") -> None:
    # printPanel
    if _HAS_RICH:
        _console.print(Panel.fit(body or "", title=title, border_style="cyan"))
    else:
        print(f"\n== {title} ==", flush=True)
        if body:
            print(body, flush=True)


def _printInfo(message: str) -> None:
    # printInfo
    if _HAS_RICH:
        _console.print(f"[bold cyan]INFO[/bold cyan] {message}")
    else:
        print(f"INFO {message}", flush=True)


def _printSuccess(message: str) -> None:
    # printSuccess
    if _HAS_RICH:
        _console.print(f"[bold green]SUCCESS[/bold green] {message}")
    else:
        print(f"SUCCESS {message}", flush=True)


def _printWarning(message: str) -> None:
    # printWarning
    if _HAS_RICH:
        _console.print(f"[bold yellow]WARNING[/bold yellow] {message}")
    else:
        print(f"WARNING {message}", flush=True)


def _printStep(step: str, detail: str = "") -> None:
    # printStep
    if _HAS_RICH:
        if detail:
            _console.print(f"[bold magenta]--> {step}[/bold magenta] [dim]{detail}[/dim]")
        else:
            _console.print(f"[bold magenta]--> {step}[/bold magenta]")
    else:
        if detail:
            print(f"\n--> {step} | {detail}", flush=True)
        else:
            print(f"\n--> {step}", flush=True)


def _printKeyValueTable(title: str, rows: List[Tuple[str, Any]]) -> None:
    # printKeyValueTable
    if _HAS_RICH:
        table = Table(title=title, header_style="bold magenta")
        table.add_column("Field", style="bold white", no_wrap=True)
        table.add_column("Value", style="white")

        for key, value in rows:
            table.add_row(str(key), str(value))

        _console.print(table)
    else:
        print(f"\n{title}:", flush=True)
        for key, value in rows:
            print(f"  {key}: {value}", flush=True)


def _printSummaryTable(rows: List[Tuple[str, Any]]) -> None:
    # printSummaryTable
    if _HAS_RICH:
        table = Table(title="Install summary", header_style="bold magenta")
        table.add_column("Field", style="bold white", no_wrap=True)
        table.add_column("Value", style="white")

        for key, value in rows:
            table.add_row(str(key), str(value))

        _console.print(table)
    else:
        print("\nInstall summary:", flush=True)
        for key, value in rows:
            print(f"  {key}: {value}", flush=True)


def installCommand(
    adminUser: str,
    adminEmail: str,
    adminPassword: str,
    apiPort: Optional[int] = None,
) -> None:
    # installCommandNonInteractive
    repoRoot = resolveRepoRoot()

    _printPanel(
        "ScipionAPI install",
        "This command configures ScipionAPI, the database, migrations, and the admin user.\n"
        "Python package installation happens in: scipionapi bootstrap",
    )
    _printStep("Resolving repository root")
    _printInfo(f"Repo root: {repoRoot}")

    # readExistingEnvFromDefaultHomeIfPresent
    defaultScipionHome = (repoRoot / "scipion_home").resolve()
    defaultEnvPath = defaultScipionHome / ".env"
    existing = readEnvFile(defaultEnvPath)

    _printStep("Resolving SCIPION_HOME")
    scipionHome = _resolveScipionHome(repoRoot, existing)
    scipionHome.mkdir(parents=True, exist_ok=True)
    _printInfo(f"SCIPION_HOME: {scipionHome}")

    _printStep("Ensuring base directories")
    configDir = scipionHome / "config"
    webDir = scipionHome / "web"
    configDir.mkdir(parents=True, exist_ok=True)
    webDir.mkdir(parents=True, exist_ok=True)

    envPath = scipionHome / ".env"
    existing = readEnvFile(envPath)

    logsDir = Path(existing.get("LOGS_PATH") or (scipionHome / "logs")).resolve()
    projectsDir = Path(existing.get("PROJECTS_PATH") or (scipionHome / "projects")).resolve()
    logsDir.mkdir(exist_ok=True, parents=True)
    projectsDir.mkdir(exist_ok=True, parents=True)

    secretKey = existing.get("SECRET_KEY") or secrets.token_urlsafe(48)

    installId = existing.get("SCIPION_INSTALL_ID") or secrets.token_hex(4)
    dbName = existing.get("DATABASE_NAME") or f"scipion_db_{installId}"
    dbUser = existing.get("DATABASE_USER") or f"scipion_user_{installId}"
    dbPass = existing.get("DATABASE_PASS") or secrets.token_urlsafe(32)
    dbHost = existing.get("POSTGRES_HOST") or "localhost"
    dbPort = existing.get("POSTGRES_PORT") or "5432"
    databaseUrl = _buildDatabaseUrl(
        dbUser=dbUser,
        dbPass=dbPass,
        dbHost=dbHost,
        dbPort=dbPort,
        dbName=dbName,
    )

    condaExePath = _resolveCondaExe(existing)
    condaExe = str(condaExePath) if condaExePath else ""
    condaActivationCmd = existing.get("CONDA_ACTIVATION_CMD")
    if not condaActivationCmd and condaExe:
        condaActivationCmd = _buildCondaActivationCmd(condaExe)

    scipionConfPath, hostsConfPath = _ensureScipionConfigFiles(
        configDir=configDir,
        condaActivationCmd=condaActivationCmd or "",
    )
    _printSuccess(f"Scipion config ready: {scipionConfPath}")
    _printSuccess(f"Hosts config ready: {hostsConfPath}")

    javaHome = _resolveManagedJavaHome()

    if javaHome:
        changed = _ensureScipionJavaHome(
            scipionConfPath,
            javaHome,
        )

        if changed:
            _printSuccess(
                f"SCIPION_JAVA_HOME configured: {javaHome}"
            )
        else:
            _printInfo(
                "Existing valid SCIPION_JAVA_HOME preserved"
            )
    else:
        _printWarning(
            "Java runtime was not found in the current conda environment. "
            "Run `scipionapi bootstrap` first."
        )

    apiPort = _resolveApiPort(
        existing,
        requestedApiPort=apiPort,
    )

    scipionPort = existing.get("SCIPION_PORT")

    if not scipionPort:
        scipionPort = _findFreePort(
            excludedPorts=[apiPort],
        )
    else:
        scipionPort = _normalizePort(
            scipionPort,
            "SCIPION_PORT",
        )

    _printKeyValueTable(
        "Resolved paths and settings",
        [
            ("SCIPION_HOME", scipionHome),
            ("Env file", envPath),
            ("Config dir", configDir),
            ("Web dir", webDir),
            ("Logs dir", logsDir),
            ("Projects dir", projectsDir),
            ("scipion.conf", scipionConfPath),
            ("hosts.conf", hostsConfPath),
            ("Database name", dbName),
            ("Database user", dbUser),
            ("Database password", _maskSecret(dbPass)),
            ("Postgres host", dbHost),
            ("Postgres port", dbPort),
            ("API host", existing.get("API_HOST") or "0.0.0.0"),
            ("API port", apiPort),
            ("SCIPION_PORT", scipionPort),
            ("Conda executable", condaExe or "not detected"),
        ],
    )

    updates: Dict[str, str] = {
        "SCIPION_HOME": str(scipionHome),
        "SCIPION_INSTALL_ID": installId,
        "DATABASE_URL": databaseUrl,
        "DATABASE_NAME": dbName,
        "DATABASE_USER": dbUser,
        "DATABASE_PASS": dbPass,
        "POSTGRES_HOST": dbHost,
        "POSTGRES_PORT": dbPort,
        "SECRET_KEY": secretKey,
        "BROKER_URL": existing.get("BROKER_URL") or "redis://localhost:6379/0",
        "LOGS_PATH": str(logsDir),
        "PROJECTS_PATH": str(projectsDir),
        "API_HOST": existing.get("API_HOST") or "0.0.0.0",
        "API_PORT": apiPort,
        "CELERY_APP": existing.get("CELERY_APP") or "app.workers.task_queue",
        "CELERY_LOGLEVEL": existing.get("CELERY_LOGLEVEL") or "info",
        "PROTOCOL_WORKER_CONCURRENCY": existing.get("PROTOCOL_WORKER_CONCURRENCY") or "4",
        "SERVE_WEB": existing.get("SERVE_WEB") or "0",
        "API_MOUNT_PATH": existing.get("API_MOUNT_PATH") or "/api",
        "WEB_DIST_PATH": existing.get("WEB_DIST_PATH") or str((scipionHome / "web" / "dist").resolve()),
        "WEB_API_BASE_URL": existing.get("WEB_API_BASE_URL") or "/api",
        "ADMIN_USERNAME": adminUser,
        "ADMIN_EMAIL": adminEmail,
        "SCIPION_PORT": scipionPort,
        "AUTO_RELOAD_ON_PLUGIN_CHANGE": "1",
        "BACKEND_RELOAD_MODE": "prod",
        "BACKEND_RELOAD_TOUCH_PATH": ".backend_reload_marker",
    }

    if condaExe and not existing.get("CONDA_EXE"):
        # persistCondaExeIfDetected
        updates["CONDA_EXE"] = condaExe

    if condaActivationCmd and not existing.get("CONDA_ACTIVATION_CMD"):
        # persistCondaActivationCmdIfDetected
        updates["CONDA_ACTIVATION_CMD"] = condaActivationCmd

    _printStep("Writing environment file", str(envPath))
    writeEnvFile(envPath, updates)
    exportEnvToOs(envPath)
    _printSuccess("Environment file written and exported")

    env: Dict[str, str] = readEnvFile(envPath)

    _printInfo("Install will now configure PostgreSQL, run Alembic, and ensure the admin user.")
    _printStep("Ensuring PostgreSQL database and role")
    ensureDatabaseAndRole(env)
    if env.get("SCIPIONAPI_MANAGED_DATABASE") != "1":
        writeEnvFile(envPath, {"SCIPIONAPI_MANAGED_DATABASE": "1"})
        exportEnvToOs(envPath)
        env["SCIPIONAPI_MANAGED_DATABASE"] = "1"

    _printSuccess("Database and role are ready")

    _printStep("Running Alembic migrations")
    runAlembicUpgrade(repoRoot)
    _printSuccess("Alembic upgrade completed")

    _printStep("Ensuring admin user")
    ensureAdminUser(env, adminPassword=adminPassword)
    _printSuccess(f"Admin user ensured: {adminEmail}")

    if not condaExePath:
        _printWarning("Conda executable not detected; CONDA_ACTIVATION_CMD was not set")

    _printSummaryTable(
        [
            ("Repo root", repoRoot),
            ("SCIPION_HOME", scipionHome),
            ("Env file", envPath),
            ("Logs dir", logsDir),
            ("Projects dir", projectsDir),
            ("scipion.conf", scipionConfPath),
            ("hosts.conf", hostsConfPath),
            ("Database", dbName),
            ("Database user", dbUser),
            ("API host", env.get("API_HOST", "0.0.0.0")),
            ("API port", env.get("API_PORT", apiPort)),
            ("SCIPION_PORT", env.get("SCIPION_PORT", scipionPort)),
            ("Admin email", adminEmail),
            ("Conda executable", condaExe or "not detected"),
            ("Next step", "scipionapi start"),
        ]
    )

    _printPanel("Install completed", "Configuration, database, migrations, and admin user are ready.")