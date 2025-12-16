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

import typer

from scipionapi_cli.install import installCommand
from scipionapi_cli.runtime import startCommand, stopCommand, restartCommand, statusCommand, logsCommand

app = typer.Typer(add_completion=False)


@app.command("install")
def install(
    user: str = typer.Option(..., "--user"),
    email: str = typer.Option(..., "--email"),
    password: str = typer.Option(..., "--pass"),
):
    # nonInteractiveInstall
    installCommand(adminUser=user, adminEmail=email, adminPassword=password)


@app.command("start")
def start():
    startCommand()


@app.command("stop")
def stop():
    stopCommand()


@app.command("restart")
def restart():
    restartCommand()


@app.command("status")
def status():
    statusCommand()


@app.command("logs")
def logs():
    logsCommand()


if __name__ == "__main__":
    app()
