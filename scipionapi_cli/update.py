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
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from scipionapi_cli.db import runAlembicUpgrade
from scipionapi_cli.envfile import exportEnvToOs, readEnvFile, writeEnvFile
from scipionapi_cli.provision import deployWebDist
from scipionapi_cli.runtime import startCommand, stopCommand
from scipionapi_cli.shell import resolveRepoRoot, runCmd
from scipionapi_cli.version import SCIPIONAPI_RELEASE_TAG


try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    _HAS_RICH = True
    _console = Console()
except Exception:
    _HAS_RICH = False
    _console = None


DEFAULT_UPDATE_BASE_URL = "https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/"
DEFAULT_MANIFEST_NAME = "manifest.json"

API_ARCHIVE_RE = re.compile(
    r"ScipionAPI-(v?[0-9]+(?:\.[0-9]+){1,3}(?:[-._A-Za-z0-9]*)?)\.zip"
)

API_MANAGED_PATHS = [
    "app",
    "scipionapi_cli",
    "scripts",
    "alembic",
    "alembic.ini",
    "pyproject.toml",
    "requirements.txt",
    "README.rst",
    "LICENSE",
    "install.sh",
]

_UPDATE_STEP_INDEX = 0


def _resetProgress() -> None:
    # resetProgress
    global _UPDATE_STEP_INDEX
    _UPDATE_STEP_INDEX = 0


def _humanSize(numBytes: int) -> str:
    # humanSize
    value = float(max(0, numBytes))
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0

    return f"{numBytes} B"


def _shortDigest(value: str, length: int = 12) -> str:
    # shortDigest
    text = (value or "").strip()
    if len(text) <= length:
        return text
    return text[:length]


def _formatChecksum(value: Optional[str]) -> str:
    # formatChecksum
    if not value:
        return "not provided"
    return _shortDigest(value)


def _printLine(message: str = "") -> None:
    # printLine
    if _HAS_RICH:
        _console.print(message)
    else:
        print(message, flush=True)


def _printPanel(title: str, body: str = "") -> None:
    # printPanel
    if _HAS_RICH:
        _console.print(Panel.fit(body or "", title=title, border_style="cyan"))
    else:
        print(f"\n== {title} ==", flush=True)
        if body:
            print(body, flush=True)


def _printInfo(message: str) -> None:
    # printInfo
    if _HAS_RICH:
        _console.print(f"[bold cyan]INFO[/bold cyan] {message}")
    else:
        print(f"INFO {message}", flush=True)


def _printSuccess(message: str) -> None:
    # printSuccess
    if _HAS_RICH:
        _console.print(f"[bold green]SUCCESS[/bold green] {message}")
    else:
        print(f"SUCCESS {message}", flush=True)


def _printWarning(message: str) -> None:
    # printWarning
    if _HAS_RICH:
        _console.print(f"[bold yellow]WARNING[/bold yellow] {message}")
    else:
        print(f"WARNING {message}", flush=True)


def _printStep(step: str, detail: str = "") -> None:
    # printStep
    global _UPDATE_STEP_INDEX
    _UPDATE_STEP_INDEX += 1
    prefix = f"[{_UPDATE_STEP_INDEX:02d}]"

    if _HAS_RICH:
        if detail:
            _console.print(f"[bold magenta]{prefix} {step}[/bold magenta] [dim]{detail}[/dim]")
        else:
            _console.print(f"[bold magenta]{prefix} {step}[/bold magenta]")
    else:
        if detail:
            print(f"\n{prefix} {step} | {detail}", flush=True)
        else:
            print(f"\n{prefix} {step}", flush=True)


def _printKeyValueTable(title: str, rows: List[Tuple[str, Any]]) -> None:
    # printKeyValueTable
    if _HAS_RICH:
        table = Table(title=title, header_style="bold magenta")
        table.add_column("Field", style="bold white", no_wrap=True)
        table.add_column("Value", style="white")
        for key, value in rows:
            table.add_row(str(key), str(value))
        _console.print(table)
    else:
        print(f"\n{title}:", flush=True)
        for key, value in rows:
            print(f"  {key}: {value}", flush=True)


