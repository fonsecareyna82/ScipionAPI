from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from scipionapi_cli.db import (
    _envFloat,
    _escapeSqlLiteral,
    _resolveAdminConnection,
    _runPsqlExec,
    _usesSudo,
    _validateIdentifier,
    _validateSudoAccess,
)
from scipionapi_cli.envfile import exportEnvToOs, readEnvFile, writeEnvFile
from scipionapi_cli.install import _resolveScipionHome
from scipionapi_cli.runtime import stopCommand
from scipionapi_cli.shell import resolveRepoRoot

console = Console()

GUIDED_INSTALL_MARKER = ".scipionweb-installation"

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
    help=(
        "Remove ScipionWeb/ScipionAPI runtime resources. A guided installation "
        "can also be removed completely with --full."
    ),
)


def _printPanel(title: str, body: str = "") -> None:
    console.print(Panel.fit(body or "", title=title, border_style="cyan"))


def _printInfo(message: str) -> None:
    console.print("[bold cyan]INFO[/bold cyan] " + message)


def _printWarning(message: str) -> None:
    console.print("[bold yellow]WARNING[/bold yellow] " + message)


def _printSuccess(message: str) -> None:
    console.print("[bold green]SUCCESS[/bold green] " + message)


def _printStep(step: str, detail: str = "") -> None:
    if detail:
        console.print(f"[bold magenta]--> {step}[/bold magenta] [dim]{detail}[/dim]")
    else:
        console.print(f"[bold magenta]--> {step}[/bold magenta]")


def _printKeyValueTable(title: str, rows: List[Tuple[str, Any]]) -> None:
    table = Table(title=title, header_style="bold magenta")
    table.add_column("Field", style="bold white", no_wrap=True)
    table.add_column("Value", style="white")

    for key, value in rows:
        table.add_row(str(key), str(value))

    console.print(table)


def _readInstallationEnv(repoRoot: Path) -> Tuple[Path, Path, Dict[str, str]]:
    defaultScipionHome = (repoRoot / "scipion_home").resolve()
    defaultEnvPath = defaultScipionHome / ".env"
    existingDefault = readEnvFile(defaultEnvPath)
    scipionHome = _resolveScipionHome(repoRoot, existingDefault)
    envPath = scipionHome / ".env"

    if envPath.exists():
        exportEnvToOs(envPath)
        env = readEnvFile(envPath)
    else:
        env = {}

    if "SCIPION_HOME" not in env:
        env["SCIPION_HOME"] = str(scipionHome)

    return scipionHome, envPath, env


def _readGuidedInstallationMarker(repoRoot: Path) -> Tuple[Path, Dict[str, str]]:
    markerPath = repoRoot / GUIDED_INSTALL_MARKER
    if not markerPath.is_file():
        raise RuntimeError(
            "Full uninstall is only allowed for installations created by the "
            f"guided installer. Missing guided installation marker: {markerPath}"
        )

    values: Dict[str, str] = {}
    for rawLine in markerPath.read_text(encoding="utf-8").splitlines():
        line = rawLine.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    return markerPath, values


def _validateGuidedInstallationMarker(repoRoot: Path) -> Path:
    repoRoot = repoRoot.expanduser().resolve()
    markerPath, marker = _readGuidedInstallationMarker(repoRoot)

    if marker.get("FORMAT") != "1":
        raise RuntimeError(
            f"Unsupported guided installation marker format: {markerPath}"
        )

    if marker.get("INSTALL_TYPE") != "guided":
        raise RuntimeError(
            f"Invalid guided installation marker: {markerPath}"
        )

    configuredRoot = marker.get("INSTALL_ROOT")
    if not configuredRoot:
        raise RuntimeError(
            f"Guided installation marker has no INSTALL_ROOT: {markerPath}"
        )

    markerRoot = Path(configuredRoot).expanduser().resolve()
    if markerRoot != repoRoot:
        raise RuntimeError(
            "Guided installation marker root does not match the current "
            f"repository root: {markerRoot} != {repoRoot}"
        )

    unsafeRoots = {
        Path("/").resolve(),
        Path.home().expanduser().resolve(),
    }
    if repoRoot in unsafeRoots:
        raise RuntimeError(
            f"Refusing unsafe full uninstall root: {repoRoot}"
        )

    return markerPath


