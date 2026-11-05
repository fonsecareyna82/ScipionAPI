"""What a plugin installation changed, so that a failed one leaves the environment as it found it.

Before installing (a plugin, an update, one binary, a devel plugin) a snapshot is written next to the task's log:
the pip packages with their versions, the entries of the EM software folder and the conda environments. When the
installation fails, the environment goes back to it:

* pip: the packages that were not there are uninstalled, the ones whose version changed are installed again at
  the version they had (the previous release of an updated plugin too). A package that cannot be put back (e.g.
  without network) is named in the report, not retried;
* binaries: only the entries of the EM folder that were not there are removed, and a link is removed as a link,
  never what it points to;
* conda: only the environments that were not there are removed.

The snapshot is the journal of the installation: it is deleted when the installation ends well or was rolled
back, so one left behind belongs to an installation the plugin worker did not finish (it was stopped or killed);
the worker rolls those back when it starts.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

JOURNAL_SUFFIX = ".install-journal.json"
# Never removed nor downgraded: the installer's own tools
PROTECTED_PACKAGES = {"pip", "setuptools", "wheel"}
COMMAND_TIMEOUT_SECONDS = 1800


def canonicalName(name: str) -> str:
    """pip's name of a package (Scipion_EM-Xmipp and scipion-em-xmipp are one)."""
    return re.sub(r"[-_.]+", "-", str(name or "")).strip().lower()


# The environment ---------------------------------------------------------------------------------------------------

def _run(command: List[str], timeout: float = COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def pipPackages(python: str = sys.executable) -> Dict[str, str]:
    """The installed pip packages and their versions, as pip sees them now."""
    result = _run([python, "-m", "pip", "list", "--format=json", "--disable-pip-version-check"], timeout=300)
    if result.returncode != 0:
        raise RuntimeError("pip list failed: %s" % (result.stderr or result.stdout).strip()[-500:])
    return {canonicalName(item["name"]): str(item["version"]) for item in json.loads(result.stdout or "[]")}


def emFolder() -> Optional[Path]:
    try:
        import pwem

        return Path(pwem.Config.EM_ROOT)
    except Exception:
        return None


def emEntries(folder: Optional[Path]) -> List[str]:
    if folder is None or not folder.is_dir():
        return []
    return sorted(entry.name for entry in folder.iterdir())


def condaExecutable() -> Optional[str]:
    return (os.environ.get("CONDA_EXE") or "").strip() or shutil.which("conda")


def condaEnvironments(conda: Optional[str]) -> Optional[List[str]]:
    """The conda environments' folders (None when conda cannot be asked)."""
    if not conda:
        return None
    try:
        result = _run([conda, "env", "list", "--json"], timeout=120)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    try:
        return sorted(json.loads(result.stdout or "{}").get("envs") or [])
    except ValueError:
        return None


# The journal -------------------------------------------------------------------------------------------------------

def journalFolder() -> Path:
    from app.backend.api.services.plugin_task_log import ensurePluginTaskLogDir

    return ensurePluginTaskLogDir()


class InstallJournal:
    """The snapshot taken before one installation, kept on disk until it ends."""

    def __init__(self, path: Path, data: Dict[str, Any]):
        self.path = path
        self.data = data

    @classmethod
    def begin(cls, taskId: Optional[str], subject: str, folder: Optional[Path] = None,
              packages: Optional[Callable[[], Dict[str, str]]] = None) -> "InstallJournal":
        # Looked up when called (not bound when defined), so a test's stand-in is the one used
        packages = packages or pipPackages
        folder = Path(folder) if folder is not None else journalFolder()
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", "%s-%s" % (taskId or "local", subject))
        em = emFolder()
        conda = condaExecutable()
        data = {
            "taskId": taskId,
            "subject": subject,
            "pid": os.getpid(),
            "python": sys.executable,
            "packages": packages(),
            "emFolder": str(em) if em else None,
            "emEntries": emEntries(em),
            "conda": conda,
            "condaEnvironments": condaEnvironments(conda),
        }
        path = folder / (name + JOURNAL_SUFFIX)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data))
        temporary.replace(path)
        return cls(path, data)

    @classmethod
    def load(cls, path: Path) -> "InstallJournal":
        return cls(Path(path), json.loads(Path(path).read_text()))

    def finish(self) -> None:
        """The installation ended (well, or rolled back): the journal is no longer needed."""
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def rollBack(self, log: Callable[[str], None] = lambda message: None,
                 packages: Optional[Callable[[str], Dict[str, str]]] = None,
                 run: Optional[Callable[[List[str]], subprocess.CompletedProcess]] = None) -> Dict[str, Any]:
        """Put the environment back as the snapshot found it; answers what was done and what could not be."""
        packages = packages or pipPackages
        run = run or _run
        report: Dict[str, Any] = {"removedPackages": [], "restoredPackages": [], "notRestored": [],
                                  "removedBinaries": [], "removedEnvironments": [], "errors": []}
        python = self.data.get("python") or sys.executable
        before = {canonicalName(name): version for name, version in (self.data.get("packages") or {}).items()}
        try:
            now = packages(python)
        except Exception as error:
            report["errors"].append("The pip packages could not be listed: %s" % error)
            now = None

        if now is not None:
            added = sorted(name for name in now if name not in before and name not in PROTECTED_PACKAGES)
            if added:
                log("Removing the pip packages this installation added: %s" % ", ".join(added))
                result = run([python, "-m", "pip", "uninstall", "-y", *added])
                if result.returncode == 0:
                    report["removedPackages"] = added
                else:
                    report["errors"].append("pip uninstall failed: %s" % (result.stderr or result.stdout).strip()[-500:])
            changed = sorted(name for name, version in before.items()
                             if name not in PROTECTED_PACKAGES and now.get(name) != version)
            for name in changed:
                version = before[name]
                log("Putting %s back to %s (it is %s now)" % (name, version, now.get(name) or "not installed"))
                result = run([python, "-m", "pip", "install", "--no-deps", "%s==%s" % (name, version)])
                if result.returncode == 0:
                    report["restoredPackages"].append("%s==%s" % (name, version))
                else:
                    lastLine = ((result.stderr or result.stdout).strip().splitlines() or [""])[-1]
                    report["notRestored"].append({"package": name, "version": version, "error": lastLine[-300:]})

        emPath = self.data.get("emFolder")
        if emPath:
            folder = Path(emPath)
            for entry in sorted(set(emEntries(folder)) - set(self.data.get("emEntries") or [])):
                target = folder / entry
                try:
                    if target.is_symlink() or target.is_file():
                        target.unlink()
                    else:
                        shutil.rmtree(target)
                    report["removedBinaries"].append(entry)
                    log("Removed the binary folder %s" % entry)
                except OSError as error:
                    report["errors"].append("%s could not be removed: %s" % (target, error))

        conda = self.data.get("conda")
        beforeEnvironments = self.data.get("condaEnvironments")
        if conda and beforeEnvironments is not None:
            nowEnvironments = condaEnvironments(conda)
            if nowEnvironments is None:
                report["errors"].append("The conda environments could not be listed")
            else:
                for prefix in sorted(set(nowEnvironments) - set(beforeEnvironments)):
                    log("Removing the conda environment %s" % prefix)
                    result = run([conda, "env", "remove", "-y", "-p", prefix])
                    if result.returncode == 0:
                        report["removedEnvironments"].append(prefix)
                    else:
                        report["errors"].append("conda env remove %s failed: %s" % (
                            prefix, (result.stderr or result.stdout).strip()[-300:]))
        return report