def _normalizeBaseUrl(value: str) -> str:
    # normalizeBaseUrl
    baseUrl = (value or DEFAULT_UPDATE_BASE_URL).strip()
    if not baseUrl:
        baseUrl = DEFAULT_UPDATE_BASE_URL
    if not baseUrl.endswith("/"):
        baseUrl = f"{baseUrl}/"
    return baseUrl


def _normalizeVersionTag(value: str) -> str:
    # normalizeVersionTag
    version = (value or "").strip()
    if not version or version.lower() == "latest":
        return "latest"
    if re.match(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[-._A-Za-z0-9]*)?$", version):
        return f"v{version}"
    return version


def _versionSortKey(version: str) -> Tuple[int, int, int, int, str]:
    # versionSortKey
    normalized = _normalizeVersionTag(version)
    match = re.match(r"^v?([0-9]+)(?:\.([0-9]+))?(?:\.([0-9]+))?(?:\.([0-9]+))?(.*)$", normalized)
    if not match:
        return (0, 0, 0, 0, normalized)

    parts = []
    for index in range(1, 5):
        token = match.group(index)
        parts.append(int(token) if token is not None else 0)

    return (parts[0], parts[1], parts[2], parts[3], match.group(5) or "")


def _readUrlText(url: str, timeoutSec: float) -> str:
    # readUrlText
    req = Request(url, headers={"User-Agent": "scipionapi-cli/update"})
    with urlopen(req, timeout=timeoutSec) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def _readJsonUrl(url: str, timeoutSec: float) -> Dict[str, Any]:
    # readJsonUrl
    text = _readUrlText(url, timeoutSec=timeoutSec)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Manifest is not a JSON object: {url}")
    return payload


def _manifestFileEntry(value: Any, fallbackFile: str) -> Tuple[str, Optional[str]]:
    # parseManifestFileEntry
    if isinstance(value, str):
        return value, None

    if isinstance(value, dict):
        fileName = (
            value.get("file")
            or value.get("filename")
            or value.get("url")
            or fallbackFile
        )
        sha256 = value.get("sha256")
        return str(fileName), str(sha256) if sha256 else None

    return fallbackFile, None


def _releaseFromManifest(
    manifest: Dict[str, Any],
    requestedVersion: str,
) -> Tuple[str, str, str, Optional[str], Optional[str]]:
    # resolveReleaseFromManifest
    releases = manifest.get("releases") if isinstance(manifest.get("releases"), dict) else {}
    latest = _normalizeVersionTag(str(manifest.get("latest") or ""))

    if requestedVersion == "latest":
        if latest == "latest":
            raise RuntimeError("Manifest does not define a valid 'latest' version.")
        version = latest
    else:
        version = requestedVersion

    release = releases.get(version) if isinstance(releases, dict) else None
    fallbackApiFile = f"ScipionAPI-{version}.zip"
    fallbackWebFile = f"ScipionWeb-{version}-dist.zip"

    if isinstance(release, dict):
        apiFile, apiSha256 = _manifestFileEntry(release.get("api"), fallbackApiFile)
        webFile, webSha256 = _manifestFileEntry(release.get("web"), fallbackWebFile)
        return version, apiFile, webFile, apiSha256, webSha256

    return version, fallbackApiFile, fallbackWebFile, None, None


def _resolveLatestFromDirectory(baseUrl: str, timeoutSec: float) -> str:
    # resolveLatestVersionFromDirectoryListing
    html = _readUrlText(baseUrl, timeoutSec=timeoutSec)
    versions = sorted(set(API_ARCHIVE_RE.findall(html)), key=_versionSortKey)

    if not versions:
        raise RuntimeError(
            "Could not detect the latest version from the update directory listing. "
            "Provide --version explicitly or publish a manifest.json file."
        )

    return _normalizeVersionTag(versions[-1])


