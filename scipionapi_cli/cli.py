import os
import re
from pathlib import Path
from typing import Optional

import typer
from importlib import metadata as importlibMetadata

from scipionapi_cli.bootstrap import bootstrapCommand
from scipionapi_cli.install import installCommand
from scipionapi_cli.provision import provisionCommand
from scipionapi_cli.doctor import doctorCommand
from scipionapi_cli.release import (
    DEFAULT_RELEASE_BASE_URL,
    DEFAULT_RELEASE_LOGIN,
    DEFAULT_RELEASE_REMOTE_DIR,
    releaseCommand,
)
from scipionapi_cli.update import updateCommand
from scipionapi_cli.version import SCIPIONAPI_RELEASE_TAG
from scipionapi_cli.runtime import (
    logsCommand,
    restartCommand,
    startCommand,
    statusCommand,
    stopCommand,
)


def _resolveCliVersion() -> str:
    # resolveCliVersion
    if SCIPIONAPI_RELEASE_TAG:
        return SCIPIONAPI_RELEASE_TAG

    packageName = "scipionapi"

    try:
        return importlibMetadata.version(packageName)
    except Exception:
        pass

    try:
        currentFile = Path(__file__).resolve()
        for parent in [currentFile.parent, *currentFile.parents]:
            pyprojectPath = parent / "pyproject.toml"
            if not pyprojectPath.exists():
                continue

            text = pyprojectPath.read_text(encoding="utf-8")
            match = re.search(
                r'^\s*version\s*=\s*"([^"]+)"\s*$',
                text,
                flags=re.MULTILINE,
            )
            if match:
                value = match.group(1)
                return value if value.startswith("v") else f"v{value}"
    except Exception:
        pass

    return "unknown"


def _resolveAdminPassword(
    password: Optional[str],
    passwordEnv: Optional[str],
    promptLabel: str = "Admin password",
) -> str:
    # Resolve admin password from CLI, environment variable, or hidden prompt.
    if password:
        return password

    if passwordEnv:
        envValue = os.environ.get(passwordEnv)
        if envValue:
            return envValue

        raise typer.BadParameter(
            f"Environment variable '{passwordEnv}' is not set or is empty.",
            param_hint="--password-env",
        )

    return typer.prompt(promptLabel, hide_input=True, confirmation_prompt=True)


CLI_VERSION = _resolveCliVersion()

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
    help=(
        f"[bold cyan]Scipion API CLI[/bold cyan] [dim]{CLI_VERSION}[/dim]\n\n"
        "Utilities to bootstrap the conda environment, install and configure the "
        "application, optionally deploy the web frontend, manage runtime services, "
        "and update existing installations.\n\n"
        "[bold]Typical usage[/bold]\n"
        "  scipionapi bootstrap\n"
        "  scipionapi install --user <name> --email <email>\n"
        "  scipionapi install --user <name> --email <email> --password-env ADMIN_PASSWORD\n"
        "  scipionapi provision --user <name> --email <email> [--web-dist <dir|zip>]\n"
        "  scipionapi update\n"
        "  scipionapi update --version v4.0.0\n"
        "  scipionapi release --upload --version v4.0.0 --downloads-dir <dir>\n"
        "  scipionapi start\n"
        "  scipionapi status\n"
        "  scipionapi logs\n"
        "  scipionapi version\n\n"
        "  scipionapi doctor\n"
        "[bold]Command groups[/bold]\n"
        "  [cyan]Setup[/cyan]: bootstrap, install, provision\n"
        "  [cyan]Update[/cyan]: update\n"
        "  [cyan]Release[/cyan]: release\n"
        "  [cyan]Runtime[/cyan]: start, stop, restart, status, logs\n"
        "  [cyan]Diagnostics[/cyan]: doctor\n"
        "  [cyan]Info[/cyan]: version\n"
    ),
)


