import typer

from scipionapi_cli.bootstrap import bootstrapCommand
from scipionapi_cli.install import installCommand
from scipionapi_cli.provision import provisionCommand
from scipionapi_cli.runtime import logsCommand, restartCommand, startCommand, statusCommand, stopCommand

app = typer.Typer(
    add_completion=False,
    help=(
        "Scipion API CLI.\n\n"
        "Typical usage:\n"
        "  scipionapi provision --user ... --email ... --pass ... [--web-dist <dir|zip>]\n"
        "  scipionapi start|stop|restart|status|logs\n"
    ),
)


@app.command("bootstrap", help="Create/update the conda env, install requirements, and install this package editable.")
def bootstrap(
    envName: str = typer.Option("scipion4Web", "--env-name", envvar="SCIPIONAPI_ENV_NAME"),
    pythonVersion: str = typer.Option("3.8", "--python", envvar="SCIPIONAPI_PYTHON_VERSION"),
    installScipionCore: bool = typer.Option(True, "--install-scipion-core/--no-install-scipion-core", envvar="SCIPIONAPI_INSTALL_SCIPION_CORE"),
    scipionCorePackages: str = typer.Option("scipion-pyworkflow scipion-em scipion-app", "--scipion-core-packages", envvar="SCIPIONAPI_SCIPION_CORE_PACKAGES"),
) -> None:
    # bootstrapCondaEnv
    bootstrapCommand(
        envName=envName,
        pythonVersion=pythonVersion,
        installScipionCore=installScipionCore,
        scipionCorePackages=scipionCorePackages,
    )


@app.command("install", help="Create/update SCIPION_HOME/.env, folders, local DB/user (if needed), run migrations, ensure admin user.")
def install(
    user: str = typer.Option(..., "--user", help="Admin username."),
    email: str = typer.Option(..., "--email", help="Admin email."),
    password: str = typer.Option(..., "--pass", help="Admin password."),
) -> None:
    # nonInteractiveInstall
    installCommand(adminUser=user, adminEmail=email, adminPassword=password)


@app.command("provision", help="One-shot provisioning: bootstrap + install + optional web deploy + start uvicorn and celery.")
def provision(
    user: str = typer.Option(..., "--user", help="Admin username."),
    email: str = typer.Option(..., "--email", help="Admin email."),
    password: str = typer.Option(..., "--pass", help="Admin password."),
    webDist: str = typer.Option(None, "--web-dist", help="Path to Vite dist directory or a .zip containing the dist."),
    apiMountPath: str = typer.Option("/api", "--api-mount-path", help="Where the API should be mounted in integrated mode."),
    apiBaseUrl: str = typer.Option(None, "--api-base-url", help="API base URL the web should use (defaults to apiMountPath)."),
    runBootstrap: bool = typer.Option(True, "--bootstrap/--no-bootstrap", help="Run conda bootstrap before install/start."),
    envName: str = typer.Option("scipion4Web", "--env-name", envvar="SCIPIONAPI_ENV_NAME"),
    pythonVersion: str = typer.Option("3.8", "--python", envvar="SCIPIONAPI_PYTHON_VERSION"),
    installScipionCore: bool = typer.Option(True, "--install-scipion-core/--no-install-scipion-core", envvar="SCIPIONAPI_INSTALL_SCIPION_CORE"),
    scipionCorePackages: str = typer.Option("scipion-pyworkflow scipion-em scipion-app", "--scipion-core-packages", envvar="SCIPIONAPI_SCIPION_CORE_PACKAGES"),
) -> None:
    # provisionOneShot
    provisionCommand(
        adminUser=user,
        adminEmail=email,
        adminPassword=password,
        webDist=webDist,
        apiMountPath=apiMountPath,
        apiBaseUrl=apiBaseUrl,
        runBootstrap=runBootstrap,
        envName=envName,
        pythonVersion=pythonVersion,
        installScipionCore=installScipionCore,
        scipionCorePackages=scipionCorePackages,
    )


@app.command("start", help="Start uvicorn and celery as detached processes (PID files in .run/).")
def start() -> None:
    startCommand()


@app.command("stop", help="Stop uvicorn and celery using PID files.")
def stop() -> None:
    stopCommand()


@app.command("restart", help="Restart uvicorn and celery.")
def restart() -> None:
    restartCommand()


@app.command("status", help="Show whether uvicorn and celery are running.")
def status() -> None:
    statusCommand()


@app.command("logs", help="Tail app and celery logs.")
def logs() -> None:
    logsCommand()


if __name__ == "__main__":
    app()
