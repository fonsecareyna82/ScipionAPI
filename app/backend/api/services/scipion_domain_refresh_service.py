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

from pyworkflow.config import Config

from app.backend.api.services.plugins_revision import getPluginsRevision


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
    # CapabilityProvider registry (pyworkflow.plugin.Domain, see
    # scipion-pyworkflow's .ai/capability-providers.md) -- e.g. pwem's
    # ProtImportParticles 'importFrom' choices. Was missing here: every
    # other Domain cache above gets reset on plugin install/uninstall via
    # the plugins_revision file check, but this one didn't, so a newly
    # (un)installed plugin's capability provider (cryoSPARC's import
    # provider, for example) kept showing stale until the whole process
    # was restarted.
    domain._capabilityProviders = {}
    domain._capabilityProvidersLoaded = False
    setattr(domain, "_Domain__mapperDict", None)


def _refreshScipionDomainLocked(force: bool = False) -> bool:
    global _lastDomainRevision

    revision = _readPluginsRevision()

    if not force and revision == _lastDomainRevision:
        return False

    importlib.invalidate_caches()
    Config.setDomain("pwem")
    domain = Config.getDomain()

    _resetScipionDomainCaches(domain)

    domain.getPlugins()
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
