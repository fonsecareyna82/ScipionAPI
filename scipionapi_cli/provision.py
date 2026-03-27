# scipionapi_cli/provision.py

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

import json
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Optional, List, Any, Tuple

from scipionapi_cli.envfile import exportEnvToOs, readEnvFile, writeEnvFile
from scipionapi_cli.install import _resolveScipionHome
from scipionapi_cli.shell import resolveRepoRoot


try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    _HAS_RICH = True
    _console = Console()
except Exception:
    _HAS_RICH = False
    _console = None


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
    if _HAS_RICH:
        if detail:
            _console.print(f"[bold magenta]--> {step}[/bold magenta] [dim]{detail}[/dim]")
        else:
            _console.print(f"[bold magenta]--> {step}[/bold magenta]")
    else:
        if detail:
            print(f"\n--> {step} | {detail}", flush=True)
        else:
            print(f"\n--> {step}", flush=True)


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


def _printSummaryTable(rows: List[Tuple[str, Any]]) -> None:
    # printSummaryTable
    if _HAS_RICH:
        table = Table(title="Provision summary", header_style="bold magenta")
        table.add_column("Field", style="bold white", no_wrap=True)
        table.add_column("Value", style="white")
        for key, value in rows:
            table.add_row(str(key), str(value))
        _console.print(table)
    else:
        print("\nProvision summary:", flush=True)
        for key, value in rows:
            print(f"  {key}: {value}", flush=True)


def _safeRemoveTree(path: Path) -> None:
    # safeRemoveTree
    if not path.exists():
        return
    shutil.rmtree(path, ignore_errors=True)


def _safeExtractZip(zipPath: Path, destDir: Path) -> None:
    # safeExtractZipPreventZipSlip
    destDir.mkdir(parents=True, exist_ok=True)
    destRoot = destDir.resolve()

    with zipfile.ZipFile(zipPath, "r") as zf:
        for member in zf.infolist():
            memberPath = (destDir / member.filename).resolve()
            if not str(memberPath).startswith(str(destRoot)):
                raise RuntimeError(f"Unsafe zip content detected: {member.filename}")
        zf.extractall(destDir)


def _normalizeViteDistLayout(extractedDir: Path) -> Path:
    # normalizeViteDistLayout
    if (extractedDir / "index.html").exists():
        return extractedDir

    distDir = extractedDir / "dist"
    if (distDir / "index.html").exists():
        return distDir

    children = [p for p in extractedDir.iterdir() if p.is_dir()]
    if len(children) == 1 and (children[0] / "index.html").exists():
        return children[0]

    raise RuntimeError(
        "Web build not detected. Expected index.html at the root, or inside dist/, "
        "or inside a single top-level folder."
    )


def _copyDirContents(srcDir: Path, dstDir: Path) -> None:
    # copyDirContents
    dstDir.mkdir(parents=True, exist_ok=True)
    for item in srcDir.iterdir():
        target = dstDir / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _writeWebConfigJs(distDir: Path, apiBaseUrl: str) -> None:
    # writeWebConfigJs
    distDir.mkdir(parents=True, exist_ok=True)
    configPath = distDir / "config.js"
    payload = {"apiBaseUrl": apiBaseUrl.rstrip("/")}
    content = f"window.__SCIPION_WEB_CONFIG__ = {json.dumps(payload, ensure_ascii=False)};\n"
    configPath.write_text(content, encoding="utf-8")


def _normalizeMountPath(value: str) -> str:
    # normalizeMountPath
    mountPath = (value or "/api").strip()
    if not mountPath:
        mountPath = "/api"
    if not mountPath.startswith("/"):
        mountPath = f"/{mountPath}"
    if mountPath != "/" and mountPath.endswith("/"):
        mountPath = mountPath.rstrip("/")
    return mountPath


