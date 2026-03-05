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
import time
from pathlib import Path


def _getRepoRoot() -> Path:
    # getRepoRoot
    return Path(__file__).resolve().parents[4]


def _resolvePath(rawPath: str, baseDir: Path) -> Path:
    # resolvePath
    p = Path(rawPath)
    return p if p.is_absolute() else (baseDir / p).resolve()


def triggerBackendReloadIfEnabled() -> None:
    # triggerBackendReloadIfEnabled
    enabled = os.environ.get("AUTO_RELOAD_ON_PLUGIN_CHANGE", "0").strip() == "1"
    if not enabled:
        return

    mode = os.environ.get("BACKEND_RELOAD_MODE", "dev").strip().lower()

    # dev: write inside repo so uvicorn --reload sees it
    # prod: write inside SCIPION_HOME so systemd/k8s can watch it
    if mode == "prod":
        scipionHome = os.environ.get("SCIPION_HOME", "").strip()
        if not scipionHome:
            return
        baseDir = Path(scipionHome)
        defaultRel = ".backend_reload_marker"
    else:
        baseDir = _getRepoRoot()
        defaultRel = "app/backend/_reload_marker.py"

    raw = os.environ.get("BACKEND_RELOAD_TOUCH_PATH", "").strip() or defaultRel
    touchPath = _resolvePath(raw, baseDir)

    try:
        touchPath.parent.mkdir(parents=True, exist_ok=True)
        touchPath.write_text(f"reloadMarker={time.time()}\n", encoding="utf-8")
    except Exception:
        # bestEffortOnly
        pass