import os
import re
from pathlib import Path
from shutil import which
from typing import Dict, Optional, Tuple

from scipionapi_cli.shell import runCmd


def _printInfo(message: str) -> None:
    # printDbInfo
    print(f"[db] {message}", flush=True)


def _validateIdentifier(identifier: str, label: str) -> None:
    # validateSqlIdentifier
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", identifier or ""):
        raise ValueError(f"Invalid {label} '{identifier}'. Use only letters, numbers and underscore.")


def _escapeSqlLiteral(value: str) -> str:
    # escapeSingleQuotesForSqlLiteral
    return (value or "").replace("'", "''")


def _resolveLocalHost(value: str) -> bool:
    # isLocalPostgresHost
    host = (value or "").strip()
    return host in ("", "localhost", "127.0.0.1", "::1")


def _hasCommand(command: str) -> bool:
    # commandExists
    return which(command) is not None


def _resolveAdminConnection(env: Dict[str, str]) -> Tuple[list, Dict[str, str]]:
    # resolvePostgresAdminConnection
    postgresHost = (env.get("POSTGRES_HOST") or "localhost").strip()
    postgresPort = (env.get("POSTGRES_PORT") or "5432").strip()

    adminUser = (
        env.get("DATABASE_ADMIN_USER")
        or env.get("POSTGRES_ADMIN_USER")
        or ""
    ).strip()
    adminPass = (
        env.get("DATABASE_ADMIN_PASS")
        or env.get("POSTGRES_ADMIN_PASS")
        or ""
    )
    adminDb = (
        env.get("DATABASE_ADMIN_DB")
        or env.get("POSTGRES_ADMIN_DB")
        or "postgres"
    ).strip()

    commandEnv = os.environ.copy()

    if adminUser:
        args = [
            "psql",
            "-h",
            postgresHost or "localhost",
            "-p",
            postgresPort,
            "-U",
            adminUser,
            "-d",
            adminDb,
            "-v",
            "ON_ERROR_STOP=1",
        ]

        if adminPass:
            commandEnv["PGPASSWORD"] = adminPass

        return args, commandEnv

    if not _resolveLocalHost(postgresHost):
        raise RuntimeError(
            "POSTGRES_HOST is not local and no PostgreSQL admin credentials were provided.\n"
            "Set DATABASE_ADMIN_USER and DATABASE_ADMIN_PASS, or pre-create the database/user."
        )

    if not _hasCommand("sudo"):
        raise RuntimeError(
            "sudo is required for local PostgreSQL bootstrap when DATABASE_ADMIN_USER is not set.\n"
            "Either install sudo, run with a configured admin user, or pre-create the database/user."
        )

    sudoArgs = ["sudo", "-u", "postgres"]
    if os.environ.get("SCIPIONAPI_SUDO_NONINTERACTIVE", "").strip() == "1":
        # doNotPromptForSudoPassword
        sudoArgs = ["sudo", "-n", "-u", "postgres"]

    return sudoArgs + ["psql", "-v", "ON_ERROR_STOP=1"], commandEnv


def _runPsqlScalar(psqlBase: list, commandEnv: Dict[str, str], sql: str) -> str:
    # psqlScalar
    proc = runCmd(psqlBase + ["-tA", "-c", sql], env=commandEnv, capture=True)
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed.\nSQL: {sql}\n{proc.stderr}")
    return (proc.stdout or "").strip()


def _runPsqlExec(psqlBase: list, commandEnv: Dict[str, str], sql: str) -> None:
    # psqlExec
    proc = runCmd(psqlBase + ["-c", sql], env=commandEnv, capture=True)
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed.\nSQL: {sql}\n{proc.stdout}\n{proc.stderr}")