def _resolveRelease(
    baseUrl: str,
    requestedVersion: str,
    timeoutSec: float,
) -> Tuple[str, str, str, Optional[str], Optional[str]]:
    # resolveTargetRelease
    requestedVersion = _normalizeVersionTag(requestedVersion)

    manifestUrl = urljoin(baseUrl, DEFAULT_MANIFEST_NAME)
    try:
        manifest = _readJsonUrl(manifestUrl, timeoutSec=timeoutSec)
        return _releaseFromManifest(manifest, requestedVersion)
    except (HTTPError, URLError, json.JSONDecodeError, RuntimeError) as exc:
        if requestedVersion != "latest":
            version = requestedVersion
            return (
                version,
                f"ScipionAPI-{version}.zip",
                f"ScipionWeb-{version}-dist.zip",
                None,
                None,
            )

        _printWarning(f"Could not use manifest.json ({exc}); trying directory listing.")
        version = _resolveLatestFromDirectory(baseUrl, timeoutSec=timeoutSec)
        return (
            version,
            f"ScipionAPI-{version}.zip",
            f"ScipionWeb-{version}-dist.zip",
            None,
            None,
        )


def _resolveScipionHome(repoRoot: Path, defaultEnv: Dict[str, str]) -> Path:
    # resolveScipionHome
    configured = os.environ.get("SCIPION_HOME") or defaultEnv.get("SCIPION_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (repoRoot / "scipion_home").resolve()


def _loadCurrentEnv(repoRoot: Path) -> Tuple[Path, Path, Dict[str, str]]:
    # loadCurrentEnv
    defaultHome = (repoRoot / "scipion_home").resolve()
    defaultEnvPath = defaultHome / ".env"
    defaultEnv = readEnvFile(defaultEnvPath)

    scipionHome = _resolveScipionHome(repoRoot, defaultEnv)
    envPath = scipionHome / ".env"

    if envPath.exists():
        exportEnvToOs(envPath)
        env = readEnvFile(envPath)
    else:
        env = {}

    return scipionHome, envPath, env


def _updatesDir(scipionHome: Path) -> Path:
    # ensureUpdatesDir
    path = scipionHome / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _downloadFile(url: str, destPath: Path, timeoutSec: float) -> None:
    # downloadFile
    destPath.parent.mkdir(parents=True, exist_ok=True)

    req = Request(url, headers={"User-Agent": "scipionapi-cli/update"})
    downloadedBytes = 0
    lastProgressAt = time.monotonic()

    with urlopen(req, timeout=timeoutSec) as response:
        contentLength = response.headers.get("Content-Length")
        totalBytes = int(contentLength) if contentLength and contentLength.isdigit() else None

        if totalBytes:
            _printInfo(f"Remote size: {_humanSize(totalBytes)}")
        else:
            _printInfo("Remote size: unknown")

        with open(destPath, "wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break

                handle.write(chunk)
                downloadedBytes += len(chunk)

                now = time.monotonic()
                if now - lastProgressAt >= 5.0:
                    if totalBytes:
                        percent = (downloadedBytes / totalBytes) * 100.0
                        _printInfo(
                            f"Downloaded {_humanSize(downloadedBytes)} / "
                            f"{_humanSize(totalBytes)} ({percent:.1f}%)"
                        )
                    else:
                        _printInfo(f"Downloaded {_humanSize(downloadedBytes)}")
                    lastProgressAt = now

    _printSuccess(f"Saved {destPath.name} ({_humanSize(downloadedBytes)})")


def _sha256(path: Path) -> str:
    # sha256File
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verifySha256(path: Path, expectedSha256: Optional[str]) -> None:
    # verifySha256
    _printInfo(f"Calculating SHA256 for {path.name}")
    actual = _sha256(path)

    if not expectedSha256:
        _printWarning(
            f"No SHA256 was provided by the manifest for {path.name}; "
            f"calculated {_shortDigest(actual)}"
        )
        return

    if actual.lower() != expectedSha256.lower():
        raise RuntimeError(
            f"SHA256 mismatch for {path.name}. Expected {expectedSha256}, got {actual}."
        )

    _printSuccess(f"Checksum verified for {path.name}: {_shortDigest(actual)}")


def _safeExtractZip(zipPath: Path, destDir: Path) -> None:
    # safeExtractZip
    destDir.mkdir(parents=True, exist_ok=True)
    destRoot = destDir.resolve()

    with zipfile.ZipFile(zipPath, "r") as zf:
        for member in zf.infolist():
            memberPath = (destDir / member.filename).resolve()
            try:
                memberPath.relative_to(destRoot)
            except ValueError:
                raise RuntimeError(f"Unsafe zip content detected: {member.filename}")
        zf.extractall(destDir)


def _normalizeApiSourceRoot(extractedDir: Path) -> Path:
    # normalizeApiSourceRoot
    candidates = [extractedDir]
    children = [path for path in extractedDir.iterdir() if path.is_dir()]
    candidates.extend(children)

    for candidate in candidates:
        if (
            (candidate / "pyproject.toml").exists()
            and (candidate / "alembic.ini").exists()
            and (candidate / "app").is_dir()
            and (candidate / "scipionapi_cli").is_dir()
            and (candidate / "scripts").is_dir()
        ):
            return candidate

    raise RuntimeError(
        "ScipionAPI source archive is not valid. Expected pyproject.toml, "
        "alembic.ini, app/, scipionapi_cli/, and scripts/."
    )


def _validateWebArchive(zipPath: Path) -> Path:
    # validateWebArchive
    with tempfile.TemporaryDirectory(prefix="scipionweb-validate-") as tmpName:
        tmpDir = Path(tmpName)
        _safeExtractZip(zipPath, tmpDir)

        candidates = [tmpDir, tmpDir / "dist"]
        children = [path for path in tmpDir.iterdir() if path.is_dir()]
        candidates.extend(children)

        for candidate in candidates:
            if (candidate / "index.html").exists():
                return candidate

    raise RuntimeError("ScipionWeb dist archive is not valid. index.html was not found.")


def _copyPath(srcPath: Path, dstPath: Path) -> None:
    # copyPath
    if srcPath.is_dir():
        shutil.copytree(srcPath, dstPath, symlinks=True)
    else:
        dstPath.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(srcPath, dstPath)


def _replacePath(srcPath: Path, dstPath: Path) -> None:
    # replacePath
    if dstPath.exists() or dstPath.is_symlink():
        if dstPath.is_dir() and not dstPath.is_symlink():
            shutil.rmtree(dstPath)
        else:
            dstPath.unlink()

    _copyPath(srcPath, dstPath)


def _backupPath(srcPath: Path, backupRoot: Path, relativePath: str) -> None:
    # backupPath
    if not srcPath.exists() and not srcPath.is_symlink():
        return

    targetPath = backupRoot / relativePath
    targetPath.parent.mkdir(parents=True, exist_ok=True)
    _copyPath(srcPath, targetPath)


def _backupCurrentInstall(
    repoRoot: Path,
    scipionHome: Path,
    env: Dict[str, str],
    timestamp: str,
    includeApi: bool,
    includeWeb: bool,
) -> Path:
    # backupCurrentInstall
    backupRoot = _updatesDir(scipionHome) / "backups" / timestamp
    backupRoot.mkdir(parents=True, exist_ok=True)

    if includeApi:
        apiBackupRoot = backupRoot / "api"
        for relativePath in API_MANAGED_PATHS:
            _backupPath(repoRoot / relativePath, apiBackupRoot, relativePath)

    if includeWeb:
        webDist = Path(env.get("WEB_DIST_PATH") or (scipionHome / "web" / "dist")).expanduser()
        if webDist.exists():
            _backupPath(webDist, backupRoot / "web", "dist")

    metadata = {
        "timestamp": timestamp,
        "repoRoot": str(repoRoot),
        "scipionHome": str(scipionHome),
        "apiVersionBefore": SCIPIONAPI_RELEASE_TAG,
        "webDistPath": env.get("WEB_DIST_PATH", ""),
    }
    (backupRoot / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return backupRoot


def _restoreApiBackup(repoRoot: Path, backupRoot: Path) -> None:
    # restoreApiBackup
    apiBackupRoot = backupRoot / "api"
    if not apiBackupRoot.exists():
        return

    for relativePath in API_MANAGED_PATHS:
        backupPath = apiBackupRoot / relativePath
        targetPath = repoRoot / relativePath

        if targetPath.exists() or targetPath.is_symlink():
            if targetPath.is_dir() and not targetPath.is_symlink():
                shutil.rmtree(targetPath)
            else:
                targetPath.unlink()

        if backupPath.exists() or backupPath.is_symlink():
            _copyPath(backupPath, targetPath)

    _ensurePostUpdatePermissions(repoRoot)


def _ensureExecutableFile(path: Path) -> None:
    # ensureExecutableFile
    if not path.exists() or not path.is_file():
        return

    currentMode = path.stat().st_mode
    path.chmod(currentMode | 0o755)


def _ensurePostUpdatePermissions(repoRoot: Path) -> None:
    # ensurePostUpdatePermissions
    _ensureExecutableFile(repoRoot / "scripts" / "scipionapi")


def _applyApiUpdate(repoRoot: Path, apiSourceRoot: Path) -> None:
    # applyApiUpdate
    for relativePath in API_MANAGED_PATHS:
        srcPath = apiSourceRoot / relativePath
        if not srcPath.exists() and not srcPath.is_symlink():
            _printWarning(f"API path missing in archive, skipping: {relativePath}")
            continue

        _printInfo(f"Updating API path: {relativePath}")
        _replacePath(srcPath, repoRoot / relativePath)

    _ensurePostUpdatePermissions(repoRoot)


def _runPipInstall(repoRoot: Path, args: List[str]) -> None:
    # runPipInstallForCurrentInterpreter
    command = [sys.executable, "-m", "pip", "install"] + list(args)
    _printInfo(f"Running command: {' '.join(command)}")
    proc = runCmd(command, cwd=repoRoot, live=True, timeout=None)
    if proc.returncode != 0:
        raise RuntimeError(f"pip install failed: {' '.join(command)}")


def _installUpdatedApi(repoRoot: Path) -> None:
    # installUpdatedApi
    _printStep(
        "Installing updated ScipionAPI and Python dependencies",
        str(repoRoot),
    )
    _printInfo(
        "This can take a few minutes depending on network and package cache."
    )
    _runPipInstall(
        repoRoot,
        ["-e", str(repoRoot)],
    )


def _cleanupOldBackups(scipionHome: Path, keepBackups: int) -> None:
    # cleanupOldBackups
    if keepBackups <= 0:
        _printInfo("Backup cleanup disabled.")
        return

    backupsDir = _updatesDir(scipionHome) / "backups"
    if not backupsDir.exists():
        _printInfo("No backup directory found.")
        return

    backups = sorted([path for path in backupsDir.iterdir() if path.is_dir()])
    removedCount = 0
    while len(backups) > keepBackups:
        oldest = backups.pop(0)
        shutil.rmtree(oldest, ignore_errors=True)
        removedCount += 1

    if removedCount:
        _printSuccess(f"Removed {removedCount} old backup(s).")
    else:
        _printInfo(f"Backup retention OK; keeping up to {keepBackups} backup(s).")


def _boolEnv(env: Dict[str, str], key: str, default: bool = False) -> bool:
    # readBoolEnv
    value = (env.get(key) or os.environ.get(key) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _intEnv(env: Dict[str, str], key: str, default: int) -> int:
    # readIntEnv
    try:
        return int((env.get(key) or os.environ.get(key) or "").strip() or default)
    except Exception:
        return default


def updateCommand(
    version: str = "latest",
    baseUrl: Optional[str] = None,
    apiZipUrl: Optional[str] = None,
    webZipUrl: Optional[str] = None,
    apiOnly: bool = False,
    webOnly: bool = False,
    dryRun: bool = False,
    noRestart: bool = False,
    force: bool = False,
) -> None:
    # updateCommand
    if apiOnly and webOnly:
        raise RuntimeError("--api-only and --web-only cannot be used together.")

    _resetProgress()

    repoRoot = resolveRepoRoot()
    scipionHome, envPath, env = _loadCurrentEnv(repoRoot)

    effectiveBaseUrl = _normalizeBaseUrl(
        baseUrl
        or env.get("SCIPIONAPI_UPDATE_BASE_URL")
        or os.environ.get("SCIPIONAPI_UPDATE_BASE_URL")
        or DEFAULT_UPDATE_BASE_URL
    )

    requestedVersionInput = (version or "").strip()
    if requestedVersionInput.lower() == "latest":
        requestedVersionInput = ""

    requestedVersion = _normalizeVersionTag(
        requestedVersionInput
        or env.get("SCIPIONAPI_UPDATE_VERSION")
        or os.environ.get("SCIPIONAPI_UPDATE_VERSION")
        or "latest"
    )
    timeoutSec = float(_intEnv(env, "SCIPIONAPI_UPDATE_TIMEOUT", 300))
    keepBackups = _intEnv(env, "SCIPIONAPI_UPDATE_KEEP_BACKUPS", 3)

    includeApi = not webOnly
    includeWeb = not apiOnly

    if not envPath.exists():
        raise RuntimeError(
            f"Environment file not found: {envPath}. "
            "Run `scipionapi install` or `scipionapi provision` before update."
        )

    targetVersion, apiFile, webFile, apiSha256, webSha256 = _resolveRelease(
        effectiveBaseUrl,
        requestedVersion,
        timeoutSec=timeoutSec,
    )

    resolvedApiUrl = apiZipUrl or urljoin(effectiveBaseUrl, apiFile)
    resolvedWebUrl = webZipUrl or urljoin(effectiveBaseUrl, webFile)

    _printPanel(
        "ScipionAPI update",
        "This command updates the API source and/or the web dist while preserving "
        "SCIPION_HOME, projects, logs, database, and the current .env file. "
        "A filesystem backup is created before replacing managed files.",
    )
    _printKeyValueTable(
        "Update plan",
        [
            ("Repo root", repoRoot),
            ("SCIPION_HOME", scipionHome),
            ("Env file", envPath),
            ("Current API version", SCIPIONAPI_RELEASE_TAG),
            ("Target version", targetVersion),
            ("Base URL", effectiveBaseUrl),
            ("API archive", resolvedApiUrl if includeApi else "skipped"),
            ("API checksum", _formatChecksum(apiSha256) if includeApi else "skipped"),
            ("Web archive", resolvedWebUrl if includeWeb else "skipped"),
            ("Web checksum", _formatChecksum(webSha256) if includeWeb else "skipped"),
            ("Dry run", "yes" if dryRun else "no"),
            ("Restart services", "no" if noRestart else "yes"),
            ("Force reinstall", "yes" if force else "no"),
            ("Backups to keep", keepBackups),
        ],
    )

    if SCIPIONAPI_RELEASE_TAG == targetVersion and not force and includeApi:
        _printWarning(
            "The installed API version already matches the target version. "
            "Use --force to reinstall the same version."
        )
        if not includeWeb:
            return

    if dryRun:
        _printSuccess("Dry run completed. No files were changed.")
        return

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    workRoot = _updatesDir(scipionHome) / "work" / timestamp
    downloadsDir = workRoot / "downloads"
    extractDir = workRoot / "extract"
    downloadsDir.mkdir(parents=True, exist_ok=True)
    extractDir.mkdir(parents=True, exist_ok=True)

    apiZipPath = downloadsDir / Path(apiFile).name
    webZipPath = downloadsDir / Path(webFile).name

    try:
        _printStep("Preparing update workspace", str(workRoot))
        _printInfo(f"Downloads directory: {downloadsDir}")
        _printInfo(f"Extraction directory: {extractDir}")
        _printSuccess("Update workspace ready.")

        if includeApi:
            _printStep("Downloading API archive", resolvedApiUrl)
            _downloadFile(resolvedApiUrl, apiZipPath, timeoutSec=timeoutSec)
            _verifySha256(apiZipPath, apiSha256)

        if includeWeb:
            _printStep("Downloading Web archive", resolvedWebUrl)
            _downloadFile(resolvedWebUrl, webZipPath, timeoutSec=timeoutSec)
            _verifySha256(webZipPath, webSha256)

        apiSourceRoot: Optional[Path] = None
        if includeApi:
            apiExtractDir = extractDir / "api"
            _printStep("Extracting API archive", str(apiZipPath))
            _safeExtractZip(apiZipPath, apiExtractDir)
            apiSourceRoot = _normalizeApiSourceRoot(apiExtractDir)
            _printSuccess(f"API archive validated: {apiSourceRoot}")

        if includeWeb:
            _printStep("Validating Web archive", str(webZipPath))
            webDistRoot = _validateWebArchive(webZipPath)
            _printSuccess(f"Web archive validated: {webDistRoot}")

        _printStep("Creating backup")
        backupRoot = _backupCurrentInstall(
            repoRoot=repoRoot,
            scipionHome=scipionHome,
            env=env,
            timestamp=timestamp,
            includeApi=includeApi,
            includeWeb=includeWeb,
        )
        _printSuccess(f"Backup created: {backupRoot}")

        _printStep("Stopping services")
        stopCommand()
        _printSuccess("Services stopped or already inactive.")

        try:
            if includeApi:
                assert apiSourceRoot is not None
                _printStep("Applying API update", str(apiSourceRoot))
                _applyApiUpdate(repoRoot, apiSourceRoot)
                _printSuccess("API managed files updated.")

                _printStep("Installing updated API")
                _installUpdatedApi(repoRoot)
                _printSuccess("Updated API package installed.")

                _printStep("Running Alembic migrations")
                runAlembicUpgrade(repoRoot)
                _printSuccess("Database migrations completed.")

            if includeWeb:
                serveWeb = _boolEnv(env, "SERVE_WEB", False)
                if serveWeb:
                    apiBaseUrl = env.get("WEB_API_BASE_URL") or env.get("API_MOUNT_PATH") or "/api"
                    _printStep("Deploying updated Web dist", str(webZipPath))
                    distPath = deployWebDist(
                        scipionHome=scipionHome,
                        webDist=webZipPath,
                        apiBaseUrl=apiBaseUrl,
                    )
                    writeEnvFile(
                        envPath,
                        {
                            "WEB_DIST_PATH": str(distPath),
                            "WEB_API_BASE_URL": apiBaseUrl,
                        },
                    )
                    exportEnvToOs(envPath)
                    _printSuccess(f"Web dist deployed: {distPath}")
                else:
                    _printWarning(
                        "SERVE_WEB is not enabled; Web archive was downloaded and validated but not deployed."
                    )

        except Exception:
            if includeApi:
                _printWarning("Update failed after backup; restoring API files from backup.")
                _restoreApiBackup(repoRoot, backupRoot)
                _printWarning("API files restored. Database migrations are not automatically rolled back.")
            raise

        if noRestart:
            _printWarning("Services were left stopped because --no-restart was used.")
        else:
            _printStep("Starting services")
            startCommand()
            _printSuccess("Services started.")

        _printStep("Writing update metadata", str(envPath))
        writeEnvFile(
            envPath,
            {
                "SCIPIONAPI_LAST_UPDATE_VERSION": targetVersion,
                "SCIPIONAPI_LAST_UPDATE_AT": timestamp,
                "SCIPIONAPI_UPDATE_BASE_URL": effectiveBaseUrl,
            },
        )
        _printSuccess("Update metadata written.")

        _printStep("Cleaning old backups")
        _cleanupOldBackups(scipionHome, keepBackups)

        _printKeyValueTable(
            "Update summary",
            [
                ("Target version", targetVersion),
                ("API updated", "yes" if includeApi else "no"),
                ("Web updated", "yes" if includeWeb else "no"),
                ("Backup", backupRoot),
                ("Work directory", workRoot),
                ("Services", "stopped" if noRestart else "started"),
                ("Metadata", envPath),
            ],
        )
        _printPanel("Update completed", "ScipionAPI update finished successfully.")

    except Exception as exc:
        _printPanel("Update failed", str(exc))
        raise