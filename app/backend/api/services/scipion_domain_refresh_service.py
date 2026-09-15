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
import importlib
import logging
import os
import threading
from typing import Set

from pyworkflow import VariablesRegistry
from pyworkflow.config import Config

from app.backend.api.services.plugins_revision import getPluginsRevision
from app.backend.api.services.environment_revision import getEnvironmentRevision
from app.backend.api.services.json_subprocess_runner import JsonSubprocessRunner
from app.backend.api.services.environment import removeCustomEnvironmentVariables


logger = logging.getLogger(__name__)

_domainRefreshLock = threading.Lock()


def _readPluginsRevision() -> int:
    try:
        return int(getPluginsRevision() or 0)
    except Exception:
        return 0


def _readEnvironmentRevision() -> int:
    try:
        return int(
            getEnvironmentRevision()
            or 0
        )
    except Exception:
        return 0


_lastDomainRevision = _readPluginsRevision()
_lastEnvironmentRevision = _readEnvironmentRevision()


def _resetScipionDomainCaches(domain) -> None:
    domain._pluginsLoaded = False
    domain._plugins = {}
    domain._protocols = {}
    domain._objects = {}
    domain._viewers = {}
    domain._wizards = {}
    domain._preferred_viewers = None
    setattr(domain, "_Domain__mapperDict", None)


def _removePluginEnvironmentVariables(
        pluginNames: Set[str],
) -> Set[str]:
    cleanPluginNames = {
        str(pluginName).strip()
        for pluginName
        in pluginNames
        if str(pluginName).strip()
    }

    if not cleanPluginNames:
        return set()

    registry = (
        VariablesRegistry.variables()
    )

    variableNames = {
        str(variableName)
        for variableName, variable
        in list(
            registry.items()
        )
        if (
            str(
                getattr(
                    variable,
                    "source",
                    "",
                )
                or ""
            ).strip()
            in cleanPluginNames
        )
    }

    if not variableNames:
        return set()

    for variableName in variableNames:
        registry.pop(
            variableName,
            None,
        )

    scipionHome = str(
        getattr(
            Config,
            "SCIPION_HOME",
            "",
        )
        or os.environ.get(
            "SCIPION_HOME",
            "",
        )
        or ""
    ).strip()

    removedOverrides = (
        removeCustomEnvironmentVariables(
            scipionHome,
            variableNames,
        )
    )

    logger.info(
        "Removed environment variables for "
        "uninstalled Scipion plugins. "
        "plugins=%s variables=%s overrides=%s",
        sorted(
            cleanPluginNames
        ),
        sorted(
            variableNames
        ),
        sorted(
            removedOverrides
        ),
    )

    return variableNames


def _getCleanScipionPluginNames() -> Set[str]:
    code = """
    import contextlib
    import sys

    with contextlib.redirect_stdout(sys.stderr):
        from pyworkflow.config import Config

        Config.setDomain("pwem")
        domain = Config.getDomain()

        _scipionPayload = sorted((domain.getPlugins() or {}).keys())
    """

    pluginNames = JsonSubprocessRunner().run(
        code=code,
        operationName="Inspect clean Scipion plugins",
    )

    return {
        str(pluginName).strip()
        for pluginName in pluginNames or []
        if str(pluginName).strip()
    }


def _refreshScipionDomainLocked(
    force: bool = False,
) -> bool:
    global _lastDomainRevision
    global _lastEnvironmentRevision

    pluginsRevision = (
        _readPluginsRevision()
    )

    environmentRevision = (
        _readEnvironmentRevision()
    )

    if (
        not force
        and pluginsRevision
        == _lastDomainRevision
        and environmentRevision
        == _lastEnvironmentRevision
    ):
        return False

    importlib.invalidate_caches()

    Config.setDomain("pwem")
    domain = Config.getDomain()

    previousPluginNames = set(
        (
                getattr(
                    domain,
                    "_plugins",
                    {},
                )
                or {}
        ).keys()
    )

    _resetScipionDomainCaches(
        domain
    )

    currentPlugins = (
        domain.getPlugins()
    )

    cleanPluginNames = (
        _getCleanScipionPluginNames()
    )

    missingPluginNames = sorted(
        cleanPluginNames
        - set(currentPlugins)
    )

    if missingPluginNames:
        logger.info(
            "Registering new Scipion plugins in runtime domain: %s",
            missingPluginNames,
        )

        for pluginName in missingPluginNames:
            domain.registerPlugin(
                pluginName
            )

        currentPlugins = (
            domain.getPlugins()
        )

    stalePluginNames = sorted(
        (
                previousPluginNames
                | set(currentPlugins)
        )
        - cleanPluginNames
    )

    if stalePluginNames:
        logger.warning(
            "Removing stale Scipion plugins from runtime domain: %s",
            stalePluginNames,
        )

        _removePluginEnvironmentVariables(
            set(
                stalePluginNames
            )
        )

    domain._plugins = {
        pluginName: pluginModule
        for pluginName, pluginModule
        in currentPlugins.items()
        if pluginName
        in cleanPluginNames
    }

    domain._protocols = {}
    setattr(
        domain,
        "_Domain__mapperDict",
        None,
    )

    domain.getProtocols()

    _lastDomainRevision = (
        pluginsRevision
    )

    _lastEnvironmentRevision = (
        environmentRevision
    )

    logger.info(
        "Refreshed Scipion domain. "
        "pluginsRevision=%s "
        "environmentRevision=%s "
        "protocols=%s",
        pluginsRevision,
        environmentRevision,
        len(domain._protocols),
    )

    return True


def refreshScipionDomain(force: bool = False) -> bool:
    with _domainRefreshLock:
        return _refreshScipionDomainLocked(force=force)


def refreshScipionDomainIfNeeded() -> bool:
    return refreshScipionDomain(force=False)


def getScipionProtocolsSnapshot() -> dict:
    with _domainRefreshLock:
        _refreshScipionDomainLocked(force=False)
        domain = Config.getDomain()
        return dict(domain.getProtocols())
