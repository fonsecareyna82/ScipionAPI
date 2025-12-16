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
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
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

import typer

from scipionapi_cli.install import installCommand
from scipionapi_cli.runtime import startCommand, stopCommand, restartCommand, statusCommand, logsCommand
from scipionapi_cli.bootstrap import bootstrapCommand, provisionCommand

app = typer.Typer(
    add_completion=False,
    help=(
        "ScipionAPI command-line interface.\n\n"
        "Typical workflow:\n"
        "  scipionapi bootstrap\n"
        "  scipionapi install --user ... --email ... --pass ...\n"
        "  scipionapi start\n\n"
        "Single-step setup:\n"
        "  scipionapi provision --user ... --email ... --pass ...\n"
    ),
)


@app.command("bootstrap", help="Create/update the conda env, install requirements, and install the package (editable).")
def bootstrap(
    envName: str = typer.Option("scipion4Web", "--env-name", help="Conda environment name to use/create."),
    pythonVersion: str = typer.Option("3.8", "--python", help="Python version for the conda environment."),
    installScipionCore: bool = typer.Option(True, "--install-scipion-core/--no-install-scipion-core", help="Install Scipion core packages if pyworkflow import is missing."),
    scipionCorePackages: str = typer.Option(
        "scipion-pyworkflow scipion-em scipion-app scipion-em-tomo",
        "--scipion-core-packages",
        help="Space-separated list of Scipion core packages to install when needed.",
    ),
):
    # bootstrapCommandEntry
    bootstrapCommand(
        envName=envName,
        pythonVersion=pythonVersion,
        installScipionCore=installScipionCore,
        scipionCorePackages=scipionCorePackages,
    )


@app.command("install", help="Generate .env under SCIPION_HOME, setup DB/role, run migrations, and create/update admin user.")
def install(
    user: str = typer.Option(..., "--user", help="Admin username to create/update."),
    email: str = typer.Option(..., "--email", help="Admin email to create/update."),
    password: str = typer.Option(..., "--pass", help="Admin password to set (will be hashed)."),
):
    # nonInteractiveInstall
    installCommand(adminUser=user, adminEmail=email, adminPassword=password)


@app.command("provision", help="One-shot setup: bootstrap + install + start. Intended for fresh deployments.")
def provision(
    user: str = typer.Option(..., "--user", help="Admin username to create/update."),
    email: str = typer.Option(..., "--email", help="Admin email to create/update."),
    password: str = typer.Option(..., "--pass", help="Admin password to set (will be hashed)."),
    envName: str = typer.Option("scipion4Web", "--env-name", help="Conda environment name to use/create."),
    pythonVersion: str = typer.Option("3.8", "--python", help="Python version for the conda environment."),
    installScipionCore: bool = typer.Option(True, "--install-scipion-core/--no-install-scipion-core", help="Install Scipion core packages if needed."),
    scipionCorePackages: str = typer.Option(
        "scipion-pyworkflow scipion-em scipion-app scipion-em-tomo",
        "--scipion-core-packages",
        help="Space-separated list of Scipion core packages to install when needed.",
    ),
    runBootstrap: bool = typer.Option(True, "--bootstrap/--no-bootstrap", help="Run bootstrap step before install/start."),
):
    # provisionCommandEntry
    provisionCommand(
        adminUser=user,
        adminEmail=email,
        adminPassword=password,
        envName=envName,
        pythonVersion=pythonVersion,
        installScipionCore=installScipionCore,
        scipionCorePackages=scipionCorePackages,
        runBootstrap=runBootstrap,
    )


@app.command("start", help="Start the FastAPI (uvicorn) API and Celery worker as detached processes.")
def start():
    # startEntry
    startCommand()


@app.command("stop", help="Stop the FastAPI (uvicorn) API and Celery worker.")
def stop():
    # stopEntry
    stopCommand()


@app.command("restart", help="Restart the FastAPI (uvicorn) API and Celery worker.")
def restart():
    # restartEntry
    restartCommand()


@app.command("status", help="Show whether the API and worker are running (pid-based).")
def status():
    # statusEntry
    statusCommand()


@app.command("logs", help="Tail the API and worker logs.")
def logs():
    # logsEntry
    logsCommand()


if __name__ == "__main__":
    app()
