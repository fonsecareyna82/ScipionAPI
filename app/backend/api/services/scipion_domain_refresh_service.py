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
    domain._plugins = {}
    domain._protocols = {}
    domain._objects = {}
    domain._viewers = {}
    domain._wizards = {}
    domain._pluginsLoaded = False
    domain._preferred_viewers = None

    setattr(
        domain,
        "_Domain__mapperDict",
        None,
    )


def refreshScipionDomain(force: bool = False) -> bool:
    global _lastDomainRevision

    revision = _readPluginsRevision()

    with _domainRefreshLock:
        if not force and revision == _lastDomainRevision:
            return False

        importlib.invalidate_caches()

        Config.setDomain("pwem")
        domain = Config.getDomain()

        _resetScipionDomainCaches(
            domain
        )

        # Discover plugin entry-points immediately. Protocols, objects,
        # viewers and wizards remain lazy and will rebuild on first use.
        domain.getPlugins()

        _lastDomainRevision = revision

        logger.info(
            "Refreshed Scipion domain after plugin change. pluginsRevision=%s",
            revision,
        )

        return True


def refreshScipionDomainIfNeeded() -> bool:
    return refreshScipionDomain(
        force=False
    )
