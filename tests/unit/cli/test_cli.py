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
import pytest
import typer

from scipionapi_cli.cli import _validateRole


def test_ValidateRoleAcceptsKnownRoles():
    assert _validateRole("all") == "all"
    assert _validateRole("API") == "api"
    assert _validateRole(" plugins ") == "plugins"
    assert _validateRole("protocols") == "protocols"


def test_ValidateRoleRejectsUnknownRole():
    with pytest.raises(typer.BadParameter):
        _validateRole("gpu-node")


def _commandNames():
    # listRegisteredCommandNames
    from scipionapi_cli.cli import app

    return {command.name or command.callback.__name__
            for command in app.registered_commands}


def test_UninstallIsOfferedByTheLauncher():
    """The command exists but was only reachable through the wrapper.

    scripts/scipionapi intercepts 'uninstall' before delegating, so the
    launcher itself never knew about it: it is absent from --help and
    answers "No such command". Anyone not reading the shell script has
    no way to find it.
    """
    assert "uninstall" in _commandNames()


def test_UninstallIsDescribedInTheHelp():
    from typer.testing import CliRunner

    from scipionapi_cli.cli import app

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "uninstall" in result.output


def _invokeUninstall(args, monkeypatch):
    from typer.testing import CliRunner

    import scipionapi_cli.cli as cliModule

    calls = []
    monkeypatch.setattr(
        cliModule,
        "uninstallWebCommand",
        lambda **kwargs: calls.append(kwargs),
    )

    result = CliRunner().invoke(cliModule.app, ["uninstall"] + args)

    return result, calls


@pytest.mark.parametrize("flag", ["--full", "--remove-conda-env"])
def test_UninstallRefusesWhatItCannotFinishFromInsideTheEnv(flag, monkeypatch):
    """Both steps delete the env this interpreter is running in.

    The wrapper runs the Python cleanup first and removes them from
    outside afterwards. Accepting them here would clean the database and
    SCIPION_HOME and then leave the env and the root behind, with no
    sign that anything was missed.
    """
    result, calls = _invokeUninstall([flag, "--yes"], monkeypatch)

    assert result.exit_code != 0
    assert "./scripts/scipionapi uninstall" in result.output
    assert calls == []


def test_UninstallRunsTheCleanupForTheSupportedOptions(monkeypatch):
    result, calls = _invokeUninstall(
        ["--yes", "--dry-run", "--keep-database"], monkeypatch)

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["yes"] is True
    assert calls[0]["dryRun"] is True
    assert calls[0]["keepDatabase"] is True
    assert calls[0]["keepCondaEnv"] is True
