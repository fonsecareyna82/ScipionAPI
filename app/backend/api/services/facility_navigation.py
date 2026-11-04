"""The navigation report of a tomography DATA: its atlas, search maps, tomogram positions and tilt series.

It is made by tomo5-mapper (Jonathan Piccirillo, CNB facility), an outside program that reads a Tomography 5
session folder (Session.dm, SearchMaps, the .mdoc) without changing it and writes a self-contained HTML page.
It is not part of ScipionWeb: the installation points to it with SCIPIONWEB_TOMO5_MAPPER (the command, e.g.
/opt/tomo5-mapper/.venv/bin/tomo5-mapper, which needs Python 3.9 or newer); without it there are no reports.

A report is made for each DATA of a tomography session, when the session finishes and whenever the staff ask,
in a thread of its own (it takes minutes), into the facility's reports folder (SCIPIONWEB_FACILITY_REPORTS_DIR,
by default SCIPION_HOME/facility/navigation), never into the microscope's folders. What happened is kept next to
the report (status.json), so the database needs nothing.
"""
import datetime
import json
import logging
import os
import shlex
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

COMMAND_VARIABLE = "SCIPIONWEB_TOMO5_MAPPER"
REPORTS_VARIABLE = "SCIPIONWEB_FACILITY_REPORTS_DIR"
STATUS_FILE = "status.json"
# A session of thousands of tilts over a network mount: no report takes longer
TIMEOUT_SECONDS = 2 * 3600
# Light reports that read Tomo 5's binned stacks: a network mount moves nine times less data
DEFAULT_ARGUMENTS = ("--tilt-source", "thumbnails", "--skip-screening", "--quiet")
LOG_LIMIT = 4000

_running = set()
_lock = threading.Lock()


def command() -> Optional[List[str]]:
    """The command that makes the reports, when the installation has one."""
    text = (os.environ.get(COMMAND_VARIABLE) or "").strip()
    return shlex.split(text) if text else None


def reportsRoot() -> Path:
    configured = (os.environ.get(REPORTS_VARIABLE) or "").strip()
    if configured:
        return Path(configured)
    return Path(os.environ.get("SCIPION_HOME") or ".") / "facility" / "navigation"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _folderOf(session: Dict[str, Any], dataset: Dict[str, Any]) -> Path:
    return reportsRoot() / str(session["id"]) / str(dataset["folder"])


def _readStatus(folder: Path) -> Dict[str, Any]:
    try:
        return json.loads((folder / STATUS_FILE).read_text())
    except (OSError, ValueError):
        return {}


def _writeStatus(folder: Path, values: Dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / (STATUS_FILE + ".tmp")
    temporary.write_text(json.dumps(values))
    temporary.replace(folder / STATUS_FILE)


def _reportFile(folder: Path) -> Optional[Path]:
    reports = sorted(folder.glob("**/*_report.html"))
    return reports[0] if reports else None


def navigationOf(session: Dict[str, Any], dataset: Dict[str, Any]) -> Dict[str, Any]:
    """Where a DATA's report is: none, making, done (with when) or failed (and why); and whether one can be made."""
    folder = _folderOf(session, dataset)
    stored = _readStatus(folder)
    state = stored.get("state") or "none"
    with _lock:
        if (session["id"], dataset["id"]) in _running:
            state = "making"
    if state == "making" and (session["id"], dataset["id"]) not in _running:
        # The API stopped while it was being made
        state = "failed"
        stored.setdefault("message", "The API stopped while the report was being made: make it again")
    report = _reportFile(folder) if state == "done" else None
    return {"state": state if state != "done" or report else "failed", "startedAt": stored.get("startedAt"),
            "finishedAt": stored.get("finishedAt"), "message": stored.get("message"),
            "available": command() is not None, "sizeBytes": report.stat().st_size if report else None}


def _sourceOf(session: Dict[str, Any], dataset: Dict[str, Any]) -> Path:
    return Path(session.get("offloadPath") or "") / str(dataset["folder"])


def _make(session: Dict[str, Any], dataset: Dict[str, Any], program: List[str]) -> None:
    key = (session["id"], dataset["id"])
    folder = _folderOf(session, dataset)
    started = _now()
    try:
        output = folder / "report"
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
        _writeStatus(folder, {"state": "making", "startedAt": started})
        source = _sourceOf(session, dataset)
        # The atlas of a session is beside its DATA, in its ATLAS folder: Tomo 5 finds the original by its id upwards
        result = subprocess.run(program + [str(source), "-o", str(output), *DEFAULT_ARGUMENTS],
                                capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
        log = ((result.stdout or "") + (result.stderr or ""))[-LOG_LIMIT:]
        (folder / "tomo5-mapper.log").write_text(log)
        if result.returncode == 0 and _reportFile(output):
            _writeStatus(folder, {"state": "done", "startedAt": started, "finishedAt": _now()})
        else:
            message = "No Tomography 5 session in %s" % source if result.returncode == 1 else (
                log.strip().splitlines()[-1] if log.strip() else "tomo5-mapper ended with code %s" % result.returncode)
            _writeStatus(folder, {"state": "failed", "startedAt": started, "finishedAt": _now(), "message": message})
    except subprocess.TimeoutExpired:
        _writeStatus(folder, {"state": "failed", "startedAt": started, "finishedAt": _now(),
                              "message": "It took more than %d hours" % (TIMEOUT_SECONDS // 3600)})
    except Exception as error:
        logger.warning("Could not make the navigation report of %s", dataset["folder"], exc_info=True)
        _writeStatus(folder, {"state": "failed", "startedAt": started, "finishedAt": _now(), "message": str(error)})
    finally:
        with _lock:
            _running.discard(key)


def startReport(session: Dict[str, Any], dataset: Dict[str, Any], wait: bool = False) -> Dict[str, Any]:
    """Make a DATA's report in a thread of its own (wait: here, for the tests); 409 when it cannot be made."""
    program = command()
    if program is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="No navigation reports here: the installation has no tomo5-mapper (%s)"
                                   % COMMAND_VARIABLE)
    if session.get("technique") != "tomo" or dataset.get("kind") != "data":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Navigation reports are made for the DATA of tomography sessions")
    if not session.get("offloadPath") or not _sourceOf(session, dataset).is_dir():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="The DATA folder %s is not there" % dataset["folder"])
    key = (session["id"], dataset["id"])
    with _lock:
        if key in _running:
            return navigationOf(session, dataset)
        _running.add(key)
    if wait:
        _make(session, dataset, program)
    else:
        threading.Thread(target=_make, args=(session, dataset, program), name="tomo5-mapper", daemon=True).start()
    return navigationOf(session, dataset)


def reportsWhenFinished(session: Dict[str, Any]) -> List[str]:
    """When a tomography session finishes, the reports of its DATA that have movies; answers their folders."""
    if command() is None or session.get("technique") != "tomo":
        return []
    started = []
    for dataset in session.get("datasets") or []:
        if dataset.get("kind") != "data" or not dataset.get("movieCount"):
            continue
        try:
            startReport(session, dataset)
            started.append(dataset["folder"])
        except HTTPException as error:
            logger.info("No navigation report for %s: %s", dataset.get("folder"), error.detail)
    return started


def reportPath(session: Dict[str, Any], dataset: Dict[str, Any]) -> Path:
    report = _reportFile(_folderOf(session, dataset))
    if report is None or navigationOf(session, dataset)["state"] != "done":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This DATA has no navigation report")
    return report
