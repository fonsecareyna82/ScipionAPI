import typer

from scipionapi_cli.install import installCommand
from scipionapi_cli.provision import provisionCommand
from scipionapi_cli.runtime import logsCommand, restartCommand, startCommand, statusCommand, stopCommand

app = typer.Typer(
    add_completion=False,
    help=(
        "Scipion API CLI.\n\n"
        "Typical usage:\n"
        "  scipionapi install --user ... --email ... --pass ...\n"
        "  scipionapi start|stop|restart|status|logs\n"
        "  scipionapi provision --user ... --email ... --pass ... [--web-dist <dir|zip>]\n"
    ),
)


@app.command("install", help="Create/update SCIPION_HOME/.env, folders, local DB/user (if needed), run migrations, ensure admin user.")
def install(
    user: str = typer.Option(..., "--user", help="Admin username."),
    email: str = typer.Option(..., "--email", help="Admin email."),
    password: str = typer.Option(..., "--pass", help="Admin password."),
) -> None:
    # nonInteractiveInstall
    installCommand(adminUser=user, adminEmail=email, adminPassword=password)


@app.command(
    "provision",
    help=(
        "One-shot provisioning: install + optional web deploy + start uvicorn and celery.\n"
        "If --web-dist is provided, the API is mounted at /api and the web is served at /."
    ),
)
def provision(
    user: str = typer.Option(..., "--user", help="Admin username."),
    email: str = typer.Option(..., "--email", help="Admin email."),
    password: str = typer.Option(..., "--pass", help="Admin password."),
    webDist: str = typer.Option(None, "--web-dist", help="Path to Vite dist directory or a .zip containing the dist."),
    apiMountPath: str = typer.Option("/api", "--api-mount-path", help="Where the API should be mounted in integrated mode."),
    apiBaseUrl: str = typer.Option(None, "--api-base-url", help="API base URL the web should use (defaults to apiMountPath)."),
) -> None:
    # provisionOneShot
    provisionCommand(
        adminUser=user,
        adminEmail=email,
        adminPassword=password,
        webDist=webDist,
        apiMountPath=apiMountPath,
        apiBaseUrl=apiBaseUrl,
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
