import os
import re
from pathlib import Path
from typing import Dict, Optional

from scipionapi_cli.shell import runCmd


def _validateIdentifier(identifier: str, label: str) -> None:
    # validateSqlIdentifier
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", identifier or ""):
        raise ValueError(f"Invalid {label} '{identifier}'. Use only letters, numbers and underscore.")


def _escapeSqlLiteral(value: str) -> str:
    # escapeSingleQuotesForSqlLiteral
    return (value or "").replace("'", "''")


def ensureDatabaseAndRole(env: Dict[str, str]) -> None:
    # ensureDatabaseAndRoleIdempotent
    dbName = (env.get("DATABASE_NAME") or "").strip()
    dbUser = (env.get("DATABASE_USER") or "").strip()
    dbPass = env.get("DATABASE_PASS") or ""

    _validateIdentifier(dbName, "database name")
    _validateIdentifier(dbUser, "database user")

    safeDbName = _escapeSqlLiteral(dbName)
    safeDbUser = _escapeSqlLiteral(dbUser)
    safeDbPass = _escapeSqlLiteral(dbPass)

    postgresHost = (env.get("POSTGRES_HOST") or "localhost").strip()
    isLocalHost = postgresHost in ("localhost", "127.0.0.1", "::1", "")

    if not isLocalHost:
        raise RuntimeError(
            "POSTGRES_HOST is not local. For remote PostgreSQL you must pre-create the DB/user "
            "or implement DATABASE_ADMIN_USER/DATABASE_ADMIN_PASS bootstrap."
        )

    sudoArgs = ["sudo", "-u", "postgres"]
    if os.environ.get("SCIPIONAPI_SUDO_NONINTERACTIVE", "").strip() == "1":
        # doNotPromptForSudoPassword
        sudoArgs = ["sudo", "-n", "-u", "postgres"]

    psqlBase = sudoArgs + ["psql", "-v", "ON_ERROR_STOP=1"]

    def psqlScalar(sql: str) -> str:
        # psqlScalar
        proc = runCmd(psqlBase + ["-tA", "-c", sql], capture=True)
        if proc.returncode != 0:
            raise RuntimeError(f"psql failed.\nSQL: {sql}\n{proc.stderr}")
        return (proc.stdout or "").strip()

    def psqlExec(sql: str) -> None:
        # psqlExec
        proc = runCmd(psqlBase + ["-c", sql], capture=True)
        if proc.returncode != 0:
            raise RuntimeError(f"psql failed.\nSQL: {sql}\n{proc.stdout}\n{proc.stderr}")

    # ensureRoleExists
    roleExists = psqlScalar(f"SELECT 1 FROM pg_roles WHERE rolname='{safeDbUser}'")
    if roleExists != "1":
        psqlExec(f"CREATE ROLE {dbUser} LOGIN PASSWORD '{safeDbPass}';")

    # ensureDatabaseExists
    dbExists = psqlScalar(f"SELECT 1 FROM pg_database WHERE datname='{safeDbName}'")
    if dbExists != "1":
        # createDatabaseMustNotRunInsideDoOrTransaction
        psqlExec(f"CREATE DATABASE {dbName} OWNER {dbUser};")

    # ensureDbOwnerAndPrivilegesEvenIfDbAlreadyExisted
    psqlExec(f"ALTER DATABASE {dbName} OWNER TO {dbUser};")
    psqlExec(f"GRANT ALL PRIVILEGES ON DATABASE {dbName} TO {dbUser};")

    # ensureSchemaPrivilegesAndOwnership
    psqlDbBase = psqlBase + ["-d", dbName]

    def psqlDbExec(sql: str) -> None:
        # psqlDbExec
        proc = runCmd(psqlDbBase + ["-c", sql], capture=True)
        if proc.returncode != 0:
            raise RuntimeError(f"psql failed.\nSQL: {sql}\n{proc.stdout}\n{proc.stderr}")

    ensureSchemaSql = (
        f"ALTER SCHEMA public OWNER TO {dbUser};"
        f" GRANT USAGE, CREATE ON SCHEMA public TO {dbUser};"
        f" GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {dbUser};"
        f" GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {dbUser};"
        f" GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO {dbUser};"
    )
    psqlDbExec(ensureSchemaSql)

    # fixOwnershipForExistingObjects
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
    psqlDbExec(fixOwnershipSql)

    # ensureDefaultPrivilegesForFutureMigrations
    defaultPrivsSql = (
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO {dbUser};"
        f" ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO {dbUser};"
        f" ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON FUNCTIONS TO {dbUser};"
    )
    psqlDbExec(defaultPrivsSql)


def _parseUpgradeTargetRevision(output: str) -> Optional[str]:
    # parseAlembicUpgradeTargetRevision
    match = re.search(r"Running upgrade\s+[0-9a-f]+ \-\>\s+([0-9a-f]+),", output)
    if not match:
        return None
    return match.group(1)


def runAlembicUpgrade(repoRoot: Path) -> None:
    # runAlembicUpgradeHead
    proc = runCmd(["alembic", "upgrade", "head"], cwd=repoRoot, capture=True)
    if proc.returncode == 0:
        return

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")

    # detectPermissionDeniedEarly
    if ("InsufficientPrivilege" in combined) or ("permission denied" in combined):
        raise RuntimeError(
            "Alembic upgrade failed due to insufficient privileges.\n"
            "This usually means the database/tables are owned by a different role.\n"
            "Re-run `scipionapi install` after updating ensureDatabaseAndRole(), or drop/recreate the DB.\n\n"
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

    # stampOnlyTheFailedRevisionSoLaterMigrationsCanRun
    stampProc = runCmd(["alembic", "stamp", targetRevision], cwd=repoRoot, capture=True)
    if stampProc.returncode != 0:
        raise RuntimeError(
            "Alembic stamp failed.\n"
            f"{stampProc.stdout}\n{stampProc.stderr}"
        )

    # retryUpgradeAfterStamp
    retryProc = runCmd(["alembic", "upgrade", "head"], cwd=repoRoot, capture=True)
    if retryProc.returncode != 0:
        combinedRetry = (retryProc.stdout or "") + "\n" + (retryProc.stderr or "")
        raise RuntimeError(f"Alembic upgrade failed after stamping.\n{combinedRetry}")
