from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from scipionapi_cli.shell import resolveRepoRoot
from scipionapi_cli.update import DEFAULT_UPDATE_BASE_URL
from scipionapi_cli.version import __version__ as SCIPIONAPI_VERSION


DEFAULT_RELEASE_LOGIN = "scipion@nolan.cnb.csic.es"
DEFAULT_RELEASE_REMOTE_DIR = "/home/scipion/scipionfiles/downloads/scipion/scipionWeb"
DEFAULT_RELEASE_BASE_URL = DEFAULT_UPDATE_BASE_URL

RELEASE_VERSION_RE = re.compile(
    r"^[0-9]+(?:\.[0-9]+){1,3}(?:[-._A-Za-z0-9]*)?$"
)

console = Console()


def _loadManifestModule(repoRoot: Path):
    scriptPath = repoRoot / "scripts" / "update_release_manifest.py"
    if not scriptPath.is_file():
        raise RuntimeError(
            f"Release manifest helper not found: {scriptPath}"
        )

    spec = importlib.util.spec_from_file_location(
        "scipionapi_release_manifest_helper",
        str(scriptPath),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Could not load release manifest helper: {scriptPath}"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _printPanel(title: str, body: str = "") -> None:
    console.print(Panel.fit(body or "", title=title, border_style="cyan"))


def _printInfo(message: str) -> None:
    console.print("[bold cyan]INFO[/bold cyan] " + message)


def _printWarning(message: str) -> None:
    console.print("[bold yellow]WARNING[/bold yellow] " + message)


def _printSuccess(message: str) -> None:
    console.print("[bold green]SUCCESS[/bold green] " + message)


def _printStep(step: str, detail: str = "") -> None:
    if detail:
        console.print(f"[bold magenta]--> {step}[/bold magenta] [dim]{detail}[/dim]")
    else:
        console.print(f"[bold magenta]--> {step}[/bold magenta]")


def _printKeyValueTable(title: str, rows: List[Tuple[str, Any]]) -> None:
    table = Table(title=title, header_style="bold magenta")
    table.add_column("Field", style="bold white", no_wrap=True)
    table.add_column("Value", style="white")

    for key, value in rows:
        table.add_row(str(key), str(value))

    console.print(table)


def _requireTool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"Required command '{name}' was not found in PATH."
        )
    return path


def _normalizeLogin(value: str) -> str:
    login = (value or "").strip()

    if not login:
        raise RuntimeError("SSH login cannot be empty.")

    if login.startswith("-") or not re.match(r"^[A-Za-z0-9._@-]+$", login):
        raise RuntimeError(f"Invalid SSH login: {login!r}")

    return login


def _normalizeRemoteDir(value: str) -> str:
    remoteDir = (value or "").strip().rstrip("/")

    if not remoteDir:
        raise RuntimeError("Remote release directory cannot be empty.")

    if not re.match(r"^[A-Za-z0-9._~/-]+$", remoteDir):
        raise RuntimeError(
            f"Invalid remote release directory: {remoteDir!r}"
        )

    if remoteDir in {"/", ".", ".."}:
        raise RuntimeError(
            f"Refusing unsafe remote release directory: {remoteDir}"
        )

    return remoteDir


def _normalizeBaseUrl(value: str) -> str:
    baseUrl = (value or DEFAULT_RELEASE_BASE_URL).strip()
    if not baseUrl:
        baseUrl = DEFAULT_RELEASE_BASE_URL
    if not baseUrl.endswith("/"):
        baseUrl = f"{baseUrl}/"
    return baseUrl


def _normalizePackageVersion(
    value: str,
    packageName: str,
) -> str:
    version = str(value or "").strip()

    if version.startswith("v"):
        version = version[1:]

    if not version or not RELEASE_VERSION_RE.fullmatch(version):
        raise RuntimeError(
            f"Invalid {packageName} version: {value!r}"
        )

    return version


def _resolveWebRoot(
    repoRoot: Path,
    webRoot: Optional[str] = None,
) -> Path:
    if webRoot:
        candidate = Path(webRoot).expanduser().resolve()
    else:
        candidate = (repoRoot.parent / "ScipionWeb").resolve()

    packagePath = candidate / "package.json"

    if not packagePath.is_file():
        raise RuntimeError(
            "Could not locate ScipionWeb. Expected package.json at "
            f"{packagePath}. Use --web-root to specify the repository."
        )

    return candidate


