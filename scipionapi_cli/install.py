from pathlib import Path
import os
import secrets
from typing import Dict

from scipionapi_cli.shell import resolveRepoRoot
from scipionapi_cli.envfile import readEnvFile, writeEnvFile, exportEnvToOs
from scipionapi_cli.db import ensureDatabaseAndRole, runAlembicUpgrade


def _resolveScipionHome(repoRoot: Path, existing: Dict[str, str]) -> Path:
    # resolveScipionHome
    configured = existing.get("SCIPION_HOME") or os.getenv("SCIPION_HOME")
    if configured:
        return Path(configured).expanduser().resolve()

    return (repoRoot / "scipion_home").resolve()


def installCommand(adminUser: str, adminEmail: str, adminPassword: str) -> None:
    # installCommandNonInteractive
    repoRoot = resolveRepoRoot()

    # readExistingEnvFromRepoScipionHomeIfPresent
    defaultScipionHome = (repoRoot / "scipion_home").resolve()
    defaultEnvPath = defaultScipionHome / ".env"
    existing = readEnvFile(defaultEnvPath)

    scipionHome = _resolveScipionHome(repoRoot, existing)
    scipionHome.mkdir(parents=True, exist_ok=True)

    # ensureConfigDirExists
    (scipionHome / "config").mkdir(parents=True, exist_ok=True)

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
        "ADMIN_USERNAME": adminUser,
        "ADMIN_EMAIL": adminEmail,
        "ADMIN_PASSWORD": adminPassword,
    }

    writeEnvFile(envPath, updates)
    exportEnvToOs(envPath)

    env: Dict[str, str] = readEnvFile(envPath)

    ensureDatabaseAndRole(env)
    runAlembicUpgrade(repoRoot)
    from scipionapi_cli.admin import ensureAdminUser
    ensureAdminUser(env)

    print("Install completed. Next: scipionapi start")