def _normalizeApiBaseUrl(value: str, fallbackMountPath: str) -> str:
    # normalizeApiBaseUrl
    apiBaseUrl = (value or "").strip()
    if not apiBaseUrl:
        apiBaseUrl = fallbackMountPath
    if not apiBaseUrl.startswith("/"):
        if "://" in apiBaseUrl:
            return apiBaseUrl.rstrip("/")
        apiBaseUrl = f"/{apiBaseUrl}"
    return apiBaseUrl.rstrip("/") or "/"


def deployWebDist(
    scipionHome: Path,
    webDist: Path,
    apiBaseUrl: str,
) -> Path:
    # deployWebDistToScipionHome
    webRoot = scipionHome / "web"
    targetDist = webRoot / "dist"

    _printStep("Preparing web target directory", str(targetDist))
    _safeRemoveTree(targetDist)
    targetDist.mkdir(parents=True, exist_ok=True)

    webDist = webDist.expanduser().resolve()
    _printInfo(f"Resolved webDist input: {webDist}")

    if webDist.is_dir():
        # deployFromDirectory
        normalizedSrc = webDist
        if (webDist / "dist" / "index.html").exists() and not (webDist / "index.html").exists():
            normalizedSrc = webDist / "dist"

        if not (normalizedSrc / "index.html").exists():
            raise RuntimeError(f"Invalid web dist directory: {webDist} (index.html not found)")

        _printStep("Copying web assets from directory", str(normalizedSrc))
        _copyDirContents(normalizedSrc, targetDist)

    elif webDist.is_file() and webDist.suffix.lower() == ".zip":
        # deployFromZip
        tempExtract = webRoot / ".dist_extract_tmp"
        _printStep("Extracting web zip", str(webDist))
        _safeRemoveTree(tempExtract)
        tempExtract.mkdir(parents=True, exist_ok=True)

        _safeExtractZip(webDist, tempExtract)
        normalizedSrc = _normalizeViteDistLayout(tempExtract)
        _printStep("Copying extracted web assets", str(normalizedSrc))
        _copyDirContents(normalizedSrc, targetDist)
        _safeRemoveTree(tempExtract)

    else:
        raise RuntimeError(f"Unsupported webDist input: {webDist} (expected directory or .zip file)")

    _printStep("Writing web runtime config", str(targetDist / "config.js"))
    _writeWebConfigJs(targetDist, apiBaseUrl)
    _printSuccess(f"Web assets deployed to: {targetDist}")
    return targetDist


