"""Refreshes app/backend/resources/plugin_catalog.json, the copy of Scipion's plugin catalog (with each plugin's PyPI
versions) that a new installation shows when Scipion's catalog server does not answer (see plugin_catalog.py).

Run from ScipionAPI when the server answers, and commit the file:
    SCIPION_HOME=$PWD/scipion_home PYTHONPATH=$PWD python scripts/update_plugin_catalog.py
"""
import json
import sys
from datetime import datetime, timezone

from app.backend.api.services import plugin_catalog


def main() -> int:
    try:
        catalog = plugin_catalog.fetchJson(plugin_catalog.repositoryUrl())
    except Exception as error:
        print("Scipion's plugin catalog server does not answer: %s" % error)
        return 1
    pypi = plugin_catalog.fetchPypi(catalog.keys())
    payload = {"savedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "catalog": catalog,
               "pypi": {name: data for name, data in pypi.items() if data}}
    plugin_catalog.SHIPPED_CATALOG.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("%d plugins (%d with PyPI data) written to %s" % (len(catalog), len(payload["pypi"]),
                                                           plugin_catalog.SHIPPED_CATALOG))
    return 0


if __name__ == "__main__":
    sys.exit(main())
