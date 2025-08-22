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

#!/usr/bin/env python
# **************************************************************************
# *
# * Authors:    J. M. De la Rosa Trevin (delarosatrevin@scilifelab.se) [1]
# *             I. Foche Perez (ifoche@cnb.csic.es) [2]
# *             P. Conesa (pconesa@cnb.csic.es) [2]
# *
# *  [1] SciLifeLab, Stockholm University
# *  [2] Unidad de Bioinformatica of Centro Nacional de Biotecnologia, CSIC
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
# **************************************************************************
"""
Main entry point to scipion. It launches the gui, tests, etc.
"""
import subprocess
import os
from configparser import ConfigParser
import sys
from os.path import join, dirname, exists, isdir, expanduser, expandvars
from os import environ
import importlib

from scipion.constants import *
from scipion.scripts.config import getConfigPathFromConfigFile, HOSTS
from scipion import __version__

__nickname__ = "Eugenius"

# *********************  Helper functions *****************************

def getVersion(long=True):
    if long:
        return "v%s - %s" % (__version__, __nickname__)
    else:
        return __version__

def config2Dict(configFile, varDict):
    """ Loads a config file if exists and populates a dictionary
    overwriting the keys.
    """
    # If config file exists
    if exists(configFile):
        # read the file
        config = ConfigParser()
        config.optionxform = str  # keep case (stackoverflow.com/questions/1611799)
        config.read(configFile)

        # For each section
        for sectionName, section in config.items():
            for variable, value in section.items():
                # Expanding user and avoiding comments
                cleanValue = value.split('#')[0]

                # Give priority to environment variables
                varDict[variable] = os.environ.get(variable, default=expandvars(cleanValue).strip())

    return varDict


def envOn(varName):
    value = os.environ.get(varName, '').lower()
    return value in ['1', 'true', 'on', 'yes']


def getMode():
    """ :returns the mode scipion has to be launched """
    return MODE_MANAGER if len(sys.argv) == 1 else sys.argv[1]

# ***************** END FUNCTIONS *****************************************


def getScipionHome():
    home = environ.get("SCIPION_HOME", '/home/yunior/Yunior/Projects/ScipionWeb/scipion')

    if not home:
        sys.exit("SCIPION_HOME environment variable must be set")

    if not exists(home):
        sys.exit("SCIPION_HOME value (%s) does not exists." % home)

    if not isdir(home):
        sys.exit("SCIPION_HOME value (%s) is not a folder." % home)

    return home

def getScipionAppPath():
    return dirname(__file__)


def getInstallPath():
    return join(getScipionAppPath(), 'install')


def getScriptsPath():
    return join(getScipionAppPath(), 'scripts')


def getTemplatesPath():
    return join(getScipionAppPath(), 'templates')


def getExternalJsonTemplates():
    import pyworkflow
    return dirname(pyworkflow.Config.SCIPION_CONFIG)


def getModuleFolder(moduleName):
    """ Returns the path of a module without importing it"""
    spec = importlib.util.find_spec(moduleName)
    return dirname(spec.origin)


def prepareEnvironment():
    # Get Scipion home
    scipionHome = getScipionHome()

    # ***************** CONFIGURATION  FILES RESOLUTION ************************
    # Default values for configuration files.
    scipionConfig = join(scipionHome, 'config', 'scipion.conf')
    scipionLocalConfig = expanduser(os.environ.get('SCIPION_LOCAL_CONFIG',
                                                   '~/.config/scipion/scipion.conf'))
    hosts = getConfigPathFromConfigFile(scipionConfig, HOSTS)
    if not exists(hosts):
        hosts = join(getTemplatesPath(), "hosts.template")

    # *********************** STORE VARIABLES ********************
    class Vars:
        """ Class to hold all the variables that are initialized here"""
        SCIPION_DOMAIN = "pwem"

        # Installation paths
        SCIPION_HOME = scipionHome

        # Scipion path to its own scripts
        SCIPION_SCRIPTS = getScriptsPath()
        # Scipion path to install
        SCIPION_INSTALL = getInstallPath()

        # Config files
        SCIPION_CONFIG = scipionConfig
        SCIPION_LOCAL_CONFIG = scipionLocalConfig
        SCIPION_HOSTS = os.environ.get('SCIPION_HOSTS', hosts)

        # Paths to apps or scripts
        PW_APPS = join(getModuleFolder("pyworkflow"), 'apps')
        SCIPION_TEMPLATES = getTemplatesPath()

        SCIPION_VERSION = getVersion()
        SCIPION_PYTHON = PYTHON
        SCIPION_TESTS_CMD = os.environ.get("SCIPION_TESTS_CMD", '%s %s' % (SCIPION_EP, MODE_TESTS))
        CONDA_ACTIVATION_CMD = os.environ.get('CONDA_ACTIVATION_CMD', 'eval "$(/home/yunior/miniconda3/bin/conda shell.bash hook)" ')

        # Priority package list
        SCIPION_PRIORITY_PACKAGE_LIST = "pwem tomo pwchem"

    # *********************** READ CONFIG FILES ***********************
    try:
        VARS = dict()

        # Load variables from Vars class into VARS dict

        if 'SCIPION_NOGUI' in os.environ:
            # This cannot work since pyworkflow is not imported and can not be imported here
            # Due to a wrong/early initialisation of the config
            # PYTHONPATH_LIST.insert(0, join(pyworkflow.Config.getPyworkflowPath(), 'gui', 'no-tkinter'))
            print("SCIPION_NOGUI variable not implemented for this version. Please contact us if you need this.")

        # Load VARS dictionary, all items here will go to the environment
        VARS['SCIPION_DOMAIN'] = Vars.SCIPION_DOMAIN
        VARS['SCIPION_CONFIG'] = Vars.SCIPION_CONFIG
        VARS['SCIPION_LOCAL_CONFIG'] = Vars.SCIPION_LOCAL_CONFIG
        VARS['SCIPION_HOSTS'] = Vars.SCIPION_HOSTS
        VARS['SCIPION_PRIORITY_PACKAGE_LIST'] = Vars.SCIPION_PRIORITY_PACKAGE_LIST
        VARS['CONDA_ACTIVATION_CMD'] = Vars.CONDA_ACTIVATION_CMD

        # Read main config file
        config2Dict(Vars.SCIPION_CONFIG, VARS)

        # Load the local config
        if Vars.SCIPION_LOCAL_CONFIG != Vars.SCIPION_CONFIG:
            config2Dict(Vars.SCIPION_LOCAL_CONFIG, VARS)

    except Exception as e:
        if len(sys.argv) == 1 or sys.argv[1] != MODE_CONFIG:
            print('Error reading config: %s\n' % e)
            print('Please check the configuration file %s and '
                  'try again.\n' % Vars.SCIPION_CONFIG)
            sys.exit(1)
    # Prepare the environment

    os.environ.update(VARS)
    # Trigger Config initialization once environment is ready
    import pyworkflow
    pwVARS = pyworkflow.Config.getVars()
    VARS.update(pwVARS)
    # Update the environment now with pyworkflow values.
    os.environ.update(VARS)
    os.chdir(scipionHome)
    # Check mode