def provisionCommand(
    adminUser: str,
    adminEmail: str,
    adminPassword: str,
    webDist: Optional[str] = None,
    apiMountPath: str = "/api",
    apiBaseUrl: Optional[str] = None,
    runBootstrap: bool = True,
    envName: str = "scipion4Web",
    pythonVersion: str = "3.8",
    installScipionCore: bool = True,
    scipionCorePackages: str = "scipion-pyworkflow scipion-em scipion-app",
) -> None:
    # provisionCommandOneShot
    from scipionapi_cli.install import installCommand
    from scipionapi_cli.runtime import startCommand

    _printPanel("ScipionAPI provision")
    _printKeyValueTable(
        "Provision configuration",
        [
            ("Admin user", adminUser),
            ("Admin email", adminEmail),
            ("webDist", webDist or "not provided"),
            ("API mount path", apiMountPath),
            ("API base URL", apiBaseUrl or "auto"),
            ("Run bootstrap", runBootstrap),
            ("Env name", envName),
            ("Python version", pythonVersion),
            ("Install Scipion core", installScipionCore),
            ("Scipion core packages", scipionCorePackages),
        ],
    )

    if runBootstrap:
        _printStep("Running bootstrap phase")
        from scipionapi_cli.bootstrap import bootstrapCommand

        bootstrapCommand(
            envName=envName,
            pythonVersion=pythonVersion,
            installScipionCore=installScipionCore,
            scipionCorePackages=scipionCorePackages,
        )
        _printSuccess("Bootstrap phase completed")
    else:
        _printWarning("Skipping bootstrap phase")

    repoRoot = resolveRepoRoot()
    _printStep("Resolving repository root", str(repoRoot))

    defaultScipionHome = (repoRoot / "scipion_home").resolve()
    defaultEnvPath = defaultScipionHome / ".env"
    existingDefault = readEnvFile(defaultEnvPath)

    scipionHome = _resolveScipionHome(repoRoot, existingDefault)
    envPath = scipionHome / ".env"

    _printKeyValueTable(
        "Resolved paths",
        [
            ("Repo root", repoRoot),
            ("Default SCIPION_HOME", defaultScipionHome),
            ("Resolved SCIPION_HOME", scipionHome),
            ("Env file", envPath),
        ],
    )

    _printStep("Running install phase")
    installCommand(adminUser=adminUser, adminEmail=adminEmail, adminPassword=adminPassword)
    _printSuccess("Install phase completed")

    env = readEnvFile(envPath)

    resolvedApiMountPath = _normalizeMountPath(apiMountPath)
    resolvedApiBaseUrl = _normalizeApiBaseUrl(apiBaseUrl or "", resolvedApiMountPath)

    _printKeyValueTable(
        "Resolved API settings",
        [
            ("Resolved API mount path", resolvedApiMountPath),
            ("Resolved API base URL", resolvedApiBaseUrl),
        ],
    )

    if webDist:
        _printStep("Deploying web distribution")
        distPath = deployWebDist(
            scipionHome=scipionHome,
            webDist=Path(webDist),
            apiBaseUrl=resolvedApiBaseUrl,
        )

        updates: Dict[str, str] = {
            "SERVE_WEB": "1",
            "API_MOUNT_PATH": resolvedApiMountPath,
            "WEB_DIST_PATH": str(distPath),
            "WEB_API_BASE_URL": resolvedApiBaseUrl,
        }
        _printStep("Updating environment for integrated web mode", str(envPath))
        writeEnvFile(envPath, updates)
        exportEnvToOs(envPath)
        env = readEnvFile(envPath)
        _printSuccess("Integrated web mode enabled")
    else:
        updates = {
            "SERVE_WEB": "0",
            "API_MOUNT_PATH": resolvedApiMountPath,
        }
        _printStep("Updating environment for API-only mode", str(envPath))
        writeEnvFile(envPath, updates)
        exportEnvToOs(envPath)
        env = readEnvFile(envPath)
        _printSuccess("API-only mode enabled")

    _printStep("Starting services")
    startCommand()
    _printSuccess("Runtime services started")

    apiHost = env.get("API_HOST", "0.0.0.0")
    apiPort = env.get("API_PORT", "8080")
    serveWeb = (env.get("SERVE_WEB") or "").strip() == "1"
    mountPath = _normalizeMountPath(env.get("API_MOUNT_PATH") or resolvedApiMountPath)

    displayHost = apiHost
    if displayHost in ("0.0.0.0", "::", ""):
        displayHost = "127.0.0.1"

    summaryRows: List[Tuple[str, Any]] = [
        ("Repo root", repoRoot),
        ("SCIPION_HOME", scipionHome),
        ("Env file", envPath),
        ("API host", apiHost),
        ("API port", apiPort),
        ("API docs", f"http://{displayHost}:{apiPort}{mountPath}/docs" if serveWeb else f"http://{displayHost}:{apiPort}/docs"),
        ("Serve web", "yes" if serveWeb else "no"),
    ]

    if serveWeb:
        summaryRows.append(("Web URL", f"http://{displayHost}:{apiPort}/"))
        summaryRows.append(("WEB_DIST_PATH", env.get("WEB_DIST_PATH", "")))
        summaryRows.append(("WEB_API_BASE_URL", env.get("WEB_API_BASE_URL", "")))

    _printSummaryTable(summaryRows)
    _printPanel("Provision completed", "Bootstrap, install, optional web deploy, and runtime startup finished.")
