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
import fcntl
from pathlib import Path

_revisionFileName = ".plugins_revision"
_lockFileName = ".plugins_revision.lock"


def _getRevisionDir() -> Path:
    # getRevisionDir
    scipionHome = os.environ.get("SCIPION_HOME")
    if not scipionHome:
        raise RuntimeError("SCIPION_HOME must be set to use pluginsRevision")
    return Path(scipionHome)


def getPluginsRevision() -> int:
    # getPluginsRevision
    path = _getRevisionDir() / _revisionFileName
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw or "0")
    except FileNotFoundError:
        return 0
    except Exception:
        return 0


def bumpPluginsRevision() -> int:
    # bumpPluginsRevision
    baseDir = _getRevisionDir()
    lockPath = baseDir / _lockFileName
    revPath = baseDir / _revisionFileName

    baseDir.mkdir(parents=True, exist_ok=True)

    with open(lockPath, "a+", encoding="utf-8") as lockFp:
        fcntl.flock(lockFp.fileno(), fcntl.LOCK_EX)

        cur = getPluginsRevision()
        nxt = cur + 1

        tmpPath = baseDir / f"{_revisionFileName}.tmp"
        tmpPath.write_text(str(nxt), encoding="utf-8")
        os.replace(str(tmpPath), str(revPath))

        fcntl.flock(lockFp.fileno(), fcntl.LOCK_UN)

    return nxt