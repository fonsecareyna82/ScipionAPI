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
import json
import os
import tempfile
from typing import Dict, Set


_CUSTOM_ENVIRONMENT_FILE_NAME = "scipionweb_environment.json"

def _getCustomEnvironmentPath(
        scipionHome: str,
) -> str:
    return os.path.join(
        scipionHome,
        "config",
        _CUSTOM_ENVIRONMENT_FILE_NAME,
    )


def _writeCustomEnvironment(
        scipionHome: str,
        values: Dict[str, str],
) -> None:
    path = _getCustomEnvironmentPath(
        scipionHome
    )

    directory = os.path.dirname(
        path
    )

    os.makedirs(
        directory,
        exist_ok=True,
    )

    fd, tempPath = tempfile.mkstemp(
        prefix=".scipionweb_environment.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )

    try:
        with os.fdopen(
                fd,
                "w",
                encoding="utf-8",
        ) as file:
            json.dump(
                values,
                file,
                indent=2,
                sort_keys=True,
            )

            file.write("\n")
            file.flush()
            os.fsync(
                file.fileno()
            )

        os.replace(
            tempPath,
            path,
        )

    finally:
        if os.path.exists(
                tempPath
        ):
            try:
                os.remove(
                    tempPath
                )
            except OSError:
                pass


def _loadCustomEnvironment(scipionHome: str) -> Dict[str, str]:
    if not scipionHome:
        return {}

    path = _getCustomEnvironmentPath(
        scipionHome
    )

    if not os.path.isfile(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as file:
            raw = json.load(file)
    except Exception:
        return {}

    if not isinstance(raw, dict):
        return {}

    return {
        str(name).strip(): "" if value is None else str(value)
        for name, value in raw.items()
        if str(name).strip()
    }


def removeCustomEnvironmentVariables(
        scipionHome: str,
        variableNames: Set[str],
) -> Set[str]:
    if not scipionHome:
        return set()

    cleanNames = {
        str(variableName).strip()
        for variableName
        in variableNames
        if str(variableName).strip()
    }

    if not cleanNames:
        return set()

    customEnvironment = (
        _loadCustomEnvironment(
            scipionHome
        )
    )

    removedNames = (
        cleanNames
        & set(
            customEnvironment
        )
    )

    if not removedNames:
        return set()

    for variableName in removedNames:
        customEnvironment.pop(
            variableName,
            None,
        )

        os.environ.pop(
            variableName,
            None,
        )

    _writeCustomEnvironment(
        scipionHome,
        customEnvironment,
    )

    return removedNames


def prepareEnvironment():
    """Prepare the Scipion environment with all variables"""
    from scipion.__main__ import Vars

    variables = Vars.init()
    os.environ.update(variables)

    import pyworkflow

    scipionHome = (
        variables.get(pyworkflow.SCIPION_HOME_VAR)
        or os.environ.get(pyworkflow.SCIPION_HOME_VAR)
    )

    customEnvironment = (
        _loadCustomEnvironment(scipionHome)
        if scipionHome
        else {}
    )

    # Custom variables must be available before loading plugins/protocols.
    os.environ.update(customEnvironment)

    pyworkflow.Config.setDomain("pwem")
    domain = pyworkflow.Config.getDomain()

    # Force protocol registry loading so VariablesRegistry is complete
    domain.getProtocols()

    pwVars = pyworkflow.Config.getVars()

    # Load config-derived values first
    os.environ.update(pwVars)

    # Keep backend bootstrap values as priority
    os.environ.update(variables)

    # Explicit ScipionWeb environment variables have final priority.
    os.environ.update(customEnvironment)

    if scipionHome:
        os.chdir(scipionHome)
        os.environ.setdefault(
            "SCIPION_PROTOCOL_STEPS_NOTIFIER",
            "app.backend.api.services.protocol_steps_sync:syncProtocolStepsEvent",
        )
        os.environ.setdefault(
            "SCIPION_PROTOCOL_STEPS_LOADER",
            (
                "app.backend.api.services."
                "protocol_steps_sync:"
                "loadProtocolSteps"
            ),
        )