def ensureDatabaseAndRole(env: Dict[str, str]) -> None:
    # ensureDatabaseAndRoleIdempotent
    skipBootstrap = (
        env.get("DATABASE_SKIP_BOOTSTRAP")
        or env.get("SKIP_DB_BOOTSTRAP")
        or ""
    ).strip() == "1"

    if skipBootstrap:
        _printInfo("Skipping PostgreSQL bootstrap because DATABASE_SKIP_BOOTSTRAP=1")
        return

    dbName = (env.get("DATABASE_NAME") or "").strip()
    dbUser = (env.get("DATABASE_USER") or "").strip()
    dbPass = env.get("DATABASE_PASS") or ""

    _validateIdentifier(dbName, "database name")
    _validateIdentifier(dbUser, "database user")

    safeDbName = _escapeSqlLiteral(dbName)
    safeDbUser = _escapeSqlLiteral(dbUser)
    safeDbPass = _escapeSqlLiteral(dbPass)

    psqlBase, commandEnv = _resolveAdminConnection(env)

    _printInfo(f"Checking PostgreSQL role '{dbUser}'")
    roleExists = _runPsqlScalar(
        psqlBase,
        commandEnv,
        f"SELECT 1 FROM pg_roles WHERE rolname='{safeDbUser}'",
    )

    if roleExists != "1":
        _printInfo(f"Creating PostgreSQL role '{dbUser}'")
        _runPsqlExec(
            psqlBase,
            commandEnv,
            f"CREATE ROLE {dbUser} LOGIN PASSWORD '{safeDbPass}';",
        )
    else:
        _printInfo(f"Role '{dbUser}' already exists")
        _printInfo(f"Ensuring PostgreSQL role '{dbUser}' has the configured password")
        _runPsqlExec(
            psqlBase,
            commandEnv,
            f"ALTER ROLE {dbUser} WITH LOGIN PASSWORD '{safeDbPass}';",
        )

    _printInfo(f"Checking PostgreSQL database '{dbName}'")
    dbExists = _runPsqlScalar(
        psqlBase,
        commandEnv,
        f"SELECT 1 FROM pg_database WHERE datname='{safeDbName}'",
    )

    if dbExists != "1":
        _printInfo(f"Creating PostgreSQL database '{dbName}'")
        _runPsqlExec(psqlBase, commandEnv, f"CREATE DATABASE {dbName} OWNER {dbUser};")
    else:
        _printInfo(f"Database '{dbName}' already exists")

    _printInfo(f"Ensuring owner and database privileges for '{dbName}'")
    _runPsqlExec(psqlBase, commandEnv, f"ALTER DATABASE {dbName} OWNER TO {dbUser};")
    _runPsqlExec(psqlBase, commandEnv, f"GRANT ALL PRIVILEGES ON DATABASE {dbName} TO {dbUser};")

    psqlDbBase = _withDatabase(psqlBase, dbName)

    _printInfo("Ensuring schema ownership and privileges")
    ensureSchemaSql = (
        f"ALTER SCHEMA public OWNER TO {dbUser};"
        f" GRANT USAGE, CREATE ON SCHEMA public TO {dbUser};"
        f" GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {dbUser};"
        f" GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {dbUser};"
        f" GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO {dbUser};"
    )
    _runPsqlExec(psqlDbBase, commandEnv, ensureSchemaSql)

    _printInfo("Fixing ownership for existing schema objects")
    fixOwnershipSql = f"""
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN SELECT schemaname, tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE %I.%I OWNER TO %I', r.schemaname, r.tablename, '{dbUser}');
  END LOOP;

  FOR r IN SELECT sequence_schema, sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public' LOOP
    EXECUTE format('ALTER SEQUENCE %I.%I OWNER TO %I', r.sequence_schema, r.sequence_name, '{dbUser}');
  END LOOP;

  FOR r IN SELECT schemaname, viewname FROM pg_views WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER VIEW %I.%I OWNER TO %I', r.schemaname, r.viewname, '{dbUser}');
  END LOOP;
END $$;
""".strip()
    _runPsqlExec(psqlDbBase, commandEnv, fixOwnershipSql)

    _printInfo("Ensuring default privileges for future migrations")
    defaultPrivsSql = (
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO {dbUser};"
        f" ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO {dbUser};"
        f" ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON FUNCTIONS TO {dbUser};"
    )
    _runPsqlExec(psqlDbBase, commandEnv, defaultPrivsSql)


def _withDatabase(psqlBase: list, dbName: str) -> list:
    # Return a psql command base targeting a specific database.
    if "-d" in psqlBase:
        result = []
        skipNext = False

        for index, value in enumerate(psqlBase):
            if skipNext:
                skipNext = False
                continue

            if value == "-d":
                skipNext = True
                continue

            result.append(value)

        return result + ["-d", dbName]

    return psqlBase + ["-d", dbName]


def _parseUpgradeTargetRevision(output: str) -> Optional[str]:
    # parseAlembicUpgradeTargetRevision
    match = re.search(r"Running upgrade\s+[0-9a-f]+ \->\s+([0-9a-f]+),", output)
    if not match:
        return None
    return match.group(1)


def runAlembicUpgrade(repoRoot: Path) -> None:
    # runAlembicUpgradeHead
    _printInfo("Running Alembic upgrade to head")
    proc = runCmd(["alembic", "upgrade", "head"], cwd=repoRoot, live=True)

    if proc.returncode == 0:
        _printInfo("Alembic upgrade finished successfully")
        return

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")

    if ("InsufficientPrivilege" in combined) or ("permission denied" in combined):
        raise RuntimeError(
            "Alembic upgrade failed due to insufficient privileges.\n"
            "This usually means the database/tables are owned by a different role.\n"
            "Re-run `scipionapi install`, or check DATABASE_ADMIN_USER/DATABASE_ADMIN_PASS.\n\n"
            f"{combined}"
        )

    isDuplicateTable = ("DuplicateTable" in combined) or ("already exists" in combined)

    if not isDuplicateTable:
        raise RuntimeError(f"Alembic upgrade failed.\n{combined}")

    targetRevision = _parseUpgradeTargetRevision(combined)
    if not targetRevision:
        raise RuntimeError(
            "Alembic upgrade failed due to duplicate table, but the target revision could not be parsed.\n"
            f"{combined}"
        )

    _printInfo(f"Stamping duplicate-table revision '{targetRevision}'")
    stampProc = runCmd(["alembic", "stamp", targetRevision], cwd=repoRoot, live=True)
    if stampProc.returncode != 0:
        raise RuntimeError(
            "Alembic stamp failed.\n"
            f"{stampProc.stdout}\n{stampProc.stderr}"
        )

    _printInfo("Retrying Alembic upgrade after stamp")
    retryProc = runCmd(["alembic", "upgrade", "head"], cwd=repoRoot, live=True)
    if retryProc.returncode != 0:
        combinedRetry = (retryProc.stdout or "") + "\n" + (retryProc.stderr or "")
        raise RuntimeError(f"Alembic upgrade failed after stamping.\n{combinedRetry}")

    _printInfo("Alembic upgrade finished successfully after stamp")