def _validateLegacyInstallationRoot(repoRoot: Path) -> None:
    repoRoot = repoRoot.expanduser().resolve()

    if (repoRoot / ".git").exists():
        raise RuntimeError(
            "Refusing legacy full uninstall for a Git checkout. "
            "Use the regular uninstall and remove the repository manually if intended."
        )

    requiredPaths = [
        repoRoot / "pyproject.toml",
        repoRoot / "alembic.ini",
        repoRoot / "scripts" / "scipionapi",
        repoRoot / "scipion_home" / ".env",
    ]
    missing = [str(path) for path in requiredPaths if not path.exists()]
    if missing:
        raise RuntimeError(
            "Legacy full uninstall could not verify the expected packaged "
            "installation layout. Missing: " + ", ".join(missing)
        )

    unsafeRoots = {
        Path("/").resolve(),
        Path.home().expanduser().resolve(),
    }
    if repoRoot in unsafeRoots:
        raise RuntimeError(
            f"Refusing unsafe legacy full uninstall root: {repoRoot}"
        )


def _validateFullInstallationRoot(
    repoRoot: Path,
    legacyInstall: bool,
) -> str:
    markerPath = repoRoot / GUIDED_INSTALL_MARKER

    if markerPath.is_file():
        _validateGuidedInstallationMarker(repoRoot)
        return "guided"

    if not legacyInstall:
        raise RuntimeError(
            "This installation has no guided installation marker. If it is a "
            "pre-marker ZIP/package installation (not a Git checkout), rerun "
            "with --full --legacy-install."
        )

    _validateLegacyInstallationRoot(repoRoot)
    return "legacy"


def _confirmPlan(
    yes: bool,
    dryRun: bool,
    keepDatabase: bool,
    keepDatabaseRole: bool,
    keepWebDist: bool,
    removeScipionHome: bool,
    keepCondaEnv: bool,
    full: bool,
    repoRoot: Path,
    fullMode: str,
) -> None:
    if yes or dryRun:
        return

    console.print()
    console.print("[bold red]This command will remove installation resources.[/bold red]")

    if full:
        console.print(
            "[bold red]The guided installation directory will also be removed "
            "after runtime cleanup.[/bold red]"
        )
    else:
        console.print("The ScipionAPI repository directory will not be removed.")

    console.print(f"Database removal: {'no' if keepDatabase else 'yes'}")
    console.print(f"Database role removal: {'no' if keepDatabase or keepDatabaseRole else 'yes'}")
    console.print(f"Web dist removal: {'no' if keepWebDist else 'yes'}")
    console.print(f"SCIPION_HOME removal: {'yes' if removeScipionHome else 'no'}")
    console.print(f"Conda env removal: {'no' if keepCondaEnv else 'yes'}")
    console.print(f"Installation root removal: {'yes' if full else 'no'}")
    if full:
        console.print(f"Installation root: {repoRoot}")
        console.print(f"Full uninstall mode: {fullMode}")

    if not Confirm.ask("Continue?", default=False):
        raise typer.Abort()


