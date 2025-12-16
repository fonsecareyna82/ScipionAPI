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
import argparse
import os
import secrets
import subprocess
from pathlib import Path


ENV_NAME = "scipion4Web"


def runCmd(args, cwd=None, env=None, allowFail=False):
    # RunCommandHelper
    mergedEnv = os.environ.copy()
    if env:
        mergedEnv.update(env)

    proc = subprocess.run(args, cwd=cwd, env=mergedEnv, text=True)
    if proc.returncode != 0 and not allowFail:
        raise RuntimeError(f"Command failed: {' '.join(args)}")


def ensureCmdExists(cmdName: str):
    # EnsureRequiredCommand
    proc = subprocess.run(["bash", "-lc", f"command -v {cmdName} >/dev/null 2>&1"])
    if proc.returncode != 0:
        raise RuntimeError(f"Missing required command: {cmdName}")


def ensureCondaEnv():
    # EnsureCondaEnvExists
    proc = subprocess.run(["bash", "-lc", f"conda env list | awk '{{print $1}}' | grep -x {ENV_NAME}"], text=True)
    if proc.returncode != 0:
        runCmd(["conda", "create", "-y", "-n", ENV_NAME, "python=3.8"])
    # else: env already exists


def installRequirements(repoRoot: Path):
    # InstallPythonDependencies
    runCmd(["conda", "run", "-n", ENV_NAME, "python", "-m", "pip", "install", "--upgrade", "pip"])
    runCmd(["conda", "run", "-n", ENV_NAME, "pip", "install", "-r", str(repoRoot / "requirements.txt")])


def readEnvFile(envPath: Path) -> dict:
    # ReadDotEnvFile
    data = {}
    if not envPath.exists():
        return data
    for line in envPath.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        data[k.strip()] = v.strip()
    return data


def writeEnvFile(envPath: Path, updates: dict):
    # WriteDotEnvFilePreservingExisting
    current = readEnvFile(envPath)
    current.update({k: v for k, v in updates.items() if v is not None})

    lines = []
    for k in sorted(current.keys()):
        lines.append(f"{k}={current[k]}")
    lines.append("")
    envPath.write_text("\n".join(lines), encoding="utf-8")


def ensureEnv(repoRoot: Path, adminUser: str, adminEmail: str, adminPassword: str):
    # EnsureEnvFile
    envPath = repoRoot / ".env"
    existing = readEnvFile(envPath)

    secretKey = existing.get("SECRET_KEY") or secrets.token_urlsafe(48)

    dbName = existing.get("DATABASE_NAME") or "scipion_db"
    dbUser = existing.get("DATABASE_USER") or "scipion_user"
    dbPass = existing.get("DATABASE_PASS") or "scipion_pass"
    dbHost = existing.get("POSTGRES_HOST") or "localhost"
    dbPort = existing.get("POSTGRES_PORT") or "5432"

    databaseUrl = existing.get("DATABASE_URL") or f"postgresql://{dbUser}:{dbPass}@{dbHost}:{dbPort}/{dbName}"

    updates = {
        "DATABASE_URL": databaseUrl,
        "DATABASE_NAME": dbName,
        "DATABASE_USER": dbUser,
        "DATABASE_PASS": dbPass,
        "SECRET_KEY": secretKey,
        "BROKER_URL": existing.get("BROKER_URL") or "redis://localhost:6379/0",
        "LOGS_PATH": existing.get("LOGS_PATH") or str(repoRoot / "logs"),
        "PROJECTS_PATH": existing.get("PROJECTS_PATH") or str(repoRoot / "projects"),
        "ADMIN_USERNAME": adminUser,
        "ADMIN_EMAIL": adminEmail,
        "ADMIN_PASSWORD": adminPassword,
        "POSTGRES_HOST": dbHost,
        "POSTGRES_PORT": dbPort,
    }

    writeEnvFile(envPath, updates)


def ensureDatabaseAndUser(repoRoot: Path):
    # EnsurePostgresDbAndUser
    envPath = repoRoot / ".env"
    env = readEnvFile(envPath)

    dbName = env["DATABASE_NAME"]
    dbUser = env["DATABASE_USER"]
    dbPass = env["DATABASE_PASS"]
    dbHost = env.get("POSTGRES_HOST", "localhost")
    dbPort = env.get("POSTGRES_PORT", "5432")

    base = ["psql", "-h", dbHost, "-p", dbPort, "-U", "postgres", "-v", "ON_ERROR_STOP=1"]

    runCmd(base + ["-c", f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{dbUser}') THEN CREATE ROLE {dbUser} LOGIN PASSWORD '{dbPass}'; END IF; END $$;"])
    runCmd(base + ["-c", f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_database WHERE datname='{dbName}') THEN CREATE DATABASE {dbName} OWNER {dbUser}; END IF; END $$;"])
    runCmd(base + ["-c", f"GRANT ALL PRIVILEGES ON DATABASE {dbName} TO {dbUser};"])


def runMigrations(repoRoot: Path):
    # RunAlembicMigrations
    runCmd(["conda", "run", "-n", ENV_NAME, "alembic", "upgrade", "head"], cwd=str(repoRoot))


def ensureAdmin(repoRoot: Path):
    # EnsureAdminUser
    runCmd(["conda", "run", "-n", ENV_NAME, "python", "app/backend/scripts/create_admin.py"], cwd=str(repoRoot))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--pass", dest="password", required=True)
    args = parser.parse_args()

    repoRoot = Path(__file__).resolve().parents[1]

    ensureCmdExists("conda")
    ensureCmdExists("psql")

    (repoRoot / "logs").mkdir(exist_ok=True)
    (repoRoot / "projects").mkdir(exist_ok=True)

    ensureCondaEnv()
    installRequirements(repoRoot)
    ensureEnv(repoRoot, adminUser=args.user, adminEmail=args.email, adminPassword=args.password)
    ensureDatabaseAndUser(repoRoot)
    runMigrations(repoRoot)
    ensureAdmin(repoRoot)

    print("Install completed. Next: scipionapi start")


if __name__ == "__main__":
    main()