@app.command(
    "bootstrap",
    help="Create/update the conda env, install requirements, install Scipion core packages if needed, and install this package editable."
)
def bootstrap(
    envName: str = typer.Option(
        "scipion4Web",
        "--env-name",
        envvar="SCIPIONAPI_ENV_NAME",
        help="Target conda environment name.",
        show_default=True,
    ),
    pythonVersion: str = typer.Option(
        "3.8",
        "--python",
        envvar="SCIPIONAPI_PYTHON_VERSION",
        help="Python version for the conda environment.",
        show_default=True,
    ),
    installScipionCore: bool = typer.Option(
        True,
        "--install-scipion-core/--no-install-scipion-core",
        envvar="SCIPIONAPI_INSTALL_SCIPION_CORE",
        help="Install Scipion core packages if pyworkflow is not already available.",
        show_default=True,
    ),
    scipionCorePackages: str = typer.Option(
        "scipion-pyworkflow scipion-em scipion-app",
        "--scipion-core-packages",
        envvar="SCIPIONAPI_SCIPION_CORE_PACKAGES",
        help="Space-separated list of Scipion core packages to install.",
        show_default=True,
    ),
) -> None:
    # bootstrapCondaEnv
    bootstrapCommand(
        envName=envName,
        pythonVersion=pythonVersion,
        installScipionCore=installScipionCore,
        scipionCorePackages=scipionCorePackages,
    )


@app.command(
    "install",
    help="Configure SCIPION_HOME/.env, create required directories and config files, ensure DB/user, run migrations, and ensure admin user. Does not install Python packages."
)
def install(
    user: str = typer.Option(
        ...,
        "--user",
        help="Admin username.",
    ),
    email: str = typer.Option(
        ...,
        "--email",
        help="Admin email.",
    ),
    password: Optional[str] = typer.Option(
        None,
        "--pass",
        "--password",
        help="Admin password. Prefer the hidden prompt or --password-env for security.",
        show_default=False,
    ),
    passwordEnv: Optional[str] = typer.Option(
        None,
        "--password-env",
        envvar="SCIPIONAPI_ADMIN_PASSWORD_ENV",
        help="Name of an environment variable containing the admin password.",
        show_default=False,
    ),
    apiPort: Optional[int] = typer.Option(
        None,
        "--api-port",
        envvar="SCIPIONAPI_API_PORT",
        help=(
            "API/Web port. If omitted, an existing API_PORT "
            "is preserved or a free port is selected automatically."
        ),
        min=1,
        max=65535,
        show_default=False,
    ),

) -> None:
    # nonInteractiveInstall
    adminPassword = _resolveAdminPassword(password, passwordEnv)

    installCommand(
        adminUser=user,
        adminEmail=email,
        adminPassword=adminPassword,
        apiPort=apiPort,
    )


@app.command(
    "provision",
    help=(
        "Run the full one-shot provisioning flow: optional bootstrap, install, "
        "optional web frontend deployment, and runtime startup."
    ),
)
def provision(
    user: str = typer.Option(
        ...,
        "--user",
        help="Admin username.",
    ),
    email: str = typer.Option(
        ...,
        "--email",
        help="Admin email.",
    ),
    password: Optional[str] = typer.Option(
        None,
        "--pass",
        "--password",
        help="Admin password. Prefer the hidden prompt or --password-env for security.",
        show_default=False,
    ),
    passwordEnv: Optional[str] = typer.Option(
        None,
        "--password-env",
        envvar="SCIPIONAPI_ADMIN_PASSWORD_ENV",
        help="Name of an environment variable containing the admin password.",
        show_default=False,
    ),
    webDist: Optional[str] = typer.Option(
        None,
        "--web-dist",
        help="Path to a Vite dist directory or a .zip containing the built frontend.",
    ),
    apiMountPath: str = typer.Option(
        "/api",
        "--api-mount-path",
        help="Mount path used by the API in integrated web mode.",
        show_default=True,
    ),
    apiBaseUrl: Optional[str] = typer.Option(
        None,
        "--api-base-url",
        help="API base URL the web frontend should use. Defaults to the resolved API mount path.",
    ),
    apiPort: Optional[int] = typer.Option(
        None,
        "--api-port",
        envvar="SCIPIONAPI_API_PORT",
        help=(
            "API/Web port. If omitted, an existing API_PORT "
            "is preserved or a free port is selected automatically."
        ),
        min=1,
        max=65535,
        show_default=False,
    ),
    runBootstrap: bool = typer.Option(
        True,
        "--bootstrap/--no-bootstrap",
        help="Run bootstrap before install and startup.",
        show_default=True,
    ),
    envName: str = typer.Option(
        "scipion4Web",
        "--env-name",
        envvar="SCIPIONAPI_ENV_NAME",
        help="Target conda environment name.",
        show_default=True,
    ),
    pythonVersion: str = typer.Option(
        "3.8",
        "--python",
        envvar="SCIPIONAPI_PYTHON_VERSION",
        help="Python version for the conda environment.",
        show_default=True,
    ),
    installScipionCore: bool = typer.Option(
        True,
        "--install-scipion-core/--no-install-scipion-core",
        envvar="SCIPIONAPI_INSTALL_SCIPION_CORE",
        help="Install Scipion core packages if pyworkflow is not already available.",
        show_default=True,
    ),
    scipionCorePackages: str = typer.Option(
        "scipion-pyworkflow scipion-em scipion-app",
        "--scipion-core-packages",
        envvar="SCIPIONAPI_SCIPION_CORE_PACKAGES",
        help="Space-separated list of Scipion core packages to install.",
        show_default=True,
    ),
) -> None:
    # provisionOneShot
    adminPassword = _resolveAdminPassword(password, passwordEnv)

    provisionCommand(
        adminUser=user,
        adminEmail=email,
        adminPassword=adminPassword,
        webDist=webDist,
        apiMountPath=apiMountPath,
        apiBaseUrl=apiBaseUrl,
        runBootstrap=runBootstrap,
        envName=envName,
        pythonVersion=pythonVersion,
        installScipionCore=installScipionCore,
        scipionCorePackages=scipionCorePackages,
        apiPort=apiPort,
    )


