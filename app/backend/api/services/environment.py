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
import os


def prepareEnvironment():
    """Prepare the Scipion environment with all variables"""
    from scipion.__main__ import Vars

    variables = Vars.init()
    os.environ.update(variables)

    import pyworkflow

    pyworkflow.Config.setDomain("pwem")
    domain = pyworkflow.Config.getDomain()

    # Force protocol registry loading so VariablesRegistry is complete
    domain.getProtocols()

    pwVars = pyworkflow.Config.getVars()

    # Load config-derived values first
    os.environ.update(pwVars)

    # Keep backend bootstrap values as priority
    os.environ.update(variables)

    scipionHome = variables.get(pyworkflow.SCIPION_HOME_VAR) or os.environ.get(pyworkflow.SCIPION_HOME_VAR)
    if scipionHome:
        os.chdir(scipionHome)
        os.environ.setdefault(
            "SCIPION_PROTOCOL_STEPS_NOTIFIER",
            "app.backend.api.services.protocol_steps_sync:syncProtocolStepsEvent",
        )