def describeRollback(report: Dict[str, Any]) -> str:
    """One line for the task: what was undone, and what was left as it is."""
    done = []
    if report.get("removedPackages"):
        done.append("removed %s" % ", ".join(report["removedPackages"]))
    if report.get("restoredPackages"):
        done.append("put back %s" % ", ".join(report["restoredPackages"]))
    if report.get("removedBinaries"):
        done.append("removed the binaries %s" % ", ".join(report["removedBinaries"]))
    if report.get("removedEnvironments"):
        done.append("removed the conda environments %s" % ", ".join(
            os.path.basename(prefix) for prefix in report["removedEnvironments"]))
    left = ["%s could not be put back to %s (%s)" % (item["package"], item["version"], item["error"])
            for item in report.get("notRestored") or []] + list(report.get("errors") or [])
    text = ("Rolled back: " + "; ".join(done)) if done else "Nothing to roll back"
    if left:
        text += ". ROLLBACK INCOMPLETE: " + "; ".join(left)
    return text


def rollBackUnfinished(folder: Optional[Path] = None, log: Callable[[str], None] = logger.warning,
                       isAlive: Callable[[int], bool] = None) -> List[Dict[str, Any]]:
    """Roll back the installations a stopped plugin worker left half done; answers what each one did."""
    folder = Path(folder) if folder is not None else journalFolder()
    isAlive = isAlive or _isAlive
    done = []
    for path in sorted(folder.glob("*" + JOURNAL_SUFFIX)):
        try:
            journal = InstallJournal.load(path)
        except Exception:
            logger.warning("Unreadable install journal %s", path, exc_info=True)
            continue
        pid = int(journal.data.get("pid") or 0)
        if pid and pid != os.getpid() and isAlive(pid):
            continue
        log("Rolling back the unfinished installation of %s" % journal.data.get("subject"))
        report = journal.rollBack(log=log)
        journal.finish()
        done.append({"taskId": journal.data.get("taskId"), "subject": journal.data.get("subject"),
                     "summary": describeRollback(report)})
    return done


def _isAlive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