@app.command(
    "update",
    help=(
        "Update an existing installation from ScipionAPI/ScipionWeb release ZIPs "
        "while preserving SCIPION_HOME, .env, projects, logs, and database data."
    ),
)
def update(
    version: str = typer.Option(
        "latest",
        "--version",
        envvar="SCIPIONAPI_UPDATE_VERSION",
        help="Target release tag such as v4.0.0. Use latest to resolve the newest release.",
        show_default=True,
    ),
    baseUrl: Optional[str] = typer.Option(
        None,
        "--base-url",
        envvar="SCIPIONAPI_UPDATE_BASE_URL",
        help="Base URL containing manifest.json and release ZIPs.",
        show_default=False,
    ),
    apiZipUrl: Optional[str] = typer.Option(
        None,
        "--api-zip-url",
        help="Explicit ScipionAPI ZIP URL. Overrides the URL resolved from version/base URL.",
        show_default=False,
    ),
    webZipUrl: Optional[str] = typer.Option(
        None,
        "--web-zip-url",
        help="Explicit ScipionWeb dist ZIP URL. Overrides the URL resolved from version/base URL.",
        show_default=False,
    ),
    apiOnly: bool = typer.Option(
        False,
        "--api-only",
        help="Update only the API source/package and migrations.",
        show_default=True,
    ),
    webOnly: bool = typer.Option(
        False,
        "--web-only",
        help="Update only the deployed web dist.",
        show_default=True,
    ),
    dryRun: bool = typer.Option(
        False,
        "--dry-run",
        help="Resolve the target release and print the update plan without changing files.",
        show_default=True,
    ),
    noRestart: bool = typer.Option(
        False,
        "--no-restart",
        help="Do not restart services after applying the update.",
        show_default=True,
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Reinstall even if the current API version matches the target version.",
        show_default=True,
    ),
) -> None:
    # updateExistingInstallation
    updateCommand(
        version=version,
        baseUrl=baseUrl,
        apiZipUrl=apiZipUrl,
        webZipUrl=webZipUrl,
        apiOnly=apiOnly,
        webOnly=webOnly,
        dryRun=dryRun,
        noRestart=noRestart,
        force=force,
    )


