from pathlib import Path
import os
import secrets
from shutil import which
from typing import Dict, Optional

from app.utils.scipion_helper import getFreePort
from scipionapi_cli.shell import resolveRepoRoot
from scipionapi_cli.envfile import readEnvFile, writeEnvFile, exportEnvToOs
from scipionapi_cli.db import ensureDatabaseAndRole, runAlembicUpgrade
from scipionapi_cli.admin import ensureAdminUser


def _resolveScipionHome(repoRoot: Path, existing: Dict[str, str]) -> Path:
    # resolveScipionHome
    configured = existing.get("SCIPION_HOME") or os.getenv("SCIPION_HOME")
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


def installCommand(adminUser: str, adminEmail: str, adminPassword: str) -> None:
    # installCommandNonInteractive
    repoRoot = resolveRepoRoot()

    # readExistingEnvFromDefaultHomeIfPresent
    defaultScipionHome = (repoRoot / "scipion_home").resolve()
    defaultEnvPath = defaultScipionHome / ".env"
    existing = readEnvFile(defaultEnvPath)

    scipionHome = _resolveScipionHome(repoRoot, existing)
    scipionHome.mkdir(parents=True, exist_ok=True)

    (scipionHome / "config").mkdir(parents=True, exist_ok=True)
    (scipionHome / "web").mkdir(parents=True, exist_ok=True)

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
    databaseUrl = existing.get("DATABASE_URL") or f"postgresql://{dbUser}:{dbPass}@{dbHost}:{dbPort}/{dbName}"

    condaExePath = _resolveCondaExe(existing)
    condaExe = str(condaExePath) if condaExePath else ""
    condaActivationCmd = existing.get("CONDA_ACTIVATION_CMD")
    if not condaActivationCmd and condaExe:
        condaActivationCmd = _buildCondaActivationCmd(condaExe)
    scipionPort = existing.get("SCIPION_PORT")
    if not scipionPort:
        scipionPort = getFreePort()

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
        "API_PORT": existing.get("API_PORT") or "8080",
        "CELERY_APP": existing.get("CELERY_APP") or "app.workers.task_queue",
        "CELERY_LOGLEVEL": existing.get("CELERY_LOGLEVEL") or "info",
        "SERVE_WEB": existing.get("SERVE_WEB") or "0",
        "API_MOUNT_PATH": existing.get("API_MOUNT_PATH") or "/api",
        "WEB_DIST_PATH": existing.get("WEB_DIST_PATH") or str((scipionHome / "web" / "dist").resolve()),
        "WEB_API_BASE_URL": existing.get("WEB_API_BASE_URL") or "/api",
        "ADMIN_USERNAME": adminUser,
        "ADMIN_EMAIL": adminEmail,
        "ADMIN_PASSWORD": adminPassword,
    }

    if condaExe and not existing.get("CONDA_EXE"):
        # persistCondaExeIfDetected
        updates["CONDA_EXE"] = condaExe

    if condaActivationCmd and not existing.get("CONDA_ACTIVATION_CMD"):
        # persistCondaActivationCmdIfDetected
        updates["CONDA_ACTIVATION_CMD"] = condaActivationCmd

    if scipionPort and not existing.get('SCIPION_PORT'):
        updates['SCIPION_PORT'] = scipionPort

    updates['AUTO_RELOAD_ON_PLUGIN_CHANGE'] = '1'
    updates['BACKEND_RELOAD_MODE'] = 'prod'
    updates['BACKEND_RELOAD_TOUCH_PATH'] ='.backend_reload_marker'

    writeEnvFile(envPath, updates)
    exportEnvToOs(envPath)

    env: Dict[str, str] = readEnvFile(envPath)

    ensureDatabaseAndRole(env)
    runAlembicUpgrade(repoRoot)
    ensureAdminUser(env)

    if not condaExePath:
        print("Install completed. Note: conda executable not detected; CONDA_ACTIVATION_CMD was not set.")
    else:
        print("Install completed. Next: scipionapi start")
