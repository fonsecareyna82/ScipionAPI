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
import threading
from typing import Set

from pyworkflow.config import Config

from app.backend.api.services.plugins_revision import getPluginsRevision
from app.backend.api.services.json_subprocess_runner import JsonSubprocessRunner


logger = logging.getLogger(__name__)

_domainRefreshLock = threading.Lock()


def _readPluginsRevision() -> int:
    try:
        return int(getPluginsRevision() or 0)
    except Exception:
        return 0


_lastDomainRevision = _readPluginsRevision()


def _resetScipionDomainCaches(domain) -> None:
    domain._pluginsLoaded = False
    domain._plugins = {}
    domain._protocols = {}
    domain._objects = {}
    domain._viewers = {}
    domain._wizards = {}
    domain._preferred_viewers = None
    setattr(domain, "_Domain__mapperDict", None)


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


def _refreshScipionDomainLocked(force: bool = False) -> bool:
    global _lastDomainRevision

    revision = _readPluginsRevision()

    if not force and revision == _lastDomainRevision:
        return False

    importlib.invalidate_caches()
    Config.setDomain("pwem")
    domain = Config.getDomain()

    _resetScipionDomainCaches(domain)

    currentPlugins = domain.getPlugins()
    cleanPluginNames = _getCleanScipionPluginNames()

    stalePluginNames = sorted(set(currentPlugins) - cleanPluginNames)

    if stalePluginNames:
        logger.warning(
            "Removing stale Scipion plugins from runtime domain: %s",
            stalePluginNames,
        )

    domain._plugins = {
        pluginName: pluginModule
        for pluginName, pluginModule in currentPlugins.items()
        if pluginName in cleanPluginNames
    }

    domain._protocols = {}
    setattr(domain, "_Domain__mapperDict", None)

    domain.getProtocols()

    _lastDomainRevision = revision

    logger.info("Refreshed Scipion domain after plugin change. pluginsRevision=%s protocols=%s", revision, len(domain._protocols))

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
