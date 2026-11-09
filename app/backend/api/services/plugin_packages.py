"""Which pip package installs a plugin known by its Python module (a workflow names the modules it needs).

A plugin's package is not always scipion-em-<module>: xmipp3 is scipion-em-xmipp, prody2 scipion-em-prody, pwchem
scipion-chem. In order, a module's package is:
1. the one a workflow exported by ScipionWeb says (it writes "module=package", known when it was exported);
2. the one installed here that brings the module;
3. the first of the usual names (the known exceptions, scipion-em-<module>, scipion-chem-<module>, the module
   without its trailing digits, a catalog entry shown with that name) that Scipion's plugin catalog lists.
None when nothing says it: better to tell the user than to install a package that does not exist. Without the
catalog (no network), the usual name is answered unchecked.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

KNOWN_PACKAGES = {"xmipp3": "scipion-em-xmipp", "emfacilities": "scipion-em-facilities", "pwchem": "scipion-chem",
                  "prody2": "scipion-em-prody"}
CATALOG_SECONDS = 3600.0
CATALOG_RETRY_SECONDS = 300.0
CATALOG_TIMEOUT_SECONDS = 5.0

_lock = threading.Lock()
_catalog: Optional[Tuple[set, Dict[str, str]]] = None
_catalogAt = 0.0
_installed: Optional[Dict[str, str]] = None


def installedModulePackages(refresh: bool = False) -> Dict[str, str]:
    """{module: package} of the Scipion plugins installed in this environment."""
    global _installed
    if _installed is not None and not refresh:
        return _installed
    try:
        from importlib import metadata
    except ImportError:  # pragma: no cover
        import importlib_metadata as metadata
    found: Dict[str, str] = {}
    for distribution in metadata.distributions():
        name = str(distribution.metadata.get("Name") or "")
        if not name.lower().startswith("scipion"):
            continue
        for module in (distribution.read_text("top_level.txt") or "").split():
            found.setdefault(module, name)
    _installed = found
    return found


def _repositoryUrl() -> Optional[str]:
    try:
        from scipion.install.plugin_funcs import REPOSITORY_URL

        return REPOSITORY_URL
    except Exception:
        return "https://scipion.i2pc.es/getplugins/"


def catalog(fetch=None) -> Optional[Tuple[set, Dict[str, str]]]:
    """Scipion's plugin catalog: its package names and {shown name, lower case: package}; None when it cannot be
    read (kept an hour; a failure is tried again after five minutes)."""
    global _catalog, _catalogAt
    with _lock:
        now = time.time()
        if now - _catalogAt < (CATALOG_SECONDS if _catalog is not None else CATALOG_RETRY_SECONDS) and _catalogAt:
            return _catalog
        _catalogAt = now
    try:
        if fetch is None:
            import requests

            response = requests.get(_repositoryUrl(), timeout=CATALOG_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
        else:
            data = fetch()
        packages = {str(key) for key in data}
        shown = {str(entry.get("name") or "").strip().lower(): str(entry.get("pipName") or key)
                 for key, entry in data.items() if isinstance(entry, dict)}
        result = (packages, shown)
    except Exception:
        logger.info("Scipion's plugin catalog could not be read: plugin packages are guessed unchecked", exc_info=True)
        result = None
    with _lock:
        _catalog = result
    return result


def candidates(module: str) -> List[str]:
    module = str(module or "").strip()
    names = [KNOWN_PACKAGES.get(module), "scipion-em-%s" % module, "scipion-chem-%s" % module]
    base = re.sub(r"\d+$", "", module)
    if base and base != module:
        names.append("scipion-em-%s" % base)
    return [name for name in dict.fromkeys(names) if name]


def packageForModule(module: str, declared: Optional[Dict[str, str]] = None, fetch=None) -> Optional[str]:
    """The pip package that installs a plugin's module, or None when nothing says it."""
    module = str(module or "").strip()
    if not module:
        return None
    if declared and declared.get(module):
        return declared[module]
    installed = installedModulePackages()
    if module in installed:
        return installed[module]
    known = catalog(fetch)
    if known is None:
        return candidates(module)[0]
    packages, shown = known
    for name in candidates(module):
        if name in packages:
            return name
    return shown.get(module.lower())


def resetCaches() -> None:
    """For tests."""
    global _catalog, _catalogAt, _installed
    with _lock:
        _catalog, _catalogAt, _installed = None, 0.0, None
