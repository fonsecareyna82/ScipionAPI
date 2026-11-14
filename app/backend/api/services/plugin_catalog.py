"""The plugin catalog the Plugins page shows, quick and never empty even when Scipion's servers do not answer.

Scipion's own PluginRepository asks its catalog server without a time limit and then PyPI once per plugin, one after
the other: half a minute when everything works, more than two minutes and an empty list when the catalog server does
not answer. Here:
- the catalog server and PyPI are asked with time limits, and PyPI for all plugins at once;
- the last catalog read well is kept on disk, and a copy ships with ScipionWeb for new installations;
- without any of them, the plugins listed in resources/plugin_categories.py and those installed are shown.
The catalog only gives each plugin's name, logo and source address: the rest (versions, author, summary) comes from
PyPI, so a saved or local catalog loses little. getPlugins() gives the same PluginInfo objects Scipion gives.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

CONNECT_SECONDS = 5.0
READ_SECONDS = 20.0
PYPI_URL = "https://pypi.org/pypi/%s/json"
PYPI_WORKERS = 16
RETRY_SECONDS = 600.0  # a catalog that is not the live one is asked again after this
SHIPPED_CATALOG = Path(__file__).resolve().parents[2] / "resources" / "plugin_catalog.json"

LIVE, SAVED, SHIPPED, LOCAL = "live", "saved", "shipped", "local"
CORE_PACKAGES = {"scipion-em", "scipion-pyworkflow", "scipion-app"}  # Scipion itself, not plugins

_lock = threading.Lock()
_status: Dict[str, Any] = {"source": None, "savedAt": None, "loadedAt": 0.0}


def status() -> Dict[str, Any]:
    """Where the catalog shown comes from: live, saved (the last one read well), shipped or local; and its date."""
    with _lock:
        return {"source": _status["source"], "savedAt": _status["savedAt"]}


def shouldRetry(now: Optional[float] = None) -> bool:
    """True when the catalog shown is not the live one and it is time to ask the server again."""
    with _lock:
        if _status["source"] in (None, LIVE):
            return False
        return (now or time.time()) - _status["loadedAt"] >= RETRY_SECONDS


def _setStatus(source: str, savedAt: Optional[str]) -> None:
    with _lock:
        _status.update(source=source, savedAt=savedAt, loadedAt=time.time())


def savedCatalogPath() -> Optional[Path]:
    home = os.environ.get("SCIPION_HOME")
    if not home:
        try:
            from pyworkflow import Config

            home = getattr(Config, "SCIPION_HOME", None)
        except Exception:
            home = None
    return Path(home) / "cache" / "plugin_catalog.json" if home else None


def repositoryUrl() -> str:
    try:
        from scipion.install.plugin_funcs import REPOSITORY_URL

        return str(REPOSITORY_URL or "https://scipion.i2pc.es/getplugins/")
    except Exception:
        return "https://scipion.i2pc.es/getplugins/"


# Reading -----------------------------------------------------------------------------------------------------

def fetchJson(url: str) -> Any:
    import requests

    response = requests.get(url, timeout=(CONNECT_SECONDS, READ_SECONDS))
    response.raise_for_status()
    return response.json()


def trimPypi(data: Dict[str, Any]) -> Dict[str, Any]:
    """Only what PluginInfo reads from a PyPI answer, so the saved copy stays small; releases without files out."""
    info = data.get("info") or {}
    releases = {}
    for version, files in (data.get("releases") or {}).items():
        if files:
            first = files[0] or {}
            releases[version] = [{"comment_text": first.get("comment_text") or "",
                                  "upload_time": first.get("upload_time") or ""}]
    return {"info": {key: info.get(key) for key in ("home_page", "project_urls", "summary", "author", "author_email")},
            "releases": releases}


def fetchPypi(pipNames, fetch: Callable[[str], Any] = fetchJson) -> Dict[str, Optional[Dict[str, Any]]]:
    """{pipName: trimmed PyPI data, or None when PyPI did not answer for it}, all asked at once. When PyPI does not
    answer for the first one, the others are not asked."""
    names = list(dict.fromkeys(pipNames))
    if not names:
        return {}

    def one(name):
        try:
            return name, trimPypi(fetch(PYPI_URL % name))
        except Exception:
            return name, None

    first = one(names[0])
    if first[1] is None:
        try:  # One that surely exists: is PyPI there at all?
            fetch(PYPI_URL % "pip")
        except Exception:
            logger.info("PyPI does not answer: plugin versions are taken from the saved catalog")
            return {name: None for name in names}
    with ThreadPoolExecutor(max_workers=PYPI_WORKERS) as pool:
        found = dict(pool.map(one, names[1:]))
    found[first[0]] = first[1]
    return found


def readSaved(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    try:
        if path and path.is_file():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved.get("catalog"), dict) and saved["catalog"]:
                return saved
    except Exception:
        logger.warning("The saved plugin catalog %s could not be read", path, exc_info=True)
    return None


def writeSaved(path: Optional[Path], catalog: Dict[str, Any], pypi: Dict[str, Any]) -> None:
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"savedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "catalog": catalog,
                   "pypi": pypi}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(path)
    except Exception:
        logger.warning("The plugin catalog could not be saved in %s", path, exc_info=True)


def localCatalog() -> Dict[str, Dict[str, Any]]:
    """The plugins ScipionWeb knows (resources/plugin_categories.py) and those installed, without the catalog."""
    from app.backend.api.services.plugin_packages import installedModulePackages
    from app.backend.resources.plugin_categories import plugins as knownPlugins

    entries = {name: {"pipName": name, "name": name.replace("scipion-em-", "")} for name in knownPlugins}
    try:
        from pwem import Domain

        modules = set(Domain.getPlugins().keys())
    except Exception:
        modules = set()
    for module, package in installedModulePackages(refresh=True).items():
        if module in modules and package not in CORE_PACKAGES:
            entries.setdefault(package, {"pipName": package, "name": module})
    return entries


# Building ----------------------------------------------------------------------------------------------------

def pluginInfo(entry: Dict[str, Any], pypi: Optional[Dict[str, Any]]):
    """A PluginInfo like Scipion's, from a catalog entry and its PyPI data (None for an uninstallable one)."""
    from scipion.install.plugin_funcs import NULL_VERSION, PluginInfo

    entry = {key: value for key, value in entry.items() if key != "remote"}
    info = PluginInfo(**entry, remote=False)
    info.remote = True
    if pypi:
        info.homePage = info.getPipData(pypi["info"], ["home_page", "project_urls.Homepage"])
        info.summary = info.getPipData(pypi["info"], ["summary"])
        info.author = info.getPipData(pypi["info"], ["author", "author_email"])
        info.email = info.getPipData(pypi["info"], ["author_email"])
        info.compatibleReleases = info.getCompatiblePipReleases(pipJsonData=pypi)
        info.latestRelease = info.compatibleReleases["latest"]
        if info.latestRelease == NULL_VERSION:
            return None  # As Scipion: no release for this Scipion
    else:
        # Versions unknown: an installed plugin still shows with what it says of itself
        info.compatibleReleases, info.latestRelease = {}, ""
    info.setLocalPluginInfo()
    return info


