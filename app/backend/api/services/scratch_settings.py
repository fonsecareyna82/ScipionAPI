"""A fast local disk (an SSD) for the protocols' temporary files: Scipion's scratch, per machine.

Scipion reads SCIPION_SCRATCH: when set, each protocol's tmp/ folder is made there (a link in the project points
to it), and Relion's "Copy particles to scratch directory" (its "Scipion's scratch" choice) copies the particles
there. It is a machine's own local disk, so each machine says its own: a single-machine installation and the
main node in the shared .env, a compute node in its profile (scipion_home/nodes/<node>.env), read over the .env.
Unset (the default), everything stays in the project. A protocol worker reads it when it starts: changing it
needs that machine's protocol worker restarted.

Each worker tells how its scratch is (``scratchStatus``) in its node report: whether the folder exists there, can
be written, and the disk's free space; only that machine can see its local disk.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

SCRATCH_KEY = "SCIPION_SCRATCH"


def scratchStatus(path: Optional[str] = None) -> Dict[str, Any]:
    """This machine's scratch as its protocols will see it (run where the protocols run)."""
    path = (path if path is not None else os.environ.get(SCRATCH_KEY) or "").strip()
    if not path:
        return {"path": None}
    folder = Path(path)
    answer: Dict[str, Any] = {"path": path, "exists": folder.is_dir(), "writable": False,
                              "totalBytes": None, "freeBytes": None, "error": None}
    if not answer["exists"]:
        answer["error"] = "The folder does not exist on this machine"
        return answer
    answer["writable"] = os.access(str(folder), os.W_OK | os.X_OK)
    if not answer["writable"]:
        answer["error"] = "The protocols cannot write in it"
    try:
        usage = shutil.disk_usage(str(folder))
        answer["totalBytes"], answer["freeBytes"] = int(usage.total), int(usage.free)
    except OSError as error:
        answer["error"] = str(error)
    return answer


def _scipionHome() -> Path:
    return Path(__file__).resolve().parents[4] / "scipion_home"


def envFileOf(hostname: str, scipionHome: Optional[Path] = None) -> Path:
    """Where a machine's own settings live: its node profile when it is a compute node, else the shared .env."""
    from scipionapi_cli import nodes

    home = scipionHome or _scipionHome()
    profile = nodes.profilePath(home, nodes.nodeName(hostname))
    return profile if profile.is_file() else home / ".env"


def setScratch(hostname: str, path: Optional[str], scipionHome: Optional[Path] = None) -> Dict[str, Any]:
    """Set (or unset, with an empty path) a machine's scratch; answers where it was written."""
    from scipionapi_cli.envfile import removeEnvKeys, writeEnvFile

    value = str(path or "").strip()
    if value and not os.path.isabs(value):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="The scratch is an absolute path, e.g. /scratch or /ssd/scipion")
    if value and value.rstrip("/") in ("", "/home", "/tmp", "/usr", "/etc", "/var"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="The scratch is a folder of its own on a fast local disk, not %s" % value)
    target = envFileOf(hostname, scipionHome)
    if value:
        writeEnvFile(target, {SCRATCH_KEY: value})
    else:
        # Unset, never empty: Scipion would take an empty one for a folder
        removeEnvKeys(target, [SCRATCH_KEY])
    return {"hostname": hostname, "path": value or None, "file": target.name,
            "node": target.parent.name == "nodes", "restartNeeded": True}
