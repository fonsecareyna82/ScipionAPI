import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence

from app.backend.api.services.plugin_task_log import appendPluginTaskLog, writePluginTaskStep

logger = logging.getLogger(__name__)


class PluginDevelService:
    def __init__(self, manifestPath: Optional[Path] = None):
        self._manifestPath = manifestPath
        self._manifestLock = Lock()

    def _getScipionHome(self) -> Path:
        scipionHome = os.environ.get("SCIPION_HOME")
        if not scipionHome:
            raise RuntimeError("SCIPION_HOME must be set to use devel plugin features")
        return Path(scipionHome).expanduser().resolve()

    def _getManifestPath(self) -> Path:
        if self._manifestPath is not None:
            return self._manifestPath
        return self._getScipionHome() / "web" / "devel_plugins.json"

    def _readManifest(self) -> List[Dict[str, Any]]:
        path = self._getManifestPath()
        if not path.exists():
            return []

        try:
            data = json.loads(path.read_text(encoding="utf-8") or "[]")
        except Exception:
            logger.exception("Could not read devel plugins manifest: %s", path)
            return []

        if not isinstance(data, list):
            return []

        return [item for item in data if isinstance(item, dict)]

    def _writeManifest(self, items: List[Dict[str, Any]]) -> None:
        path = self._getManifestPath()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmpPath = path.with_suffix(path.suffix + ".tmp")
        tmpPath.write_text(json.dumps(items, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(str(tmpPath), str(path))

    def listDevelPlugins(self) -> List[Dict[str, Any]]:
        with self._manifestLock:
            return list(self._readManifest())

    def getDevelPluginByPipName(self, pipName: str) -> Optional[Dict[str, Any]]:
        cleanPipName = str(pipName or "").strip()
        if not cleanPipName:
            return None

        for item in self.listDevelPlugins():
            if str(item.get("pipName") or "").strip() == cleanPipName:
                return item
        return None

    def _registerDevelPlugin(self, pluginPath: Path, pipName: str, taskId: Optional[str]) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "pipName": pipName,
            "path": str(pluginPath),
            "mode": "devel",
            "installedAt": now,
            "updatedAt": now,
        }
        if taskId:
            item["taskId"] = taskId

        with self._manifestLock:
            items = self._readManifest()
            previous = None
            remaining = []
            for existing in items:
                if str(existing.get("pipName") or "") == pipName:
                    previous = existing
                    continue
                remaining.append(existing)

            if previous:
                item["installedAt"] = previous.get("installedAt") or now

            remaining.append(item)
            remaining.sort(key=lambda x: str(x.get("pipName") or ""))
            self._writeManifest(remaining)

        return item

    def unregisterDevelPlugin(self, pipName: str) -> bool:
        cleanPipName = str(pipName or "").strip()
        if not cleanPipName:
            return False

        with self._manifestLock:
            items = self._readManifest()
            remaining = [item for item in items if str(item.get("pipName") or "") != cleanPipName]
            changed = len(remaining) != len(items)
            if changed:
                self._writeManifest(remaining)
            return changed

    def _getAllowedRoots(self) -> List[Path]:
        rawRoots = os.environ.get("SCIPIONAPI_DEVEL_PLUGIN_ROOTS", "").strip()
        if not rawRoots:
            return []

        roots = []
        for rawRoot in rawRoots.split(os.pathsep):
            rawRoot = rawRoot.strip()
            if not rawRoot:
                continue
            roots.append(Path(rawRoot).expanduser().resolve())
        return roots

    def _getBrowserRoots(self) -> List[Path]:
        allowedRoots = self._getAllowedRoots()
        if allowedRoots:
            return allowedRoots
        return [Path.home().resolve()]

    def _getBrowserRoot(self) -> Path:
        root = Path(os.environ.get("SCIPIONAPI_DEVEL_BROWSER_ROOT", "/")).expanduser().resolve()
        return root

    def _isPathAllowed(self, path: Path) -> bool:
        allowedRoots = self._getAllowedRoots()
        if not allowedRoots:
            return True

        for root in allowedRoots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def _resolveBrowserPath(self, relPath: str) -> Path:
        root = self._getBrowserRoot()
        rawPath = str(relPath or "").replace("\\", "/").strip()
        rawPath = rawPath.lstrip("/")
        parts = []
        for part in rawPath.split("/"):
            if not part or part == ".":
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)

        resolvedPath = (root / Path(*parts)).resolve() if parts else root.resolve()
        try:
            resolvedPath.relative_to(root)
        except ValueError:
            raise ValueError("Browser path is outside the configured browser root")
        return resolvedPath

    def _pathToBrowserRel(self, path: Path) -> str:
        root = self._getBrowserRoot()
        return str(path.resolve().relative_to(root)).replace(os.sep, "/")

    def getDevelPluginBrowserPaths(self) -> Dict[str, Any]:
        root = self._getBrowserRoot()
        visibleRoots = self._getBrowserRoots()
        startPath = ""
        if visibleRoots:
            try:
                startPath = str(visibleRoots[0].resolve().relative_to(root)).replace(os.sep, "/")
            except ValueError:
                startPath = ""
        return {
            "rootAbs": str(root),
            "startPath": startPath,
            "allowedRoots": [str(root) for root in visibleRoots],
        }

    def listDevelPluginBrowserDirectory(self, relPath: str = "") -> List[Dict[str, Any]]:
        directory = self._resolveBrowserPath(relPath)
        if not directory.exists():
            raise FileNotFoundError(f"Directory does not exist: {directory}")
        if not directory.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {directory}")

        items: List[Dict[str, Any]] = []
        for child in directory.iterdir():
            try:
                stat = child.stat()
                isDir = child.is_dir()
                relChild = self._pathToBrowserRel(child)
                mime, _ = mimetypes.guess_type(str(child))
                items.append(
                    {
                        "name": child.name,
                        "path": relChild,
                        "absPath": str(child.resolve()),
                        "isDir": isDir,
                        "size": 0 if isDir else stat.st_size,
                        "mime": "inode/directory" if isDir else (mime or "application/octet-stream"),
                    }
                )
            except PermissionError:
                continue
            except OSError:
                continue

        items.sort(key=lambda item: (not bool(item.get("isDir")), str(item.get("name") or "").lower()))
        return items

    def _extractNameFromPyproject(self, pyprojectPath: Path) -> Optional[str]:
        try:
            text = pyprojectPath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

        match = re.search(r"(?m)^\s*name\s*=\s*['\"]([^'\"]+)['\"]", text)
        if match:
            return self._normalizePipName(match.group(1))
        return None

    def _extractNameFromSetupCfg(self, setupCfgPath: Path) -> Optional[str]:
        try:
            text = setupCfgPath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

        match = re.search(r"(?im)^\s*name\s*=\s*([^\n#]+)", text)
        if match:
            return self._normalizePipName(match.group(1).strip())
        return None

    def _extractNameFromSetupPy(self, setupPyPath: Path) -> Optional[str]:
        try:
            text = setupPyPath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

        match = re.search(r"name\s*=\s*['\"]([^'\"]+)['\"]", text)
        if match:
            return self._normalizePipName(match.group(1))
        return None

    def _normalizePipName(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None

        text = str(value).strip().strip("'\"")
        if not text:
            return None

        if not re.match(r"^[A-Za-z0-9_.-]+$", text):
            return None
        return text

    def _guessPipName(self, pluginPath: Path) -> Optional[str]:
        candidates = [
            self._extractNameFromPyproject(pluginPath / "pyproject.toml"),
            self._extractNameFromSetupCfg(pluginPath / "setup.cfg"),
            self._extractNameFromSetupPy(pluginPath / "setup.py"),
            self._normalizePipName(pluginPath.name),
        ]

        for candidate in candidates:
            if candidate:
                return candidate
        return None

    def validateDevelPluginPath(self, pluginPath: str) -> Dict[str, Any]:
        rawPath = str(pluginPath or "").strip()
        if not rawPath:
            return {
                "valid": False,
                "path": "",
                "exists": False,
                "isDirectory": False,
                "allowed": False,
                "pipName": None,
                "message": "Plugin path is required",
            }

        resolvedPath = Path(rawPath).expanduser().resolve()
        exists = resolvedPath.exists()
        isDirectory = resolvedPath.is_dir()
        allowed = self._isPathAllowed(resolvedPath)

        hasPyproject = (resolvedPath / "pyproject.toml").exists()
        hasSetupPy = (resolvedPath / "setup.py").exists()
        hasSetupCfg = (resolvedPath / "setup.cfg").exists()
        hasInstallMetadata = hasPyproject or hasSetupPy or hasSetupCfg
        pipName = self._guessPipName(resolvedPath) if exists and isDirectory else None

        valid = bool(exists and isDirectory and allowed and hasInstallMetadata and pipName)

        if not exists:
            message = "Plugin path does not exist"
        elif not isDirectory:
            message = "Plugin path must be a directory"
        elif not allowed:
            message = "Plugin path is outside allowed development roots"
        elif not hasInstallMetadata:
            message = "No pyproject.toml, setup.py or setup.cfg found"
        elif not pipName:
            message = "Could not detect a valid pip package name"
        else:
            message = "Valid Scipion devel plugin candidate"

        return {
            "valid": valid,
            "path": str(resolvedPath),
            "exists": exists,
            "isDirectory": isDirectory,
            "allowed": allowed,
            "pipName": pipName,
            "hasPyproject": hasPyproject,
            "hasSetupPy": hasSetupPy,
            "hasSetupCfg": hasSetupCfg,
            "hasInstallMetadata": hasInstallMetadata,
            "allowedRoots": [str(root) for root in self._getAllowedRoots()],
            "message": message,
        }

    def _resolveScipionCommand(self) -> Sequence[str]:
        explicitExecutable = os.environ.get("SCIPIONAPI_SCIPION_EXECUTABLE") or os.environ.get("SCIPION_EXECUTABLE")
        if explicitExecutable:
            return [explicitExecutable]

        scipion3 = shutil.which("scipion3")
        if scipion3:
            return [scipion3]

        scipion = shutil.which("scipion")
        if scipion:
            return [scipion]

        return [sys.executable, "-m", "scipion"]

    def _runCommand(self, command: Sequence[str], cwd: Path, taskId: Optional[str]) -> None:
        if taskId:
            appendPluginTaskLog(taskId, "$ " + " ".join(str(part) for part in command))

        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )

        assert process.stdout is not None
        for line in process.stdout:
            if taskId:
                appendPluginTaskLog(taskId, line)

        returnCode = process.wait()
        if returnCode != 0:
            raise RuntimeError(f"Command failed with exit code {returnCode}: {' '.join(str(part) for part in command)}")

    def installDevelPlugin(
        self,
        pluginPath: str,
        taskId: Optional[str] = None,
        skipBinaries: bool = False,
        force: bool = False,
    ) -> Dict[str, Any]:
        validation = self.validateDevelPluginPath(pluginPath)
        if not validation.get("valid"):
            raise ValueError(str(validation.get("message") or "Invalid devel plugin path"))

        resolvedPath = Path(str(validation["path"])).resolve()
        pipName = str(validation["pipName"])

        if taskId:
            writePluginTaskStep(taskId, f"Validated devel plugin path: {resolvedPath}")
            writePluginTaskStep(taskId, f"Detected pip name: {pipName}")

        command = list(self._resolveScipionCommand()) + ["installp", "-p", str(resolvedPath), "--devel"]

        skipBinariesArg = os.environ.get("SCIPIONAPI_DEVEL_SKIP_BINARIES_ARG", "").strip()
        if skipBinaries and skipBinariesArg:
            command.append(skipBinariesArg)
        elif skipBinaries and taskId:
            writePluginTaskStep(taskId, "skipBinaries requested, but no SCIPIONAPI_DEVEL_SKIP_BINARIES_ARG is configured.")

        forceArg = os.environ.get("SCIPIONAPI_DEVEL_FORCE_ARG", "").strip()
        if force and forceArg:
            command.append(forceArg)
        elif force and taskId:
            writePluginTaskStep(taskId, "force requested, but no SCIPIONAPI_DEVEL_FORCE_ARG is configured.")

        if taskId:
            writePluginTaskStep(taskId, "Running Scipion devel plugin installer...")

        self._runCommand(command, cwd=resolvedPath, taskId=taskId)

        manifestItem = self._registerDevelPlugin(resolvedPath, pipName, taskId)

        if taskId:
            writePluginTaskStep(taskId, "Devel plugin registered in manifest.")

        return {
            "installed": "SUCCESS",
            "mode": "devel",
            "pipName": pipName,
            "path": str(resolvedPath),
            "manifestItem": manifestItem,
            "skipBinaries": bool(skipBinaries),
            "force": bool(force),
        }