def _dropDatabaseAndRole(
    env: Dict[str, str],
    keepDatabase: bool,
    keepDatabaseRole: bool,
    dryRun: bool,
) -> bool:
    dbName = (env.get("DATABASE_NAME") or "").strip()
    dbUser = (env.get("DATABASE_USER") or "").strip()

    if keepDatabase:
        _printInfo("Skipping PostgreSQL cleanup because --keep-database was provided")
        return False

    if not dbName:
        _printWarning("DATABASE_NAME is not configured. Skipping PostgreSQL database cleanup.")
        return False

    _validateIdentifier(dbName, "database name")
    if dbUser:
        _validateIdentifier(dbUser, "database user")

    _printStep("Cleaning PostgreSQL database", dbName)

    if dryRun:
        _printInfo(f"Would terminate connections to database '{dbName}'")
        _printInfo(f"Would drop database '{dbName}'")
        if dbUser and not keepDatabaseRole:
            _printInfo(f"Would drop role '{dbUser}'")
        return True

    psqlTimeoutSec = _envFloat(env, "POSTGRES_COMMAND_TIMEOUT", 60.0)
    psqlBase, commandEnv = _resolveAdminConnection(env)

    if _usesSudo(psqlBase):
        _validateSudoAccess(env, commandEnv)

    safeDbName = _escapeSqlLiteral(dbName)
    terminateSql = (
        "SELECT pg_terminate_backend(pid) "
        "FROM pg_stat_activity "
        f"WHERE datname = '{safeDbName}' AND pid <> pg_backend_pid();"
    )
    _runPsqlExec(psqlBase, commandEnv, terminateSql, psqlTimeoutSec)

    try:
        _runPsqlExec(psqlBase, commandEnv, f"DROP DATABASE IF EXISTS {dbName};", psqlTimeoutSec)
    except RuntimeError:
        _printWarning("Regular DROP DATABASE failed. Retrying with FORCE.")
        _runPsqlExec(psqlBase, commandEnv, f"DROP DATABASE IF EXISTS {dbName} WITH (FORCE);", psqlTimeoutSec)

    if dbUser and not keepDatabaseRole:
        try:
            _runPsqlExec(psqlBase, commandEnv, f"DROP ROLE IF EXISTS {dbUser};", psqlTimeoutSec)
        except RuntimeError as exc:
            _printWarning(f"Could not drop PostgreSQL role '{dbUser}': {exc}")

    _printSuccess("PostgreSQL cleanup completed")
    return True


def _removePath(path: Path, label: str, dryRun: bool) -> bool:
    if not path.exists():
        _printInfo(f"{label} not found: {path}")
        return False

    if path.resolve() == Path("/").resolve():
        raise RuntimeError(f"Refusing to remove unsafe {label}: {path}")

    if dryRun:
        _printInfo(f"Would remove {label}: {path}")
        return True

    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)

    _printSuccess(f"Removed {label}: {path}")
    return True


def _removeWebDist(env: Dict[str, str], scipionHome: Path, keepWebDist: bool, dryRun: bool) -> bool:
    if keepWebDist:
        _printInfo("Skipping web dist cleanup because --keep-web-dist was provided")
        return False

    configuredPath = (env.get("WEB_DIST_PATH") or "").strip()
    webDistPath = Path(configuredPath).expanduser() if configuredPath else scipionHome / "web" / "dist"

    _printStep("Removing deployed web assets", str(webDistPath))
    removed = _removePath(webDistPath, "web dist", dryRun=dryRun)

    envPath = scipionHome / ".env"
    if envPath.exists() and not dryRun:
        writeEnvFile(
            envPath,
            {
                "SERVE_WEB": "0",
                "WEB_DIST_PATH": "",
            },
        )
        _printInfo("Disabled integrated web mode in .env")

    return removed


def _stopServices(dryRun: bool) -> None:
    _printStep("Stopping runtime services")

    if dryRun:
        _printInfo("Would run service stop phase")
        return

    try:
        stopCommand()
    except Exception as exc:
        _printWarning(f"Service stop failed or was not available: {exc}")


