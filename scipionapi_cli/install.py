from pathlib import Path
import os
import secrets
from shutil import which
from typing import Dict, Optional, List, Any, Tuple

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
    # buildDatabaseUrl
    return f"postgresql://{dbUser}:{dbPass}@{dbHost}:{dbPort}/{dbName}"


def _ensureEmptyFile(path: Path) -> None:
    # ensureEmptyFileExists
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


def _ensureScipionConfigFiles(configDir: Path) -> Tuple[Path, Path]:
    # ensureRequiredScipionConfigFiles
    scipionConf = configDir / "scipion.conf"
    hostsConf = configDir / "hosts.conf"

    _ensureEmptyFile(scipionConf)
    _ensureEmptyFile(hostsConf)

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


def installCommand(adminUser: str, adminEmail: str, adminPassword: str) -> None:
    # installCommandNonInteractive
    repoRoot = resolveRepoRoot()

    _printPanel("ScipionAPI install")
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

    scipionConfPath, hostsConfPath = _ensureScipionConfigFiles(configDir)

    envPath = scipionHome / ".env"
    existing = readEnvFile(envPath)

    logsDir = Path(existing.get("LOGS_PATH") or (scipionHome / "logs")).resolve()
    projectsDir = Path(existing.get("PROJECTS_PATH") or (scipionHome / "projects")).resolve()
    logsDir.mkdir(exist_ok=True, parents=True)
    projectsDir.mkdir(exist_ok=True, parents=True)

    secretKey = existing.get("SECRET_KEY") or secrets.token_urlsafe(48)

    dbName = existing.get("DATABASE_NAME") or "scipion_db"
    dbUser = existing.get("DATABASE_USER") or "scipion_user"
    dbPass = existing.get("DATABASE_PASS") or "scipion_pass"
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

    apiPort = existing.get("API_PORT") or "8080"

    scipionPort = existing.get("SCIPION_PORT")
    if not scipionPort:
        scipionPort = str(getFreePort())
    else:
        scipionPort = str(scipionPort)

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
        "SERVE_WEB": existing.get("SERVE_WEB") or "0",
        "API_MOUNT_PATH": existing.get("API_MOUNT_PATH") or "/api",
        "WEB_DIST_PATH": existing.get("WEB_DIST_PATH") or str((scipionHome / "web" / "dist").resolve()),
        "WEB_API_BASE_URL": existing.get("WEB_API_BASE_URL") or "/api",
        "ADMIN_USERNAME": adminUser,
        "ADMIN_EMAIL": adminEmail,
        "ADMIN_PASSWORD": adminPassword,
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

    _printStep("Ensuring PostgreSQL database and role")
    ensureDatabaseAndRole(env)
    _printSuccess("Database and role are ready")

    _printStep("Running Alembic migrations")
    runAlembicUpgrade(repoRoot)
    _printSuccess("Alembic upgrade completed")

    _printStep("Ensuring admin user")
    ensureAdminUser(env)
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
            ("API port", env.get("API_PORT", "8080")),
            ("SCIPION_PORT", env.get("SCIPION_PORT", scipionPort)),
            ("Admin email", adminEmail),
            ("Conda executable", condaExe or "not detected"),
            ("Next step", "scipionapi start"),
        ]
    )

    _printPanel("Install completed", "Configuration, database, migrations, and admin user are ready.")