class PluginCatalog:
    """Answers like Scipion's PluginRepository.getPlugins(), with the catalog of this module."""

    def __init__(self, fetch: Callable[[str], Any] = fetchJson, path: Optional[Path] = None,
                 shipped: Path = SHIPPED_CATALOG, local: Callable[[], Dict[str, Dict[str, Any]]] = localCatalog):
        self.fetch = fetch
        self.path = path if path is not None else savedCatalogPath()
        self.shipped = shipped
        self.local = local

    def getPlugins(self, pluginList=None, getPipData=True) -> Dict[str, Any]:
        started = time.time()
        saved, savedSource = readSaved(self.path), SAVED
        if saved is None:
            saved, savedSource = readSaved(self.shipped), SHIPPED
        source, savedAt = LIVE, None
        try:
            catalog = self.fetch(repositoryUrl())
            if not isinstance(catalog, dict) or not catalog:
                raise ValueError("empty plugin catalog")
        except Exception as error:
            logger.warning("Scipion's plugin catalog server does not answer (%s)", error)
            if saved is not None:
                catalog, source, savedAt = saved["catalog"], savedSource, saved.get("savedAt")
            else:
                catalog, source = self.local(), LOCAL
        if pluginList is not None:
            catalog = {name: entry for name, entry in catalog.items() if name in set(pluginList)}

        pypi = fetchPypi(catalog.keys(), self.fetch)
        savedPypi = (saved or {}).get("pypi") or {}
        for name, data in pypi.items():
            if data is None and savedPypi.get(name):
                pypi[name] = savedPypi[name]
        if source == LIVE and pluginList is None:
            writeSaved(self.path, catalog, {name: data for name, data in pypi.items() if data})

        plugins = {}
        for name, entry in catalog.items():
            try:
                info = pluginInfo(dict(entry, pipName=entry.get("pipName") or name), pypi.get(name))
            except Exception:
                logger.warning("Plugin %s of the catalog could not be read", name, exc_info=True)
                continue
            if info is not None:
                plugins[name] = info
        _setStatus(source, savedAt)
        logger.info("Plugin catalog read (%s, %d plugins) in %.1f s", source, len(plugins), time.time() - started)
        return plugins