def uninstallWebCommand(
    yes: bool = False,
    dryRun: bool = False,
    keepDatabase: bool = False,
    keepDatabaseRole: bool = False,
    keepWebDist: bool = False,
    removeScipionHome: bool = False,
    keepCondaEnv: bool = True,
    full: bool = False,
    legacyInstall: bool = False,
) -> None:
    repoRoot = resolveRepoRoot().expanduser().resolve()
    fullMode = "none"

    if full:
        fullMode = _validateFullInstallationRoot(
            repoRoot,
            legacyInstall=legacyInstall,
        )
        if keepDatabase or keepDatabaseRole or keepWebDist:
            raise RuntimeError(
                "--full cannot be combined with --keep-database, "
                "--keep-database-role, or --keep-web-dist."
            )
        removeScipionHome = True
        keepCondaEnv = False

    scipionHome, envPath, env = _readInstallationEnv(repoRoot)
    condaEnv = os.environ.get("SCIPIONAPI_ENV_NAME") or os.environ.get("SCIPIONAPI_CONDA_ENV") or "scipion4Web"

    _printPanel("ScipionAPI web uninstall")
    _printKeyValueTable(
        "Resolved installation",
        [
            ("Repo root", repoRoot),
            ("SCIPION_HOME", scipionHome),
            ("Env file", envPath),
            ("Conda env", condaEnv),
            ("Database", env.get("DATABASE_NAME", "")),
            ("Database user", env.get("DATABASE_USER", "")),
            ("WEB_DIST_PATH", env.get("WEB_DIST_PATH", str(scipionHome / "web" / "dist"))),
            ("Full uninstall", "yes" if full else "no"),
            ("Full uninstall mode", fullMode),
        ],
    )

    _confirmPlan(
        yes=yes,
        dryRun=dryRun,
        keepDatabase=keepDatabase,
        keepDatabaseRole=keepDatabaseRole,
        keepWebDist=keepWebDist,
        removeScipionHome=removeScipionHome,
        keepCondaEnv=keepCondaEnv,
        full=full,
        repoRoot=repoRoot,
        fullMode=fullMode,
    )

    _stopServices(dryRun=dryRun)
    _dropDatabaseAndRole(
        env=env,
        keepDatabase=keepDatabase,
        keepDatabaseRole=keepDatabaseRole,
        dryRun=dryRun,
    )

    if removeScipionHome:
        _printStep("Removing SCIPION_HOME", str(scipionHome))
        _removePath(scipionHome, "SCIPION_HOME", dryRun=dryRun)
    else:
        _removeWebDist(env=env, scipionHome=scipionHome, keepWebDist=keepWebDist, dryRun=dryRun)

    if keepCondaEnv:
        _printInfo("Conda env removal is handled by the scripts/scipionapi wrapper after this phase.")

    if full:
        action = "Would remove" if dryRun else "Will remove"
        _printInfo(
            f"{action} installation root from the wrapper: {repoRoot}"
        )

    _printSuccess("Uninstall cleanup phase completed.")


@app.command("run")
def run(
    full: bool = typer.Option(
        False,
        "--full",
        help=(
            "Completely remove an installation created by install.sh, including "
            "SCIPION_HOME, the conda env, and the installation directory."
        ),
        show_default=True,
    ),
    legacyInstall: bool = typer.Option(
        False,
        "--legacy-install",
        help=(
            "Allow --full for a pre-marker packaged installation. Git checkouts "
            "are always rejected."
        ),
        show_default=True,
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Run without interactive confirmation.",
        show_default=True,
    ),
    dryRun: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the cleanup plan without removing anything.",
        show_default=True,
    ),
    keepDatabase: bool = typer.Option(
        False,
        "--keep-database",
        help="Do not drop the configured PostgreSQL database.",
        show_default=True,
    ),
    keepDatabaseRole: bool = typer.Option(
        False,
        "--keep-database-role",
        help="Drop the database but keep the configured PostgreSQL role.",
        show_default=True,
    ),
    keepWebDist: bool = typer.Option(
        False,
        "--keep-web-dist",
        help="Do not remove the deployed web dist directory.",
        show_default=True,
    ),
    removeScipionHome: bool = typer.Option(
        False,
        "--remove-scipion-home",
        help="Remove SCIPION_HOME after stopping services and cleaning the database.",
        show_default=True,
    ),
    keepCondaEnv: bool = typer.Option(
        True,
        "--keep-conda-env/--remove-conda-env",
        help="Keep the conda env in this Python phase. The wrapper removes it safely outside the env.",
        show_default=True,
    ),
) -> None:
    uninstallWebCommand(
        yes=yes,
        dryRun=dryRun,
        keepDatabase=keepDatabase,
        keepDatabaseRole=keepDatabaseRole,
        keepWebDist=keepWebDist,
        removeScipionHome=removeScipionHome,
        keepCondaEnv=keepCondaEnv,
        full=full,
        legacyInstall=legacyInstall,
    )


if __name__ == "__main__":
    app()