def _readWebPackageVersion(
    webRoot: Path,
) -> str:
    packagePath = webRoot / "package.json"

    try:
        package = json.loads(
            packagePath.read_text(
                encoding="utf-8",
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ) as error:
        raise RuntimeError(
            f"Could not read ScipionWeb package.json: {error}"
        ) from error

    if not isinstance(package, dict):
        raise RuntimeError(
            f"Invalid ScipionWeb package.json: {packagePath}"
        )

    packageName = str(
        package.get("name")
        or ""
    ).strip()

    if packageName != "scipionweb":
        raise RuntimeError(
            "Invalid ScipionWeb package identity. "
            f"Expected 'scipionweb', found {packageName!r}."
        )

    return _normalizePackageVersion(
        package.get("version"),
        "ScipionWeb",
    )


def _resolvePairedReleaseVersion(
    webRoot: Path,
    requestedVersion: Optional[str] = None,
) -> str:
    apiVersion = _normalizePackageVersion(
        SCIPIONAPI_VERSION,
        "ScipionAPI",
    )

    webVersion = _readWebPackageVersion(
        webRoot
    )

    if apiVersion != webVersion:
        raise RuntimeError(
            "Release version mismatch. "
            f"ScipionAPI={apiVersion}, "
            f"ScipionWeb={webVersion}. "
            "Both packages must use the same version."
        )

    if requestedVersion:
        expectedVersion = _normalizePackageVersion(
            requestedVersion,
            "requested release",
        )

        if expectedVersion != apiVersion:
            raise RuntimeError(
                "Requested release version does not match "
                "the package versions. "
                f"Requested={expectedVersion}, "
                f"packages={apiVersion}."
            )

    return f"v{apiVersion}"


def _resolveAssetPath(
    downloadsDir: Path,
    value: Optional[str],
    defaultName: str,
) -> Path:
    candidate = Path(value).expanduser() if value else Path(defaultName)
    if not candidate.is_absolute():
        candidate = downloadsDir / candidate
    return candidate.resolve()


def _run(
    args: List[str],
    captureOutput: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        check=check,
        capture_output=captureOutput,
        text=True,
    )


def _runSsh(
    login: str,
    command: str,
    captureOutput: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    return _run(
        ["ssh", login, command],
        captureOutput=captureOutput,
        check=check,
    )


def _remotePath(remoteDir: str, fileName: str) -> str:
    return f"{remoteDir.rstrip('/')}/{fileName}"


def _remoteIsDirectory(login: str, remotePath: str) -> bool:
    result = _runSsh(
        login,
        f"test -d {shlex.quote(remotePath)}",
        captureOutput=True,
        check=False,
    )

    if result.returncode == 0:
        return True

    if result.returncode == 1:
        return False

    detail = (result.stderr or result.stdout or "").strip()
    raise RuntimeError(
        f"Could not check remote directory {remotePath}: "
        f"{detail or 'ssh failed'}"
    )


def _remoteExists(login: str, remotePath: str) -> bool:
    result = _runSsh(
        login,
        f"test -e {shlex.quote(remotePath)}",
        captureOutput=True,
        check=False,
    )

    if result.returncode == 0:
        return True

    if result.returncode == 1:
        return False

    detail = (result.stderr or result.stdout or "").strip()
    raise RuntimeError(
        f"Could not check remote path {remotePath}: "
        f"{detail or 'ssh failed'}"
    )


def _downloadRemoteManifest(
    login: str,
    remoteDir: str,
    destination: Path,
) -> bool:
    remoteManifest = _remotePath(remoteDir, "manifest.json")
    if not _remoteExists(login, remoteManifest):
        return False

    _run([
        "rsync",
        "-rl",
        f"{login}:{remoteManifest}",
        str(destination),
    ])
    return True


def _remoteReleaseAlreadyExists(
    login: str,
    remoteDir: str,
    apiFileName: str,
    webFileName: str,
) -> List[str]:
    existing = []

    for fileName in [apiFileName, webFileName]:
        remotePath = _remotePath(remoteDir, fileName)
        if _remoteExists(login, remotePath):
            existing.append(fileName)

    return existing


def _rsyncUpload(
    localPath: Path,
    login: str,
    remotePath: str,
    mode: str,
) -> None:
    _run([
        "rsync",
        "-rlv",
        f"--chmod=F{mode}",
        str(localPath),
        f"{login}:{remotePath}",
    ])


def _atomicUpload(
    localPath: Path,
    login: str,
    remoteDir: str,
    finalName: str,
    mode: str,
) -> None:
    token = f"{os.getpid()}"
    temporaryName = f".{finalName}.uploading-{token}"
    temporaryPath = _remotePath(remoteDir, temporaryName)
    finalPath = _remotePath(remoteDir, finalName)

    _rsyncUpload(
        localPath,
        login,
        temporaryPath,
        mode=mode,
    )

    command = (
        f"chmod {shlex.quote(mode)} {shlex.quote(temporaryPath)} && "
        f"mv -f -- {shlex.quote(temporaryPath)} {shlex.quote(finalPath)}"
    )
    _runSsh(login, command)


def _readPublishedManifest(
    baseUrl: str,
    timeoutSec: float = 15.0,
) -> Dict[str, Any]:
    url = urljoin(baseUrl, "manifest.json")
    request = Request(
        url,
        headers={"User-Agent": "scipionapi-cli/release"},
    )

    with urlopen(request, timeout=timeoutSec) as response:
        payload = json.loads(
            response.read().decode("utf-8", errors="replace")
        )

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Published manifest is not a JSON object: {url}"
        )

    return payload


def _verifyPublishedManifest(
    baseUrl: str,
    version: str,
    setLatest: bool,
) -> None:
    try:
        manifest = _readPublishedManifest(baseUrl)
    except (HTTPError, URLError, json.JSONDecodeError, RuntimeError) as exc:
        _printWarning(
            f"Release was uploaded, but HTTP manifest verification failed: {exc}"
        )
        return

    releases = manifest.get("releases")
    if not isinstance(releases, dict) or version not in releases:
        _printWarning(
            f"Release {version} was uploaded, but it is not visible in the "
            "published manifest yet."
        )
        return

    if setLatest and str(manifest.get("latest") or "") != version:
        _printWarning(
            f"Release {version} is published, but manifest latest is "
            f"{manifest.get('latest')!r}."
        )
        return

    _printSuccess("Published manifest is visible over HTTP")


def releaseUploadCommand(
    version: Optional[str] = None,
    webRoot: Optional[str] = None,
    downloadsDir: str = ".",
    apiFile: Optional[str] = None,
    webFile: Optional[str] = None,
    login: str = DEFAULT_RELEASE_LOGIN,
    remoteDir: str = DEFAULT_RELEASE_REMOTE_DIR,
    baseUrl: str = DEFAULT_RELEASE_BASE_URL,
    setLatest: bool = True,
    dryRun: bool = False,
    yes: bool = False,
    force: bool = False,
) -> None:
    repoRoot = resolveRepoRoot()

    resolvedWebRoot = _resolveWebRoot(
        repoRoot,
        webRoot,
    )

    normalizedVersion = _resolvePairedReleaseVersion(
        resolvedWebRoot,
        requestedVersion=version,
    )

    manifestModule = _loadManifestModule(repoRoot)
    downloadsPath = Path(downloadsDir).expanduser().resolve()
    login = _normalizeLogin(login)
    remoteDir = _normalizeRemoteDir(remoteDir)
    baseUrl = _normalizeBaseUrl(baseUrl)

    apiPath = _resolveAssetPath(
        downloadsPath,
        apiFile,
        f"ScipionAPI-{normalizedVersion}.zip",
    )
    webPath = _resolveAssetPath(
        downloadsPath,
        webFile,
        f"ScipionWeb-{normalizedVersion}-dist.zip",
    )
    installerPath = (repoRoot / "install.sh").resolve()

    for path, label in [
        (apiPath, "ScipionAPI release ZIP"),
        (webPath, "ScipionWeb release ZIP"),
        (installerPath, "guided installer"),
    ]:
        if not path.is_file():
            raise RuntimeError(f"{label} not found: {path}")

    _requireTool("rsync")
    _requireTool("ssh")

    _printPanel("ScipionWeb release upload")

    _printStep("Validating remote release directory", remoteDir)
    if not _remoteIsDirectory(login, remoteDir):
        raise RuntimeError(
            "Remote release directory does not exist. Verify --remote-dir "
            f"before publishing: {login}:{remoteDir}"
        )

    with tempfile.TemporaryDirectory(
        prefix="scipionweb-release-"
    ) as tempDir:
        tempPath = Path(tempDir)
        manifestPath = tempPath / "manifest.json"

        _printStep("Reading remote release state")
        manifestFound = _downloadRemoteManifest(
            login,
            remoteDir,
            manifestPath,
        )

        if manifestFound:
            _printInfo("Downloaded current remote manifest.json")
        else:
            _printWarning(
                "Remote manifest.json was not found; a new one will be created."
            )

        existingManifest = manifestModule.readManifest(manifestPath)
        releases = existingManifest.get("releases")
        releaseAlreadyInManifest = (
            isinstance(releases, dict)
            and normalizedVersion in releases
        )

        existingRemoteFiles = _remoteReleaseAlreadyExists(
            login,
            remoteDir,
            apiPath.name,
            webPath.name,
        )

        if not force and (
            releaseAlreadyInManifest
            or existingRemoteFiles
        ):
            details = []
            if releaseAlreadyInManifest:
                details.append(
                    f"manifest already contains {normalizedVersion}"
                )
            if existingRemoteFiles:
                details.append(
                    "remote files already exist: "
                    + ", ".join(existingRemoteFiles)
                )
            raise RuntimeError(
                "Release already appears to be published ("
                + "; ".join(details)
                + "). Use --force only when intentionally replacing it."
            )

        _, manifest = manifestModule.updateManifest(
            downloadsDir=downloadsPath,
            version=normalizedVersion,
            manifestPath=manifestPath,
            apiFile=str(apiPath),
            webFile=str(webPath),
            setLatest=setLatest,
        )

        releaseEntry = manifest["releases"][normalizedVersion]
        apiSha = releaseEntry["api"]["sha256"]
        webSha = releaseEntry["web"]["sha256"]

        _printKeyValueTable(
            "Release plan",
            [
                ("Version", normalizedVersion),
                ("ScipionAPI ZIP", apiPath),
                ("API SHA256", apiSha),
                ("ScipionWeb ZIP", webPath),
                ("Web SHA256", webSha),
                ("Installer", installerPath),
                ("SSH login", login),
                ("Remote directory", remoteDir),
                ("Public URL", baseUrl),
                ("Set latest", "yes" if setLatest else "no"),
                ("Force replacement", "yes" if force else "no"),
            ],
        )

        if dryRun:
            _printInfo("Dry run: no remote files were modified.")
            return

        if not yes:
            console.print()
            console.print(
                "[bold yellow]This publishes files to the ScipionWeb "
                "download server.[/bold yellow]"
            )
            if not Confirm.ask("Continue?", default=False):
                _printInfo("Release upload cancelled")
                return

        _printStep("Uploading release archives")
        _atomicUpload(
            apiPath,
            login,
            remoteDir,
            apiPath.name,
            mode="644",
        )
        _atomicUpload(
            webPath,
            login,
            remoteDir,
            webPath.name,
            mode="644",
        )

        _printStep("Publishing guided installer")
        _atomicUpload(
            installerPath,
            login,
            remoteDir,
            "install.sh",
            mode="755",
        )

        _printStep("Publishing manifest.json", "atomic final step")
        _atomicUpload(
            manifestPath,
            login,
            remoteDir,
            "manifest.json",
            mode="644",
        )

        _printStep("Verifying published manifest")
        _verifyPublishedManifest(
            baseUrl,
            normalizedVersion,
            setLatest=setLatest,
        )

        _printSuccess(
            f"ScipionWeb release {normalizedVersion} published successfully."
        )