@app.command(
    "release",
    help=(
            "Build paired ScipionAPI/ScipionWeb release archives locally "
            "and optionally publish them to the download server."
    ),
)
def release(
        upload: bool = typer.Option(
            False,
            "--upload",
            help=(
                    "Publish the release to the configured remote server "
                    "after building it, unless --no-build is used."
            ),
            show_default=True,
        ),
        buildArtifacts: bool = typer.Option(
            True,
            "--build/--no-build",
            help=(
                "Build fresh ScipionAPI and ScipionWeb release ZIPs first. "
                "Use --no-build only when uploading existing archives."
            ),
            show_default=True,
        ),
        version: Optional[str] = typer.Option(
            None,
            "--version",
            help=(
                    "Optional expected release version, for example v4.0.0. "
                    "The actual version is read from ScipionAPI and ScipionWeb."
            ),
            show_default=False,
        ),
        webRoot: Optional[str] = typer.Option(
            None,
            "--web-root",
            envvar="SCIPIONWEB_RELEASE_WEB_ROOT",
            help=(
                "Path to the ScipionWeb repository. "
                "Defaults to a ScipionWeb sibling of ScipionAPI."
            ),
            show_default=False,
        ),
        downloadsDir: str = typer.Option(
            ".",
            "--downloads-dir",
            help="Directory where the ScipionAPI and ScipionWeb release ZIPs are created or read.",
            show_default=True,
        ),
        apiFile: Optional[str] = typer.Option(
            None,
            "--api-file",
            help="Optional custom ScipionAPI ZIP path or filename.",
            show_default=False,
        ),
        webFile: Optional[str] = typer.Option(
            None,
            "--web-file",
            help="Optional custom ScipionWeb ZIP path or filename.",
            show_default=False,
        ),
        login: str = typer.Option(
            DEFAULT_RELEASE_LOGIN,
            "--login",
            envvar="SCIPIONWEB_RELEASE_LOGIN",
            help="SSH login used to publish release files.",
            show_default=True,
        ),
        remoteDir: str = typer.Option(
            DEFAULT_RELEASE_REMOTE_DIR,
            "--remote-dir",
            envvar="SCIPIONWEB_RELEASE_REMOTE_DIR",
            help="Remote directory corresponding to the public ScipionWeb download URL.",
            show_default=True,
        ),
        baseUrl: str = typer.Option(
            DEFAULT_RELEASE_BASE_URL,
            "--base-url",
            envvar="SCIPIONWEB_RELEASE_BASE_URL",
            help="Public HTTP base URL used to verify the published manifest.",
            show_default=True,
        ),
        setLatest: bool = typer.Option(
            True,
            "--latest/--no-latest",
            help="Update manifest.json latest to this release.",
            show_default=True,
        ),
        dryRun: bool = typer.Option(
            False,
            "--dry-run",
            help="Resolve and validate the release plan without uploading files.",
            show_default=True,
        ),
        yes: bool = typer.Option(
            False,
            "--yes",
            "-y",
            help="Upload without interactive confirmation.",
            show_default=True,
        ),
        force: bool = typer.Option(
            False,
            "--force",
            help="Intentionally replace an already-published release version.",
            show_default=True,
        ),
    ) -> None:
    if not buildArtifacts and not upload:
        raise typer.BadParameter(
            "--no-build requires --upload because there would be no release action.",
            param_hint="--no-build",
        )

    releaseCommand(
        upload=upload,
        buildArtifacts=buildArtifacts,
        version=version,
        webRoot=webRoot,
        downloadsDir=downloadsDir,
        apiFile=apiFile,
        webFile=webFile,
        login=login,
        remoteDir=remoteDir,
        baseUrl=baseUrl,
        setLatest=setLatest,
        dryRun=dryRun,
        yes=yes,
        force=force,
    )


@app.command(
    "start",
    help="Start uvicorn and the celery worker as detached processes using PID files under .run/.",
)
def start() -> None:
    # startRuntimeServices
    startCommand()


@app.command(
    "stop",
    help="Stop uvicorn and the celery worker using the PID files stored under .run/.",
)
def stop() -> None:
    # stopRuntimeServices
    stopCommand()


@app.command(
    "restart",
    help="Restart uvicorn and the celery worker.",
)
def restart() -> None:
    # restartRuntimeServices
    restartCommand()


@app.command(
    "status",
    help="Show runtime status for uvicorn and the celery worker, including health checks and log locations.",
)
def status() -> None:
    # showRuntimeStatus
    statusCommand()


@app.command(
    "logs",
    help="Follow the application and celery log files.",
)
def logs() -> None:
    # followRuntimeLogs
    logsCommand()


@app.command(
    "doctor",
    help="Run read-only diagnostics for the repository, environment, database, broker, imports, and runtime services.",
)
def doctor(
    strict: bool = typer.Option(
        False,
        "--strict/--no-strict",
        help="Exit with code 1 when failures are detected.",
        show_default=True,
    ),
    full: bool = typer.Option(
        True,
        "--full/--quick",
        help="Run heavier checks such as importing the FastAPI app and checking Alembic.",
        show_default=True,
    ),
) -> None:
    # runDoctorDiagnostics
    doctorCommand(strict=strict, full=full)


@app.command(
    "version",
    help="Show the installed Scipion API CLI version.",
)
def version() -> None:
    # showCliVersion
    typer.echo(f"scipionapi {CLI_VERSION}")


if __name__ == "__main__":
    app()
