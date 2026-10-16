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
import site
import sys
import threading
from typing import Dict, Iterable, List, Set

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


class PathFileTracker:
    """The .pth files of some site directories, as the interpreter processed them when it started.

    A plugin installed in develop mode (pip install -e) while this process runs is importable only through the .pth
    file the install writes, and the interpreter reads .pth files only at startup. activateNewPathFiles processes
    the files written or changed since, so the plugin can be imported without restarting the process. The import
    lines of a new file run once (they install import finders); those of a changed file already ran at startup, so
    only its new paths are added.
    """

    def __init__(self, siteDirs: Iterable[str]):
        self.siteDirs = [str(siteDir) for siteDir in siteDirs if siteDir]
        self.seen = self._scan()

    def _scan(self) -> Dict[str, float]:
        pathFiles = {}
        for siteDir in self.siteDirs:
            try:
                names = os.listdir(siteDir)
            except OSError:
                continue
            for name in names:
                if name.endswith(".pth"):
                    pathFile = os.path.join(siteDir, name)
                    try:
                        pathFiles[pathFile] = os.path.getmtime(pathFile)
                    except OSError:
                        continue
        return pathFiles

    def activateNewPathFiles(self) -> List[str]:
        """Process the .pth files written or changed since the last time. Returns those processed."""
        current = self._scan()
        processed = []
        for pathFile, mtime in sorted(current.items()):
            isNew = pathFile not in self.seen
            if isNew or mtime != self.seen[pathFile]:
                try:
                    self._process(pathFile, runImports=isNew)
                    processed.append(pathFile)
                except Exception as e:
                    logger.warning("Could not process %s: %s", pathFile, e)
        self.seen = current
        if processed:
            importlib.invalidate_caches()
            logger.info("Processed .pth files written while running: %s", processed)
        return processed

    @staticmethod
    def _process(pathFile: str, runImports: bool) -> None:
        siteDir = os.path.dirname(pathFile)
        with open(pathFile, encoding="utf-8") as f:
            lines = f.read().splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("import ", "import\t")):
                if runImports:
                    exec(line)  # As site.addpackage does for these lines
                continue
            path = os.path.abspath(os.path.join(siteDir, line))
            if os.path.exists(path) and path not in sys.path:
                sys.path.append(path)


def _getSiteDirs() -> List[str]:
    siteDirs = list(getattr(site, "getsitepackages", lambda: [])())
    userSite = getattr(site, "getusersitepackages", lambda: None)()
    if userSite:
        siteDirs.append(userSite)
    return siteDirs


# Taken when the process starts: the .pth files the interpreter already processed
_pathFiles = PathFileTracker(_getSiteDirs())

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
    # Plugins installed in develop mode since this process started are importable only from here on
    _pathFiles.activateNewPathFiles()

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
