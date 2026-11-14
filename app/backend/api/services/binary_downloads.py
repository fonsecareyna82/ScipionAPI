"""Binaries that are downloaded from Scipion's own server, checked before installing them.

A plugin's binary is installed with commands Scipion builds; some of them download a package from Scipion's server
with wget, which tries 20 times and can wait minutes each when the server does not answer. So, before installing:
- the binaries that still need a download from that server are found (with their dependencies);
- the server is asked once, with a short time limit;
- when it does not answer, the installation stops at once and says which binaries cannot be installed now.
Binaries installed with conda, pip or git only need void.tgz from that server, an empty package Scipion never
unpacks: it is made here when missing, so they install without the server.
"""
from __future__ import annotations

import io
import logging
import os
import tarfile
import threading
import time
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)

CHECK_SECONDS = 5.0
REMEMBER_SECONDS = 60.0
VOID_TGZ = "void.tgz"

_lock = threading.Lock()
_answered = {"at": 0.0, "value": None}


class DownloadServerDown(RuntimeError):
    """Scipion's download server does not answer, and some binaries need it."""


def downloadServer() -> str:
    try:
        from pyworkflow import Config

        return str(Config.SCIPION_URL_SOFTWARE)
    except Exception:
        return "https://scipion.cnb.csic.es/downloads/scipion/software"


def serverAnswers(url: Optional[str] = None, ask=None) -> bool:
    """Whether Scipion's download server answers (any HTTP answer counts); remembered for a minute."""
    with _lock:
        if _answered["value"] is not None and time.time() - _answered["at"] < REMEMBER_SECONDS:
            return bool(_answered["value"])
    try:
        if ask is None:
            import requests

            requests.head((url or downloadServer()).rstrip("/") + "/", timeout=(CHECK_SECONDS, CHECK_SECONDS),
                          allow_redirects=True)
        else:
            ask(url or downloadServer())
        answered = True
    except Exception:
        answered = False
    with _lock:
        _answered.update(at=time.time(), value=answered)
    return answered


def makeVoidTgz(folder: str) -> None:
    """The empty package conda/pip/git binaries are declared with, when it is not there yet."""
    path = os.path.join(folder, VOID_TGZ)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return
    try:
        os.makedirs(folder, exist_ok=True)
        with tarfile.open(path, "w:gz") as archive:
            folderEntry = tarfile.TarInfo("void")
            folderEntry.type = tarfile.DIRTYPE
            folderEntry.mode = 0o775
            archive.addfile(folderEntry)
            fileEntry = tarfile.TarInfo("void/void.txt")
            archive.addfile(fileEntry, io.BytesIO(b""))
    except Exception:
        logger.warning("Could not make %s", path, exc_info=True)


def pendingServerDownloads(environment, targetNames: Iterable[str], server: Optional[str] = None) -> List[str]:
    """The targets (and their dependencies) whose package still has to be downloaded from Scipion's server."""
    server = (server or downloadServer()).split("://", 1)[-1].split("/", 1)[0]
    pending: List[str] = []
    seen = set()
    stack = list(targetNames)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            target = environment.getTarget(name)
        except Exception:
            continue
        stack.extend(getattr(target, "getDeps", lambda: [])() or [])
        for command in getattr(target, "getCommands", lambda: [])() or []:
            line = str(getattr(command, "_cmd", "") or "")
            if "wget" not in line or server not in line:
                continue
            files = list(getattr(command, "_targets", []) or [])
            if files and os.path.basename(files[0]) == VOID_TGZ:
                makeVoidTgz(os.path.dirname(files[0]))  # Where the download would leave it
            if files and all(os.path.exists(path) for path in files):
                continue  # Downloaded before
            pending.append(name)
            break
    return sorted(set(pending))


def defaultTargets(environment) -> List[str]:
    return [target.getName() for target in environment.getTargetList() if target.isDefault()]


def checkDownloads(environment, targetNames: Iterable[str], ask=None) -> None:
    """Raises DownloadServerDown, at once, when a binary needs Scipion's server and it does not answer."""
    pending = pendingServerDownloads(environment, targetNames)
    if pending and not serverAnswers(ask=ask):
        raise DownloadServerDown(
            "Scipion's download server does not answer, and these binaries are downloaded from it: %s. "
            "They cannot be installed now; try again later." % ", ".join(pending))
